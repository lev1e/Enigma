"""Числа вне ячеек: условное форматирование, проверка данных, литералы форматов, примечания, текст фигур, оси диаграмм.

Тот же множитель, что и для ячеек; каждая замена записывается (часть, вид, было, стало), возврат заменяет строку обратно.
"""

from __future__ import annotations

import re
from decimal import Decimal

from lxml import etree

from .finance_formula import col_to_num, parse_ref, Conflict
from .vault import canon_number

_NUM_LIT = re.compile(r'"[^"]*"|(?<![\w$.!\'])(\d+(?:\.\d+)?)(?![\w.(!:\'])')
ATTR_KEYS = {"cfvo": "val", "numFmt": "formatCode", "max": "val", "min": "val", "majorUnit": "val", "minorUnit": "val"}
XM = "http://schemas.microsoft.com/office/excel/2006/main"
AXIS_TAGS = {"max", "min", "majorUnit", "minorUnit"}


def _local(node) -> str:
    return etree.QName(node).localname if isinstance(node.tag, str) else ""


def _fmt(d: Decimal) -> str:
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def iter_surfaces(parsed: dict):
    """(часть, узел, атрибут|None, вид, sqref): все места вне ячеек, где может стоять число."""
    for part, root in parsed.items():
        low = part.lower()
        if root is None or not hasattr(root, "iter"):
            continue
        if re.match(r"^xl/worksheets/[^/]+\.xml$", low):
            for cf in root.iter():
                n = _local(cf)
                if n == "conditionalFormatting":
                    sq = cf.get("sqref") or ""
                    for d in cf.iter():
                        ln = _local(d)
                        if ln == "formula":
                            yield part, d, None, "cf", sq
                        elif ln == "cfvo" and d.get("val") is not None and d.get("type") in ("num", "formula"):
                            yield part, d, "val", "cf", sq
                elif n == "dataValidation":
                    sq = cf.get("sqref") or ""
                    for d in cf:
                        if _local(d) in ("formula1", "formula2"):
                            yield part, d, None, "dv", sq
                    for att in ("error", "errorTitle", "prompt", "promptTitle"):
                        if cf.get(att) and re.search(r"\d", cf.get(att)):
                            yield part, cf, att, "dvtext", ""
            for d in root.iter():
                # расширенное условное форматирование и проверка данных (x14): формулы в xm:f
                if isinstance(d.tag, str) and _local(d) == "f" and etree.QName(d).namespace == XM:
                    yield part, d, None, "cf", ""
        elif low == "xl/styles.xml":
            for d in root.iter():
                if _local(d) == "numFmt" and d.get("formatCode") and '"' in d.get("formatCode") and re.search(r"\d", d.get("formatCode")):
                    yield part, d, "formatCode", "fmt", ""
        elif re.match(r"^xl/comments[^/]*\.xml$", low):
            for d in root.iter():
                if _local(d) == "t" and d.text and re.search(r"\d", d.text):
                    yield part, d, None, "comment", ""
        elif "threadedcomment" in low:
            for d in root.iter():
                if _local(d) == "text" and d.text and re.search(r"\d", d.text):
                    yield part, d, None, "comment", ""
        elif low.startswith("xl/drawings/") and not low.endswith(".rels"):
            for d in root.iter():
                if _local(d) == "t" and d.text and re.search(r"\d", d.text):
                    yield part, d, None, "draw", ""
        elif low.startswith("xl/charts/") and "_rels" not in low:
            for d in root.iter():
                ln = _local(d)
                if ln in AXIS_TAGS and d.get("val") is not None:
                    yield part, d, "val", "axis", ""
                elif ln == "t" and d.text and re.search(r"\d", d.text):
                    yield part, d, None, "charttext", ""
        elif low.startswith("xl/pivotcache/") and "_rels" not in low:
            for d in root.iter():
                ln = _local(d)
                if ln in ("sharedItems", "cacheField") or ln == "n":
                    for att in ("minValue", "maxValue", "v"):
                        if d.get(att) is not None and (ln == "n" or att != "v") and re.search(r"\d", d.get(att)):
                            yield part, d, att, "pivot", ""
        elif low.startswith("docprops/") and not low.endswith(".rels") and low != "docprops/core.xml":
            for d in root.iter():
                if isinstance(d.tag, str) and d.text and re.search(r"\d{4,}", d.text) and len(d) == 0 and _local(d) in ("lpstr", "i4", "r8", "i8", "lpwstr"):
                    yield part, d, None, "prop", ""


def _get(node, attr):
    return node.get(attr) if attr else (node.text or "")


def _set(node, attr, value):
    if attr:
        node.set(attr, value)
    else:
        node.text = value


def _sqref_cells(sqref: str):
    for part in sqref.split():
        try:
            ref = parse_ref(part.replace("$", ""))
        except Conflict:
            continue
        _, _, c1, r1, c2, r2 = ref
        yield (c1[0] or 1, c2[0] or 16384, r1[0] or 1, r2[0] or 1048576)


def _applies(sheet_cells: dict, sqref: str, scaled_keys: set, si: int) -> bool | None:
    """True: диапазон в основном из масштабированных сумм; False: из несуммовых чисел; None: чисел нет."""
    yes = no = 0
    for c1, c2, r1, r2 in _sqref_cells(sqref):
        for (cc, rr), cell in sheet_cells.items():
            if cell.kind == "num" and c1 <= cc <= c2 and r1 <= rr <= r2:
                if (si, cc, rr) in scaled_keys:
                    yes += 1
                else:
                    no += 1
    if not yes and not no:
        return None
    return yes >= no


def _scale_literals(text: str, k, scale, whole_ok: bool) -> str:
    stripped = text.strip()
    if canon_number(stripped.lstrip("=")) is not None and re.fullmatch(r"=?-?[\d.,\s]+", stripped):
        value = Decimal(canon_number(stripped.lstrip("=")))
        if whole_ok or abs(value) >= 1000:
            return ("=" if stripped.startswith("=") else "") + _fmt(scale(value, k))
        return text

    def repl(m):
        if m.group(1) is None:
            return m.group(0)
        value = Decimal(m.group(1))
        if value >= 1000 and whole_ok is not False:
            return _fmt(scale(value, k))
        return m.group(0)
    if stripped.startswith('"') and stripped.endswith('"'):
        items = stripped[1:-1].split(",")
        out = []
        for it in items:
            c = canon_number(it.strip())
            out.append(_fmt(scale(Decimal(c), k)) if c is not None and (whole_ok or abs(Decimal(c)) >= 1000) else it)
        return '"' + ",".join(out) + '"'
    return _NUM_LIT.sub(repl, text)


def mask_surfaces(model, plan, k, scale, scale_text, text_amounts: bool) -> list[dict]:
    """Заменяет числа вне ячеек на месте. -> записи [{part, kind, orig, masked}]."""
    records: list[dict] = []
    scaled_keys = set(plan.scaled)
    known_values = {c.value for c in plan.scaled.values() if c.value is not None}
    sheet_by_part = {s.part: (i, s) for i, s in enumerate(model.sheets)}
    for part, node, attr, kind, sqref in list(iter_surfaces(model.parsed)):
        orig = _get(node, attr)
        if kind in ("cf", "dv"):
            si, sheet = sheet_by_part.get(part, (0, None))
            verdict = _applies(sheet.cells, sqref, scaled_keys, si) if sheet is not None and sqref else None
            if verdict is False:
                continue
            new = _scale_literals(orig, k, scale, whole_ok=bool(verdict))
        elif kind == "fmt":
            pairs: list = []
            new = re.sub(r'"([^"]*)"', lambda m: '"' + scale_text(m.group(1), k, pairs, True) + '"', orig)
        elif kind == "pivot":
            c = canon_number(orig)
            if c is None or Decimal(c) not in known_values:
                continue
            new = _fmt(scale(Decimal(c), k))
        elif kind == "axis":
            ch = _chart_scaled(model, part, plan)
            if not ch:
                continue
            c = canon_number(orig)
            new = _fmt(scale(Decimal(c), k)) if c is not None else orig
        else:   # comment / draw / charttext / dvtext / prop
            if kind == "charttext" and not text_amounts:
                continue
            new = scale_text(orig, k, [], True)
        if new != orig:
            _set(node, attr, new)
            records.append({"part": part, "kind": kind, "orig": orig, "masked": new})
    return records


def _chart_scaled(model, part: str, plan) -> bool:
    root = model.parsed.get(part)
    if root is None:
        return False
    from .finance import _range_cells
    for f in root.iter():
        if _local(f) == "f" and f.text:
            info = _range_cells(model, f.text)
            memo = getattr(getattr(plan, "degrees", None), "memo", {})
            if info and any((info[0], c.col, c.row) in plan.scaled or memo.get((info[0], c.col, c.row)) == (1, 0) for c in info[1]):
                return True
    return False


def restore_surfaces(parsed: dict, records: list[dict]) -> dict:
    """Возвращает настоящие строки там, где замаскированная строка осталась на месте."""
    done = missing = 0
    by_part: dict = {}
    for r in records:
        by_part.setdefault((r["part"], r["kind"]), []).append(r)
    seen = set()
    for part, node, attr, kind, _sq in list(iter_surfaces(parsed)):
        for r in by_part.get((part, kind), ()):
            cur = _get(node, attr)
            if cur == r["masked"]:
                _set(node, attr, r["orig"])
                seen.add(id(r))
                done += 1
                break
            if kind in ("comment", "draw", "charttext", "prop") and r["masked"] in cur:
                _set(node, attr, cur.replace(r["masked"], r["orig"]))
                seen.add(id(r))
                done += 1
                break
    missing = sum(1 for r in records if id(r) not in seen)
    return {"surfaces": done, "surfaces_missing": missing}
