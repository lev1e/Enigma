"""Маскирование финансовых чисел в Excel: суммы масштабируются одним секретным множителем, формулы остаются рабочими.

Схема описана в docs/superpowers/finance-masking.md. Коротко:
  1. Каждая числовая ячейка-константа получает класс: сумма (масштабируется), безразмерное число или видимая сумма.
  2. По формулам считается «степень денежности» (finance_formula.py). Формула, которая ломается при масштабировании
     (сумма*сумма, сумма+число, сравнение суммы с числом), — конфликт: входные суммы остаются видимыми (exclude)
     или файл не выдаётся (block). Тексты формул не меняются.
  3. Кэшированные результаты формул удаляются, книга пересчитывается при открытии.
  4. Исходные значения и множитель лежат только в зашифрованном хранилище (vault.finance).
  5. Перед выдачей файл проверяется: ни одно настоящее значение суммы не должно остаться в частях файла.
"""

from __future__ import annotations

import re
import secrets
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from math import gcd

from lxml import etree

from . import numbers as numeric
from .finance_formula import (Analyzer, CONFLICT_TEXT, Conflict, ZERO, col_to_num, num_to_col, parse_formula, parse_ref,
                              refs_in, shift_ref, VALID)
from .vault import canon_number

_RND = secrets.SystemRandom()
STAMP_PREFIX = "_AnonFin_"
MAX_ITER = 40


def _local(node) -> str:
    return etree.QName(node).localname if isinstance(node.tag, str) else ""


# -- множитель -------------------------------------------------------------------------------

_ROUND_K = (0.5, 1.0, 1.5, 2.0, 2.5, 0.25, 0.75, 0.4, 0.6, 0.8, 1.2, 1.25, 0.75)
K_DEN = 10_000
SIG_MAX = 15            # Excel хранит 15 значащих цифр


def make_factor() -> tuple[int, int]:
    """k = p/10000 в [0.37, 2.9]: умножение на десятичную дробь точное, суммы и разности сохраняются без дрейфа округления."""
    while True:
        p = _RND.randrange(3700, 29000)
        if p % 10 == 0 or any(abs(p / K_DEN - r) < 0.04 * r for r in _ROUND_K):
            continue
        return p, K_DEN


def _fmt(d: Decimal) -> str:
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _cap_sig(value: Decimal, sig: int = SIG_MAX) -> Decimal:
    """Не больше 15 значащих цифр (больше Excel не хранит)."""
    if value == 0:
        return value
    exp = value.copy_abs().adjusted()
    return value.quantize(Decimal(1).scaleb(exp - sig + 1), rounding=ROUND_HALF_UP) if exp - sig + 1 > -60 else value


def scale_value(orig: Decimal, k: tuple[int, int], places: int = 0) -> Decimal:
    """Полная точность: orig * p / q (для q = 10**n результат конечная десятичная дробь, суммы сходятся точно)."""
    p, q = k
    out = _cap_sig(orig * p / q)
    if out == orig and orig != 0:
        out = _cap_sig(orig * (p + 1) / q)
    return out


def unscale_value(value: Decimal, k: tuple[int, int], places: int = 0) -> Decimal:
    """Из масштаба обратно: деление, округление до копеек (для сумм от 100) или до 6 знаков, лишние нули убираются."""
    p, q = k
    raw = value * q / p
    return raw.quantize(Decimal("0.01") if abs(raw) >= 100 else Decimal("0.000001"), rounding=ROUND_HALF_UP)


def places_of(text: str) -> int:
    canon = canon_number(text) or ""
    return len(canon.split(".")[1]) if "." in canon else 0


# -- словари ---------------------------------------------------------------------------------

NONMONEY = re.compile(r"(?i)%|процент|\bдол[яи]\b|\bshare\b|ставк|\brate\b|коэф|ratio|индекс|index|курс|\bшт\b|штук|кол-?во|колич|"
                      r"\bqty\b|quantity|\bunits?\b|headcount|числен|штат|\bчел\b|человек|акци[йяи]|shares|\bгод\b|\bгода\b|\byear\b|"
                      r"период|period|квартал|quarter|месяц|\bmonth\b|\bдн[ейя]+\b|\bdays\b|№|\bномер|\bid\b|\bкод\b|\bинн\b|"
                      r"рейтинг|\brank\b|\bscore\b|\bвес\b|weight|\bcagr\b|\birr\b|\broi\b|\bдата\b|\bdate\b|\bчас(?:ов|ы)?\b|hours|"
                      r"площад|\bкм\b|\bкг\b|тонн|литр|\bvat rate\b|\bмультипликатор|multiple|\bpayback|срок|\bnper\b|\bmargin\s*%|"
                      r"норма|\bшаг\b|\bstep\b|\bscenario\b|сценарий|\bprobab|вероятн|\bkpi\b")
MONEY = re.compile(r"(?i)выручк|доход|себестоим|прибыл|убыт|расход|затрат|сумм|\bцен[аыу]\b|стоимост|бюджет|ebitda|\bebit\b|revenue|"
                   r"\bsales\b|cogs|\bcosts?\b|expens|profit|\bloss\b|income|opex|capex|\bcash\b|\bdebt\b|долг|кредит|займ|налог|"
                   r"\btax\b|зарплат|\bфот\b|оклад|аренд|амортиз|капитал|актив|пассив|баланс|остаток|денежн|платеж|платёж|оплат|"
                   r"поступлен|инвестиц|дивиденд|взнос|депозит|\bprice\b|amount|budget|salary|payroll|\brent\b|equity|asset|"
                   r"liabilit|оборот|комисси|выплат|штраф|аванс|задолж|резерв|\bfee\b|\bfees\b|маркетинг|реклам|прочие|"
                   r"услуг|материал|закупк|продаж|оборудован|ремонт|лизинг|страхов|премия|бонус|скидк|обязательств|cash flow|\bpl\b|"
                   r"деньги|средства|ввод|вывод|внесен|снят|списан|начислен|нераспределен|уставн|добавочн|ндс\b(?!\s*\()")
CURRENCY_WORD = re.compile(r"(?i)руб|₽|\$|€|£|¥|\busd\b|\beur\b|\brub\b|тыс\.?\s*р|млн\.?\s*р|\bk\$|\bm\$|долл|евро")
CURRENCY_FMT = re.compile(r'(?i)[₽$€£¥]|руб|\[\$|"?(?:RUB|USD|EUR)')

BUILTIN_FMT = {9: "0%", 10: "0.00%", 3: "#,##0", 4: "#,##0.00", 5: "$#,##0", 6: "$#,##0", 7: "$#,##0.00", 8: "$#,##0.00",
               37: "#,##0", 38: "#,##0", 39: "#,##0.00", 40: "#,##0.00", 41: "#,##0", 42: "$#,##0", 43: "#,##0.00", 44: "$#,##0.00"}
THOUSANDS = re.compile(r"#,##0|# ##0|#\s?##0")


@dataclass
class Cell:
    node: object
    ref: str
    col: int
    row: int
    kind: str                    # num | text | formula | member | empty
    text: str = ""
    value: Decimal | None = None
    style: int = 0
    ast: object = None
    off: tuple[int, int] = (0, 0)
    ftext: str = ""
    degree: tuple | None = None


@dataclass
class Sheet:
    name: str
    sheet_id: str
    part: str
    root: object
    cells: dict = field(default_factory=dict)       # (col,row) -> Cell
    state: str = ""


class Model:
    def __init__(self, parsed: dict):
        self.parsed = parsed
        self.sheets: list[Sheet] = []
        self.by_name: dict[str, Sheet] = {}
        self.names: dict[str, str] = {}
        self.tables: dict[str, tuple] = {}
        self.strings = self._strings()
        self.formats = self._formats()
        self.date_styles = numeric.date_style_indexes(parsed["xl/styles.xml"]) if parsed.get("xl/styles.xml") is not None else set()
        self._load_sheets()
        self._load_names_tables()

    # -- чтение -----------------------------------------------------------------------------
    def _strings(self) -> list[str]:
        root = self.parsed.get("xl/sharedStrings.xml")
        if root is None:
            return []
        out = []
        for si in root:
            if _local(si) == "si":
                out.append("".join(t.text or "" for t in si.iter() if _local(t) == "t" and _local(t.getparent()) != "rPh"))
        return out

    def _formats(self) -> dict[int, str]:
        styles = self.parsed.get("xl/styles.xml")
        if styles is None:
            return {}
        custom = {}
        for n in styles.iter():
            if _local(n) == "numFmt":
                try:
                    custom[int(n.get("numFmtId"))] = n.get("formatCode") or ""
                except (TypeError, ValueError):
                    pass
        out = {}
        for holder in styles.iter():
            if _local(holder) == "cellXfs":
                for i, xf in enumerate(c for c in holder if _local(c) == "xf"):
                    fid = int(xf.get("numFmtId", "0") or 0)
                    out[i] = custom.get(fid) or BUILTIN_FMT.get(fid, "General" if fid == 0 else str(fid))
        return out

    def _load_sheets(self) -> None:
        wb = self.parsed.get("xl/workbook.xml")
        if wb is None:
            return
        rels = {}
        rel_root = self.parsed.get("xl/_rels/workbook.xml.rels")
        if rel_root is not None:
            for r in rel_root:
                rels[r.get("Id")] = r.get("Target")
        rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        for node in wb.iter():
            if _local(node) == "sheet":
                target = rels.get(node.get(rid_attr), "")
                part = target.lstrip("/") if target.startswith("/") else "xl/" + target
                root = self.parsed.get(part)
                if root is None:
                    continue
                sheet = Sheet(node.get("name") or "", node.get("sheetId") or "", part, root, state=node.get("state") or "")
                self.sheets.append(sheet)
                self.by_name[sheet.name] = sheet
                self._load_cells(sheet)

    def _load_cells(self, sheet: Sheet) -> None:
        masters: dict[str, tuple] = {}
        array_refs: list[tuple] = []
        for c in sheet.root.iter():
            if _local(c) != "c":
                continue
            m = re.match(r"^([A-Z]+)(\d+)$", c.get("r", ""))
            if not m:
                continue
            col, row = col_to_num(m.group(1)), int(m.group(2))
            kids = {_local(k): k for k in c}
            style = int(c.get("s", "0") or 0)
            f, v = kids.get("f"), kids.get("v")
            t = c.get("t")
            cell = Cell(c, c.get("r"), col, row, "empty", style=style)
            if f is not None:
                cell.kind = "formula"
                ftext = f.text or ""
                ftype = f.get("t")
                try:
                    if ftype == "shared":
                        si = f.get("si")
                        if ftext:
                            masters[si] = (parse_formula(ftext), col, row)
                            cell.ast = masters[si][0]
                        elif si in masters:
                            ast, mc, mr = masters[si]
                            cell.ast, cell.off = ast, (col - mc, row - mr)
                    elif ftype == "dataTable":
                        cell.ast = None
                    else:
                        cell.ast = parse_formula(ftext) if ftext else None
                        if ftype == "array" and f.get("ref"):
                            array_refs.append((cell, f.get("ref")))
                except Conflict:
                    cell.ast = "BAD"
                cell.ftext = ftext
            elif v is not None and (v.text or "").strip():
                if t in (None, "n") and canon_number(v.text) is not None:
                    cell.kind = "num"
                    cell.value = Decimal(canon_number(v.text))
                elif t == "s" and (v.text or "").strip().isdigit() and int(v.text) < len(self.strings):
                    cell.kind, cell.text = "text", self.strings[int(v.text)]
                elif t == "inlineStr":
                    cell.kind, cell.text = "text", "".join(x.text or "" for x in c.iter() if _local(x) == "t")
                elif t == "str":
                    cell.kind, cell.text = "text", v.text or ""
            elif t == "inlineStr":
                cell.kind, cell.text = "text", "".join(x.text or "" for x in c.iter() if _local(x) == "t")
            sheet.cells[(col, row)] = cell
        for master, ref in array_refs:
            try:
                node = parse_ref(ref)
            except Conflict:
                continue
            for (cc, rr), cell in sheet.cells.items():
                if node[2][0] <= cc <= node[4][0] and node[3][0] <= rr <= node[5][0] and cell is not master and cell.kind != "formula":
                    cell.kind, cell.ast, cell.off = "member", master.ast, (0, 0)

    def _load_names_tables(self) -> None:
        wb = self.parsed.get("xl/workbook.xml")
        if wb is not None:
            for n in wb.iter():
                if _local(n) == "definedName" and n.get("name") and not n.get("name").startswith(STAMP_PREFIX) \
                        and n.get("localSheetId") is None:
                    self.names[n.get("name")] = (n.text or "").strip()
        sheet_of_part = {s.part: s for s in self.sheets}
        for part, root in self.parsed.items():
            m = re.match(r"^xl/worksheets/_rels/(.+)\.xml\.rels$", part)
            if not m or f"xl/worksheets/{m.group(1)}.xml" not in sheet_of_part:
                continue
            sheet = sheet_of_part[f"xl/worksheets/{m.group(1)}.xml"]
            for rel in root:
                target = rel.get("Target") or ""
                if "/tables/" in target:
                    tpart = "xl/tables/" + target.rsplit("/", 1)[1]
                    troot = self.parsed.get(tpart)
                    if troot is not None and troot.get("name"):
                        cols = [c.get("name") for c in troot.iter() if _local(c) == "tableColumn"]
                        self.tables[troot.get("name")] = (sheet.name, troot.get("ref"), cols,
                                                          int(troot.get("headerRowCount", "1")), int(troot.get("totalsRowCount", "0")))

    # -- метки ------------------------------------------------------------------------------
    def row_label(self, sheet: Sheet, col: int, row: int) -> str:
        texts = [(c, cell.text) for (c, r), cell in sheet.cells.items() if r == row and c < col and cell.kind == "text" and cell.text.strip()]
        texts.sort()
        if not texts:
            return ""
        return texts[0][1] if len(texts) == 1 else texts[0][1] + " " + texts[-1][1]

    def header(self, sheet: Sheet, col: int, row: int) -> str:
        best = None
        for (c, r), cell in sheet.cells.items():
            if c == col and r < row and cell.kind == "text" and cell.text.strip():
                if best is None or r > best[0]:
                    best = (r, cell.text)
        return best[1] if best else ""


# -- классификация ---------------------------------------------------------------------------

def _is_percent_fmt(code: str) -> bool:
    return "%" in re.sub(r'"[^"]*"', "", code or "")


def verdict_for_label(label: str) -> str | None:
    """'money' | 'no' | None по тексту подписи."""
    if not label.strip():
        return None
    if re.search(r"%|процент", label):
        return "no"
    if CURRENCY_WORD.search(label):
        return "money"
    if NONMONEY.search(label):
        return "no"
    if MONEY.search(label):
        return "money"
    return None


def classify_cell(model: Model, sheet: Sheet, cell: Cell, financial_sheet: bool = False) -> tuple[str, str]:
    """-> ('money'|'dimless'|'unknown', причина)."""
    if cell.style in model.date_styles:
        return "dimless", "дата"
    code = model.formats.get(cell.style, "General")
    if _is_percent_fmt(code):
        return "dimless", "процент"
    v = cell.value
    row_v = verdict_for_label(model.row_label(sheet, cell.col, cell.row))
    head_v = verdict_for_label(model.header(sheet, cell.col, cell.row))
    if CURRENCY_FMT.search(re.sub(r"\[(?!\$)[^\]]*\]", "", code)):
        return ("dimless", "ставка/количество в подписи") if row_v == "no" and head_v != "money" else ("money", "формат валюты")
    if row_v == "no" or (row_v is None and head_v == "no"):
        return "dimless", "подпись"
    if row_v == "money" or head_v == "money":
        return "money", "подпись"
    if v is not None and v == v.to_integral_value() and 1900 <= abs(v) <= 2100 and not THOUSANDS.search(code):
        return "dimless", "год"
    if v is not None and v == v.to_integral_value() and abs(v) <= 12:
        return "dimless", "малое целое"
    if financial_sheet and THOUSANDS.search(code) and v is not None and abs(v) >= 100:
        return "money", "формат разрядов на финансовом листе"
    return "unknown", "нет признаков"


# -- анализ книги ----------------------------------------------------------------------------

@dataclass
class Conflicted:
    sheet: str
    ref: str
    kind: str

    @property
    def text(self) -> str:
        return f"Лист {self.sheet}, ячейка {self.ref}: {CONFLICT_TEXT.get(self.kind, self.kind)} — значения не замаскированы"


@dataclass
class Plan:
    scaled: dict = field(default_factory=dict)         # (sheet_idx, col, row) -> Cell
    excluded: set = field(default_factory=set)
    conflicts: list = field(default_factory=list)
    formulas: int = 0
    factors: dict = field(default_factory=dict)        # sheet_idx -> (p, q)
    blocked: bool = False
    classes: dict = field(default_factory=dict)


class Analysis:
    def __init__(self, model: Model, scaled: set, excluded: set):
        self.m, self.scaled, self.excluded = model, scaled, excluded
        self.idx = {s.name: i for i, s in enumerate(model.sheets)}
        self.memo: dict = {}
        self.busy: set = set()
        self.conflicts: dict = {}
        self.cur: tuple | None = None

    def cell_pair(self, si: int, cell: Cell):
        key = (si, cell.col, cell.row)
        if cell.kind == "num":
            if cell.value == 0:
                return "ZERO"
            return (1, 0) if key in self.scaled else ((0, 1) if key in self.excluded else ZERO)
        if cell.kind in ("formula", "member"):
            if key in self.memo:
                return self.memo[key]
            if key in self.busy or cell.ast in (None, "BAD"):
                return ZERO if cell.ast is None else None
            self.busy.add(key)
            saved = self.cur
            self.cur = key
            try:
                res = Analyzer(self.resolve_range, self.resolve_name, self.resolve_table, si)
                res.cur_row = cell.row
                val = res.ev(cell.ast, *cell.off)
                pair = val[1] if val[0] == "P" else (ZERO if val[0] == "L" else None)
            except Conflict as exc:
                self.conflicts[key] = exc.kind
                pair = ZERO
            finally:
                self.cur = saved
                self.busy.discard(key)
            self.memo[key] = pair
            return pair
        return None

    def sheet_of(self, name, si):
        if name is None:
            return si
        return self.idx.get(name)

    def bounds(self, sheet: Sheet, ref):
        _, _, c1, r1, c2, r2 = ref
        lo_c, hi_c = (c1[0] or 1), (c2[0] or 16384)
        lo_r, hi_r = (r1[0] or 1), (r2[0] or 1048576)
        return min(lo_c, hi_c), max(lo_c, hi_c), min(lo_r, hi_r), max(lo_r, hi_r)

    def cells_in(self, si: int, ref):
        sheet = self.m.sheets[si]
        c1, c2, r1, r2 = self.bounds(sheet, ref)
        if (c2 - c1 + 1) * (r2 - r1 + 1) <= len(sheet.cells):
            for cc in range(c1, c2 + 1):
                for rr in range(r1, r2 + 1):
                    cell = sheet.cells.get((cc, rr))
                    if cell is not None:
                        yield cell
        else:
            for (cc, rr), cell in sheet.cells.items():
                if c1 <= cc <= c2 and r1 <= rr <= r2:
                    yield cell

    def resolve_range(self, ref, current):
        si = self.sheet_of(ref[1], current)
        if si is None:
            return None
        pairs = set()
        for cell in self.cells_in(si, ref):
            p = self.cell_pair(si, cell)
            if p is not None and p != "ZERO":
                pairs.add(p)
        if not pairs:
            return None
        return pairs.pop() if len(pairs) == 1 else "MIX"

    def resolve_name(self, name, current):
        text = self.m.names.get(name)
        if text is None:
            return None
        try:
            return ("ref", parse_ref(text.replace(" ", "")))
        except Conflict:
            pass
        canon = canon_number(text)
        if canon is not None:
            return ("value", ("P", (1, 0)) if ("name", name) in self.scaled else ("L", Decimal(canon)))
        return None

    def resolve_table(self, node, current):
        text = node[1]
        if node[0] == "thisrow":
            return None
        m = re.match(r"^([^\[]+)\[(.*)\]$", text)
        if not m or m.group(1) not in self.m.tables:
            return None
        sheet_name, ref, cols, header, totals = self.m.tables[m.group(1)]
        body = m.group(2)
        this_row = "#This Row" in body or body.startswith("@")
        colname = re.findall(r"\[([^\[\]#@]+)\]", body) or [body.lstrip("@")]
        colname = colname[-1].strip()
        if colname not in cols:
            return None
        a, b = ref.split(":")
        pa, pb = parse_ref(a), parse_ref(b)
        c = pa[2][0] + cols.index(colname)
        r1, r2 = pa[3][0] + header, pb[3][0] - totals
        if this_row:
            row = getattr(self, "cur_row", None) or r1
            r1 = r2 = row
        return ("ref", sheet_name, (c, True), (r1, True), (c, True), (r2, True))

    def run(self):
        for si, sheet in enumerate(self.m.sheets):
            for cell in sheet.cells.values():
                if cell.kind in ("formula", "member"):
                    self.cell_pair(si, cell)
        return self.conflicts

    def precedents(self, si: int, cell: Cell, seen: set, out: set) -> None:
        key = (si, cell.col, cell.row)
        if key in seen:
            return
        seen.add(key)
        if cell.kind == "num":
            out.add(key)
            return
        if cell.kind not in ("formula", "member") or cell.ast in (None, "BAD"):
            return
        for r in refs_in(cell.ast, []):
            if r[0] == "ref":
                ref = shift_ref(r, *cell.off)
                tsi = self.sheet_of(ref[1], si)
                if tsi is None:
                    continue
                for c in self.cells_in(tsi, ref):
                    self.precedents(tsi, c, seen, out)
            elif r[0] == "name":
                text = self.m.names.get(r[1], "")
                try:
                    ref = parse_ref(text.replace(" ", ""))
                except Conflict:
                    out.add(("name", r[1]))
                    continue
                tsi = self.sheet_of(ref[1], si)
                if tsi is not None:
                    for c in self.cells_in(tsi, ref):
                        self.precedents(tsi, c, seen, out)
            elif r[0] in ("tbl", "thisrow"):
                self.cur_row = cell.row
                target = self.resolve_table(r, si)
                if target:
                    tsi = self.sheet_of(target[1], si)
                    for c in self.cells_in(tsi, target):
                        self.precedents(tsi, c, seen, out)


def build_plan(model: Model, mode: str = "exclude", per_sheet: bool = False, mask_percents: bool = False) -> Plan:
    plan = Plan()
    candidates: dict = {}
    financial = {}
    for si, sheet in enumerate(model.sheets):
        n_money = sum(1 for c in sheet.cells.values() if c.kind == "num" and c.value != 0 and classify_cell(model, sheet, c)[0] == "money")
        financial[si] = n_money >= 3
    for si, sheet in enumerate(model.sheets):
        for cell in sheet.cells.values():
            if cell.kind == "formula" or cell.kind == "member":
                plan.formulas += 1
            if cell.kind != "num" or cell.value == 0:
                continue
            klass, why = classify_cell(model, sheet, cell, financial[si])
            plan.classes[(si, cell.col, cell.row)] = (klass, why)
            if klass == "money":
                candidates[(si, cell.col, cell.row)] = cell
    wb = model.parsed.get("xl/workbook.xml")
    name_nodes = {}
    if wb is not None:
        for n in wb.iter():
            if _local(n) == "definedName" and n.get("name") and canon_number(n.text or "") not in (None, "0") \
                    and not n.get("name").startswith(STAMP_PREFIX):
                nv = verdict_for_label(n.get("name").replace("_", " "))
                big = abs(Decimal(canon_number(n.text))) >= 1000
                huge = abs(Decimal(canon_number(n.text))) >= 100000
                if nv == "money" or (nv is None and big) or (nv == "no" and huge):
                    name_nodes[n.get("name")] = n
    scaled = set(candidates) | {("name", n) for n in name_nodes}
    excluded: set = set()
    for _ in range(MAX_ITER):
        an = Analysis(model, scaled - excluded, excluded)
        conflicts = an.run()
        newly = set()
        found = []
        for (si, col, row), kind in conflicts.items():
            cell = model.sheets[si].cells[(col, row)]
            deps: set = set()
            an.precedents(si, cell, set(), deps)
            deps &= (scaled - excluded)
            if deps:
                found.append((si, cell, kind))
                newly |= deps
        if not found:
            break
        if mode == "block":
            plan.blocked = True
            plan.conflicts = [Conflicted(model.sheets[si].name, c.ref, k) for si, c, k in found]
            break
        for si, c, k in found:
            plan.conflicts.append(Conflicted(model.sheets[si].name, c.ref, k))
        excluded |= newly
    plan.excluded = excluded
    plan.scaled = {k: candidates[k] for k in candidates if k not in excluded}
    plan.names = {n: node for n, node in name_nodes.items() if ("name", n) not in excluded}
    # множители: общий, либо по листам, если нет перекрёстных ссылок на суммы
    shared = make_factor()
    cross = False
    if per_sheet:
        an = Analysis(model, set(plan.scaled), set())
        for si, sheet in enumerate(model.sheets):
            for cell in sheet.cells.values():
                if cell.kind in ("formula", "member") and cell.ast not in (None, "BAD"):
                    for r in refs_in(cell.ast, []):
                        if r[0] == "ref" and r[1] and an.sheet_of(r[1], si) not in (None, si):
                            tsi = an.sheet_of(r[1], si)
                            if any((tsi, c.col, c.row) in plan.scaled for c in an.cells_in(tsi, r)):
                                cross = True
                elif cell.kind == "formula" and cell.ast in (None, "BAD"):
                    cross = True
    for si in range(len(model.sheets)):
        plan.factors[si] = make_factor() if (per_sheet and not cross) else shared
    plan.cross_sheet = cross
    plan.degrees = Analysis(model, set(plan.scaled), excluded)
    plan.degrees.run()
    return plan


def looks_financial(parsed: dict) -> bool:
    try:
        model = Model(parsed)
    except Exception:
        return False
    money = formulas = 0
    for sheet in model.sheets:
        for c in sheet.cells.values():
            if c.kind in ("formula", "member"):
                formulas += 1
            elif c.kind == "num" and c.value != 0 and classify_cell(model, sheet, c)[0] == "money":
                money += 1
    return money >= 8 and formulas >= 2


# -- применение ------------------------------------------------------------------------------

def _set_v(cell: Cell, text: str) -> None:
    for k in cell.node:
        if _local(k) == "v":
            k.text = text


def _set_inline(node, text: str) -> None:
    """Текстовая ячейка с числом: значение переписывается как встроенная строка (общая строка могла быть у других ячеек)."""
    for k in list(node):
        node.remove(k)
    node.set("t", "inlineStr")
    ns = etree.QName(node).namespace
    inline = etree.SubElement(node, f"{{{ns}}}is")
    etree.SubElement(inline, f"{{{ns}}}t").text = text


def _drop_cached(cell: Cell) -> None:
    node = cell.node
    for k in list(node):
        if _local(k) == "v":
            node.remove(k)
    if node.get("t") in ("str", "e", "b", "n"):
        del node.attrib["t"]


_TEXT_AMOUNT = re.compile(
    r"(?P<pre>(?:[$€£₽]|USD|EUR|RUB|GBP|CHF|CNY)\s?)?(?P<num>\d{1,3}(?:[   ,.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
    r"(?P<mid>\s?(?:млрд|млн|тыс|трлн|mln|million|billion|thousand|bn|[kKmMbB])\b\.?)?(?P<post>\s?(?:₽|руб\.?|р\.|\$|€|£|USD|EUR|RUB|долл\.?)(?!\w))?")


_WORD_MULT = re.compile(r"(?i)^\s?(млрд|млн|тыс|трлн|mln|million|billion|thousand|bn)")


def _scale_text(text: str, k, pairs: list, force: bool = False) -> str:
    """Суммы в тексте: «1 250 000 руб», «4,2 млн», «$4.5M». force: любое число от 1000 (кроме года) считается суммой."""
    def repl(m):
        mid = m.group("mid") or ""
        word_mult = bool(_WORD_MULT.match(mid))
        if not (m.group("pre") or m.group("post") or word_mult or force):
            return m.group(0)
        raw = m.group("num")
        group_sep = next((s for s in (" ", " ", " ") if s in raw), None)
        tail = re.search(r"([.,])(\d{1,2})$", raw)
        dec_sep = tail.group(1) if tail and (tail.group(1) not in raw[:tail.start()] or group_sep or
                                              (raw.count(tail.group(1)) == 1 and len(tail.group(2)) != 3)) else None
        body = raw[:tail.start()] if dec_sep else raw
        if group_sep is None and re.search(r"[.,]\d{3}", body):
            group_sep = "," if "," in body else "."
        digits = re.sub(r"\D", "", body)
        value = Decimal(digits + ("." + tail.group(2) if dec_sep else ""))
        if mid:
            threshold = 0
        elif force and not (m.group("pre") or m.group("post")):
            if value < 1000 or (group_sep is None and not dec_sep and 1900 <= value <= 2100):
                return m.group(0)
            threshold = 1000
        else:
            threshold = 100 if not mid else 0
        if value < threshold or value == 0:
            return m.group(0)
        new = scale_value(value, k)
        if mid:
            new = new.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) if abs(new) < 1000 else new.quantize(Decimal(1), rounding=ROUND_HALF_UP)
        elif not dec_sep:
            new = new.quantize(Decimal(1), rounding=ROUND_HALF_UP)
        else:
            new = new.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        s = format(new, "f")
        whole, _, frac = s.partition(".")
        frac = frac.rstrip("0") if mid else frac
        if group_sep and not (mid and len(whole) <= 3):
            whole = f"{int(whole):,}".replace(",", group_sep)
        out = (m.group("pre") or "") + whole + ((dec_sep or ".") + frac if frac else "") + mid + (m.group("post") or "")
        if out != m.group(0):
            pairs.append((out, m.group(0)))
        return out
    return _TEXT_AMOUNT.sub(repl, text)


_SUM_RE = re.compile(r"^SUM\(\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)\)$", re.I)


def _blank_orphan_strings(model: Model, cells: dict) -> None:
    """Настоящие числа-строки, на которые больше не ссылается ни одна ячейка, стираются из общих строк."""
    origs = {snap[2] for entry in cells.values() for snap in entry["snap"].values() if snap[0] == "t"}
    sst = model.parsed.get("xl/sharedStrings.xml")
    if not origs or sst is None:
        return
    used = set()
    for sheet in model.sheets:
        for c in sheet.root.iter():
            if _local(c) == "c" and c.get("t") == "s":
                v = c.find("{*}v")
                if v is not None and (v.text or "").strip().isdigit():
                    used.add(int(v.text))
    for i, si in enumerate(x for x in sst if _local(x) == "si"):
        if i not in used and "".join(t.text or "" for t in si.iter() if _local(t) == "t").strip() in origs:
            for t in si.iter():
                if _local(t) == "t":
                    t.text = ""


def _tie_out(model: Model, plan: Plan, new_vals: dict, exact: dict) -> int:
    """Сходимость итогов: если округление до 15 цифр сдвинуло сумму диапазона SUM, разница уходит в самую крупную строку диапазона."""
    fixed = 0
    for si, sheet in enumerate(model.sheets):
        for cell in sheet.cells.values():
            m = _SUM_RE.match((cell.ftext or "").strip().lstrip("=")) if cell.kind == "formula" and not cell.off[0] and not cell.off[1] else None
            if not m or m.group(1).upper() != m.group(3).upper():
                continue
            c = col_to_num(m.group(1))
            keys = [(si, c, r) for r in range(int(m.group(2)), int(m.group(4)) + 1)]
            if not all(k in new_vals for k in keys if k in sheet.cells and sheet.cells[(c, k[2])].kind == "num"):
                continue
            keys = [k for k in keys if k in new_vals]
            if len(keys) < 2:
                continue
            diff = _cap_sig(sum(exact[k] for k in keys)) - sum(new_vals[k] for k in keys)
            if diff:
                big = max(keys, key=lambda k: abs(new_vals[k]))
                new_vals[big] += diff
                fixed += 1
    return fixed


def _cells_with_text_amounts(model: Model) -> list[str]:
    """Адреса ячеек, в тексте которых есть суммы (для названного предупреждения)."""
    out = []
    for sheet in model.sheets:
        for (col, row), cell in sorted(sheet.cells.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            if cell.kind == "text" and cell.text and re.search(r"\d", cell.text):
                probe: list = []
                _scale_text(cell.text, (23135, 10000), probe)
                if probe:
                    out.append(f"{sheet.name}!{cell.ref}")
    return out


def apply_plan(model: Model, plan: Plan, text_amounts: bool, vault, rel: str = "") -> dict:
    """Меняет разобранные части на месте и возвращает запись для хранилища (снимок выданного файла нужен для возврата правок)."""
    from . import finance_surfaces
    fin_id = secrets.token_hex(6)
    cells: dict = {}
    sheets = []
    notes: list[str] = []
    for si, sheet in enumerate(model.sheets):
        sheets.append({"sheetId": sheet.sheet_id, "part": sheet.part, "name": sheet.name, "k": list(plan.factors[si])})
        cells[sheet.part] = {"s": {}, "x": [], "f": [], "snap": {}}
    new_vals: dict = {}
    exact: dict = {}
    origs: dict = {}
    for key, cell in plan.scaled.items():
        text = (cell.node.find("{*}v").text or "").strip()
        orig = Decimal(canon_number(text))
        p, q = plan.factors[key[0]]
        origs[key] = text
        exact[key] = orig * p / q
        new_vals[key] = scale_value(orig, plan.factors[key[0]])
    repaired = _tie_out(model, plan, new_vals, exact)
    for key, cell in plan.scaled.items():
        sheet = model.sheets[key[0]]
        scaled_text = _fmt(new_vals[key])
        cells[sheet.part]["s"][cell.ref] = [origs[key], scaled_text]
        _set_v(cell, scaled_text)
    for key in plan.excluded:
        if len(key) == 3:
            si, col, row = key
            cells[model.sheets[si].part]["x"].append(model.sheets[si].cells[(col, row)].ref)
    memo = getattr(getattr(plan, "degrees", None), "memo", {})
    formulas = 0
    for si, sheet in enumerate(model.sheets):
        snap = cells[sheet.part]["snap"]
        for (col, row), cell in sheet.cells.items():
            key = (si, col, row)
            if cell.kind in ("formula", "member"):
                pair = memo.get(key)
                deg = "m" if pair == (1, 0) else "d" if pair == ZERO else "x" if pair == (0, 1) else "u"
                snap[cell.ref] = ["f", (cell.ftext or "").strip(), deg]
                _drop_cached(cell)
                cells[sheet.part]["f"].append(cell.ref)
                formulas += 1
            elif cell.kind == "num":
                v = cell.node.find("{*}v")
                masked = canon_number((v.text or "")) if v is not None else None
                cls = "m" if key in plan.scaled else "x" if key in plan.excluded else "d"
                snap[cell.ref] = ["n", cells[sheet.part]["s"].get(cell.ref, [masked])[0] if cls != "m" else cells[sheet.part]["s"][cell.ref][0],
                                  masked, cls]
            elif cell.kind == "text" and cell.text.strip():
                canon = canon_number(cell.text.strip())
                if canon is not None and abs(Decimal(canon)) >= 1000 and (
                        verdict_for_label(model.row_label(sheet, col, row)) == "money"
                        or verdict_for_label(model.header(sheet, col, row)) == "money"):
                    masked_text = _fmt(scale_value(Decimal(canon), plan.factors[si]))
                    _set_inline(cell.node, masked_text)
                    snap[cell.ref] = ["t", masked_text, cell.text.strip()]
                    cells[sheet.part]["s"][cell.ref] = [cell.text.strip(), masked_text]
                else:
                    snap[cell.ref] = ["s", cell.text]
    _blank_orphan_strings(model, cells)
    consts = []
    k0 = plan.factors[0] if plan.factors else make_factor()
    for name, node in getattr(plan, "names", {}).items():
        text = (node.text or "").strip()
        new = _fmt(scale_value(Decimal(canon_number(text)), k0))
        consts.append({"part": "xl/workbook.xml", "kind": "name", "name": name, "orig": text, "scaled": new})
        node.text = new
    pairs: list = []
    amounts_left = 0
    for part, root in model.parsed.items():
        low = part.lower()
        if low == "xl/sharedstrings.xml" or (re.match(r"^xl/worksheets/[^/]+\.xml$", low)):
            for t in root.iter():
                if _local(t) == "t" and t.text and re.search(r"\d", t.text) and (low == "xl/sharedstrings.xml" or _local(t.getparent()) == "is"
                                                                                 or _local(t.getparent().getparent()) == "is"):
                    if text_amounts:
                        t.text = _scale_text(t.text, k0, pairs)
                    else:
                        probe: list = []
                        _scale_text(t.text, k0, probe)
                        amounts_left += len(probe)
    surfaces = finance_surfaces.mask_surfaces(model, plan, k0, scale_value, _scale_text, text_amounts)
    _scale_charts(model, plan, consts)
    _neutralize_caches(model.parsed)
    if amounts_left:
        where = _cells_with_text_amounts(model)
        notes.append(f"В тексте ячеек остались суммы ({amounts_left}): " + (", ".join(where[:8]) + (" и др." if len(where) > 8 else "") + "; " if where else "")
                     + "включите «Суммы в тексте ячеек и примечаний»")
    unknown = []
    for key, (klass, _why) in plan.classes.items():
        if klass == "unknown" and key not in plan.excluded:
            cell = model.sheets[key[0]].cells[(key[1], key[2])]
            if abs(cell.value) >= 1000:
                unknown.append(f"{model.sheets[key[0]].name}!{cell.ref}")
    if unknown:
        notes.append(f"Числа от 1000 без признаков суммы остались видимыми ({len(unknown)}): " + ", ".join(unknown[:8])
                     + (" и др." if len(unknown) > 8 else ""))
    record = {"id": fin_id, "v": 2, "sheets": sheets, "cells": cells, "consts": consts, "text_map": pairs, "k": list(k0),
              "surfaces": surfaces, "created": __import__("time").time()}
    stamp_workbook(model.parsed["xl/workbook.xml"], fin_id)
    numeric.request_recalculation(model.parsed["xl/workbook.xml"])
    vault.finance[fin_id] = record
    vault.dirty = True
    return {"scaled": len(plan.scaled), "formulas": formulas, "excluded": len([k for k in plan.excluded if len(k) == 3]),
            "texts": len(pairs), "surfaces": len(surfaces), "tie_out": repaired, "notes": notes, "id": fin_id}


def stamp_workbook(wb_root, fin_id: str) -> None:
    ns = etree.QName(wb_root).namespace
    holder = next((n for n in wb_root if _local(n) == "definedNames"), None)
    if holder is None:
        holder = etree.Element(f"{{{ns}}}definedNames")
        anchor = None
        for n in wb_root:
            if _local(n) in ("sheets", "functionGroups", "externalReferences"):
                anchor = n
        anchor.addnext(holder) if anchor is not None else wb_root.insert(0, holder)
    node = etree.SubElement(holder, f"{{{ns}}}definedName")
    node.set("name", STAMP_PREFIX + fin_id)
    node.set("hidden", "1")
    node.text = "0"


def read_stamp(wb_root) -> str:
    for n in wb_root.iter():
        if _local(n) == "definedName" and (n.get("name") or "").startswith(STAMP_PREFIX):
            return n.get("name")[len(STAMP_PREFIX):]
    return ""


def remove_stamp(wb_root) -> None:
    for n in list(wb_root.iter()):
        if _local(n) == "definedName" and (n.get("name") or "").startswith(STAMP_PREFIX):
            parent = n.getparent()
            parent.remove(n)
            if len(parent) == 0:
                parent.getparent().remove(parent)


def _neutralize_caches(parsed: dict) -> None:
    """Кэш сводных таблиц и внешних связей хранит настоящие значения: обнуляется, сводная обновится при открытии."""
    for part, root in parsed.items():
        low = part.lower()
        if "/pivotcache/" in low:
            for n in root.iter():
                if _local(n) == "n" and n.get("v") is not None:
                    n.set("v", "0")
                if _local(n) == "pivotCacheDefinition":
                    n.set("refreshOnLoad", "1")
        elif "/externallinks/" in low and "_rels" not in low:
            for n in root.iter():
                if _local(n) == "cell":
                    for v in [x for x in n if _local(x) == "v"]:
                        v.text = "0"


def _range_cells(model: Model, formula: str):
    try:
        node = parse_ref(formula.replace("$", "$").strip("()"))
    except Conflict:
        return None
    an = Analysis(model, set(), set())
    si = an.sheet_of(node[1], 0) if node[1] else 0
    if si is None:
        return None
    return si, sorted(an.cells_in(si, node), key=lambda c: (c.row, c.col)), an


def _scale_charts(model: Model, plan: Plan, consts: list) -> None:
    for part, root in model.parsed.items():
        if "/charts/" not in part.lower() or "_rels" in part:
            continue
        for cache in [n for n in root.iter() if _local(n) == "numCache"]:
            ser_f = cache.getparent().find("{*}f")
            info = _range_cells(model, ser_f.text) if ser_f is not None and ser_f.text else None
            for pt in [p for p in cache if _local(p) == "pt"]:
                idx = int(pt.get("idx", "0"))
                v = pt.find("{*}v")
                keep = False
                if info and idx < len(info[1]):
                    cell = info[1][idx]
                    key = (info[0], cell.col, cell.row)
                    if cell.kind == "num" and key in plan.scaled and v is not None:
                        v.text = (cell.node.find("{*}v").text or "")
                        keep = True
                    elif cell.kind == "num" and key not in plan.scaled and key not in plan.excluded and (plan.classes.get(key, ("",))[0] != "money"):
                        keep = True
                    elif cell.kind == "num" and key in plan.excluded:
                        keep = True
                if not keep:
                    cache.remove(pt)


# -- восстановление --------------------------------------------------------------------------

def find_record(vault, parsed: dict):
    wb = parsed.get("xl/workbook.xml")
    if wb is None or not getattr(vault, "finance", None):
        return None
    fin_id = read_stamp(wb)
    if fin_id and fin_id in vault.finance:
        return vault.finance[fin_id]
    best, score = None, 0
    try:
        model = Model(parsed)
    except Exception:
        return None
    for rec in vault.finance.values():
        hit = 0
        for sheet in model.sheets:
            for ref, (orig, scaled) in rec["cells"].get(sheet.part, {}).get("s", {}).items():
                m = re.match(r"^([A-Z]+)(\d+)$", ref)
                cell = sheet.cells.get((col_to_num(m.group(1)), int(m.group(2)))) if m else None
                if cell is not None and cell.kind == "num" and canon_number(scaled) == canon_number(str(cell.value)):
                    hit += 1
        if hit > score:
            best, score = rec, hit
    return best if score >= 3 else None


def restore_workbook(parsed: dict, record: dict, vault=None) -> dict:
    """Возврат: сравнение возвращённого файла со снимком выданного и перенос правок в исходные единицы (finance_restore)."""
    from .finance_restore import restore_by_patch
    return restore_by_patch(parsed, record)


# -- проверка выхода -------------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.,])\d[\d   .,]*\d(?![\w])|(?<![\w.,])\d(?![\w.,])")
_MULT = {"k": 3, "K": 3, "тыс": 3, "m": 6, "M": 6, "млн": 6, "mln": 6, "b": 9, "B": 9, "млрд": 9, "bn": 9}
_VALUE_ATTRS = {"val", "v", "formatCode", "max", "min", "formula", "fmla", "error", "errorTitle", "prompt", "promptTitle"}
_ID_TAGS = {"axId", "crossAx"}


def _significant(value: Decimal) -> int:
    digits = format(abs(value).normalize(), "f").replace(".", "").lstrip("0").rstrip("0")
    return len(digits)


def _secret_worthy(value: Decimal) -> bool:
    """Круглые суммы от 100 000 тоже считаются настоящими (4 200 000 — это сумма, а не совпадение), мелкие круглые нет."""
    return abs(value) >= 100000 or (abs(value) >= 100 and _significant(value) >= 3)


def _variants(token: str):
    clean = re.sub(r"[   ]", "", token)
    out = {clean}
    if "," in clean and "." in clean:
        last = max(clean.rfind(","), clean.rfind("."))
        out.add(clean[:last].replace(",", "").replace(".", "") + "." + clean[last + 1:])
    else:
        out.add(clean.replace(",", "."))
        out.add(clean.replace(",", ""))
        out.add(clean.replace(".", ""))
        if clean.count(".") > 1:
            out.add(clean.replace(".", "", clean.count(".") - 1))
    return out


def _value_texts(root):
    """Тексты и значимые атрибуты узлов (без адресов ячеек, ширин и т. п.)."""
    for n in root.iter():
        if not isinstance(n.tag, str) or _local(n) in _ID_TAGS:
            continue
        if n.text and n.text.strip():
            yield n.text
        if (etree.QName(n).namespace or "").endswith("/drawingml/2006/main"):
            continue                    # lumMod/tint/alpha и т. п.: проценты цвета, не суммы
        for key in _VALUE_ATTRS:
            val = n.get(key)
            if val:
                yield val


def verify_output(path, record: dict, text_amounts: bool = False, warnings: list | None = None) -> list[str]:
    """Что осталось от настоящих сумм в готовом файле (пусто — чисто). Ячейки проверяются по адресу, остальные части — по значениям.

    Число, которое случайно совпало с настоящей суммой в другом месте и осталось видимым намеренно (год, количество, исключённая
    ячейка), файл не блокирует. warnings получает названные предупреждения о числах, которые могли остаться неузнанными."""
    from lxml import etree as _et
    leaks: list[str] = []
    clear: set[str] = set()
    masked_all: set[str] = set()
    secret: set[str] = set()
    rounded: set[tuple[int, str]] = set()
    sheet_parts = {}
    for part, entry in record["cells"].items():
        sheet_parts[part] = entry
        for ref, (orig, scaled) in entry.get("s", {}).items():
            masked_all.add(canon_number(scaled))
            value = Decimal(canon_number(orig))
            if _secret_worthy(value):
                secret.add(canon_number(orig))
                for exp in (3, 6, 9):
                    for places in (0, 1, 2, 3):
                        q = (abs(value) / Decimal(10) ** exp).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
                        if q >= 1:
                            rounded.add((exp, _fmt(q)))
        for ref, item in entry.get("snap", {}).items():
            if item[0] == "n" and item[3] in ("d", "x"):
                clear.add(canon_number(item[2]) or "")
    for rec in record.get("surfaces", []):
        gone = {m.group(0) for m in _NUMBER.finditer(rec["orig"])} - {m.group(0) for m in _NUMBER.finditer(rec["masked"])}
        for tok in gone:
            for var in _variants(tok):
                c = canon_number(var)
                if c and _secret_worthy(Decimal(c)):
                    secret.add(c)
    for rec in record.get("surfaces", []):
        for m in _NUMBER.finditer(rec["masked"]):
            for var in _variants(m.group(0)):
                if canon_number(var):
                    masked_all.add(canon_number(var))
    for c in record.get("consts", []):
        c1 = canon_number(c["orig"])
        if c1:
            secret.add(c1)
        if c.get("scaled") and canon_number(c["scaled"]):
            masked_all.add(canon_number(c["scaled"]))
    secret -= masked_all
    secret -= clear
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".bin", ".emf", ".wmf", ".ttf", ".rels")) or name.lower().startswith("xl/theme/"):
                continue
            raw = z.read(name)
            try:
                root = _et.fromstring(raw, _et.XMLParser(resolve_entities=False, huge_tree=True))
            except Exception:
                continue
            low = name.lower()
            if name in sheet_parts:
                entry = sheet_parts[name]
                for c in root.iter():
                    if isinstance(c.tag, str) and _local(c) == "c" and c.get("r") in entry.get("s", {}):
                        v = c.find("{*}v")
                        orig, scaled = entry["s"][c.get("r")]
                        if v is not None and v.text and canon_number(v.text) == canon_number(orig) and canon_number(orig) != canon_number(scaled):
                            leaks.append(f"{name}!{c.get('r')}: настоящая сумма в ячейке")
                # всё, кроме данных ячеек, проверяется по значениям
                for sd in [n for n in root.iter() if isinstance(n.tag, str) and _local(n) == "sheetData"]:
                    if sd.getparent() is not None:
                        sd.getparent().remove(sd)
            if name == "xl/workbook.xml":
                for n in [n for n in root.iter() if isinstance(n.tag, str) and _local(n) == "definedName" and (n.get("name") or "").startswith(STAMP_PREFIX)]:
                    n.getparent().remove(n)
            is_strings = low == "xl/sharedstrings.xml"
            hits: list[str] = []
            for text in _value_texts(root):
                for m in _NUMBER.finditer(text):
                    token = m.group(0)
                    hit = None
                    for variant in _variants(token):
                        if canon_number(variant) in secret:
                            hit = token
                            break
                    if hit is None:
                        mm = re.match(r"\s?(млрд|млн|тыс|mln|bn|[kKmMbB])\b", text[m.end():m.end() + 7])
                        if mm and any((_MULT[mm.group(1)], canon_number(v)) in rounded for v in _variants(token)):
                            hit = token
                    if hit is not None:
                        hits.append(hit)
                    elif warnings is not None and not is_strings:
                        c = canon_number(token)
                        if c and abs(Decimal(c)) >= 1000 and _significant(Decimal(c)) >= 4 and c not in masked_all and c not in clear \
                                and not re.search(r"(?i)xl/(theme|styles)|docprops/|calcchain|/printersettings", low) and not (1900 <= abs(Decimal(c)) <= 2100):
                            warnings.append(f"{name}: число {token} не обработано (не совпало с известными суммами)")
            if hits:
                if is_strings and not text_amounts:
                    if warnings is not None:
                        warnings.append(f"{name}: суммы в тексте ячеек не замаскированы ({', '.join(hits[:3])})")
                else:
                    leaks.append(f"{name}: {', '.join(hits[:3])}")
    return leaks
