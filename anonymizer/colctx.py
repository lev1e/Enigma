"""Заголовок столбца как подпись значений: «Passport No», «Date of Birth», «ИНН», «Город».

Значение в ячейке таблицы без подписи рядом (голый номер паспорта, дата, город) правилами по тексту не узнаётся.
Подпись стоит в заголовке столбца: по нему значения запоминаются как известные литералы вида `kind`, и детектор
заменяет их везде в файле. Один разбор на все форматы: CSV/TSV, таблицы DOCX/PPTX, листы XLSX, pipe-таблицы Markdown.
"""
from __future__ import annotations

import re
from html import unescape
from collections import defaultdict

_DIGITS = re.compile(r"\d")
_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
           r"январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]\w*|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*")
_DATE = re.compile(rf"(?i)^(?:\d{{1,4}}[./\-\s]\d{{1,2}}[./\-\s]\d{{1,4}}|(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?)?(?:{_MONTHS})\.?,?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|"
                   rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\.?,?\s+\d{{4}}(?:\s*г\.?|\s*года)?)$")
_STOP_PLACE = {"n/a", "na", "tbd", "none", "remote", "online", "hq", "head office", "various", "unknown", "total", "all", "other", "others",
               "-", "—", "нет", "удалённо", "удаленно", "онлайн", "все", "прочее", "итого", "не указано", "н/д"}


def _passport(value: str) -> bool:
    compact = re.sub(r"[\s-]", "", value)
    return 6 <= len(compact) <= 12 and compact.isalnum() and sum(c.isdigit() for c in compact) >= 6 and len(value) <= 16


def _national(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return 8 <= len(digits) <= 11 and re.fullmatch(r"[A-Za-z]{0,2}[\d \-]{8,16}[A-Za-z]?", value.strip()) is not None


def _tax(value: str) -> bool:
    compact = re.sub(r"[\s-]", "", value)
    return 8 <= len(compact) <= 15 and compact.isalnum() and sum(c.isdigit() for c in compact) >= 8


def _license(value: str) -> bool:
    compact = re.sub(r"[\s-]", "", value)
    return 6 <= len(compact) <= 18 and compact.isalnum() and sum(c.isdigit() for c in compact) >= 5


def _birth(value: str) -> bool:
    return bool(_DIGITS.search(value)) and len(value) <= 32 and bool(_DATE.match(value.strip()))


def _place(value: str) -> bool:
    value = value.strip()
    if not 3 <= len(value) <= 40 or value.casefold() in _STOP_PLACE or _DIGITS.search(value):
        return False
    words = re.split(r"[\s,]+", value.replace("-", " "))
    return 1 <= len(words) <= 3 and all(len(w) >= 3 or w.lower() in {"on", "up", "la", "de"} for w in words) \
        and bool(re.match(r"^[^\W\d_]", value)) and value[0].isupper()


# (заголовок, вид, проверка значения). Заголовок: короткая подпись (до 6 слов), не фраза.
HEADER_RULES: tuple[tuple[re.Pattern, str, object], ...] = (
    (re.compile(r"(?i)^\s*(?:паспорт\w*(?:\s+(?:данные|№|номер|no\.?))?|серия\s*(?:и|,|/)?\s*номер|passport(?:\s*(?:no\.?|number|num\.?|#|id|nr\.?))?)\s*[:№#.]*\s*$"),
     "PASSPORT", _passport),
    (re.compile(r"(?i)^\s*(?:дата\s+рождения|д\.\s*р\.?|день\s+рождения|рожд\w*|date\s+of\s+birth|d\.?o\.?b\.?|birth\s*date|birthday|born|birth)\s*[:.]*\s*$"),
     "BIRTH_DATE", _birth),
    (re.compile(r"(?i)^\s*(?:ssn|social\s+security(?:\s+(?:no\.?|number|#))?|national\s+insurance(?:\s+(?:no\.?|number))?|ni\s*(?:no\.?|number)|sin|"
                r"national\s+id(?:\s+(?:no\.?|number))?|id\s*(?:no\.?|number|card)|tax\s+file\s+number|tfn)\s*[:#.]*\s*$"),
     "NATIONAL_ID", _national),
    (re.compile(r"(?i)^\s*(?:tax\s*id|tin|ein|taxpayer(?:\s+(?:id|no\.?|number))?|vat\s*(?:id|no\.?|number|reg\w*)?|utr|"
                r"company\s+(?:reg\w*|number|no\.?)|registration\s*(?:no\.?|number))\s*[:#.]*\s*$"),
     "INN_ORG", _tax),
    (re.compile(r"(?i)^\s*(?:водительск\w+(?:\s+удостоверение)?|в/у|driv\w*\s*licen[cs]e(?:\s+(?:no\.?|number|#))?|dl\s*(?:no\.?|number|#)?|licen[cs]e\s+(?:no\.?|number|#))\s*[:#.]*\s*$"),
     "DRIVER_LICENSE", _license),
    (re.compile(r"(?i)^\s*(?:город\w*|населённый\s+пункт|населенный\s+пункт|city|town|hometown|city\s*/\s*town|place\s+of\s+(?:birth|residence)|birthplace|"
                r"location|office\s+(?:city|location)|branch\s+city)\s*[:.]*\s*$"),
     "CITY", _place),
)


# Заголовок столбца → вид идентификатора и допустимое число цифр.
ID_HEADERS = (
    (re.compile(r"(?i)^\s*(?:инн|inn)\b"), "INN_ORG", (10, 12)),
    (re.compile(r"(?i)^\s*(?:кпп|kpp)\b"), "KPP", (9, 9)),
    (re.compile(r"(?i)^\s*(?:огрн|ogrn)"), "OGRN", (13, 15)),
    (re.compile(r"(?i)^\s*снилс"), "SNILS", (11, 11)),
    (re.compile(r"(?i)^\s*(?:паспорт|серия\s*(?:и|,)?\s*номер)"), "PASSPORT", (10, 10)),
    (re.compile(r"(?i)^\s*(?:номер\s+)?(?:банковск\w+\s+)?карт"), "CARD", (13, 19)),
    (re.compile(r"(?i)^\s*(?:бик|bik)\b"), "BIK", (9, 9)),
    (re.compile(r"(?i)^\s*(?:р/?с|расч[её]тный\s+сч[её]т|сч[её]т\b|iban)"), "BANK_ACCOUNT", (20, 20)),
    (re.compile(r"(?i)^\s*(?:полис\s+)?омс"), "OMS", (16, 16)),
)


def classify_header(text: str):
    text = text.strip()
    if not text or len(text.split()) > 6 or len(text) > 40:
        return None
    for pattern, category, check in HEADER_RULES:
        if pattern.search(text):
            return category, check
    return None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(" ", " ")).strip().casefold()


_SPLIT_GUARD: dict = {}


def learn_grid(cells, detector, limit_rows: int = 15) -> int:
    """cells: (столбец, строка, текст). Значения под подходящим заголовком запоминаются в `detector.known_values`."""
    rows = [(c, r, t) for c, r, t in cells if t and t.strip()]
    # Вторая шапка посреди файла («Name,Phone,Email,SSN,Passport,Address» под таблицей другого содержания): блоки разбираются отдельно.
    hdr_hits: dict = {}
    for column, row, text in rows:
        if row > limit_rows and len(text) <= 24 and classify_header(text):
            hdr_hits.setdefault(row, 0)
            hdr_hits[row] += 1
    starts = sorted(r for r, n in hdr_hits.items() if n >= 2 and not (r - 1) in hdr_hits)
    if starts and not _SPLIT_GUARD.get(id(cells)):
        _SPLIT_GUARD[id(cells)] = True
        try:
            bounds = [0] + starts + [10 ** 9]
            learned = 0
            for lo, hi in zip(bounds, bounds[1:]):
                learned += learn_grid([(c, r - lo, t) for c, r, t in cells if lo <= r < hi], detector, limit_rows)
            return learned
        finally:
            _SPLIT_GUARD.pop(id(cells), None)
    headers: dict = {}
    for column, row, text in rows:
        if row <= limit_rows and column not in headers:
            found = classify_header(text)
            if found:
                headers[column] = (row, *found)
    learned = learn_ids(rows, detector, limit_rows)
    if not headers:
        return learned
    for column, row, text in rows:
        head = headers.get(column)
        if not head or row <= head[0]:
            continue
        value = text.strip()
        if head[2](value):
            detector.known_values.setdefault(_norm(value), (head[1], value))
            learned += 1
    return learned


# -- разбор таблиц разных форматов в (столбец, строка, текст) ---------------------------------------------------

def grid_from_markdown(text: str) -> list[list[tuple[int, int, str]]]:
    """Таблицы с вертикальными чертами («| Name | DOB |»): по одной сетке на таблицу."""
    tables: list[list[tuple[int, int, str]]] = []
    current: list[tuple[int, int, str]] = []
    row = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.count("|") >= 2:
            parts = [p.strip() for p in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", p) for p in parts if p):
                continue
            current.extend((c, row, p) for c, p in enumerate(parts))
            row += 1
        elif current:
            tables.append(current)
            current, row = [], 0
    if current:
        tables.append(current)
    return tables


def grid_from_tabs(text: str) -> list[list[tuple[int, int, str]]]:
    """Plain-text tables: tab-separated lines or columns aligned with 2+ spaces; one grid per run of >= 2 such lines."""
    tables: list[list[tuple[int, int, str]]] = []
    current: list[tuple[int, int, str]] = []
    row = 0
    for line in text.splitlines():
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else re.split(r" {2,}", line.strip())) if p.strip()] if line.strip() else []
        if len(parts) >= 2:
            current.extend((c, row, p) for c, p in enumerate(parts))
            row += 1
        else:
            if row >= 2:
                tables.append(current)
            current, row = [], 0
    if row >= 2:
        tables.append(current)
    return tables


def learn_tabs(text: str, detector) -> int:
    return sum(learn_grid(g, detector) for g in grid_from_tabs(text))


def grids_from_xml_tables(parsed: dict) -> list[list[tuple[int, int, str]]]:
    """Таблицы DOCX (w:tbl) и PPTX (a:tbl) из разобранных частей пакета."""
    grids: list[list[tuple[int, int, str]]] = []
    for name, root in parsed.items():
        low = name.lower()
        if not low.endswith(".xml") or not (low.startswith("word/") or low.startswith("ppt/")):
            continue
        for tbl in root.iter():
            tag = tbl.tag if isinstance(tbl.tag, str) else ""
            if not (tag.endswith("}tbl") and ("wordprocessingml" in tag or "drawingml" in tag)):
                continue
            cells: list[tuple[int, int, str]] = []
            rows = [r for r in tbl if isinstance(r.tag, str) and r.tag.endswith("}tr")]
            for ri, tr in enumerate(rows):
                tcs = [c for c in tr if isinstance(c.tag, str) and c.tag.endswith("}tc")]
                for ci, tc in enumerate(tcs):
                    value = "".join(t.text or "" for t in tc.iter() if isinstance(t.tag, str) and t.tag.endswith("}t"))
                    if value.strip():
                        cells.append((ci, ri, value.strip()))
            if cells:
                grids.append(cells)
    return grids


def learn_markdown(text: str, detector) -> int:
    if "|" not in text:
        return 0
    return sum(learn_grid(g, detector) for g in grid_from_markdown(text))


def learn_xml_tables(parsed: dict, detector) -> int:
    return sum(learn_grid(g, detector) for g in grids_from_xml_tables(parsed))


class KnownValues:
    """Скомпилированный поиск известных литералов: пересобирается только после изменения набора."""

    def __init__(self):
        self._size = -1
        self._rx = None

    def regex(self, values: dict):
        if len(values) != self._size:
            keys = sorted({v[1] for v in values.values()}, key=len, reverse=True)
            self._size = len(values)
            self._rx = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys) + r")(?![\w])", re.I) if keys else None
        return self._rx


def by_category(values: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for _, (category, original) in values.items():
        out[category].append(original)
    return out


def learn_ids(rows, detector, limit_rows: int = 15) -> int:
    """Числа под заголовком «ИНН», «Паспорт», «Карта»: цифры без разделителей становятся известными номерами."""
    heads: dict = {}
    for column, row, text in rows:
        if row <= limit_rows and len(text.split()) <= 6:
            for pattern, category, size in ID_HEADERS:
                if pattern.search(text):
                    heads[column] = (row, category, size)
                    break
    learned = 0
    for column, row, text in rows:
        head = heads.get(column)
        if not head or row <= head[0] or not re.fullmatch(r"[\d \u00a0-]+", text.strip() or "x"):
            continue
        digits = re.sub(r"\D", "", text)
        if head[2][0] <= len(digits) <= head[2][1]:
            detector.known_ids.setdefault(digits, head[1])
            # Литерал целиком: рядом с запятой («14.03.1985,770708389312» в CSV) число-разделитель тысяч склеивает соседей.
            detector.known_values.setdefault(_norm(text), (head[1], text.strip()))
            learned += 1
    return learned


def grids_from_html(text: str) -> list[list[tuple[int, int, str]]]:
    """Таблицы HTML (<table><tr><th|td>): по одной сетке на таблицу."""
    import html as _html
    grids = []
    for table in re.finditer(r"(?is)<table\b.*?</table\s*>", text):
        cells: list[tuple[int, int, str]] = []
        for ri, tr in enumerate(re.finditer(r"(?is)<tr\b.*?</tr\s*>", table.group(0))):
            for ci, td in enumerate(re.finditer(r"(?is)<t[hd]\b[^>]*>(.*?)</t[hd]\s*>", tr.group(0))):
                value = _html.unescape(re.sub(r"(?s)<[^>]+>", " ", td.group(1)))
                value = re.sub(r"\s+", " ", value).strip()
                if value:
                    cells.append((ci, ri, value))
        if cells:
            grids.append(cells)
    return grids


def learn_html(text: str, detector) -> int:
    if "<table" not in text.lower():
        return 0
    return sum(learn_grid(g, detector) for g in grids_from_html(text))


PDF_TABLE_CHAR_BUDGET = 24000       # find_tables is slow on dense pages (about 1 s per 4000 characters): a per-file work cap


def learn_pdf_tables(doc, detector, max_pages: int = 40, char_budget: int = PDF_TABLE_CHAR_BUDGET) -> int:
    """PDF tables (ruled or text-aligned) through PyMuPDF find_tables: header cells label the values below.

    Text-based table parsing (the slow part) runs only while the total text it has processed stays within `char_budget`;
    the cheap markdown/tab learning always runs on every page up to `max_pages`.
    """
    learned = 0
    spent = 0
    for pno in range(min(len(doc), max_pages)):
        try:
            page = doc[pno]
            text = page.get_text("text")
            got = learn_markdown(text, detector) + learn_tabs(text, detector)
            learned += got
            if got:
                continue
            if spent >= char_budget:
                continue
            spent += len(text)
            grids = []
            for strategy in ("lines", "text"):
                found = page.find_tables(strategy=strategy)
                for tab in found.tables:
                    cells = [(c, r, (v or "").replace("\n", " ").strip()) for r, row in enumerate(tab.extract()) for c, v in enumerate(row)]
                    cells = [x for x in cells if x[2]]
                    if cells:
                        grids.append(cells)
                if grids:
                    break
            learned += sum(learn_grid(g, detector) for g in grids)
        except Exception:                                     # noqa: BLE001 - a table that cannot be parsed must not break the file
            continue
    return learned


_XML_ELEMENT = re.compile(r"<([A-Za-z_][\w.:-]*)(?:\s[^<>]*)?>([^<>]{1,64})</\1\s*>")
_XML_ATTRIBUTE = re.compile(r"""([A-Za-z_][\w.:-]*)\s*=\s*(?:"([^"<>]{1,64})"|'([^'<>]{1,64})')""")


def _spaced(name: str) -> str:
    name = name.rsplit(":", 1)[-1]
    name = re.sub(r"(?<=[a-zа-я])(?=[A-ZА-Я])", " ", name)
    return re.sub(r"[_.\-]+", " ", name).strip()


_XML_ATTR_ROW = re.compile(r"""<([A-Za-z_][\w.:-]*)((?:\s+[A-Za-z_][\w.:-]*\s*=\s*"[^"<>]{0,200}"){2,})\s*/?>""")
_XML_ATTR_VALUE = re.compile(r"""\s+([A-Za-z_][\w.:-]*)\s*=\s*"([^"<>]{0,200})\"""")
_XML_LEAF_ROW = re.compile(r"<([A-Za-z_][\w.:-]*)(?:\s[^<>]*)?>((?:\s*<([A-Za-z_][\w.:-]*)(?:\s[^<>]*)?>[^<>]{0,200}</\3\s*>){2,})\s*</\1\s*>")
_XML_LEAF = re.compile(r"<([A-Za-z_][\w.:-]*)(?:\s[^<>]*)?>([^<>]{0,200})</\1\s*>")


def grids_from_xml_rows(text: str) -> list[list[tuple[int, int, str]]]:
    """A table written as repeated XML elements: `<person f0=".." f1=".."/>` (values in attributes) or `<row><cell>..</cell>..</row>` (leaf children).
    The first row holding header-like words labels the columns, as in a spreadsheet."""
    by_tag: dict[tuple, list[list[str]]] = {}
    for m in _XML_ATTR_ROW.finditer(text):
        vals = [(k, v) for k, v in _XML_ATTR_VALUE.findall(m.group(2))]
        by_tag.setdefault(("a", m.group(1), tuple(k for k, _ in vals)), []).append([unescape(v) for _, v in vals])
    for m in _XML_LEAF_ROW.finditer(text):
        vals = [unescape(v) for _, v in _XML_LEAF.findall(m.group(2))]
        by_tag.setdefault(("e", m.group(1), len(vals)), []).append(vals)
    grids = []
    for rows in by_tag.values():
        if len(rows) >= 2:
            grids.append([(c, r, v.strip()) for r, row in enumerate(rows) for c, v in enumerate(row) if v.strip()])
    return grids


def learn_xml_rows(text: str, detector) -> int:
    if "<" not in text:
        return 0
    learned = 0
    for grid in grids_from_xml_rows(text):
        learned += learn_grid(grid, detector)
        learned += learn_column_shape(grid, detector)
    return learned


_PASSPORT_SHAPE = re.compile(r"[A-Z]\d{8}|\d{9}")


def learn_column_shape(cells, detector, min_rows: int = 3) -> int:
    """A table without header labels: a column in which (nearly) every cell has the shape of a passport number (`E92485238`, `723549216`)
    is a passport column, so the rows the content rules missed are known values too."""
    columns: dict = defaultdict(list)
    for column, row, text in cells:
        columns[column].append(text.strip())
    learned = 0
    for values in columns.values():
        hits = [v for v in values if _PASSPORT_SHAPE.fullmatch(v)]
        if len(values) >= min_rows and len(hits) >= 0.8 * len(values) and any(not v.isdigit() for v in hits):
            for v in hits:
                if detector.known_values.setdefault(_norm(v), ("PASSPORT", v)) == ("PASSPORT", v):
                    learned += 1
    return learned


def learn_xml_names(text: str, detector) -> int:
    """Голое число в элементе или атрибуте `<inn>…</inn>`, `passport="…"`: имя элемента служит заголовком столбца."""
    if "<" not in text:
        return 0
    pairs = [(m.group(1), m.group(2)) for m in _XML_ELEMENT.finditer(text)]
    pairs += [(m.group(1), m.group(2) or m.group(3)) for m in _XML_ATTRIBUTE.finditer(text)]
    learned = 0
    for name, value in pairs:
        label, value = _spaced(name), (value or "").strip()
        if not value:
            continue
        for pattern, category, size in ID_HEADERS:
            if pattern.search(label) and re.fullmatch(r"[\d  -]+", value):
                digits = re.sub(r"\D", "", value)
                if size[0] <= len(digits) <= size[1]:
                    detector.known_ids.setdefault(digits, category)
                    detector.known_values.setdefault(_norm(value), (category, value))
                    learned += 1
                break
        else:
            found = classify_header(label)
            if found and found[1](value):
                detector.known_values.setdefault(_norm(value), (found[0], value))
                learned += 1
    return learned
