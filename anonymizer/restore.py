"""Возврат исходных значений в файл, который вернулся из внешней модели.

Файл после модели редко совпадает с отправленным: порядок данных другой, часть строк добавлена,
листы перенесены. Поэтому восстановление не сопоставляет структуры, а ищет токены в любом месте
любого текстового узла и подставляет значение из хранилища. Формулы, форматирование и всё, что в
токенах не участвует, остаётся как вернула модель.

Токен, которого нет в хранилище, не угадывается: подставить вместо `Name77` похожее `Name7` значило бы
приписать документу чужое имя. Такой токен остаётся в файле и попадает в отчёт.
"""

from __future__ import annotations

import hashlib
import io
import os
import codecs
import re
import tempfile
import zipfile
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from lxml import etree

from . import finance as finance_module
from . import imagereplace
from . import numbers as numeric
from .formats import (BARCODE_LABEL, RAW_TEXT_EXTS, HEADER_FOOTER_TAGS, IDENTIFIER_ATTRS, _groups, _is_worksheet, _mask_header_codes, _parser, parse_part, _xml_name, _zip_snapshot,
                      NUM_MARK, NUMERIC_TEXT, is_embedded_package, splice_segments, strip_vault_marker)
from .pdftext import PageChars, RectGrid, find_all, font_for, kept_chars, put_text, redraw_lost, rgb, text_width
from .tokens import EMAIL_TOKEN_RE, INNER_EMAIL_TOKEN_RE, INNER_TOKEN_RE, KINDS, RELAXED_TOKEN_RE, TOKEN_RE, TOKEN_RE_AFTER_UNDERSCORE, parse_match
from .util import atomic_write, sniff_encoding
from .vault import Vault

MAX_SHEET_NAME = 31
INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


@dataclass
class RestoreStats:
    found: int = 0
    restored: int = 0
    unknown: dict[str, int] = field(default_factory=dict)        # токен → сколько раз
    removed: dict[str, int] = field(default_factory=dict)        # токены удалённых секретов
    variant_fallback: int = 0
    endings: int = 0
    loose: int = 0                                                # метки с нарушенной записью, всё же возвращённые
    numbers: int = 0
    finance: dict = field(default_factory=dict)       # exact / divided / new / missing при возврате сумм
    finance_flags: list[str] = field(default_factory=list)     # ячейки, где единицы неизвестны: названы в отчёте
    finance_changes: list[str] = field(default_factory=list)   # правки модели, переведённые в исходные единицы
    number_cells: list[str] = field(default_factory=list)
    sheet_fixes: list[str] = field(default_factory=list)
    entities: set[str] = field(default_factory=set)              # какие токены встретились и были восстановлены

    def merge(self, other: "RestoreStats") -> None:
        self.found += other.found
        self.restored += other.restored
        for name in ("unknown", "removed"):
            target = getattr(self, name)
            for token, count in getattr(other, name).items():
                target[token] = target.get(token, 0) + count
        self.variant_fallback += other.variant_fallback
        self.endings += other.endings
        self.numbers += other.numbers
        for key, count in other.finance.items():
            self.finance[key] = self.finance.get(key, 0) + count
        self.finance_flags.extend(other.finance_flags)
        self.finance_changes.extend(other.finance_changes)
        self.number_cells.extend(other.number_cells)
        self.sheet_fixes.extend(other.sheet_fixes)
        self.entities |= other.entities


class Restorer:
    """Подставляет значения вместо токенов и считает, что удалось, а что нет."""

    def __init__(self, vault: Vault):
        self.vault = vault
        self.stats = RestoreStats()
        self._cache: dict[str, str | None] = {}

    # -- поиск ----------------------------------------------------------------

    def matches(self, text: str, after_underscore: bool = False) -> list[tuple[int, int, str]]:
        """(начало, конец, замена) для каждого токена, который можно вернуть; остальное учитывается в отчёте."""
        out: list[tuple[int, int, str]] = []
        if not any(ch.isdigit() for ch in text):
            return out
        # PDF extraction can concatenate labels, including email-shaped labels.
        # Accept only a complete run of exact known tokens, never a known prefix
        # of an unknown numeric ID or a partial sequence containing unknown IDs.
        glued = list(_glued_runs(text))
        glued_ranges = [(start, end) for start, end, _ in glued]
        glued_starts = [start for start, _ in glued_ranges]

        def overlaps_glued(start, end):
            index = bisect_left(glued_starts, end) - 1
            return index >= 0 and glued_ranges[index][1] > start

        for start, end, parts in glued:
            results = [self.vault.lookup(*parse_match(m, email=is_email)) for m, is_email in parts]
            if all(result.status == "ok" for result in results):
                for m, is_email in parts:
                    original = self._resolve(m, is_email)
                    if original is not None:
                        out.append((m.start(), m.end(), original))
                        self.stats.loose += 1
            else:
                for (m, _), result in zip(parts, results):
                    if result.status != "ok":
                        token = m.group(0)
                        self.stats.unknown[token] = self.stats.unknown.get(token, 0) + 1
        for regex, is_email in ((TOKEN_RE_AFTER_UNDERSCORE if after_underscore else TOKEN_RE, False), (EMAIL_TOKEN_RE, True)):
            for m in regex.finditer(text):
                if overlaps_glued(m.start(), m.end()):
                    continue
                replacement = self._resolve(m, is_email)
                if replacement is not None:
                    start, end = m.start(), m.end()
                    # Невидимый разделитель, поставленный при обезличивании, уходит вместе с токеном.
                    if start > 0 and text[start - 1] == "\u200b":
                        start -= 1
                    if end < len(text) and text[end] == "\u200b":
                        end += 1
                    out.append((start, end, replacement))
        # Второй проход: тот же токен в нарушенной записи (`_Name1_`, `вName1`, `Name 1`). Берётся только то, что знает
        # хранилище, и только там, где первый проход ничего не нашёл.
        taken = sorted((a, b) for a, b, _ in out)
        for m in RELAXED_TOKEN_RE.finditer(text):
            if overlaps_glued(m.start(), m.end()) or any(a < m.end() and b > m.start() for a, b in taken):
                continue
            replacement = self._resolve(m, False, relaxed=True)
            if replacement is None:
                continue
            start, end = m.start(), m.end()
            if start > 0 and text[start - 1] == "\u200b":
                start -= 1
            if end < len(text) and text[end] == "\u200b":
                end += 1
            out.append((start, end, replacement))
        return out

    def substitute(self, text: str, after_underscore: bool = False) -> str:
        edits = self.matches(text, after_underscore)
        if not edits:
            return text
        edits.sort()
        pieces, cursor = [], 0
        for start, end, replacement in edits:
            if start < cursor:
                # Невидимый разделитель между двумя склеенными метками уже съеден первой из них.
                if start < cursor <= end and not text[start:cursor].strip("​"):
                    start = cursor
                else:
                    continue
            pieces.append(text[cursor:start])
            pieces.append(replacement)
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces)

    def _resolve(self, m: re.Match[str], is_email: bool, relaxed: bool = False) -> str | None:
        if relaxed:
            digits = m.group(2)
            # Литерал документа, похожий на метку («Moscow-City 05.jpg»), не метка: модель не пишет номер с нулём впереди,
            # а пробел или дефис внутри имени файла или идентификатора - часть этого имени.
            if len(digits) > 1 and digits.startswith("0"):
                return None
            # Цифра перед меткой: «n0name321» - логин или идентификатор документа, а не метка (строгий проход такое тоже
            # не берёт); без этой проверки при больших номерах хранилища литерал подменялся чужим значением.
            # Исключение: цифры - конец соседней метки («Inn1Name1»), такие склеенные метки возвращаются по-прежнему.
            if m.start() > 0 and m.string[m.start() - 1].isdigit():
                head = m.string[max(0, m.start() - 40):m.start()]
                if not any(g.end() == len(head) for g in INNER_TOKEN_RE.finditer(head)):
                    return None
            if m.start(2) > m.end(1):
                before = m.string[m.start() - 1:m.start()]
                after = m.string[m.end():m.end() + 2]
                if before and before in "-/\\._:@#" or re.match(r"\.[A-Za-z0-9]", after):
                    return None
            kind, number, variant = parse_match(m)
            if self.vault.lookup(kind, number, variant).status not in ("ok", "variant_missing"):
                return None
            self.stats.loose += 1
        self.stats.found += 1
        following = m.string[m.end():m.end() + 1]
        if following and "а" <= following <= "я" and following.islower():
            self.stats.endings += 1
        kind, number, variant = parse_match(m, email=is_email)
        result = self.vault.lookup(kind, number, variant)
        if result.status == "ok":
            self.stats.restored += 1
            self.stats.entities.add(result.base)
            return result.original
        if result.status == "variant_missing":
            # `Name1_2024`: суффикс не номер написания, а часть текста. Возвращаем первое написание и суффикс.
            self.stats.variant_fallback += 1
            self.stats.restored += 1
            self.stats.entities.add(result.base)
            variant_text = m.group(3) if m.lastindex and m.lastindex >= 3 and m.group(3) else ""
            return (result.original or "") + (f"_{variant_text}" if variant_text else "")
        if result.status == "removed":
            self.stats.removed[result.base] = self.stats.removed.get(result.base, 0) + 1
            return None
        canonical = f"{kind.stem}{number}" + (f"_{variant}" if variant > 1 else "")
        self.stats.unknown[canonical] = self.stats.unknown.get(canonical, 0) + 1
        return None


# ---------------------------------------------------------------------------
# Текстовые форматы
# ---------------------------------------------------------------------------

# Пометка хранилища в текстовом файле: невидимые «теговые» знаки Юникода в конце файла. Только .txt и .md: в .csv
# лишний знак испортил бы последнюю ячейку. Файл без пометки (старый, или пометку стёрла модель) возвращается как раньше.
TEXT_MARK_SUFFIXES = (".txt", ".md")
LINE_MARK_SUFFIXES = (".csv", ".tsv")      # пометка в конце первой строки: после последней строки появилась бы лишняя запись
TEXT_MARK_RE = re.compile("[\U000E0020-\U000E007E]+")


def stamp_text_marker(path: Path, vault_id: str) -> None:
    suffix = path.suffix.lower()
    if suffix not in TEXT_MARK_SUFFIXES + LINE_MARK_SUFFIXES or not vault_id:
        return
    raw = path.read_bytes()
    enc = sniff_encoding(raw)
    if not enc.lower().replace("_", "-").startswith("utf-8"):
        return
    text = raw.decode(enc, errors="strict")
    mark = "".join(chr(0xE0000 + ord(ch)) for ch in "anonymizer:" + vault_id)
    if suffix in LINE_MARK_SUFFIXES:
        first = re.search(r"\r\n|\n|\r|$", text).start()
        atomic_write(path, (text[:first] + mark + text[first:]).encode(enc))
        return
    body = text.rstrip()
    atomic_write(path, (body + mark + text[len(body):]).encode(enc))


def read_text_marker(path: Path) -> str:
    """Идентификатор хранилища из пометки в конце текстового файла; пусто, если пометки нет."""
    try:
        raw = path.read_bytes()
        text = raw.decode(sniff_encoding(raw), errors="replace")
    except Exception:
        return ""
    found = TEXT_MARK_RE.findall(text)
    if not found:
        return ""
    decoded = "".join(chr(ord(ch) - 0xE0000) for ch in found[-1])
    return decoded[len("anonymizer:"):] if decoded.startswith("anonymizer:") else ""


def restore_text_file(src: Path, dst: Path, restorer: Restorer) -> None:
    raw = src.read_bytes()
    enc = sniff_encoding(raw)
    text = restorer.substitute(TEXT_MARK_RE.sub("", raw.decode(enc, errors="replace")))
    text = imagereplace.restore_data_uris(text, restorer.vault)[0]
    if enc == "utf-8" and raw.isascii():
        # В обезличенном файле нет русских букв, по ним кодировку не определить: берём объявленную в самом файле
        # (<meta charset>, <?xml encoding?>, coding:), иначе cp1251-файл вернулся бы в UTF-8 вопреки своему объявлению.
        declared = re.search(r"(?i)(?:charset|encoding|coding)\s*[=:]\s*[\"']?([A-Za-z0-9_-]+)", text[:2000])
        if declared:
            try:
                name = codecs.lookup(declared.group(1)).name
                if name in ("cp1251", "koi8-r", "cp866"):
                    enc = name
            except LookupError:
                pass
    try:
        payload = text.encode(enc)
    except UnicodeEncodeError:
        payload = text.encode("utf-8")
    atomic_write(dst, payload)


# ---------------------------------------------------------------------------
# OOXML
# ---------------------------------------------------------------------------

def restore_ooxml(src: Path, dst: Path, restorer: Restorer, numbers: bool = True, depth: int = 0) -> bool:
    """Возвращает True, если структура контейнера не пострадала."""
    before = _zip_snapshot(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".restore-office-", suffix=src.suffix, dir=dst.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(src) as zin:
            parsed: dict[str, object] = {}
            for info in zin.infolist():
                if info.filename.lower().endswith((".xml", ".rels", ".vml")):
                    root = parse_part(info.filename, zin.read(info.filename))
                    if root is not None:
                        parsed[info.filename] = root
            fin_record = None
            if src.suffix.lower() == ".xlsx" and depth == 0:
                try:
                    fin_record = finance_module.find_record(restorer.vault, parsed)
                    if fin_record is not None:
                        fin_stats = finance_module.restore_workbook(parsed, fin_record, restorer.vault)
                        restorer.stats.finance_flags.extend(fin_stats.pop("_flags", []))
                        restorer.stats.finance_changes.extend(fin_stats.pop("_changes", []))
                        for key, count in fin_stats.items():
                            restorer.stats.finance[key] = restorer.stats.finance.get(key, 0) + count
                except Exception:
                    fin_record = None
                    restorer.stats.finance["failed"] = 1
            use_numbers = numbers and src.suffix.lower() == ".xlsx" and bool(restorer.vault.numbers_back)
            date_styles: set[int] = set()
            if use_numbers and parsed.get("xl/styles.xml") is not None:
                date_styles = numeric.date_style_indexes(parsed["xl/styles.xml"])
            numbers_restored = 0
            swapped_images: set[str] = set()
            sheet_renames: list[tuple[str, str]] = []
            with zipfile.ZipFile(tmp_name, "w") as zout:
                for info in zin.infolist():
                    raw = zin.read(info.filename)
                    root = parsed.get(info.filename)
                    if root is None and imagereplace.replaces_part(info.filename, raw):
                        original = restorer.vault.original_image(hashlib.sha256(raw).hexdigest())
                        if original is not None:
                            raw = original
                            swapped_images.add(info.filename)
                    if root is None and info.filename.lower().endswith(RAW_TEXT_EXTS) \
                            and "/media/" not in info.filename.lower():
                        enc = sniff_encoding(raw)
                        try:
                            new_raw = restorer.substitute(raw.decode(enc)).encode(enc)
                        except (UnicodeError, LookupError):
                            new_raw = raw
                        if new_raw != raw:
                            swapped_images.add(info.filename)
                            raw = new_raw
                    if root is None and is_embedded_package(info.filename) and depth < 2:
                        raw = _restore_embedded(raw, info.filename, restorer, numbers, depth)
                    elif root is None and info.filename.lower().endswith(".zip") and raw[:4] == b"PK\x03\x04":
                        raw = _restore_zip(raw, info.filename, restorer, numbers, depth + 1)
                    if root is not None:
                        marked_cells = _strip_numeric_marks(root) if _is_worksheet(info.filename) else []
                        changed = _restore_tree(root, info.filename, restorer) or bool(marked_cells) or fin_record is not None
                        _renumber(marked_cells)
                        if depth == 0 and info.filename == "docProps/core.xml":
                            changed = strip_vault_marker(root) or changed
                        if use_numbers:
                            if _is_worksheet(info.filename):
                                done = numeric.restore_worksheet(root, date_styles, restorer.vault,
                                                                 [])  # ячейки в отчёт не выводим поимённо
                                restorer.stats.numbers += done
                                numbers_restored += done
                                changed = changed or bool(done)
                            elif "/charts/" in info.filename.lower():
                                done = numeric.restore_chart_cache(root, restorer.vault)
                                changed = changed or bool(done)
                        if info.filename.lower() == "xl/workbook.xml":
                            renames = _fix_sheet_names(root)
                            sheet_renames.extend(renames)
                            restorer.stats.sheet_fixes.extend(f"{old} → {new}" for old, new in renames)
                            changed = True
                        if changed:
                            raw = etree.tostring(root, xml_declaration=raw.lstrip().startswith(b"<?xml"),
                                                 encoding="UTF-8")
                    zout.writestr(info, raw)
            if numbers_restored:
                _request_recalc_in_zip(tmp_name)
            if sheet_renames:
                _rewrite_sheet_references(tmp_name, sheet_renames)
        os.replace(tmp_name, dst)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    after = _zip_snapshot(dst)
    return before["names"] == after["names"] and {k: v for k, v in before["binary_hashes"].items() if k not in swapped_images} \
        == {k: v for k, v in after["binary_hashes"].items() if k not in swapped_images}


def _strip_numeric_marks(root) -> list:
    """Ячейки, которые до обезличивания были числами (метка NUM_MARK в конце текста): метка снимается, ячейки возвращаются списком."""
    cells = []
    for cell in root.iter():
        if _xml_name(cell) == "c" and cell.get("t") == "inlineStr":
            texts = [t for t in cell.iter() if _xml_name(t) == "t"]
            if len(texts) == 1 and (texts[0].text or "").endswith(NUM_MARK):
                texts[0].text = texts[0].text[:-len(NUM_MARK)]
                cells.append(cell)
    return cells


def _renumber(cells: list) -> None:
    """После возврата значения ячейка снова число (ИНН, паспорт, серийная дата), если оно числовое."""
    for cell in cells:
        texts = [t for t in cell.iter() if _xml_name(t) == "t"]
        text = (texts[0].text or "").strip() if texts else ""
        if not NUMERIC_TEXT.match(text):
            continue
        for child in list(cell):
            cell.remove(child)
        del cell.attrib["t"]
        etree.SubElement(cell, f"{{{etree.QName(cell).namespace}}}v").text = text


def _restore_embedded(raw: bytes, name: str, restorer: Restorer, numbers: bool, depth: int) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ("in" + Path(name).suffix)
        target = Path(tmp) / ("out" + Path(name).suffix)
        source.write_bytes(raw)
        try:
            restore_ooxml(source, target, restorer, numbers, depth + 1)
        except Exception:
            return raw
        return target.read_bytes() if target.exists() else raw


def _restore_zip(raw: bytes, name: str, restorer: Restorer, numbers: bool, depth: int) -> bytes:
    """Произвольный zip внутри файла: картинки возвращаются по хэшу заглушки, вложенные книги и архивы разбираются глубже."""
    if depth > 4:
        return raw
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zin:
            items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    except Exception:
        return raw
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            lowered = info.filename.lower()
            if not info.is_dir():
                if imagereplace.replaces_part(lowered, data):
                    original = restorer.vault.original_image(hashlib.sha256(data).hexdigest())
                    if original is not None:
                        data = original
                elif is_embedded_package(lowered) and depth < 4:
                    data = _restore_embedded(data, info.filename, restorer, numbers, depth)
                elif lowered.endswith(".zip") and data[:4] == b"PK\x03\x04":
                    data = _restore_zip(data, info.filename, restorer, numbers, depth + 1)
            zout.writestr(info, data)
    return out.getvalue()


def _request_recalc_in_zip(path: str) -> None:
    """Excel пересчитает книгу при открытии: формулы после возврата чисел ссылаются на исходные значения."""
    with zipfile.ZipFile(path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]
    with zipfile.ZipFile(path, "w") as zout:
        for info, data in items:
            if info.filename.lower() == "xl/workbook.xml":
                root = etree.fromstring(data, _parser())
                numeric.request_recalculation(root)
                data = etree.tostring(root, xml_declaration=data.lstrip().startswith(b"<?xml"), encoding="UTF-8")
            zout.writestr(info, data)


INTERNAL_PART_PATH = re.compile(r"(?i)^(?:\.\./|\./|/)*(?:[\w\-]+/)*[\w\-]+\.(?:xml|rels|vml|bin|png|jpe?g|gif|bmp|tiff?|emf|wmf|"
                                r"svg|xlsx|docx|pptx|vsdx|odttf|fntdata|ttf|otf|eot|mp[34]|wav|mov)$")


def _restore_tree(root, part: str, restorer: Restorer) -> bool:
    """Токен мог быть разорван форматированием, поэтому текст абзаца собирается целиком,
    но правятся только затронутые участки — оформление остальных runs сохраняется."""
    changed = False
    covered: set[int] = set()
    keep_alive = []      # lxml создаёт обёртки узлов по требованию: без ссылки id() освобождается и повторяется
    for group_name, segments in _groups(root, part):
        joined = "".join(s.text for s in segments)
        if group_name.split(":")[0] in HEADER_FOOTER_TAGS:
            joined = _mask_header_codes(joined)       # `&Remail1@example.com`: R — код колонтитула, а не буква адреса
        edits = restorer.matches(joined) if any(ch.isdigit() for ch in joined) else []
        for segment in segments:
            covered.add(id(segment.element))
            keep_alive.append(segment.element)
        if not edits:
            continue
        splice_segments(segments, edits)
        changed = True
    for node in root.iter():
        if id(node) not in covered and node.text and any(ch.isdigit() for ch in node.text) and \
                not isinstance(node, etree._Comment):
            replaced = restorer.substitute(node.text)
            if replaced != node.text:
                node.text = replaced
                changed = True
        for attr, value in list(node.attrib.items()):
            if any(ch.isdigit() for ch in value):
                if INTERNAL_PART_PATH.match(value) and node.get("TargetMode") != "External":
                    continue        # `diagrams/data1.xml`: имя части пакета, а не метка «Data1»
                replaced = restorer.substitute(value, after_underscore=True)
                if replaced != value and (_xml_name(node), etree.QName(attr).localname) in IDENTIFIER_ATTRS \
                        and _xml_name(node) != "tableColumn":      # имя столбца обязано совпадать с текстом заголовка
                    # Имя таблицы или диапазона Excel — идентификатор: «Смирнов_Алексей» при обезличивании читалось как слова,
                    # а вернуть его с пробелом нельзя (Excel и openpyxl такой файл не открывают).
                    replaced = re.sub(r"\s+", "_", replaced.strip())
                if replaced != value:
                    node.set(attr, replaced)
                    changed = True
    return changed


def _rewrite_sheet_references(path: str, renames: list[tuple[str, str]]) -> None:
    """Лист переименован под ограничения Excel: формулы, имена и диаграммы должны ссылаться на новое имя, а не на несуществующее."""
    with zipfile.ZipFile(path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]
    with zipfile.ZipFile(path, "w") as zout:
        for info, data in items:
            name = info.filename.lower()
            if name.endswith(".xml") and (_is_worksheet(info.filename) or name == "xl/workbook.xml" or "/charts/" in name):
                root = etree.fromstring(data, _parser())
                changed = False
                for node in root.iter():
                    if _xml_name(node) in {"f", "definedName", "formula1", "formula2", "formula"} and node.text:
                        text = node.text
                        for old, new in renames:
                            quoted_old, quoted_new = "'" + old.replace("'", "''") + "'!", "'" + new.replace("'", "''") + "'!"
                            text = text.replace(quoted_old, quoted_new)
                            if old != new:
                                # Имя без кавычек: при подстановке значения вместо метки кавычки не ставились.
                                plain_new = new if re.fullmatch(r"[A-Za-zА-Яа-яЁё_][\w.]*", new) else "'" + new.replace("'", "''") + "'"
                                text = re.sub(rf"(?<![\w.'])({re.escape(old)})!", lambda _m, n=plain_new: n + "!", text)
                        if text != node.text:
                            node.text, changed = text, True
                if changed:
                    data = etree.tostring(root, xml_declaration=data.lstrip().startswith(b"<?xml"), encoding="UTF-8")
            zout.writestr(info, data)


def _fix_sheet_names(workbook_root) -> list[tuple[str, str]]:
    """Имя листа Excel — до 31 знака и без `[]:*?/\\`. Подстановка исходных значений могла его испортить."""
    fixes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node in workbook_root.iter():
        if _xml_name(node) != "sheet":
            continue
        name = node.get("name") or ""
        fixed = INVALID_SHEET_CHARS.sub("_", name).strip("'")[:MAX_SHEET_NAME] or "Лист"
        candidate, counter = fixed, 2
        while candidate.casefold() in seen:
            suffix = f"_{counter}"
            candidate = fixed[:MAX_SHEET_NAME - len(suffix)] + suffix
            counter += 1
        seen.add(candidate.casefold())
        if candidate != name:
            node.set("name", candidate)
            fixes.append((name, candidate))
    return fixes


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

RESTORE_FONT = "china-s"
PLACEHOLDER_FONT_RANGE = (3.0, 8.0)


def _fit_font_size(text: str, width: float) -> float:
    size = PLACEHOLDER_FONT_RANGE[1]
    fontname, fontfile = font_for(text)
    while size > PLACEHOLDER_FONT_RANGE[0]:
        if text_width(text, fontname, fontfile, size) <= width:
            return size
        size -= .25
    return PLACEHOLDER_FONT_RANGE[0]


def _restore_pdf_extras(doc, restorer: Restorer) -> None:
    """Примечания, поля форм и закладки: метки в них возвращаются так же, как в тексте страниц."""
    try:
        toc = doc.get_toc(simple=False)
        fixed = False
        for entry in toc:
            new = restorer.substitute(str(entry[1]))
            if new != entry[1]:
                entry[1], fixed = new, True
        if fixed:
            doc.set_toc(toc)
    except Exception:
        pass
    for page in doc:
        try:
            for widget in (page.widgets() or []):
                value = widget.field_value
                if isinstance(value, str) and value:
                    new = restorer.substitute(value)
                    if new != value:
                        widget.field_value = new
                        widget.update()
        except Exception:
            pass
        try:
            for annot in (page.annots() or []):
                info = dict(annot.info or {})
                changed = {k: restorer.substitute(info[k]) for k in ("content", "title", "subject")
                           if isinstance(info.get(k), str) and info[k] and restorer.substitute(info[k]) != info[k]}
                if changed:
                    annot.set_info(**changed)
                    annot.update()
        except Exception:
            pass


def _restore_page_images(doc, page, restorer: Restorer, areas: list[fitz.Rect] | None = None) -> set[str]:
    """Картинки страницы, закрашенные при обезличивании, возвращаются из хранилища. -> метки, стоявшие на их тексте.

    areas — куда добавляются места на странице, где вернулась картинка: метка вне этих мест принадлежит обычному тексту."""
    import hashlib
    import json
    labels: set[str] = set()
    for img in page.get_images(full=True):
        try:
            current = doc.extract_image(img[0])["image"]
            original = None
            for _ in range(5):                       # обезличивание могло идти в несколько проходов: цепочка до исходной
                sha = hashlib.sha256(current).hexdigest()
                earlier = restorer.vault.original_image(sha)
                if earlier is None:
                    break
                original, current = earlier, earlier
                stored = restorer.vault.original_image(sha + "_labels")
                if stored:
                    labels.update(json.loads(stored.decode("utf-8")))
            if original is not None:
                if areas is not None:
                    try:
                        areas.extend(page.get_image_rects(img[0]))
                    except Exception:
                        pass
                page.replace_image(img[0], stream=original)
                labels.add(BARCODE_LABEL)           # метка на месте закрашенного кода уходит вместе с вернувшейся картинкой
        except Exception:
            continue
    return labels


def _vector_crop(restorer: Restorer, page_index: int, token: str, lead: fitz.Rect):
    """Прежние пиксели области, где стояла метка текста-рисунка: (область, PNG) или None."""
    import json
    from .formats import vector_key
    raw = restorer.vault.original_image(vector_key(page_index, token))
    if not raw:
        return None
    try:
        entries = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    mid = (lead.y0 + lead.y1) / 2
    for x0, y0, x1, y1, sha in entries:
        if abs(lead.x0 - x0) <= 4 and y0 - 1 <= mid <= y1 + 1:
            png = restorer.vault.original_image(sha)
            if png:
                return fitz.Rect(x0, y0, x1, y1), png
    return None


def _inside_longer(rect: fitz.Rect, token: str, other: fitz.Rect, other_token: str) -> bool:
    """Вхождение `rect` — часть более длинного токена `other` (а не отдельный токен рядом)."""
    if token == other_token or token not in other_token or not rect.intersects(other):
        return False
    area = rect.get_area()
    return area <= 0 or (rect & other).get_area() >= .5 * area


class _Room:
    """Свободное место справа от метки: слова страницы, не лежащие под метками, в сетке (без перебора всех слов на каждую метку)."""

    def __init__(self, page, pending: list[fitz.Rect], neighbours: list[tuple[fitz.Rect, str]]):
        self.limit = page.rect.x1 - 12.0
        under = RectGrid(pending)
        self.free = RectGrid(box for box, _ in neighbours if not under.intersects(box))

    def right_of(self, rect: fitz.Rect) -> float:
        limit = self.limit
        for box in self.free.near(fitz.Rect(rect.x1 - .5, rect.y0, max(self.limit, rect.x1), rect.y1)):
            if box.x0 < rect.x1 - .5:
                continue
            overlap = min(box.y1, rect.y1) - max(box.y0, rect.y0)
            if overlap > .4 * min(box.height, rect.height):
                limit = min(limit, box.x0 - 1.0)
        return max(rect.width, 20.0, limit - rect.x0)


def _collateral_runs(page, cuts: list[fitz.Rect], own: dict[str, list[fitz.Point]] | None = None) -> list[tuple]:
    """Чужой текст, который удаление рамок меток заденет (соседняя строка, наложенный текст): его надо дорисовать обратно.
    Своими считаются только символы самих меток (`own`: та же буква в той же точке). Текст другой строки, лежащий под
    рамкой метки (наложенные строки), своим не считается и дорисовывается: иначе возврат теряет его буквы."""
    if own is None:
        grid = RectGrid(cuts)
        return kept_chars(page, cuts, skip=lambda c, at: grid.contains(at))
    return kept_chars(page, cuts, skip=lambda c, at: any(abs(p.x - at.x) < .7 and abs(p.y - at.y) < .7 for p in own.get(c, ())))


def _glued_runs(text: str):
    """Complete adjacent-label runs, with greedy numeric IDs and no backtracking.

    Dots belong only to email-shaped labels or surrounding punctuation. A
    natural word, login, extra digit, or unknown suffix invalidates the run.
    """
    for run in re.finditer(r"[A-Za-z0-9_@.]{8,}", text):
        start, end = run.start(), run.end()
        while start < end and text[start] == ".":
            start += 1
        while end > start and text[end - 1] == ".":
            end -= 1
        pos, parts = start, []
        while pos < end:
            m = INNER_EMAIL_TOKEN_RE.match(text, pos, end)
            is_email = m is not None
            if m is None:
                m = INNER_TOKEN_RE.match(text, pos, end)
            if m is None:
                break
            parts.append((m, is_email))
            pos = m.end()
        if pos == end and len(parts) > 1:
            yield start, end, parts


def _glued_tokens(text: str, vault=None) -> set[str]:
    """Labels from completely parsed adjacent runs (exact known values in PDF)."""
    out: set[str] = set()
    for _, _, parts in _glued_runs(text):
        if vault is not None and not all(vault.lookup(*parse_match(m, email=is_email)).status == "ok"
                                         for m, is_email in parts):
            continue
        out.update(m.group(0) for m, _ in parts)
    return out


def _pdf_geometric_label_runs(chars: PageChars):
    """Rejoin label glyphs split into different PDF text blocks by redaction.

    Only exact horizontal adjacency is accepted. Read the entire visible run
    greedily, including all digits, so a known ID never wins over an unknown
    longer ID. The caller still requires an exact full token and vault lookup.
    """
    stems = "|".join(re.escape(kind.stem) for kind in KINDS if kind.code != "EMAIL")
    prefix = re.compile(rf"(?:{stems})[0-9]{{0,7}}(?:_[0-9]{{0,6}})?", re.I)
    grid: dict[tuple[int, int], list[int]] = {}
    for cid, char in enumerate(chars.chars):
        if char.rot == 0:
            cy = (char.y0 + char.y1) / 2
            grid.setdefault((int(char.x0 // 4), int(cy // 2)), []).append(cid)
    for line in chars.lines:
        if not line or chars.chars[line[-1]].c.isspace():
            continue
        text = "".join(chars.chars[cid].c for cid in line)
        if not prefix.fullmatch(text):
            continue
        ids = list(line)
        seen = set(ids)
        while len(ids) < 80:
            last = chars.chars[ids[-1]]
            if last.rot:
                break
            cy = (last.y0 + last.y1) / 2
            candidates = []
            for gx in range(int((last.x1 - .25) // 4), int((last.x1 + .25) // 4) + 1):
                for gy in range(int((cy - .75) // 2), int((cy + .75) // 2) + 1):
                    for cid in grid.get((gx, gy), ()):
                        char = chars.chars[cid]
                        if (cid not in seen and abs(char.x0 - last.x1) <= .25
                                and abs((char.y0 + char.y1) / 2 - cy) <= .75
                                and abs(char.size - last.size) <= max(.25, .2 * last.size)):
                            candidates.append(cid)
            if len(candidates) != 1:
                break                    # ambiguous geometry is never guessed
            cid = candidates[0]
            if len(ids) == len(line) and chars.chars[cid].c not in "0123456789_":
                break                    # only a detached ID/variant continues a label
            if not re.fullmatch(r"[A-Za-z0-9_@.]", chars.chars[cid].c):
                break
            if chars.chars[cid].c == "." and not any(chars.chars[i].c == "@" for i in ids):
                break                    # ordinary punctuation after a label
            seen.add(cid)
            ids.append(cid)
        if len(ids) > len(line):
            yield "".join(chars.chars[cid].c for cid in ids), tuple(ids)


_IMAGE_LABEL = re.compile(r"Image\d+")
_IMAGE_LABEL_WRAPPED = re.compile(r"(?<!\w)Image(?:\d+|[ \t]*\n[ \t]*\d+)(?!\w)")


def _placeholder_label_boxes(doc, vault) -> dict[int, list[fitz.Rect]]:
    """Подписи ImageN, нарисованные обезличиванием поверх заглушек картинок (imagereplace.replace_pdf_images): по страницам,
    рамки слов внутри конкретной заглушки с оригиналом в хранилище. Идентичность картинки задаётся случайным
    /AnonImg, а не числом в подписи. Без известного оригинала подпись сохраняется вместе с заглушкой.
    Читать до возврата картинок."""
    known_images: set[int] = set()
    for xref in range(1, doc.xref_length()):
        try:
            kind, ident = doc.xref_get_key(xref, imagereplace.PDF_ID_KEY)
        except Exception:
            continue
        if kind != "null" and ident and vault.original_image("pdfimg_" + ident.strip("()")) is not None:
            known_images.add(xref)
    if not known_images:
        return {}
    out: dict[int, list[fitz.Rect]] = {}
    for page in doc:
        all_words = page.get_text("words")
        words = [w for w in all_words if _IMAGE_LABEL.fullmatch(w[4])]
        known_areas: list[fitz.Rect] = []
        try:
            images = page.get_images(full=True)
            all_known = all(info[0] in known_images for info in images)
            for info in images:
                if info[0] in known_images:
                    # get_image_rects matches image pixel digests: all our gray
                    # placeholders share one, even if their vault IDs differ.
                    # With an unknown image present use its exact page resource
                    # name, never the digest-based list of all gray rectangles.
                    if all_known:
                        known_areas.extend(fitz.Rect(r) for r in page.get_image_rects(info[0]))
                    elif info[-1] == 0:
                        box = page.get_image_bbox(info)
                        if not box.is_empty and not box.is_infinite:
                            known_areas.append(box)
        except Exception:
            continue
        boxes = []
        for w in words:
            box = fitz.Rect(w[:4])
            centre = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
            if any(a.contains(centre) for a in known_areas):
                boxes.append(box)
        # insert_textbox wraps a cosmetic ImageN caption on a narrow image.
        # Its N is not a vault ID: restoration uses the exact random /AnonImg
        # identity above. Only a two-word caption block inside that known image
        # may be removed; natural text outside it and unknown images are kept.
        for area in known_areas:
            # MuPDF may extract the two lines as different blocks, or merge
            # captions of adjacent images into one block. Geometry is the
            # common invariant; block/line numbers are not.
            block = [word for word in all_words
                     if (area + (-.1, -.1, .1, .1)).contains(fitz.Rect(word[:4]))]
            if len(block) != 2:
                continue
            first, second = sorted(block, key=lambda word: (word[1], word[0]))
            if first[4] != "Image" or not second[4].isdigit() or second[1] < first[3] - .5:
                continue
            box = fitz.Rect(first[:4]) | fitz.Rect(second[:4])
            if any((area + (-.1, -.1, .1, .1)).contains(box) for area in known_areas):
                boxes.append(box)
        if boxes:
            out[page.number] = boxes
    return out


def _erase_placeholder_labels(doc, boxes: dict[int, list[fitz.Rect]]) -> None:
    """Подпись ImageN была дорисована текстом поверх заглушки; вместе с возвращённой картинкой её надо убрать, иначе в
    восстановленном файле остаётся лишний текст, которого не было в исходном. Рамки по одной на символ подписи: соседний
    текст (колонтитул под подписью) не задевается."""
    for page_index, rects in boxes.items():
        page = doc[page_index]
        pc = PageChars(page)
        view = pc.view("lines")
        cuts: list[fitz.Rect] = []
        own: dict[str, list[fitz.Point]] = {}
        for m in _IMAGE_LABEL_WRAPPED.finditer(view.text):
            ids = view.ids(m.start(), m.end())
            if not ids:
                continue
            segs = pc.segments(ids)
            if not any(fitz.Rect(r).intersects(sg.rect) for r in rects for sg in segs):
                continue
            cuts.extend(pc.slivers(ids))
            for i in ids:
                ch = pc.chars[i]
                own.setdefault(ch.c, []).append(fitz.Point((ch.x0 + ch.x1) / 2, (ch.y0 + ch.y1) / 2))
        if not cuts:
            continue
        # Своими считаются только символы подписи (та же буква в той же точке); всё остальное под рамками дорисовывается.
        collateral = kept_chars(page, cuts, skip=lambda c, at: any(abs(p.x - at.x) < .7 and abs(p.y - at.y) < .7 for p in own.get(c, ())))
        for cut in cuts:
            page.add_redact_annot(cut, fill=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        redraw_lost(page, collateral)


def restore_pdf(src: Path, dst: Path, restorer: Restorer) -> bool:
    doc = fitz.open(src)
    label_boxes = _placeholder_label_boxes(doc, restorer.vault)
    imagereplace.restore_pdf_images(doc, restorer.vault)
    if label_boxes:
        _erase_placeholder_labels(doc, label_boxes)
    metadata = dict(doc.metadata or {})
    restored_meta = {k: restorer.substitute(v) for k, v in metadata.items() if isinstance(v, str) and v}
    if str(restored_meta.get("producer", "")).startswith("anonymizer:"):
        restored_meta["producer"] = ""       # служебная пометка хранилища; прежнее значение не сохранялось
    if any(restored_meta[k] != metadata.get(k) for k in restored_meta):
        doc.set_metadata({**metadata, **restored_meta})
    _restore_pdf_extras(doc, restorer)
    for page in doc:
        picture_areas: list[fitz.Rect] = []
        picture_labels = _restore_page_images(doc, page, restorer, picture_areas)
        pending: list[tuple[fitz.Rect, str]] = []
        rect_token: dict[int, str] = {}
        picture_rects: set[int] = set()        # метки, на месте которых вернётся картинка
        crops: list[tuple] = []                # (область, PNG) прежних пикселей текста, нарисованного контурами
        cuts: list[tuple] = []                # (рамка, заливка): рамки редактирования: по одной на символ метки, соседние буквы не задеваются
        colours: dict[int, tuple] = {}
        pc = PageChars(page)
        view = pc.view("lines")
        # Keep recognized positions, not just token spellings. Searching a known
        # spelling again would also select its prefix inside an unknown ID.
        positions: dict[str, set[tuple[int, ...]]] = {}
        for regex in (TOKEN_RE, EMAIL_TOKEN_RE):
            for match in regex.finditer(view.text):
                positions.setdefault(match.group(0), set()).add(tuple(view.ids(*match.span())))
        for _, _, parts in _glued_runs(view.text):
            if all(restorer.vault.lookup(*parse_match(match, email=is_email)).status == "ok"
                   for match, is_email in parts):
                for match, _ in parts:
                    positions.setdefault(match.group(0), set()).add(tuple(view.ids(*match.span())))
        for token, ids in _pdf_geometric_label_runs(pc):
            covered = set(ids)
            for key in list(positions):
                positions[key] = {group for group in positions[key] if not set(group) <= covered}
            match = TOKEN_RE.fullmatch(token)
            if match is not None:
                if restorer.vault.lookup(*parse_match(match)).status == "ok":
                    positions.setdefault(token, set()).add(ids)
                else:
                    restorer.stats.unknown[token] = restorer.stats.unknown.get(token, 0) + 1
            else:
                for _, _, parts in _glued_runs(token):
                    if all(restorer.vault.lookup(*parse_match(m, email=email)).status == "ok" for m, email in parts):
                        for match, _ in parts:
                            positions.setdefault(match.group(0), set()).add(ids[match.start():match.end()])
        taken: set[int] = set()
        own_chars: dict[str, list[fitz.Point]] = {}
        for token in sorted(positions, key=len, reverse=True):
            original = restorer.substitute(token)
            if original == token:
                continue
            for ids in sorted(positions[token]):
                if not ids or taken.intersection(ids):
                    continue                  # вхождение внутри более длинного токена
                taken.update(ids)
                for i in ids:
                    ch = pc.chars[i]
                    own_chars.setdefault(ch.c, []).append(fitz.Point((ch.x0 + ch.x1) / 2, (ch.y0 + ch.y1) / 2))
                segs = pc.segments(ids)
                lead = segs[0].rect if segs else None
                picture = token in picture_labels and lead is not None and any(a.intersects(lead) for a in picture_areas)
                crop = _vector_crop(restorer, page.number, token, lead) if lead is not None and not picture else None
                for k, seg in enumerate(segs):
                    pending.append((seg.rect, original if k == 0 else ""))
                    rect_token[id(seg.rect)] = token
                    colours[id(seg.rect)] = rgb(seg.color)
                    if picture or crop:
                        picture_rects.add(id(seg.rect))
                    if crop and k == 0:
                        crops.append(crop)
                cuts.extend((c, False if (picture or crop) else (1, 1, 1)) for c in pc.slivers(ids))
        if BARCODE_LABEL in picture_labels:
            for rect in page.search_for(BARCODE_LABEL):
                pending.append((rect, ""))
                rect_token[id(rect)] = BARCODE_LABEL
                picture_rects.add(id(rect))
                cuts.append((rect, False))
                for ch in pc.chars:
                    centre = fitz.Point((ch.x0 + ch.x1) / 2, (ch.y0 + ch.y1) / 2)
                    if rect.contains(centre):
                        own_chars.setdefault(ch.c, []).append(centre)
        if not pending:
            continue
        neighbours = [(fitz.Rect(w[:4]), w[4]) for w in page.get_text("words")]
        collateral = _collateral_runs(page, [c for c, _ in cuts], own_chars)
        for cut, fill in cuts:
            page.add_redact_annot(cut, fill=fill)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        # Потерянные чужие буквы дорисовываются до возвращаемых значений: иначе вернувшееся значение с теми же буквами рядом
        # (адрес почты поверх соседней строки) принимается за живую букву, и чужая буква пропадает.
        redraw_lost(page, collateral)
        room = _Room(page, [r for r, _ in pending], neighbours)
        for rect, original in pending:
            if id(rect) in picture_rects:
                continue
            if not original:
                continue
            available = room.right_of(rect)
            size = _fit_font_size(original, available)
            put_text(page, (rect.x0, rect.y1 - size * .2), original, size, colours.get(id(rect), (0, 0, 0)))
        for area, png in crops:
            try:
                page.insert_image(area, stream=png)
            except Exception:
                pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    pages = len(doc)
    doc.save(dst, garbage=4, deflate=True, clean=True)
    doc.close()
    check = fitz.open(dst)
    ok = len(check) == pages
    check.close()
    return ok


def count_tokens(text: str) -> int:
    return sum(1 for _ in TOKEN_RE.finditer(text)) + sum(1 for _ in EMAIL_TOKEN_RE.finditer(text))
