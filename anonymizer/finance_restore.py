"""Возврат сумм по принципу «заплатка к оригиналу»: возвращённый файл сравнивается со снимком того, что было выдано.

Для каждой ячейки находится её прежний адрес (по идентификатору листа, подписям строк и заголовкам столбцов, а не по номеру
строки), затем:
  * не менялась            -> настоящее значение из хранилища (то же число, что было);
  * правка суммы           -> перевод в исходные единицы (деление на коэффициент);
  * формула -> константа   -> перевод по степени денежности формулы (сумма делится, доля остаётся);
  * новая ячейка/лист      -> по подписи и формату; если решить нельзя, число остаётся как есть и попадает в список «проверить».
Ничто неоднозначное не проходит молча: такие ячейки названы в отчёте.
"""

from __future__ import annotations

import re
from decimal import Decimal
from difflib import SequenceMatcher

from . import finance as F
from .finance_formula import col_to_num
from .finance_surfaces import _NUM_LIT, restore_surfaces
from .vault import canon_number

_REF = re.compile(r"^([A-Z]+)(\d+)$")
MAX_NAMED = 8


def _canon(v) -> str:
    return canon_number(F._fmt(v)) if isinstance(v, Decimal) else (canon_number(str(v)) or str(v))


def _s_sig(entry):
    if entry[0] == "n":
        return ("n", canon_number(entry[2]))
    return ("s" if entry[0] == "t" else entry[0], entry[1])


def _r_sig(cell):
    if cell.kind == "num":
        return ("n", _canon(cell.value))
    if cell.kind == "text":
        return ("s", cell.text)
    return ("f", (cell.ftext or "").strip())


def align(s_full, s_lab, r_full, r_lab) -> dict:
    """{индекс справа: индекс слева}: точные совпадения, затем по подписям, затем позиционно для строк без подписи."""
    out: dict = {}
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, s_full, r_full, autojunk=False).get_opcodes():
        if tag == "equal":
            out.update({j1 + d: i1 + d for d in range(i2 - i1)})
        elif tag == "replace":
            pool: dict = {}
            for i in range(i1, i2):
                pool.setdefault(s_lab[i], []).append(i)
            for j in range(j1, j2):
                if r_lab[j] and pool.get(r_lab[j]):
                    out[j] = pool[r_lab[j]].pop(0)
            used = set(out.values())
            rem_s = [i for i in range(i1, i2) if i not in used and not s_lab[i]]
            rem_r = [j for j in range(j1, j2) if j not in out and not r_lab[j]]
            if len(rem_s) == len(rem_r):
                out.update(dict(zip(rem_r, rem_s)))
    return out


def _grid(snap: dict) -> dict:
    grid = {}
    for ref, entry in snap.items():
        m = _REF.match(ref)
        if m:
            grid[(col_to_num(m.group(1)), int(m.group(2)))] = entry
    return grid


def _align_sheet(S: dict, R: dict):
    """-> (карта строк R->S, карта столбцов R->S)."""
    by_row_s: dict = {}
    for (c, r), e in S.items():
        by_row_s.setdefault(r, []).append((c, e))
    by_row_r: dict = {}
    for (c, r), cell in R.items():
        if cell.kind in ("num", "text", "formula", "member"):
            by_row_r.setdefault(r, []).append((c, cell))
    s_rows, r_rows = sorted(by_row_s), sorted(by_row_r)
    srt = lambda items: sorted(items, key=lambda x: x[0])
    s_full = [tuple(_s_sig(e) for _c, e in srt(by_row_s[r])) for r in s_rows]
    s_lab = [tuple(e[1] for _c, e in srt(by_row_s[r]) if e[0] == "s") for r in s_rows]
    r_full = [tuple(_r_sig(c) for _c, c in srt(by_row_r[r])) for r in r_rows]
    r_lab = [tuple(c.text for _c, c in srt(by_row_r[r]) if c.kind == "text") for r in r_rows]
    rmap = {r_rows[j]: s_rows[i] for j, i in align(s_full, s_lab, r_full, r_lab).items()}
    s_cols = sorted({c for (c, _r) in S})
    r_cols = sorted({c for (c, r) in R if R[(c, r)].kind in ("num", "text", "formula", "member")})
    pairs = sorted(rmap.items(), key=lambda x: x[1])

    def col_sig_s(c):
        return tuple(_s_sig(S[(c, s)]) if (c, s) in S else None for _r, s in pairs)

    def col_sig_r(c):
        return tuple(_r_sig(R[(c, r)]) if (c, r) in R and R[(c, r)].kind in ("num", "text", "formula", "member") else None
                     for r, _s in pairs)

    def head_s(c):
        texts = [(r, e[1]) for (cc, r), e in S.items() if cc == c and e[0] == "s"]
        return min(texts)[1] if texts else ""

    def head_r(c):
        texts = [(r, cell.text) for (cc, r), cell in R.items() if cc == c and cell.kind == "text"]
        return min(texts)[1] if texts else ""

    cmap_idx = align([col_sig_s(c) for c in s_cols], [head_s(c) for c in s_cols],
                     [col_sig_r(c) for c in r_cols], [head_r(c) for c in r_cols])
    return rmap, {r_cols[j]: s_cols[i] for j, i in cmap_idx.items()}


def _literals(text: str) -> set:
    return {m.group(1) for m in _NUM_LIT.finditer(text or "") if m.group(1) is not None and Decimal(m.group(1)) >= 1000}


def restore_by_patch(parsed: dict, record: dict) -> dict:
    stats = {"exact": 0, "divided": 0, "new": 0, "kept": 0, "inferred": 0, "missing": 0}
    flags: list[str] = []
    changes: list[str] = []
    model = F.Model(parsed)
    by_id = {s.sheet_id: s for s in model.sheets}
    by_part = {s.part: s for s in model.sheets}
    by_name = {s.name: s for s in model.sheets}
    matched: dict = {}
    for info in record["sheets"]:
        sheet = by_id.get(info["sheetId"]) or by_part.get(info["part"]) or by_name.get(info["name"])
        if sheet is None or sheet.part in matched:
            stats["missing"] += len(record["cells"].get(info["part"], {}).get("s", {}))
            continue
        matched[sheet.part] = info
        if sheet.name != info["name"]:
            changes.append(f"лист «{info['name']}» переименован в «{sheet.name}»")
    k0 = tuple(record["k"])

    def back(sheet, cell, k, why):
        text = F._fmt(F.unscale_value(cell.value, k))
        F._set_v(cell, text)
        stats["divided"] += 1
        changes.append(f"{sheet.name}!{cell.ref}: {why} -> {text}")

    for sheet in model.sheets:
        info = matched.get(sheet.part)
        k = tuple(info["k"]) if info else k0
        S = _grid(record["cells"].get(info["part"], {}).get("snap", {})) if info else {}
        R = sheet.cells
        rmap, cmap = _align_sheet(S, R) if info else ({}, {})
        financial = sum(1 for c in R.values() if c.kind == "num" and F.classify_cell(model, sheet, c)[0] == "money") >= 3
        col_ctx: dict = {}
        for (c, _r), e in S.items():
            if e[0] == "n":
                col_ctx.setdefault(c, [0, 0])[0 if e[3] == "m" else 1] += 1
        unresolved: list[str] = []
        for (col, row), cell in list(R.items()):
            s_row, s_col = rmap.get(row), cmap.get(col)
            e = S.get((s_col, s_row)) if s_row is not None and s_col is not None else None
            if cell.kind == "formula":
                lit = _literals(cell.ftext)
                old = _literals(e[1]) if e is not None and e[0] == "f" else set()
                if lit - old:
                    flags.append(f"{sheet.name}!{cell.ref}: в формуле константа {sorted(lit - old)[0]}, единицы неизвестны — проверьте")
                continue
            if cell.kind == "text" and e is not None and e[0] == "t" and cell.text.strip() == e[1]:
                F._set_inline(cell.node, e[2])
                stats["exact"] += 1
                continue
            if cell.kind == "text" and canon_number(cell.text.strip() or "x") and abs(Decimal(canon_number(cell.text.strip()))) >= 1000 and (
                    (e is not None and e[0] == "n" and e[3] == "m") or (e is None and F.verdict_for_label(model.row_label(sheet, col, row)) == "money")):
                flags.append(f"{sheet.name}!{cell.ref}: число записано текстом, единицы неизвестны — оставлено как есть, проверьте")
                continue
            if cell.kind != "num" or cell.value == 0:
                continue
            masked = _canon(cell.value)
            if e is not None and e[0] == "n":
                if masked == canon_number(e[2]):
                    F._set_v(cell, e[1])
                    stats["exact"] += 1
                elif e[3] == "m":
                    back(sheet, cell, k, "правка суммы")
                else:
                    stats["kept"] += 1
                continue
            if e is not None and e[0] == "f":
                if e[2] == "m":
                    back(sheet, cell, k, "формула заменена значением")
                elif e[2] == "d":
                    stats["kept"] += 1
                else:
                    flags.append(f"{sheet.name}!{cell.ref}: формула заменена числом, единицы неизвестны — число оставлено как есть, проверьте")
                continue
            klass, why = F.classify_cell(model, sheet, cell, financial)
            if klass == "money":
                back(sheet, cell, k, "новое число (" + why + ")")
                stats["new"] += 1
            elif klass == "dimless":
                stats["kept"] += 1
            else:
                a = col_ctx.get(s_col) if s_col is not None else None
                if a and a[0] >= 2 and a[0] >= 0.7 * (a[0] + a[1]) and abs(cell.value) >= 100:
                    back(sheet, cell, k, "новое число (столбец сумм)")
                    stats["inferred"] += 1
                else:
                    unresolved.append(cell.ref)
        if unresolved:
            where = "лист" if info else "новый лист"
            more = " и др." if len(unresolved) > MAX_NAMED else ""
            flags.append(f"{where} «{sheet.name}»: {len(unresolved)} чисел не удалось отнести к суммам или к не-суммам "
                         f"({', '.join(unresolved[:MAX_NAMED])}{more}) — оставлены как есть, проверьте")
        for cell in sheet.cells.values():
            if cell.kind in ("formula", "member"):
                F._drop_cached(cell)
    wb = parsed["xl/workbook.xml"]
    for const in record.get("consts", []):
        for n in wb.iter():
            if F._local(n) == "definedName" and n.get("name") == const.get("name") and const["kind"] == "name":
                cur = canon_number(n.text or "")
                if cur is None:
                    flags.append(f"имя {const['name']}: значение заменено формулой, проверьте")
                elif cur == canon_number(const["scaled"]):
                    n.text = const["orig"]
                else:
                    n.text = F._fmt(F.unscale_value(Decimal(cur), k0))
                    changes.append(f"имя {const['name']}: правка -> {n.text}")
    for key, count in restore_surfaces(parsed, record.get("surfaces", [])).items():
        if key == "surfaces_missing" and count:
            flags.append(f"числа вне ячеек (условное форматирование, проверка данных, примечания и др.): {count} не найдены на месте — проверьте")
    pairs = record.get("text_map", [])
    if pairs:
        for part, root in parsed.items():
            low = part.lower()
            if low == "xl/sharedstrings.xml" or re.match(r"^xl/worksheets/[^/]+\.xml$", low):
                for t in root.iter():
                    if F._local(t) == "t" and t.text:
                        for scaled_text, orig_text in pairs:
                            if scaled_text in t.text:
                                t.text = t.text.replace(scaled_text, orig_text)
    for part, root in parsed.items():
        if "/charts/" in part.lower():
            for cache in [n for n in root.iter() if F._local(n) == "numCache"]:
                for pt in [p for p in cache if F._local(p) == "pt"]:
                    cache.remove(pt)
    F._neutralize_caches(parsed)
    F.remove_stamp(wb)
    F.numeric.request_recalculation(wb)
    stats["_flags"] = flags
    stats["_changes"] = changes
    return stats
