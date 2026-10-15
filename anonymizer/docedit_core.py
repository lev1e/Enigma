"""Общая основа движка правки Office-файлов (P2A): пакет OOXML, ошибки, лимиты, защита меток.

Файл правится на месте через lxml: меняются только затронутые части, остальные записываются в архив байт в байт
(без перепаковки содержимого). Любая ошибка до конца — исключение PatchRejected, результат не выдаётся (атомарность).
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field

from lxml import etree

from .restore import TEXT_MARK_RE
from .tokens import EMAIL_TOKEN_RE, KINDS, TOKEN_RE

MAX_ZIP_BYTES = 256 * 1024 * 1024
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU_PT = 12700


class PatchRejected(ValueError):
    """Патч отклонён целиком. code — машинный код причины, text — русское пояснение, details — без текста документа."""

    def __init__(self, code: str, text: str, op_index: int | None = None, at: str | None = None):
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text
        self.op_index = op_index
        self.at = at

    def report(self) -> dict:
        return {"ok": False, "code": self.code, "message": self.text, "op_index": self.op_index, "at": self.at}


@dataclass
class Opts:
    """Настройки. Значения по умолчанию совпадают с policy.edit из спецификации S14."""
    max_ops: int = 200
    max_growth: float = 0.30            # суммарный рост текста по заменяемым абзацам (0.30 = +30 %)
    growth_floor: int = 40              # символов запаса на операцию: короткий заголовок вправе вырасти
    max_text: int = 4000                # длина одного нового текста
    max_total_insert: int = 20000
    max_comment: int = 600
    max_elements: int = 20000           # потолок размера outline
    safe_fonts: tuple[str, ...] = ()    # дополнительные шрифты поверх шрифтов документа/темы (по решению политики)
    known_labels: frozenset[str] = frozenset()   # метки файла, если известны снаружи; иначе берутся из текста документа
    text: str = "full"                  # "full" | "stub" (только для outline)
    min_font_pt: float = 4.0
    max_font_pt: float = 400.0
    max_col_width_pt: float = 1500.0
    max_numfmt: int = 120


def fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def labels_of(text: str) -> set[str]:
    return {m.group(0) for rx in (TOKEN_RE, EMAIL_TOKEN_RE) for m in rx.finditer(text)}


_STEMS = sorted({k.stem for k in KINDS} | {"Email"}, key=len, reverse=True)
_LOOSE_RE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, _STEMS)) + r")[\s_\-]*(\d{1,7})(?![A-Za-z0-9])", re.I)


def loose_labels(text: str, known: set[str]) -> list[str]:
    """Искажённые метки: «Name 1», «name_1», «NAME1» там, где в файле есть настоящая метка Name1."""
    exact_spans = {(m.start(), m.end()) for rx in (TOKEN_RE, EMAIL_TOKEN_RE) for m in rx.finditer(text)}
    bad = []
    by_lower = {k.lower(): k for k in known}
    for m in _LOOSE_RE.finditer(text):
        if (m.start(), m.end()) in exact_spans:
            continue
        canon = (m.group(1) + m.group(2)).lower()
        if canon in by_lower or any(k.lower().startswith(canon + "_") for k in known):
            bad.append(m.group(0))
    return bad


def check_labels(old: str | None, new: str, known: set[str], op_index: int, at: str, *, allow_removal: bool = False) -> list[str]:
    """Защита меток. Возвращает список снятых меток (для карточки), либо бросает PatchRejected."""
    old_l = labels_of(old) if old else set()
    new_l = labels_of(new)
    removed = sorted(old_l - new_l)
    if removed and not allow_removal:
        raise PatchRejected("label_removed", f"Метки не должны пропадать: {', '.join(removed)}.", op_index, at)
    unknown = sorted(l for l in new_l - old_l if l not in known)
    if unknown:
        raise PatchRejected("label_unknown", f"Неизвестные метки (их нет в файле): {', '.join(unknown)}.", op_index, at)
    if loose_labels(new, known | old_l):
        raise PatchRejected("label_loose", "Метка записана с искажением (регистр, пробел или подчёркивание).", op_index, at)
    return removed


def check_plain_text(text, op_index: int, at: str, opts: Opts, *, allow_empty: bool = False, allow_newline: bool = False) -> str:
    if not isinstance(text, str):
        raise PatchRejected("bad_type", "Текст должен быть строкой.", op_index, at)
    if not text and not allow_empty:
        raise PatchRejected("bad_text", "Пустой текст.", op_index, at)
    if len(text) > opts.max_text:
        raise PatchRejected("text_too_long", f"Текст длиннее {opts.max_text} символов.", op_index, at)
    if TEXT_MARK_RE.search(text):
        raise PatchRejected("bad_text", "Недопустимые служебные символы.", op_index, at)
    for ch in text:
        if ch == "\n" and allow_newline:
            continue
        if unicodedata.category(ch) in ("Cc", "Cs", "Co") or ch in "  ￾￿":
            raise PatchRejected("bad_text", "Управляющие символы в тексте недопустимы.", op_index, at)
    return text


def stub_text(text: str) -> str:
    """Заглушка той же длины: буквы и цифры -> x; пробелы, знаки и метки сохраняются (метки — псевдонимы, не данные)."""
    keep: set[int] = set()
    for rx in (TOKEN_RE, EMAIL_TOKEN_RE):
        for m in rx.finditer(text):
            keep.update(range(m.start(), m.end()))
    return "".join(ch if (i in keep or not ch.isalnum()) else "x" for i, ch in enumerate(text))


# --- пакет OOXML -------------------------------------------------------------------------------------------

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


class Package:
    """Архив OOXML в памяти. Изменённые части сериализуются заново, остальные пишутся теми же байтами."""

    def __init__(self, data: bytes):
        if len(data) > MAX_ZIP_BYTES:
            raise PatchRejected("too_big", "Файл слишком большой.")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise PatchRejected("bad_file", "Файл не является документом Office.") from exc
        self.infos = zf.infolist()
        names = [i.filename for i in self.infos]
        if len(set(names)) != len(names):
            raise PatchRejected("bad_file", "В архиве повторяются имена частей.")
        self.raw: dict[str, bytes] = {}
        total = 0
        for info in self.infos:
            if info.file_size > MAX_ZIP_BYTES:
                raise PatchRejected("too_big", "Часть файла слишком велика.")
            total += info.file_size
            if total > MAX_ZIP_BYTES:
                raise PatchRejected("too_big", "Файл слишком большой после распаковки.")
            self.raw[info.filename] = zf.read(info)
        self._xml: dict[str, etree._Element] = {}
        self.dirty: set[str] = set()
        self.removed: set[str] = set()
        self.added: dict[str, bytes] = {}

    def has(self, name: str) -> bool:
        return name in self.raw and name not in self.removed

    def xml(self, name: str):
        """Корень XML-части (кэшируется; правки видны всем)."""
        if name in self.removed or name not in self.raw:
            raise PatchRejected("bad_file", f"В файле нет части {name}.")
        if name not in self._xml:
            try:
                self._xml[name] = etree.fromstring(self.raw[name], _PARSER)
            except etree.XMLSyntaxError as exc:
                raise PatchRejected("bad_file", f"Часть {name} повреждена.") from exc
        return self._xml[name]

    def touch(self, name: str) -> None:
        self.xml(name)
        self.dirty.add(name)

    def remove(self, name: str) -> None:
        if name in self.raw:
            self.removed.add(name)
            self._xml.pop(name, None)
            self.dirty.discard(name)

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """Связи части: id -> (type, абсолютное имя цели)."""
        d, _, base = part.rpartition("/")
        rel = f"{d}/_rels/{base}.rels" if d else f"_rels/{base}.rels"
        if not self.has(rel):
            return {}
        out = {}
        for r in self.xml(rel):
            if r.get("TargetMode") == "External":
                out[r.get("Id")] = (r.get("Type", ""), "")
                continue
            out[r.get("Id")] = (r.get("Type", ""), resolve_target(d, r.get("Target", "")))
        return out

    def rels_name(self, part: str) -> str:
        d, _, base = part.rpartition("/")
        return f"{d}/_rels/{base}.rels" if d else f"_rels/{base}.rels"

    def serialize(self) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for info in self.infos:
                name = info.filename
                if name in self.removed:
                    continue
                if name in self.dirty:
                    payload = etree.tostring(self._xml[name], xml_declaration=True, encoding="UTF-8", standalone=True)
                else:
                    payload = self.raw[name]
                zi = zipfile.ZipInfo(name, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zi.create_system = info.create_system
                zf.writestr(zi, payload)
        return out.getvalue()


def resolve_target(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    parts = [p for p in base_dir.split("/") if p]
    for seg in target.split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return "/".join(parts)


# --- упорядоченная вставка дочерних элементов (схема OOXML чувствительна к порядку) --------------------------

def set_child(parent, tag: str, order: list[str], make=None):
    """Найти или создать дочерний элемент tag (в Clark-нотации) с соблюдением порядка order (список Clark-имён)."""
    for ch in parent:
        if ch.tag == tag:
            return ch
    el = make() if make else etree.Element(tag)
    idx = order.index(tag)
    after = set(order[idx + 1:])
    for i, ch in enumerate(parent):
        if ch.tag in after:
            parent.insert(i, el)
            return el
    parent.append(el)
    return el


def drop_child(parent, tag: str) -> None:
    for ch in list(parent):
        if ch.tag == tag:
            parent.remove(ch)


def q(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


HEX6 = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def parse_color(value, op_index: int, at: str) -> str:
    m = HEX6.match(value) if isinstance(value, str) else None
    if not m:
        raise PatchRejected("bad_color", "Цвет задаётся как RRGGBB.", op_index, at)
    return m.group(1).upper()


@dataclass
class Elem:
    """Адресуемый элемент: узел XML и его свойства."""
    addr: str
    kind: str
    node: object
    part: str
    text: str | None = None
    editable: bool = True
    reason: str = ""
    parent: str = ""
    extra: dict = field(default_factory=dict)
