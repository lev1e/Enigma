"""Разбор формул Excel и вывод «степени денежности» результата (dimensional analysis).

Каждое число в модели имеет степень (a, b): значение хранится как истинное * k**a, где k — секретный множитель
(a=1 для замаскированных сумм), а b — степень «видимых» сумм (исключённых из маскирования, b=1). Безразмерные числа
(доли, проценты, количества) имеют (0, 0). Допустимы только степени (0,0), (1,0), (0,1): сумма, умноженная на сумму,
сумма плюс число и т. п. дают недопустимую степень — формула помечается как конфликтная.
Формулы здесь никогда не переписываются, модуль только читает их.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

VALID = {(0, 0), (1, 0), (0, 1)}
ZERO = (0, 0)


class Conflict(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


CONFLICT_TEXT = {
    "mul": "произведение двух сумм",
    "div": "деление на сумму",
    "mix": "складываются или сравниваются суммы разного вида",
    "add_const": "к сумме прибавлено или с ней сравнивается число",
    "cmp_const": "сумма сравнивается с числом",
    "lookup": "поиск по значениям сумм",
    "text": "сумма превращается в текст",
    "unknown_fn": "функция, влияние которой на суммы неизвестно",
    "ref": "ссылка не распознана",
    "pow": "степень от суммы",
}

COL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")
TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<sheetref>(?:'(?:[^']|'')+'|[A-Za-z_Ѐ-ӿ][\w.Ѐ-ӿ]*)!(?:\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?\d+:\$?\d+))
  | (?P<ref>\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?(?![\w(\[]))
  | (?P<colrange>\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}(?![\w(]))
  | (?P<rowrange>\$?\d+:\$?\d+)
  | (?P<tbl>[A-Za-z_Ѐ-ӿ][\w.Ѐ-ӿ]*\[(?:[^\[\]]|\[[^\]]*\])*\])
  | (?P<thisrow>@[A-Za-z_Ѐ-ӿ][\w.Ѐ-ӿ]*|\[@[^\]]+\])
  | (?P<func>[A-Za-z_Ѐ-ӿ][\w.Ѐ-ӿ]*(?=\())
  | (?P<name>[A-Za-z_Ѐ-ӿ\\][\w.Ѐ-ӿ]*)
  | (?P<arr>\{[^}]*\})
  | (?P<op><>|<=|>=|[-+*/^&=<>%(),;:])
""", re.X)


def col_to_num(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def num_to_col(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def tokenize(text: str):
    pos, out = 0, []
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise Conflict("ref")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group(kind)))
    return out


def _split_sheet(token: str):
    if "!" in token and not token.startswith('"'):
        sheet, rest = token.rsplit("!", 1)
        if sheet.startswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
        return sheet, rest
    return None, token


def parse_ref(token: str):
    """-> ('ref', sheet, (c1, ca1), (r1, ra1), (c2, ca2), (r2, ra2)); столбцы и строки целиком получают границы 0 / 10**6."""
    sheet, rest = _split_sheet(token)
    parts = rest.split(":")
    cells = []
    for part in parts:
        m = re.match(r"^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$", part)
        if m:
            cells.append(((col_to_num(m.group(2)), bool(m.group(1))), (int(m.group(4)), bool(m.group(3)))))
            continue
        m = re.match(r"^(\$?)([A-Za-z]{1,3})$", part)
        if m:
            cells.append(((col_to_num(m.group(2)), bool(m.group(1))), (None, True)))
            continue
        m = re.match(r"^(\$?)(\d+)$", part)
        if m:
            cells.append(((None, True), (int(m.group(2)), bool(m.group(1)))))
            continue
        raise Conflict("ref")
    if len(cells) == 1:
        cells.append(cells[0])
    (c1, r1), (c2, r2) = cells
    return ("ref", sheet, c1, r1, c2, r2)


class Parser:
    def __init__(self, text: str):
        self.toks = tokenize(text.lstrip("="))
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        node = self.cmp()
        if self.i != len(self.toks):
            raise Conflict("ref")
        return node

    def cmp(self):
        left = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            left = ("cmp", op, left, self.concat())
        return left

    def concat(self):
        left = self.add()
        while self.peek()[1] == "&":
            self.take()
            left = ("cat", left, self.add())
        return left

    def add(self):
        left = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            left = ("bin", op, left, self.mul())
        return left

    def mul(self):
        left = self.pow()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            left = ("bin", op, left, self.pow())
        return left

    def pow(self):
        left = self.unary()
        while self.peek()[1] == "^":
            self.take()
            left = ("pow", left, self.unary())
        return left

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            return ("neg", self.unary()) if op == "-" else self.unary()
        node = self.atom()
        while self.peek()[1] == "%":
            self.take()
            node = ("pct", node)
        return node

    def atom(self):
        kind, value = self.take()
        if kind == "num":
            return ("num", Decimal(value))
        if kind == "str":
            return ("str", value[1:-1].replace('""', '"'))
        if kind in ("ref", "sheetref", "colrange", "rowrange"):
            return parse_ref(value)
        if kind == "tbl":
            return ("tbl", value)
        if kind == "thisrow":
            return ("thisrow", value)
        if kind == "arr":
            return ("num", None)
        if kind == "name":
            if value.upper() in ("TRUE", "FALSE"):
                return ("str", value)
            return ("name", value)
        if kind == "func":
            self.take()  # (
            args = []
            if self.peek()[1] == ")":
                self.take()
                return ("fn", value.upper().replace("_XLFN.", ""), args)
            while True:
                if self.peek()[1] in (",", ";"):
                    args.append(("num", None))
                else:
                    args.append(self.cmp())
                nxt = self.take()[1]
                if nxt == ")":
                    break
                if nxt not in (",", ";"):
                    raise Conflict("ref")
            return ("fn", value.upper().replace("_XLFN.", ""), args)
        if value == "(":
            node = self.cmp()
            if self.take()[1] != ")":
                raise Conflict("ref")
            return node
        raise Conflict("ref")


def parse_formula(text: str):
    return Parser(text).parse()


def shift_ref(node, dc: int, dr: int):
    """Относительные части ссылки сдвигаются (для общих формул t="shared")."""
    _, sheet, c1, r1, c2, r2 = node

    def mv(part, delta):
        value, absolute = part
        return (value if (value is None or absolute) else value + delta, absolute)
    return ("ref", sheet, mv(c1, dc), mv(r1, dr), mv(c2, dc), mv(r2, dr))


# -- степени ---------------------------------------------------------------------------------

def _valid(pair, why: str):
    if pair not in VALID:
        raise Conflict(why)
    return pair


def _num(x):
    """Значение -> ('P', пара) | ('L', число|None) | ('S',) | ('N',)."""
    return x


def _is_zero_lit(x) -> bool:
    return x[0] == "L" and x[1] is not None and x[1] == 0


def add(x, y):
    if x[0] in ("S", "N") or y[0] in ("S", "N"):
        return y if x[0] in ("S", "N") and y[0] not in ("S", "N") else x
    if x[0] == "P" and y[0] == "P":
        if x[1] != y[1]:
            raise Conflict("mix")
        return x
    if x[0] == "L" and y[0] == "L":
        return ("L", None)
    pair = x[1] if x[0] == "P" else y[1]
    lit = y if x[0] == "P" else x
    if pair != ZERO and not _is_zero_lit(lit):
        raise Conflict("add_const")
    return ("P", pair)


def mul(x, y, divide=False):
    if x[0] in ("S", "N") or y[0] in ("S", "N"):
        return ("N",)
    if x[0] == "L" and y[0] == "L":
        return ("L", None)
    if x[0] == "L":
        pair = y[1]
        return ("P", _valid((-pair[0], -pair[1]) if divide else pair, "div"))
    if y[0] == "L":
        return ("P", x[1])
    a = (x[1][0] - y[1][0], x[1][1] - y[1][1]) if divide else (x[1][0] + y[1][0], x[1][1] + y[1][1])
    return ("P", _valid(a, "div" if divide else "mul"))


def compare(x, y):
    if x[0] in ("S", "N") or y[0] in ("S", "N"):
        return ("P", ZERO)
    if x[0] == "P" and y[0] == "P":
        if x[1] != y[1]:
            raise Conflict("mix")
    elif x[0] == "P" or y[0] == "P":
        pair = x[1] if x[0] == "P" else y[1]
        lit = y if x[0] == "P" else x
        if pair != ZERO and not _is_zero_lit(lit):
            raise Conflict("cmp_const")
    return ("P", ZERO)


def unify(items):
    """Сложение произвольного числа значений (SUM, MIN, ветки IF...)."""
    result = ("N",)
    for item in items:
        result = add(result, item) if result[0] != "N" else item
    return result


SAME = {"SUM", "MIN", "MAX", "AVERAGE", "MEDIAN", "SUBTOTAL", "AGGREGATE", "MINA", "MAXA", "AVERAGEA"}
FIRST = {"ABS", "ROUND", "ROUNDUP", "ROUNDDOWN", "INT", "TRUNC", "FLOOR", "CEILING", "MROUND", "LARGE", "SMALL",
         "N", "VALUE", "NEG", "CEILING.MATH", "FLOOR.MATH"}
ZEROFN = {"COUNT", "COUNTA", "COUNTIF", "COUNTIFS", "COUNTBLANK", "ROW", "COLUMN", "ROWS", "COLUMNS", "YEAR", "MONTH", "DAY",
          "DATE", "TODAY", "NOW", "LEN", "ISNUMBER", "ISBLANK", "ISERROR", "ISERR", "ISTEXT", "ISNA", "AND", "OR", "NOT",
          "TRUE", "FALSE", "NA", "SIGN", "IRR", "RATE", "RANK", "PERCENTRANK", "CORREL", "STDEV", "STDEV.S", "VAR",
          "WEEKDAY", "EOMONTH", "EDATE", "DAYS", "NETWORKDAYS", "XIRR", "MIRR", "ISLOGICAL", "ISEVEN", "ISODD", "COUNTUNIQUE",
          "SEARCH", "FIND", "EXACT", "ISFORMULA", "ISREF", "DATEDIF", "YEARFRAC", "MOD", "RAND", "RANDBETWEEN", "PI"}
TEXTFN = {"TEXT", "CONCATENATE", "CONCAT", "TEXTJOIN", "LEFT", "RIGHT", "MID", "FIXED", "DOLLAR", "TRIM", "UPPER", "LOWER",
          "SUBSTITUTE", "REPLACE", "T", "REPT", "PROPER"}


class Analyzer:
    """Вычисляет степени. `resolve(ref, offset)` -> пара | 'MIX' | None по ячейкам; `resolve_name`/`resolve_table` дают ссылку."""

    def __init__(self, resolve_range, resolve_name, resolve_table, current_sheet):
        self.resolve_range, self.resolve_name, self.resolve_table = resolve_range, resolve_name, resolve_table
        self.sheet = current_sheet

    def rng(self, node, dc, dr):
        if node[0] == "name":
            target = self.resolve_name(node[1], self.sheet)
            if target is None:
                return ("L", None)          # именованная константа вне денежных
            if target[0] == "value":
                return target[1]
            return self.rng(target[1], 0, 0)
        if node[0] in ("tbl", "thisrow"):
            target = self.resolve_table(node, self.sheet)
            if target is None:
                raise Conflict("ref")
            return self.rng(target, dc, dr)
        ref = shift_ref(node, dc, dr)
        res = self.resolve_range(ref, self.sheet)
        if res == "MIX":
            return ("MIX",)
        if res is None:
            return ("N",)
        return ("P", res)

    def column_of(self, node, col_index: int, dc, dr):
        """Столбец col_index (с 1) двумерного диапазона."""
        if node[0] in ("tbl", "thisrow", "name"):
            target = self.resolve_table(node, self.sheet) if node[0] != "name" else (self.resolve_name(node[1], self.sheet) or (None, None))[1]
            if not target:
                raise Conflict("ref")
            node = target
        _, sheet, c1, r1, c2, r2 = shift_ref(node, dc, dr)
        col = (c1[0] or 1) + col_index - 1
        sub = ("ref", sheet, (col, True), r1, (col, True), r2)
        return self.rng(sub, 0, 0)

    def ev(self, node, dc=0, dr=0):
        kind = node[0]
        if kind == "num":
            return ("L", node[1])
        if kind == "str":
            return ("S",)
        if kind in ("ref", "name", "tbl", "thisrow"):
            value = self.rng(node, dc, dr)
            if value[0] == "MIX":
                raise Conflict("mix")
            return value
        if kind == "neg":
            return self.ev(node[1], dc, dr)
        if kind == "pct":
            return self.ev(node[1], dc, dr)
        if kind == "cat":
            self.ev(node[1], dc, dr)
            self.ev(node[2], dc, dr)
            return ("S",)
        if kind == "bin":
            x, y = self.ev(node[2], dc, dr), self.ev(node[3], dc, dr)
            if node[1] in ("+", "-"):
                return add(x, y)
            return mul(x, y, divide=node[1] == "/")
        if kind == "pow":
            x, y = self.ev(node[1], dc, dr), self.ev(node[2], dc, dr)
            if x[0] == "P" and x[1] != ZERO:
                if y[0] == "L" and y[1] is not None and y[1] == 1:
                    return x
                raise Conflict("pow")
            return x if x[0] == "P" else ("L", None)
        if kind == "cmp":
            return compare(self.ev(node[2], dc, dr), self.ev(node[3], dc, dr))
        if kind == "fn":
            return self.fn(node[1], node[2], dc, dr)
        raise Conflict("ref")

    def ranges_of(self, args, dc, dr):
        out = []
        for arg in args:
            if arg[0] in ("ref", "name", "tbl", "thisrow"):
                value = self.rng(arg, dc, dr)
                if value[0] == "MIX":
                    raise Conflict("mix")
                out.append(value)
            else:
                out.append(self.ev(arg, dc, dr))
        return out

    def fn(self, name, args, dc, dr):
        if name in SAME:
            return unify(self.ranges_of(args[1:] if name in ("SUBTOTAL", "AGGREGATE") else args, dc, dr))
        if name in FIRST:
            first = self.ranges_of(args[:1], dc, dr)[0] if args else ("N",)
            for extra in args[1:]:
                self.ev(extra, dc, dr)
            return ("P", ZERO) if first[0] == "N" else first
        if name in ("IF", "IFERROR", "IFNA", "IFS", "CHOOSE", "SWITCH", "XOR"):
            if name == "IF":
                self.ev(args[0], dc, dr)
                branches = args[1:]
            elif name in ("IFERROR", "IFNA"):
                branches = args
            elif name == "IFS":
                for cond in args[0::2]:
                    self.ev(cond, dc, dr)
                branches = args[1::2]
            elif name == "CHOOSE":
                self.ev(args[0], dc, dr)
                branches = args[1:]
            elif name == "SWITCH":
                self.ev(args[0], dc, dr)
                branches = args[2::2] + ([args[-1]] if len(args) % 2 == 0 else [])
            else:
                for a in args:
                    self.ev(a, dc, dr)
                return ("P", ZERO)
            values = [self.ev(b, dc, dr) for b in branches]
            return unify(values) if values else ("P", ZERO)
        if name in ("SUMIF", "SUMIFS", "AVERAGEIF", "AVERAGEIFS"):
            return self.sumif(name, args, dc, dr)
        if name in ("VLOOKUP", "HLOOKUP", "LOOKUP"):
            table = args[1]
            idx = args[2] if len(args) > 2 else ("num", Decimal(1))
            key = self.ev(args[0], dc, dr)
            if key[0] == "P" and key[1] != ZERO:
                raise Conflict("lookup")
            if idx[0] != "num" or idx[1] is None:
                raise Conflict("lookup")
            if name == "HLOOKUP":
                raise Conflict("lookup")
            first = self.column_of(table, 1, dc, dr)
            if first[0] == "MIX" or (first[0] == "P" and first[1] != ZERO):
                raise Conflict("lookup")
            result = self.column_of(table, int(idx[1]), dc, dr)
            if result[0] == "MIX":
                raise Conflict("mix")
            return ("P", ZERO) if result[0] == "N" else result
        if name == "INDEX":
            value = self.ranges_of(args[:1], dc, dr)[0]
            for extra in args[1:]:
                self.ev(extra, dc, dr)
            return ("P", ZERO) if value[0] == "N" else value
        if name in ("MATCH", "XMATCH"):
            key = self.ev(args[0], dc, dr)
            rngv = self.ranges_of(args[1:2], dc, dr)[0]
            if (key[0] == "P" and key[1] != ZERO) or (rngv[0] == "P" and rngv[1] != ZERO):
                raise Conflict("lookup")
            return ("P", ZERO)
        if name == "XLOOKUP":
            key = self.ev(args[0], dc, dr)
            look = self.ranges_of(args[1:2], dc, dr)[0]
            if (key[0] == "P" and key[1] != ZERO) or (look[0] == "P" and look[1] != ZERO):
                raise Conflict("lookup")
            ret = self.ranges_of(args[2:3], dc, dr)[0]
            for extra in args[3:]:
                self.ev(extra, dc, dr)
            return ("P", ZERO) if ret[0] == "N" else ret
        if name == "NPV":
            rate = self.ev(args[0], dc, dr)
            if rate[0] == "P" and rate[1] != ZERO:
                raise Conflict("mix")
            return unify(self.ranges_of(args[1:], dc, dr))
        if name in ("PMT", "PPMT", "IPMT", "PV", "FV"):
            vals = self.ranges_of(args, dc, dr)
            money = [v for i, v in enumerate(vals) if i >= 2 and v[0] == "P" and v[1] != ZERO]
            for i, v in enumerate(vals[:2]):
                if v[0] == "P" and v[1] != ZERO:
                    raise Conflict("mix")
            return unify(money) if money else ("P", ZERO)
        if name == "SUMPRODUCT":
            vals = self.ranges_of(args, dc, dr)
            result = ("L", None)
            for v in vals:
                result = mul(result, v) if result[0] != "L" or result[1] is not None else (v if v[0] == "P" else result)
            return result if result[0] == "P" else ("P", ZERO)
        if name in TEXTFN:
            for v in self.ranges_of(args, dc, dr):
                if v[0] == "P" and v[1] != ZERO:
                    raise Conflict("text")
            return ("S",)
        if name in ZEROFN:
            for a in args:
                if a[0] in ("ref", "name", "tbl", "thisrow"):
                    self.rng(a, dc, dr)
                else:
                    self.ev(a, dc, dr)
            return ("P", ZERO)
        for v in self.ranges_of(args, dc, dr):
            if v[0] == "P" and v[1] != ZERO:
                raise Conflict("unknown_fn")
        return ("P", ZERO)

    def sumif(self, name, args, dc, dr):
        if name in ("SUMIF", "AVERAGEIF"):
            crit_range = self.ranges_of(args[:1], dc, dr)[0]
            crit = args[1]
            target = self.ranges_of(args[2:3], dc, dr)[0] if len(args) > 2 else crit_range
            pairs = [(crit_range, crit)]
        else:
            target = self.ranges_of(args[:1], dc, dr)[0]
            pairs = [(self.ranges_of([args[i]], dc, dr)[0], args[i + 1]) for i in range(1, len(args) - 1, 2)]
        for rng, crit in pairs:
            if rng[0] == "P" and rng[1] != ZERO:
                if crit[0] == "str" and re.match(r"^[<>=]+\s*-?\d", crit[1]):
                    raise Conflict("cmp_const")
                if crit[0] == "num" and crit[1] not in (None, 0):
                    raise Conflict("cmp_const")
                if crit[0] not in ("str", "num"):
                    other = self.ev(crit, dc, dr)
                    if other[0] == "P" and other[1] != rng[1]:
                        raise Conflict("mix")
            elif crit[0] not in ("str", "num"):
                self.ev(crit, dc, dr)
        return ("P", ZERO) if target[0] == "N" else target


def refs_in(node, out: list):
    """Все ссылки на диапазоны внутри разобранной формулы."""
    if not isinstance(node, tuple):
        return out
    if node and node[0] in ("ref", "name", "tbl", "thisrow"):
        out.append(node)
        return out
    for part in node[1:] if node and isinstance(node[0], str) else node:
        if isinstance(part, tuple):
            refs_in(part, out)
        elif isinstance(part, list):
            for item in part:
                refs_in(item, out)
    return out
