"""xlsx: адреса Лист!Ячейка, outline и операции правки (P2A). Формулы хранятся строкой и не вычисляются."""

from __future__ import annotations

import copy
import math
import re

from lxml import etree

from .docedit_core import (NS_CT, NS_REL, Elem, Opts, Package, PatchRejected, check_labels, check_plain_text, fingerprint,
                           q, stub_text)

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
x_ = lambda n: q(X, n)
REF_RE = re.compile(r"^([A-Za-z]{1,3})(\d{1,7})$")
BAD_FUNC_RE = re.compile(r"(?i)\b(WEBSERVICE|HYPERLINK|CALL|REGISTER|REGISTER\.ID|EXEC|RTD|DDE|FILTERXML|ENCODEURL|SQL\.REQUEST)\s*\(")
BUILTIN_FMT = {"General": 0, "0": 1, "0.00": 2, "#,##0": 3, "#,##0.00": 4, "0%": 9, "0.00%": 10, "0.00E+00": 11, "d/m/yyyy": 14,
               "@": 49}
BUILTIN_NAME = {v: k for k, v in BUILTIN_FMT.items()}


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_addr(addr, i: int):
    if not isinstance(addr, str) or "!" not in addr:
        raise PatchRejected("unknown_address", "Адрес ячейки: Лист!B4.", i, str(addr)[:40])
    sheet, _, ref = addr.rpartition("!")
    return sheet, ref


def parse_ref(ref: str, i: int, at: str) -> tuple[int, int]:
    m = REF_RE.match(ref or "")
    if not m or not 1 <= col_index(m.group(1)) <= 16384 or not 1 <= int(m.group(2)) <= 1048576:
        raise PatchRejected("unknown_address", "Неверная ссылка на ячейку.", i, at)
    return col_index(m.group(1)), int(m.group(2))


class XlsxHandler:
    fmt = "xlsx"
    OPS = {"replace_text", "comment", "set_cell", "number_format", "col_width"}
    SCHEMA = {
        "replace_text": ({"at", "expect", "text"}, set()),
        "comment": ({"at", "text"}, set()),
        "set_cell": ({"at"}, {"value", "formula", "expect"}),
        "number_format": ({"at", "format"}, set()),
        "col_width": ({"at", "width"}, set()),
    }

    def __init__(self, pkg: Package, opts: Opts):
        self.pkg, self.opts = pkg, opts
        self.wb_part = "xl/workbook.xml"
        if not pkg.has(self.wb_part):
            raise PatchRejected("bad_file", "Нет xl/workbook.xml.")
        wb = pkg.xml(self.wb_part)
        rels = pkg.rels(self.wb_part)
        self.sst = self._shared_strings(rels)
        self.containers: list[dict] = []
        self.sheets: dict[str, dict] = {}
        self.formulas_changed = False
        self.warnings: list[str] = []
        for sh in wb.iterfind(f"{x_('sheets')}/{x_('sheet')}"):
            tgt = rels.get(sh.get(q(NS_R, "id")))
            name = sh.get("name")
            if not tgt or not pkg.has(tgt[1]) or "worksheet" not in tgt[0]:
                self.containers.append({"addr": name, "kind": "sheet", "title": name, "hidden": sh.get("state") not in (None, "visible"),
                                        "part": None, "unsupported": True})
                continue
            c = {"addr": name, "kind": "sheet", "title": name, "hidden": sh.get("state") not in (None, "visible"), "part": tgt[1]}
            self.containers.append(c)
            self.sheets[name] = c
        self._cells: dict[str, dict[str, object]] = {}
        self._xf_cache: dict = {}
        self._styles_root = pkg.xml("xl/styles.xml") if pkg.has("xl/styles.xml") else None

    # ---- чтение ---
    def _shared_strings(self, rels) -> list[str]:
        part = next((t for ty, t in rels.values() if ty.endswith("/sharedStrings")), None)
        out = []
        if part and self.pkg.has(part):
            for si in self.pkg.xml(part).iterfind(x_("si")):
                t = "".join(el.text or "" for el in si.iterfind(x_("t"))) + "".join(
                    el.text or "" for el in si.iterfind(f"{x_('r')}/{x_('t')}"))
                out.append(t)
        return out

    def root_of(self, sheet: str):
        return self.pkg.xml(self.sheets[sheet]["part"])

    def cellmap(self, sheet: str) -> dict[str, object]:
        if sheet not in self._cells:
            m = {}
            for c in self.root_of(sheet).iterfind(f"{x_('sheetData')}/{x_('row')}/{x_('c')}"):
                if c.get("r"):
                    m[c.get("r").upper()] = c
            self._cells[sheet] = m
        return self._cells[sheet]

    def info(self, c) -> tuple[str, str, str]:
        """(тип, текст, причина запрета правки). Тип: text|number|bool|error|formula|empty."""
        f = c.find(x_("f"))
        v = c.find(x_("v"))
        t = c.get("t")
        if f is not None:
            reason = "общая или массивная формула" if f.get("t") in ("shared", "array", "dataTable") else ""
            return "formula", "=" + (f.text or ""), reason
        if t == "s":
            try:
                return "text", self.sst[int(v.text)], ""
            except (TypeError, ValueError, IndexError, AttributeError):
                return "text", "", ""
        if t == "inlineStr":
            isn = c.find(x_("is"))
            txt = "".join(el.text or "" for el in isn.iter(x_("t"))) if isn is not None else ""
            return "text", txt, ""
        if t == "str":
            return "text", v.text or "" if v is not None else "", ""
        if t == "b":
            return "bool", v.text if v is not None else "", ""
        if t == "e":
            return "error", v.text if v is not None else "", ""
        if v is None or v.text is None:
            return "empty", "", ""
        return "number", v.text, ""

    def fonts(self) -> set[str]:
        out = set()
        if self._styles_root is not None:
            out.update(n.get("val") for n in self._styles_root.iter(x_("name")) if n.get("val"))
        return out

    # ---- outline ---
    def _style(self, c) -> dict:
        st: dict = {}
        sr = self._styles_root
        if sr is None:
            return st
        xfs = sr.find(x_("cellXfs"))
        idx = int(c.get("s", 0) or 0)
        if xfs is None or idx >= len(xfs):
            return st
        xf = xfs[idx]
        nid = int(xf.get("numFmtId", 0))
        if nid:
            code = BUILTIN_NAME.get(nid)
            if code is None:
                nf = next((n for n in sr.iterfind(f"{x_('numFmts')}/{x_('numFmt')}") if n.get("numFmtId") == str(nid)), None)
                code = nf.get("formatCode") if nf is not None else f"builtin:{nid}"
            st["number_format"] = code
        fonts = sr.find(x_("fonts"))
        fid = int(xf.get("fontId", 0))
        if fonts is not None and fid < len(fonts):
            f = fonts[fid]
            for k, tag in (("size", "sz"), ("font", "name")):
                el = f.find(x_(tag))
                if el is not None and el.get("val"):
                    st[k] = float(el.get("val")) if k == "size" else el.get("val")
            for k, tag in (("bold", "b"), ("italic", "i")):
                if f.find(x_(tag)) is not None:
                    st[k] = True
            col = f.find(x_("color"))
            if col is not None and col.get("rgb"):
                st["color"] = col.get("rgb")
        al = xf.find(x_("alignment"))
        if al is not None and al.get("horizontal"):
            st["align"] = al.get("horizontal")
        return st

    def outline(self, stub: bool) -> dict:
        out = {"format": "xlsx", "fonts": sorted(self.fonts()), "containers": []}
        budget = self.opts.max_elements
        for cont in self.containers:
            d = {k: v for k, v in cont.items() if k != "part"}
            els: list[dict] = []
            if cont.get("part") and budget > 0:
                root = self.root_of(cont["addr"])
                widths = [{"cols": f"{col_letters(int(c.get('min')))}:{col_letters(int(c.get('max')))}", "width": float(c.get("width"))}
                          for c in root.iterfind(f"{x_('cols')}/{x_('col')}") if c.get("width") and c.get("min") and c.get("max")]
                d["col_widths"] = widths
                for ref, c in self.cellmap(cont["addr"]).items():
                    ctype, text, reason = self.info(c)
                    if ctype == "empty":
                        continue
                    if budget <= 0:
                        d["truncated"] = True
                        break
                    budget -= 1
                    ed = {"addr": f"{cont['addr']}!{ref}", "kind": "cell", "role": ctype,
                          "editable": not reason, "text": stub_text(text) if stub else text, "style": self._style(c)}
                    if not stub:
                        ed["fp"] = fingerprint(text)
                    if reason:
                        ed["flags"] = ["not_editable", reason]
                    els.append(ed)
            d["elements"] = els
            out["containers"].append(d)
        return out

    def all_texts(self):
        for name in self.sheets:
            for c in self.cellmap(name).values():
                ctype, text, _ = self.info(c)
                if text and ctype in ("text", "formula"):
                    yield text

    # ---- поиск и создание ячейки ---
    def find_cell(self, addr, i: int, create: bool = False):
        sheet, ref = split_addr(addr, i)
        if sheet not in self.sheets:
            raise PatchRejected("unknown_address", "Неизвестный лист.", i, str(addr)[:60])
        col, row = parse_ref(ref, i, addr)
        ref = f"{col_letters(col)}{row}"
        cells = self.cellmap(sheet)
        if ref in cells:
            return sheet, ref, cells[ref]
        if not create:
            raise PatchRejected("unknown_address", "В этой ячейке ничего нет.", i, addr)
        root = self.root_of(sheet)
        sd = root.find(x_("sheetData"))
        if sd is None:
            raise PatchRejected("bad_file", "Лист без sheetData.", i, addr)
        rowel = next((r for r in sd.iterfind(x_("row")) if r.get("r") == str(row)), None)
        if rowel is None:
            rowel = etree.Element(x_("row"))
            rowel.set("r", str(row))
            pos = 0
            for k, r in enumerate(sd.iterfind(x_("row"))):
                if int(r.get("r", 0)) < row:
                    pos = k + 1
            sd.insert(pos, rowel)
        c = etree.Element(x_("c"))
        c.set("r", ref)
        pos = 0
        for k, ex in enumerate(rowel.iterfind(x_("c"))):
            if col_index(REF_RE.match(ex.get("r")).group(1)) < col:
                pos = k + 1
        rowel.insert(pos, c)
        cells[ref] = c
        return sheet, ref, c

    def _elem(self, sheet, ref, c) -> Elem:
        ctype, text, reason = self.info(c)
        return Elem(f"{sheet}!{ref}", "cell", c, self.sheets[sheet]["part"], text=text, editable=not reason, reason=reason,
                    extra={"ctype": ctype})

    @staticmethod
    def _clear(c) -> None:
        for ch in list(c):
            if ch.tag in (x_("v"), x_("f"), x_("is")):
                c.remove(ch)
        c.attrib.pop("t", None)

    def _write_text(self, c, text: str) -> None:
        self._clear(c)
        c.set("t", "inlineStr")
        t = etree.SubElement(etree.SubElement(c, x_("is")), x_("t"))
        t.text = text
        if text != text.strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    # ---- операции ---
    def op_replace_text(self, ctx, i, op):
        sheet, ref, c = self.find_cell(op["at"], i)
        e = self._elem(sheet, ref, c)
        if e.extra["ctype"] != "text":
            raise PatchRejected("not_editable", "Это не текстовая ячейка: используйте set_cell для чисел и формул.", i, e.addr)
        ctx.expect(e, op, i)
        text = check_plain_text(op["text"], i, e.addr, self.opts, allow_newline=True)
        removed = check_labels(e.text, text, ctx.known, i, e.addr)
        ctx.grow(len(e.text), len(text))
        self._write_text(c, text)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, old=e.text, new=text, removed_labels=removed)

    def op_comment(self, ctx, i, op):
        self.find_cell(op["at"], i)
        text = check_plain_text(op["text"], i, op["at"], self.opts)
        if len(text) > self.opts.max_comment:
            raise PatchRejected("text_too_long", "Комментарий слишком длинный.", i, op["at"])
        check_labels(None, text, ctx.known, i, op["at"])
        ctx.comments.append({"at": op["at"], "text": text})
        ctx.done(i, op, op["at"], new=text, kind="comment")

    def op_set_cell(self, ctx, i, op):
        has_v, has_f = "value" in op, "formula" in op
        if has_v == has_f:
            raise PatchRejected("bad_op", "set_cell: укажите ровно одно из value или formula.", i, str(op.get("at"))[:40])
        sheet, ref, c = self.find_cell(op["at"], i, create=True)
        e = self._elem(sheet, ref, c)
        if not e.editable:
            raise PatchRejected("not_editable", f"Ячейка не редактируется ({e.reason}).", i, e.addr)
        if e.extra["ctype"] != "empty":
            ctx.expect(e, op, i)
        if has_f:
            f = op["formula"]
            if not isinstance(f, str):
                raise PatchRejected("bad_type", "Формула должна быть строкой.", i, e.addr)
            f = f[1:] if f.startswith("=") else f
            check_plain_text(f, i, e.addr, self.opts)
            if not f or len(f) > 1000 or "[" in f or BAD_FUNC_RE.search(f):
                raise PatchRejected("bad_formula", "Формула недопустима (внешние ссылки и опасные функции запрещены).", i, e.addr)
            new_text = "=" + f
            removed = check_labels(e.text, new_text, ctx.known, i, e.addr)
            self._clear(c)
            etree.SubElement(c, x_("f")).text = f       # значение не вычисляется и не хранится; Excel пересчитает при открытии
            self.formulas_changed = True
        else:
            v = op["value"]
            if isinstance(v, bool):
                self._clear(c)
                c.set("t", "b")
                etree.SubElement(c, x_("v")).text = "1" if v else "0"
                new_text, removed = "1" if v else "0", []
            elif isinstance(v, (int, float)):
                if isinstance(v, float) and not math.isfinite(v):
                    raise PatchRejected("bad_number", "Число недопустимо.", i, e.addr)
                new_text = repr(v)
                removed = check_labels(e.text, new_text, ctx.known, i, e.addr)
                self._clear(c)
                etree.SubElement(c, x_("v")).text = new_text
            elif isinstance(v, str):
                if v.startswith("="):
                    raise PatchRejected("bad_formula", "Для формулы используйте поле formula.", i, e.addr)
                new_text = check_plain_text(v, i, e.addr, self.opts, allow_empty=True, allow_newline=True)
                removed = check_labels(e.text, new_text, ctx.known, i, e.addr)
                self._write_text(c, new_text)
            else:
                raise PatchRejected("bad_type", "value: строка, число или true/false.", i, e.addr)
            if e.extra["ctype"] == "formula":
                self.formulas_changed = True
        ctx.grow(len(e.text), len(new_text))
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, old=e.text, new=new_text, removed_labels=removed, kind="set_cell")

    # -- формат числа ---
    def _range(self, addr, i: int):
        sheet, ref = split_addr(addr, i)
        if sheet not in self.sheets:
            raise PatchRejected("unknown_address", "Неизвестный лист.", i, str(addr)[:60])
        a, _, b = ref.partition(":")
        c1, r1 = parse_ref(a, i, addr)
        c2, r2 = parse_ref(b or a, i, addr)
        if c1 > c2 or r1 > r2 or (c2 - c1 + 1) * (r2 - r1 + 1) > 100000:
            raise PatchRejected("bad_range", "Диапазон недопустим.", i, addr)
        return sheet, (c1, r1, c2, r2)

    def _numfmt_id(self, code: str, i: int) -> int:
        if code in BUILTIN_FMT:
            return BUILTIN_FMT[code]
        sr = self._styles_root
        nfs = sr.find(x_("numFmts"))
        if nfs is None:
            nfs = etree.Element(x_("numFmts"))
            sr.insert(0, nfs)
        for n in nfs:
            if n.get("formatCode") == code:
                return int(n.get("numFmtId"))
        new_id = max([163] + [int(n.get("numFmtId")) for n in nfs]) + 1
        nf = etree.SubElement(nfs, x_("numFmt"))
        nf.set("numFmtId", str(new_id))
        nf.set("formatCode", code)
        nfs.set("count", str(len(nfs)))
        return new_id

    def op_number_format(self, ctx, i, op):
        code = op["format"]
        if not isinstance(code, str) or not code or len(code) > self.opts.max_numfmt or any(ord(ch) < 32 for ch in code):
            raise PatchRejected("bad_format", "Формат числа недопустим.", i, str(op.get("at"))[:40])
        if "[" in code and re.search(r"(?i)\[(?!(red|black|blue|green|white|cyan|magenta|yellow|color\d+|[<>=]|h+|m+|s+|\$|\d))", code):
            raise PatchRejected("bad_format", "Формат числа недопустим.", i, str(op.get("at"))[:40])
        sheet, (c1, r1, c2, r2) = self._range(op["at"], i)
        if self._styles_root is None:
            raise PatchRejected("bad_file", "В книге нет styles.xml.", i)
        cells = [c for ref, c in self.cellmap(sheet).items()
                 if (m := REF_RE.match(ref)) and c1 <= col_index(m.group(1)) <= c2 and r1 <= int(m.group(2)) <= r2]
        if not cells:
            raise PatchRejected("unknown_address", "В диапазоне нет ячеек.", i, op["at"])
        nid = self._numfmt_id(code, i)
        xfs = self._styles_root.find(x_("cellXfs"))
        for c in cells:
            old = int(c.get("s", 0) or 0)
            key = (old, nid)
            if key not in self._xf_cache:
                xf = copy.deepcopy(xfs[old])
                xf.set("numFmtId", str(nid))
                xf.set("applyNumberFormat", "1")
                xfs.append(xf)
                xfs.set("count", str(len(xfs)))
                self._xf_cache[key] = len(xfs) - 1
            c.set("s", str(self._xf_cache[key]))
        self.pkg.touch("xl/styles.xml")
        self.pkg.touch(self.sheets[sheet]["part"])
        ctx.done(i, op, op["at"], kind="number_format", new=code)

    # -- ширина столбцов ---
    def op_col_width(self, ctx, i, op):
        width = op["width"]
        if not isinstance(width, (int, float)) or isinstance(width, bool) or not 1 <= width <= min(255, self.opts.max_col_width_pt):
            raise PatchRejected("bad_number", "Ширина столбца вне допустимых пределов (1..255).", i, str(op.get("at"))[:40])
        sheet, ref = split_addr(op["at"], i)
        if sheet not in self.sheets:
            raise PatchRejected("unknown_address", "Неизвестный лист.", i, str(op["at"])[:60])
        a, _, b = ref.partition(":")
        if not re.fullmatch(r"[A-Za-z]{1,3}", a) or (b and not re.fullmatch(r"[A-Za-z]{1,3}", b)):
            raise PatchRejected("unknown_address", "Столбец: Лист!B или Лист!B:D.", i, str(op["at"])[:60])
        lo, hi = col_index(a), col_index(b or a)
        if not 1 <= lo <= hi <= 16384:
            raise PatchRejected("unknown_address", "Столбцы вне допустимых пределов.", i, op["at"])
        root = self.root_of(sheet)
        cols = root.find(x_("cols"))
        if cols is None:
            cols = etree.Element(x_("cols"))
            sd = root.find(x_("sheetData"))
            sd.addprevious(cols)
        for c in list(cols):
            cmin, cmax = int(c.get("min")), int(c.get("max"))
            if cmax < lo or cmin > hi:
                continue
            idx = list(cols).index(c)
            cols.remove(c)
            if cmin < lo:
                left = copy.deepcopy(c)
                left.set("max", str(lo - 1))
                cols.insert(idx, left)
                idx += 1
            if cmax > hi:
                right = copy.deepcopy(c)
                right.set("min", str(hi + 1))
                cols.insert(idx, right)
        new = etree.Element(x_("col"))
        new.set("min", str(lo)), new.set("max", str(hi)), new.set("width", str(float(width))), new.set("customWidth", "1")
        pos = 0
        for k, c in enumerate(cols):
            if int(c.get("min")) < lo:
                pos = k + 1
        cols.insert(pos, new)
        self.pkg.touch(self.sheets[sheet]["part"])
        ctx.done(i, op, op["at"], kind="col_width")

    def finalize(self, ctx) -> None:
        """После правки формул цепочка вычислений устарела: убираем её и просим Excel пересчитать при открытии."""
        if not self.formulas_changed:
            return
        pkg = self.pkg
        for name in [n for n in pkg.raw if n == "xl/calcChain.xml" and pkg.has(n)]:
            pkg.remove(name)
            ct = pkg.xml("[Content_Types].xml")
            for ov in list(ct):
                if ov.get("PartName") == "/xl/calcChain.xml":
                    ct.remove(ov)
            pkg.touch("[Content_Types].xml")
            rel = pkg.rels_name(self.wb_part)
            root = pkg.xml(rel)
            for r in list(root):
                if r.get("Type", "").endswith("/calcChain"):
                    root.remove(r)
            pkg.touch(rel)
        wb = pkg.xml(self.wb_part)
        cp = wb.find(x_("calcPr"))
        if cp is None:
            cp = etree.Element(x_("calcPr"))
            nxt = [ch for ch in wb if ch.tag in {x_(n) for n in ("oleSize", "customWorkbookViews", "pivotCaches", "smartTagPr",
                                                               "smartTagTypes", "webPublishing", "fileRecoveryPr", "webPublishObjects",
                                                               "extLst")}]
            if nxt:
                nxt[0].addprevious(cp)
            else:
                wb.append(cp)
        cp.set("fullCalcOnLoad", "1")
        pkg.touch(self.wb_part)
