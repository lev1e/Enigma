"""Структура текстовых таблиц и JSON: ячейки CSV/TSV и строки JSON.

Детектор видит файл как сплошной текст, поэтому находка могла пересечь границу ячейки (`Смирнов,Name1` вместо
двух ячеек) или захватить кавычку (`"type":"Company2` без закрывающих `"}`). Здесь структурные кавычки заменяются
пробелами (длина текста не меняется, смещения сохраняются), а находки обрезаются по границам ячеек и строк.
Столбцы «Фамилия», «Имя», «Отчество», «ФИО» дополнительно считаются именами: отдельное слово в такой ячейке
иначе не отличить от обычного.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace

from .models import Decision, Finding
from .bounded_regex import markup_tokens

CSV_SUFFIXES = (".csv", ".tsv")

_HEADER_PERSON = re.compile(
    r"(?i)^\W*(?:фамилия(?:[\s,/]+имя(?:[\s,/]+отчество)?)?|фамилия\s+и\.?\s?о\.?|имя(?:\s+отчество)?|отчество|"
    r"фио|ф\.?\s?и\.?\s?о\.?|(?:last|first|middle|given|full)[ _-]?name|surname|patronymic)\W*$")
_PERSON_CELL = re.compile(r"[^\W\d_]+(?:[-'.\s,][^\W\d_]+){0,3}\.?")
_SEPARATORS = ",;\t|"


def _unquoted_counts(line: str) -> dict[str, int]:
    counts = dict.fromkeys(_SEPARATORS, 0)
    quoted = False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in counts:
            counts[ch] += 1
    return counts


def _delimiter(text: str, suffix: str) -> str:
    if suffix == ".tsv":
        return "\t"
    lines = [ln for ln in text.split("\n", 12)[:12] if ln.strip()]
    per_line = [_unquoted_counts(ln) for ln in lines]
    best, best_score = ",", (-1, -1)
    for d in (";", "\t", "|", ","):
        values = [c[d] for c in per_line]
        if not values or not max(values):
            continue
        consistent = sum(1 for v in values if v == values[0] and v > 0)
        score = (consistent, values[0])
        if score > best_score:
            best, best_score = d, score
    return best


def _csv_cells(text: str, delim: str) -> tuple[list[tuple[int, int, int, int]], list[int]]:
    """[(строка, столбец, начало, конец содержимого)] и позиции структурных кавычек."""
    cells, quotes = [], []
    i, n, row, col = 0, len(text), 0, 0
    while True:
        if i < n and text[i] == '"':
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            start, end = i + 1, j
            quotes.append(i)
            if j < n:
                quotes.append(j)
            k = j + 1 if j < n else j
            while k < n and text[k] not in (delim, "\n", "\r"):
                k += 1
            if j < n and k > j + 1:
                # Текст после закрывающей кавычки до разделителя («"A";"B"» в файле с запятыми) — тоже содержимое ячейки,
                # иначе всё, что в нём найдено, обрезалось бы как «вне ячейки» и оставалось в файле.
                end = k
                quotes.extend(q for q in range(j + 1, k) if text[q] == '"')
        else:
            k = i
            while k < n and text[k] not in (delim, "\n", "\r"):
                k += 1
            start, end = i, k
        cells.append((row, col, start, end))
        if k >= n:
            break
        if text[k] == delim:
            col += 1
            i = k + 1
        else:
            if text[k] == "\r" and k + 1 < n and text[k + 1] == "\n":
                k += 1
            row += 1
            col = 0
            i = k + 1
            if i >= n:
                break
    return cells, quotes


_NUMBER_CELL = re.compile(r"^[\s$€£]*-?(?:\d{1,3}(?:[ ,' ]\d{3})+|\d+)(?:[.,]\d+)?(?:[eE][-+]?\d+)?\s*%?$")
_CODE_CELL = re.compile(r"^[A-Z0-9][A-Z0-9_./-]{0,5}$")
# Заголовок, по которому столбец несёт идентификаторы или контакты: их числа и коды ищутся как обычно.
_ID_OR_CONTACT_HEADER = re.compile(
    r"(?i)инн|inn\b|tin\b|tax|кпп|kpp|огрн|ogrn|снилс|snils|паспорт|passport|серия|карт|card|pan\b|бик|bik\b|сч[её]т|account|iban|омс|полис|"
    r"телефон|тел\b|тел\.|phone|mobile|моб|факс|fax|whatsapp|telegram|водител|licen|ssn|контакт|contact")
_NAME_HEADER = re.compile(r"(?i)фио|имя|фамил|отчеств|name|компан|организ|клиент|контрагент|company|org|фирм|наименован|назван|проект|project|бренд|brand")
_NUMERIC_FALSE = frozenset({"PHONE", "SNILS", "CARD", "INN_ORG", "INN_PERSON", "OGRN", "KPP", "BIK", "OMS", "BANK_ACCOUNT",
                            "PASSPORT", "DRIVER_LICENSE"})
_VOCAB_HEADER = re.compile(r"(?i)country|страна|currency|валют|region|регион|continent|континент|language|язык|capital|official[_ ]name|"
                           r"unterm|cldr|display[_ ]name|short[_ ]name|formal")
_VOCAB_FALSE = frozenset({"PERSON", "POSSIBLE_PERSON", "ORG", "PROJECT", "POSSIBLE_ENTITY", "TERM"})
_CODE_FALSE = frozenset({"ORG", "PROJECT", "POSSIBLE_ENTITY", "TERM", "POSSIBLE_PERSON"})


# Строка, вставленная в столбец стран, но не название страны: инициал («Thomas L. Whitfield»), двоеточие, цифры, «@», «<» или пять слов и больше.
_FREE_TEXT_CELL = re.compile(r"[\d:@<]|\b[A-ZА-ЯЁ]\.|^\S+(?:\s+\S+){4,}")


def _column_drops(text: str, cells) -> list[tuple[int, int, frozenset]]:
    """Столбцы CSV, значения которых по заголовку и виду не могут быть телефоном, СНИЛС, ИНН или организацией.

    Числовой столбец без подписи «ИНН / Телефон / Карта» (ВВП, население, id) не даёт находок номерных видов;
    столбец коротких кодов ISO / FIFA / FIPS и заголовки столбцов не дают организаций. Подпись столбца важнее вида значений."""
    columns: dict[int, list[tuple[int, int, int]]] = {}
    for row, col, s, e in cells:
        columns.setdefault(col, []).append((row, s, e))
    drops: list[tuple[int, int, frozenset]] = []
    # Вторая шапка посреди файла («Name,Phone,Email,SSN,Passport,Address»): строки под ней несут идентификаторы, как бы ни было подписано начало файла.
    by_row: dict[int, list[tuple[int, int, int]]] = {}
    for row, col, s, e in cells:
        by_row.setdefault(row, []).append((col, s, e))
    inner_rows: set[int] = set()
    for row in sorted(by_row):
        if row == 0:
            continue
        hits = [c for c, s, e in by_row[row] if 0 < len(text[s:e].strip()) <= 24 and _ID_OR_CONTACT_HEADER.search(text[s:e])]
        if len(hits) >= 3:
            nxt = row + 1
            while nxt in by_row and len(by_row[nxt]) == len(by_row[row]):
                inner_rows.add(nxt)
                nxt += 1
    for col, items in columns.items():
        items = [it for it in items if it[0] not in inner_rows] if inner_rows else items
        header = next((text[s:e] for row, s, e in items if row == 0), "")
        body = [(s, e) for row, s, e in items if row > 0 and text[s:e].strip()]
        for row, s, e in items:
            if row == 0 and text[s:e].strip():
                drops.append((s, e, _CODE_FALSE))
        if len(body) >= 3 and _VOCAB_HEADER.search(header) and not _HEADER_PERSON.match(header):
            # Столбец стран, валют, регионов, языков: название «Costa Rica» или «Australian Dollar» — не человек.
            drops.extend((s, e, _VOCAB_FALSE) for s, e in body if not _FREE_TEXT_CELL.search(text[s:e]))
            continue
        if len(body) < 3 or _ID_OR_CONTACT_HEADER.search(header):
            continue
        numeric = sum(1 for s, e in body if _NUMBER_CELL.match(text[s:e]))
        codes = sum(1 for s, e in body if _CODE_CELL.match(text[s:e].strip()))
        kinds: frozenset = frozenset()
        if numeric >= 0.85 * len(body):
            kinds = _NUMERIC_FALSE | _CODE_FALSE
        elif codes + numeric >= 0.85 * len(body) and not _NAME_HEADER.search(header):
            kinds = _CODE_FALSE | (_NUMERIC_FALSE if numeric >= 0.5 * len(body) else frozenset())
        if kinds:
            # Только сами числа и коды: «passport no. 301427730», вставленное в числовой столбец, остаётся паспортом.
            drops.extend((s, e, kinds) for s, e in body
                         if _NUMBER_CELL.match(text[s:e]) or _CODE_CELL.match(text[s:e].strip()))
    drops.sort(key=lambda d: d[0])
    return drops


def _json_segments(text: str) -> tuple[list[tuple[int, int]], list[int], set[tuple[int, int]]] | None:
    try:
        json.loads(text)
    except ValueError:
        return None
    segments, quotes, keys = [], [], set()
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    # «\n» внутри строки — перевод строки, а не буква слова: без маски граница («\nИНН») не видна.
                    quotes += [j, j + 1]
                    j += 2
                else:
                    j += 1
            quotes += [i, j]
            segments.append((i + 1, j))
            k = j + 1
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] == ":":
                keys.add((i + 1, j))
            i = j + 1
        elif ch in " \t\r\n{}[],:":
            i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n{}[],:"':
                j += 1
            segments.append((i, j))
            i = j
    return segments, quotes, keys


# -- HTML ------------------------------------------------------------------------
# Разметка (теги, атрибуты, скрипты, стили) не текст документа: детектор видел её как слова и принимал за
# названия («Entity">]<», «class», «id»), а замена внутри тега ломала страницу. Для поиска теги закрываются
# пробелами (длина не меняется), блочные теги дают перевод строки, чтобы соседние абзацы не склеивались в имя.
# Остаются видимыми: текст между тегами, комментарии, данные JSON в скриптах и значения атрибутов, которые читает человек
# (alt, title, placeholder, aria-label, mailto:/tel: в href).
HTML_SUFFIXES = (".html", ".htm", ".xhtml")
_HTML_TOKEN = re.compile(
    r"<!--(?P<com>.*?)-->|<(?P<sname>script|style)\b(?P<sattr>[^>]*)>(?P<sbody>.*?)</(?P=sname)\s*>"
    r"|<[A-Za-z/!?](?:\"[^\"]*\"|'[^']*'|[^>\"'])*>", re.S | re.I)
_HTML_ATTR = re.compile(r"""(?i)\b(alt|title|placeholder|aria-label|label|summary|href|content|data-[\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_HTML_BLOCK = re.compile(r"(?i)^</?(?:br|p|div|li|ul|ol|tr|td|th|table|h[1-6]|section|article|header|footer|blockquote|pre|dd|dt|dl|hr|body|html|head|title|form|nav|aside|figure|figcaption|caption|option|select|textarea|button)\b")
_HTML_DATA_TEXT = re.compile(r"^(?![{\[<])(?:\S+\s+){2,}\S+")
_HTML_KEEP_HREF = re.compile(r"(?i)^(?:mailto|tel):")


def _html_layout(text: str) -> tuple[str, list[tuple[int, int]]]:
    chars = list(text)
    visible: list[tuple[int, int]] = []

    def blank(a: int, b: int, lead: str = " ") -> None:
        if b > a:
            chars[a:b] = [" "] * (b - a)
            chars[a] = lead

    pos = 0
    for m in markup_tokens(text, _HTML_TOKEN):
        if m.start() > pos:
            visible.append((pos, m.start()))
        pos = m.end()
        if m.group("com") is not None:
            blank(m.start(), m.start("com"), "\n")
            blank(m.end("com"), m.end(), "\n")
            visible.append((m.start("com"), m.end("com")))
            continue
        if m.group("sname"):
            body_a, body_b = m.start("sbody"), m.end("sbody")
            blank(m.start(), body_a, "\n")
            blank(body_b, m.end(), "\n")
            if m.group("sname").lower() == "script" and "json" in m.group("sattr").lower():
                found = _json_segments(text[body_a:body_b])
                if found:
                    segs, quotes, _ = found
                    for q in quotes:
                        chars[body_a + q] = " "
                    visible.extend((body_a + a, body_a + b) for a, b in segs)
                    continue
            blank(body_a, body_b, "\n")
            continue
        tag = m.group(0)
        blank(m.start(), m.end(), "\n" if _HTML_BLOCK.match(tag) else " ")
        is_author = re.search(r"(?i)\bname\s*=\s*[\"'](?:author|description|keywords)[\"']", tag) is not None
        for am in _HTML_ATTR.finditer(tag):
            name = am.group(1).lower()
            group = 2 if am.group(2) is not None else 3
            a, b = m.start() + am.start(group), m.start() + am.end(group)
            if name == "href":
                if not _HTML_KEEP_HREF.match(am.group(group)):
                    continue
            elif name == "content" and not is_author:
                continue
            elif name.startswith("data-") and not _HTML_DATA_TEXT.match(am.group(group)):
                continue          # data-owner="Ship to ... contact Name +1-..." читает человек, data-id="x7" и JSON нет
            if b > a:
                chars[a:b] = list(text[a:b])
                chars[a - 1] = "\n"
                if b < len(chars):
                    chars[b] = "\n"
                visible.append((a, b))
    if pos < len(text):
        visible.append((pos, len(text)))
    visible.sort()
    return "".join(chars), visible


# -- XML -------------------------------------------------------------------------
# Файл XML — это узлы с текстом и значения атрибутов. Теги, объявление, DOCTYPE и пространства имён — разметка:
# находка, перешагнувшая `</para><para>`, ломала документ («Secret2 The Court» вместо закрывающего тега).
# Разметка закрывается пробелами и переводами строк (длина не меняется), а находки обрезаются по границам узлов.
XML_SUFFIXES = (".xml",)
_XML_TOKEN = re.compile(
    r"<!--(?P<com>.*?)-->|<!\[CDATA\[(?P<cdata>.*?)\]\]>|<\?.*?\?>|<![A-Za-z](?:\"[^\"]*\"|'[^']*'|\[[^\]]*\]|[^>\"'\[])*>"
    r"|<[A-Za-z_:/](?:\"[^\"]*\"|'[^']*'|[^>\"'])*>", re.S)
_XML_ATTR = re.compile(r"""([^\s=<>/"']+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_XML_TECH_ATTR = re.compile(r"(?i)^(?:xmlns(?::[\w.-]+)?|xsi:[\w.-]+|xml:[\w.-]+|version|encoding|standalone|id|ref|idref|class|type)$")


def _xml_layout(text: str) -> tuple[str, list[tuple[int, int]]]:
    chars = list(text)
    visible: list[tuple[int, int]] = []

    def blank(a: int, b: int, lead: str = "\n") -> None:
        if b > a:
            chars[a:b] = [" "] * (b - a)
            chars[a] = lead

    pos = 0
    for m in markup_tokens(text, _XML_TOKEN, xml=True):
        if m.start() > pos:
            visible.append((pos, m.start()))
        pos = m.end()
        if m.group("com") is not None:
            blank(m.start(), m.start("com"))
            blank(m.end("com"), m.end())
            visible.append((m.start("com"), m.end("com")))
            continue
        if m.group("cdata") is not None:
            blank(m.start(), m.start("cdata"))
            blank(m.end("cdata"), m.end())
            visible.append((m.start("cdata"), m.end("cdata")))
            continue
        tag = m.group(0)
        blank(m.start(), m.end())
        if tag.startswith("</") or tag.startswith("<?") or tag.startswith("<!"):
            continue
        for am in _XML_ATTR.finditer(tag):
            if _XML_TECH_ATTR.match(am.group(1)):
                continue
            group = 2 if am.group(2) is not None else 3
            a, b = m.start() + am.start(group), m.start() + am.end(group)
            if b > a:
                chars[a:b] = list(text[a:b])
                chars[a - 1] = "\n"
                if b < len(chars):
                    chars[b] = "\n"
                visible.append((a, b))
    if pos < len(text):
        visible.append((pos, len(text)))
    visible.sort()
    return "".join(chars), visible


def _mask(text: str, positions: list[int]) -> str:
    if not positions:
        return text
    chars = list(text)
    for p in positions:
        if p < len(chars):
            chars[p] = " "
    return "".join(chars)


# Виды, у которых значение может лежать в двух соседних узлах разметки («<b>Иван</b> Иванов»).
_CROSS_NODE_OK = frozenset({"PERSON", "POSSIBLE_PERSON", "ORG", "PROJECT", "POSSIBLE_ENTITY"})


class Structure:
    """Разметка файла: маскированный текст для поиска и границы, по которым обрезаются находки."""

    def __init__(self, text: str, suffix: str):
        self.suffix = suffix
        self.text = text
        self.masked = text
        self.segments: list[tuple[int, int]] = []
        self.header_cells: list[tuple[int, int, int]] = []      # (начало, конец, строка) ячеек столбцов с именами
        self.keys: set[tuple[int, int]] = set()
        self.column_drops: list[tuple[int, int, frozenset]] = []   # (начало, конец, виды) ячеек, где эти виды заведомо ложные
        self.ok = False
        self.markup = suffix in HTML_SUFFIXES or suffix in XML_SUFFIXES
        if suffix in CSV_SUFFIXES:
            delim = _delimiter(text, suffix)
            cells, quotes = _csv_cells(text, delim)
            self.segments = [(s, e) for _, _, s, e in cells]
            self.masked = _mask(text, quotes)
            person_cols = {col for row, col, s, e in cells if row == 0 and _HEADER_PERSON.match(text[s:e])}
            if person_cols:
                self.header_cells = [(s, e, row) for row, col, s, e in cells if row > 0 and col in person_cols]
            self.column_drops = _column_drops(text, cells)
            self.ok = True
        elif suffix in HTML_SUFFIXES:
            self.masked, self.segments = _html_layout(text)
            self.ok = True
        elif suffix in XML_SUFFIXES and text.lstrip("﻿ \t\r\n").startswith("<"):
            self.masked, self.segments = _xml_layout(text)
            self.ok = True
        elif suffix == ".json":
            found = _json_segments(text)
            if found:
                self.segments, quotes, self.keys = found
                self.masked = _mask(text, quotes)
                self.ok = True

    def grid(self) -> list[tuple[int, int, str]]:
        """Ячейки CSV как (столбец, строка, текст) для подписей столбцов."""
        if self.suffix not in CSV_SUFFIXES:
            return []
        cells, _ = _csv_cells(self.text, _delimiter(self.text, self.suffix))
        return [(col, row, self.text[s:e].strip().replace('""', '"')) for row, col, s, e in cells if self.text[s:e].strip()]

    def column_filter(self, findings: list[Finding]) -> list[Finding]:
        """Находки, которые по столбцу заведомо ложные: число из столбца ВВП — не телефон, код ISO — не организация."""
        if not self.column_drops or not findings:
            return findings
        import bisect
        starts = [s for s, _, _ in self.column_drops]
        out = []
        for f in findings:
            lo = bisect.bisect_right(starts, f.start) - 1
            drop = False
            if lo >= 0:
                s, e, kinds = self.column_drops[lo]
                drop = (f.start < e and f.end <= e and f.category in kinds and not (
                    f.category == "CARD" and 15 <= len(re.sub(r"\D", "", f.original)) <= 19 and f.original.isdigit()))
            if not drop:
                out.append(f)
        return out

    # -- обрезка ----------------------------------------------------------------

    def clip(self, findings: list[Finding]) -> list[Finding]:
        if not self.ok or not self.segments:
            return findings
        import bisect
        starts = [s for s, _ in self.segments]
        out: list[Finding] = []
        for f in findings:
            lo = bisect.bisect_right(starts, f.start) - 1
            inside = lo >= 0 and self.segments[lo][0] <= f.start and f.end <= self.segments[lo][1]
            if inside or f.end <= f.start:
                out.append(f)
                continue
            pieces = []
            index = max(lo, 0)
            while index < len(self.segments) and self.segments[index][0] < f.end:
                s, e = self.segments[index]
                a, b = max(f.start, s), min(f.end, e)
                index += 1
                chunk = self.text[a:b]
                lead = len(chunk) - len(chunk.lstrip())
                chunk = chunk.strip()
                if not chunk or b <= a:
                    continue
                pieces.append((a + lead, a + lead + len(chunk), chunk))
            if self.markup and f.category not in _CROSS_NODE_OK:
                # Адрес, телефон или номер, дошедший до соседнего узла («Halifax</cell><cell>Phone»), — это хвост соседа, а не часть значения.
                pieces = pieces[:1]
            single = len(pieces) == 1
            for n, (a, b, chunk) in enumerate(pieces):
                out.append(replace(f, start=a, end=b, original=chunk, finding_id=f"{f.finding_id}-{n}",
                                   person_id=f.person_id if single else None, key=f.key if single else ""))
        return out

    def header_findings(self, findings: list[Finding], rel: str) -> list[Finding]:
        """Слова в ячейках столбцов «Фамилия/Имя/Отчество/ФИО», которые находки не закрыли."""
        covered = sorted((f.start, f.end) for f in findings if f.decision == Decision.AUTO)
        starts = [a for a, _ in covered]
        import bisect
        added: list[Finding] = []
        for cs, ce, _ in self.header_cells:
            cell = self.text[cs:ce]
            if not cell.strip() or not _PERSON_CELL.fullmatch(cell.strip()):
                continue
            position = cs
            gaps = []
            idx = max(bisect.bisect_left(starts, cs) - 1, 0)
            for a, b in covered[idx:]:
                if b <= cs:
                    continue
                if a >= ce:
                    break
                if a > position:
                    gaps.append((position, a))
                position = max(position, b)
            if position < ce:
                gaps.append((position, ce))
            for a, b in gaps:
                chunk = self.text[a:b]
                lead = len(chunk) - len(chunk.lstrip(" ,;"))
                chunk = chunk.strip(" ,;")
                if len(chunk) < 2 or not any(c.isalpha() for c in chunk):
                    continue
                if re.fullmatch(r"[A-Za-z]+\d+(?:_\d+)?", chunk):
                    continue
                added.append(Finding(f"hc{a}", rel, "", "PERSON", chunk, a + lead, a + lead + len(chunk), Decision.AUTO, 0.9,
                                     reason="Столбец с фамилией, именем или отчеством"))
        return added
