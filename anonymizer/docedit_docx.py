"""docx: адреса, outline и операции правки (P2A). XML правится на месте через lxml."""

from __future__ import annotations

import copy
import re

from lxml import etree

from .docedit_core import (Elem, Opts, Package, PatchRejected, check_labels, check_plain_text, fingerprint, parse_color, q,
                           set_child, stub_text, drop_child)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
w_ = lambda n: q(W, n)
RPR_ORDER = [w_(n) for n in ("rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline", "shadow",
                              "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern",
                              "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs",
                              "em", "lang", "eastAsianLayout", "specVanish", "oMath")]
PPR_ORDER = [w_(n) for n in ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
                              "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
                              "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid",
                              "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
                              "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")]
ALIGN = {"left": "left", "center": "center", "right": "right", "justify": "both"}
SPECIAL_RUN = {w_(n) for n in ("drawing", "pict", "object", "footnoteReference", "endnoteReference", "commentReference", "sym",
                               "ptab", "fldChar", "instrText", "delText")} | {q("http://schemas.openxmlformats.org/markup-compatibility/2006", "AlternateContent")}
OK_PARA_CHILDREN = {w_(n) for n in ("pPr", "r", "hyperlink", "bookmarkStart", "bookmarkEnd", "proofErr", "commentRangeStart",
                                    "commentRangeEnd", "permStart", "permEnd")}
REVISION = {w_(n) for n in ("ins", "del", "moveFrom", "moveTo")}


def local(tag) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""


def run_is_special(r) -> bool:
    return any(ch.tag in SPECIAL_RUN or (ch.tag == w_("br") and ch.get(w_("type")) in ("page", "column")) for ch in r)


def run_text(r) -> str:
    out = []
    for ch in r:
        if ch.tag == w_("t"):
            out.append(ch.text or "")
        elif ch.tag == w_("tab"):
            out.append("\t")
        elif ch.tag in (w_("br"), w_("cr")):
            out.append("\n")
    return "".join(out)


def text_runs(p) -> list:
    return [r for r in p.iter(w_("r")) if not run_is_special(r)]


def para_text(p) -> str:
    return "".join(run_text(r) for r in text_runs(p))


def para_block(p) -> str:
    for ch in p:
        if ch.tag in REVISION:
            return "исправление (рецензирование)"
        if ch.tag == w_("sdt") or ch.tag == w_("fldSimple") or ch.tag == w_("oMath") or ch.tag == w_("oMathPara"):
            return "поле или элемент управления"
        if ch.tag not in OK_PARA_CHILDREN:
            return "вложенный объект"
    for r in p.iter(w_("r")):
        if r.find(w_("fldChar")) is not None or r.find(w_("instrText")) is not None:
            return "поле"
        if any(a.tag in REVISION for a in r.iterancestors()):
            return "исправление (рецензирование)"
    return ""


class DocxHandler:
    fmt = "docx"
    OPS = {"replace_text", "insert_paragraph", "delete", "comment", "set_style", "paragraph_style", "col_width"}
    SCHEMA = {
        "replace_text": ({"at", "expect", "text"}, set()),
        "insert_paragraph": ({"after", "text"}, set()),
        "delete": ({"at"}, {"expect"}),
        "comment": ({"at", "text"}, set()),
        "set_style": ({"at"}, {"font", "size", "bold", "italic", "color", "alignment", "space_before", "space_after", "line_spacing"}),
        "paragraph_style": ({"at", "style"}, set()),
        "col_width": ({"at", "col", "width"}, set()),
    }

    def __init__(self, pkg: Package, opts: Opts):
        self.pkg, self.opts = pkg, opts
        self.main = "word/document.xml"
        if not pkg.has(self.main):
            raise PatchRejected("bad_file", "Нет word/document.xml.")
        self.root = pkg.xml(self.main)
        self.body = self.root.find(w_("body"))
        self.elems: dict[str, Elem] = {}
        self.containers: list[dict] = []
        self._fonts: set[str] | None = None
        self.warnings: list[str] = []
        cont = {"addr": "body", "kind": "body", "title": "", "part": self.main, "elements": []}
        self.containers.append(cont)
        self._index_body(cont)
        self._index_hf()
        self.styles = self._styles()

    # ---- индекс ---
    def _index_body(self, cont: dict) -> None:
        pn = tn = xn = 0
        for ch in self.body:
            if ch.tag == w_("p"):
                self._para(ch, f"p{pn}", self._role(ch), self.main, cont, "body")
                pn += 1
            elif ch.tag == w_("tbl"):
                tn += 1
                self._table(ch, f"t{tn}", self.main, cont, "body")
            elif ch.tag == w_("sdt"):
                self._add(Elem(f"x{xn}", "shape", ch, self.main, editable=False, reason="элемент управления", parent="body",
                               extra={"type": "other", "role": "other", "name": ""}), cont)
                xn += 1

    def _index_hf(self) -> None:
        rels = self.pkg.rels(self.main)
        seen: list[tuple[str, str]] = []
        for sp in self.root.iter(w_("sectPr")):
            for ref in sp:
                kind = {"headerReference": "h", "footerReference": "f"}.get(local(ref.tag))
                if not kind:
                    continue
                tgt = rels.get(ref.get(q("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id")))
                if tgt and self.pkg.has(tgt[1]) and (kind, tgt[1]) not in seen:
                    seen.append((kind, tgt[1]))
        counts = {"h": 0, "f": 0}
        for kind, part in seen:
            counts[kind] += 1
            addr = f"{kind}{counts[kind]}"
            cont = {"addr": addr, "kind": "header" if kind == "h" else "footer", "title": "", "part": part, "elements": []}
            self.containers.append(cont)
            root = self.pkg.xml(part)
            pn = tn = 0
            for ch in root:
                if ch.tag == w_("p"):
                    self._para(ch, f"{addr}.p{pn}", "header" if kind == "h" else "footer", part, cont, addr)
                    pn += 1
                elif ch.tag == w_("tbl"):
                    tn += 1
                    self._table(ch, f"{addr}.t{tn}", part, cont, addr)

    def _role(self, p) -> str:
        sid = self._style_id(p)
        if sid and re.match(r"(?i)(heading|title|заголовок|subtitle)", sid):
            return "title"
        return "body"

    @staticmethod
    def _style_id(p) -> str:
        ps = p.find(f"{w_('pPr')}/{w_('pStyle')}")
        return ps.get(w_("val"), "") if ps is not None else ""

    def _para(self, p, addr: str, role: str, part: str, cont: dict, parent: str) -> None:
        blocked = para_block(p)
        e = Elem(addr, "paragraph", p, part, text=para_text(p), editable=not blocked, reason=blocked, parent=parent,
                 extra={"role": role})
        self._add(e, cont)
        if role == "title" and not cont["title"] and e.text:
            cont["title"] = e.text[:80]

    def _table(self, tbl, addr: str, part: str, cont: dict, parent: str) -> None:
        self._add(Elem(addr, "shape", tbl, part, editable=True, parent=parent,
                       extra={"type": "table", "role": "table", "name": ""}), cont)
        for ri, tr in enumerate(tbl.findall(w_("tr"))):
            for ci, tc in enumerate(tr.findall(w_("tc"))):
                for k, p in enumerate(tc.findall(w_("p"))):
                    self._para(p, f"{addr}.r{ri}.c{ci}.p{k}", "table cell", part, cont, addr)

    def _add(self, e: Elem, cont: dict) -> None:
        self.elems[e.addr] = e
        cont["elements"].append(e.addr)

    def _styles(self) -> dict[str, str]:
        out = {}
        if self.pkg.has("word/styles.xml"):
            for st in self.pkg.xml("word/styles.xml").iter(w_("style")):
                if st.get(w_("type")) == "paragraph":
                    nm = st.find(w_("name"))
                    out[st.get(w_("styleId"))] = nm.get(w_("val")) if nm is not None else st.get(w_("styleId"))
        return out

    def fonts(self) -> set[str]:
        if self._fonts is None:
            fs: set[str] = set()
            for name in self.pkg.raw:
                if not self.pkg.has(name):
                    continue
                if re.fullmatch(r"word/(document|styles|numbering|header\d*|footer\d*|footnotes|endnotes)\.xml", name):
                    for el in self.pkg.xml(name).iter(w_("rFonts")):
                        for att in ("ascii", "hAnsi", "cs", "eastAsia"):
                            if el.get(w_(att)):
                                fs.add(el.get(w_(att)))
                elif name == "word/fontTable.xml":
                    fs.update(f.get(w_("name")) for f in self.pkg.xml(name).iter(w_("font")) if f.get(w_("name")))
                elif re.fullmatch(r"word/theme/theme\d+\.xml", name):
                    for tag in ("majorFont", "minorFont"):
                        el = self.pkg.xml(name).find(f".//{q(A, tag)}/{q(A, 'latin')}")
                        if el is not None and el.get("typeface"):
                            fs.add(el.get("typeface"))
            self._fonts = fs
        return self._fonts

    # ---- outline ---
    def _style(self, p) -> dict:
        st: dict = {}
        sid = self._style_id(p)
        if sid:
            st["style"] = self.styles.get(sid, sid)
        runs = text_runs(p)
        rpr = runs[0].find(w_("rPr")) if runs else None
        if rpr is not None:
            rf = rpr.find(w_("rFonts"))
            if rf is not None and (rf.get(w_("ascii")) or rf.get(w_("hAnsi"))):
                st["font"] = rf.get(w_("ascii")) or rf.get(w_("hAnsi"))
            sz = rpr.find(w_("sz"))
            if sz is not None and sz.get(w_("val")):
                st["size"] = int(sz.get(w_("val"))) / 2
            for k, tag in (("bold", "b"), ("italic", "i")):
                el = rpr.find(w_(tag))
                if el is not None:
                    st[k] = el.get(w_("val"), "true") not in ("0", "false")
            c = rpr.find(w_("color"))
            if c is not None and c.get(w_("val")):
                st["color"] = c.get(w_("val"))
        jc = p.find(f"{w_('pPr')}/{w_('jc')}")
        if jc is not None:
            st["align"] = {"both": "justify"}.get(jc.get(w_("val")), jc.get(w_("val")))
        return st

    def element_dict(self, e: Elem, stub: bool) -> dict:
        d = {"addr": e.addr, "kind": e.kind, "editable": e.editable}
        if e.kind == "shape":
            t = e.extra["type"]
            d.update(type=t, role=e.extra["role"])
            if t == "table":
                d["cols"] = [round(int(c.get(w_("w"), 0)) / 20, 1) for c in e.node.iterfind(f"{w_('tblGrid')}/{w_('gridCol')}")]
            if not e.editable:
                d["flags"] = ["not_editable", e.reason]
                d["label"] = f"<{e.reason}: не редактируется>"
        else:
            d["role"] = e.extra["role"]
            d["text"] = stub_text(e.text) if stub else e.text
            if not stub:
                d["fp"] = fingerprint(e.text)
            d["style"] = self._style(e.node)
            has_obj = any(run_is_special(r) for r in e.node.iter(w_("r")))
            flags = []
            if not e.editable:
                flags = ["not_editable", e.reason]
            if has_obj:
                flags.append("has_object")
            if flags:
                d["flags"] = flags
        return d

    def outline(self, stub: bool) -> dict:
        sect = list(self.root.iter(w_("sectPr")))
        page = {}
        if sect:
            sz, mar = sect[-1].find(w_("pgSz")), sect[-1].find(w_("pgMar"))
            if sz is not None:
                page = {"w": round(int(sz.get(w_("w"), 0)) / 20, 1), "h": round(int(sz.get(w_("h"), 0)) / 20, 1), "unit": "pt"}
        return {"format": "docx", "page": page, "fonts": sorted(self.fonts()),
                "styles": sorted(set(self.styles.values())),
                "containers": [{**{k: v for k, v in c.items() if k not in ("elements", "part")},
                                "elements": [self.element_dict(self.elems[a], stub) for a in c["elements"]]}
                               for c in self.containers]}

    def all_texts(self):
        for e in self.elems.values():
            if e.text:
                yield e.text

    def need(self, ctx, i, addr, *, kind=None) -> Elem:
        if not isinstance(addr, str) or addr not in self.elems:
            raise PatchRejected("unknown_address", "Неизвестный адрес элемента.", i, str(addr)[:40])
        e = self.elems[addr]
        if kind and e.kind != kind:
            raise PatchRejected("bad_address", "Адрес указывает на элемент другого вида.", i, addr)
        ctx.live(e, i)
        return e

    # ---- текст ---
    def _set_text(self, p, text: str) -> None:
        """Текст кладётся в первый текстовый прогон (его rPr сохраняется), остальные текстовые прогоны удаляются;
        прогоны с рисунками, сносками, полями остаются на месте. Причина та же, что в pptx: детерминированно и без
        перемешивания границ жирного/ссылок."""
        runs = text_runs(p)
        if runs:
            first = runs[0]
            for r in runs[1:]:
                r.getparent().remove(r)
        else:
            first = etree.Element(w_("r"))
            ppr = p.find(w_("pPr"))
            mark = ppr.find(w_("rPr")) if ppr is not None else None
            if mark is not None:
                first.append(copy.deepcopy(mark))
            p.insert(list(p).index(ppr) + 1 if ppr is not None else 0, first)
        for ch in list(first):
            if ch.tag in (w_("t"), w_("tab"), w_("br"), w_("cr")):
                first.remove(ch)
        lines = text.split("\n")
        for n, line in enumerate(lines):
            if n:
                etree.SubElement(first, w_("br"))
            parts = line.split("\t")
            for m, part in enumerate(parts):
                if m:
                    etree.SubElement(first, w_("tab"))
                if part:
                    t = etree.SubElement(first, w_("t"))
                    t.text = part
                    t.set(f"{{{XML}}}space", "preserve")

    def op_replace_text(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="paragraph")
        if not e.editable:
            raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
        ctx.expect(e, op, i)
        text = check_plain_text(op["text"], i, e.addr, self.opts, allow_newline=True)
        removed = check_labels(e.text, text, ctx.known, i, e.addr)
        ctx.grow(len(e.text), len(text))
        self._set_text(e.node, text)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, old=e.text, new=text, removed_labels=removed)
        e.text = text

    def op_insert_paragraph(self, ctx, i, op):
        e = self.need(ctx, i, op["after"], kind="paragraph")
        if not e.editable:
            raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
        text = check_plain_text(op["text"], i, e.addr, self.opts, allow_newline=True)
        check_labels(None, text, ctx.known, i, e.addr)
        ctx.insert(len(text))
        new = etree.Element(w_("p"))
        ppr = e.node.find(w_("pPr"))
        if ppr is not None:
            c = copy.deepcopy(ppr)
            drop_child(c, w_("sectPr"))      # копия не должна создавать разрыв раздела
            drop_child(c, w_("pPrChange"))
            new.append(c)
        runs = text_runs(e.node)
        run = etree.SubElement(new, w_("r"))
        if runs and runs[-1].find(w_("rPr")) is not None:
            run.append(copy.deepcopy(runs[-1].find(w_("rPr"))))
        e.node.addnext(new)
        self._set_text(new, text)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, new=text, kind="insert")

    def op_delete(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="paragraph")
        if not e.editable:
            raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
        ctx.expect(e, op, i)
        par = e.node.getparent()
        if e.node.find(f"{w_('pPr')}/{w_('sectPr')}") is not None:
            raise PatchRejected("section_break", "Абзац содержит разрыв раздела.", i, e.addr)
        if par.tag == w_("tc") and len(par.findall(w_("p"))) < 2:
            raise PatchRejected("last_paragraph", "Нельзя удалить последний абзац ячейки.", i, e.addr)
        if par.tag != w_("tc") and len(par.findall(w_("p"))) < 2:
            raise PatchRejected("last_paragraph", "Нельзя удалить единственный абзац.", i, e.addr)
        par.remove(e.node)
        ctx.kill(e)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, old=e.text, kind="delete")

    def op_comment(self, ctx, i, op):
        self.need(ctx, i, op["at"])
        text = check_plain_text(op["text"], i, op["at"], self.opts)
        if len(text) > self.opts.max_comment:
            raise PatchRejected("text_too_long", "Комментарий слишком длинный.", i, op["at"])
        check_labels(None, text, ctx.known, i, op["at"])
        ctx.comments.append({"at": op["at"], "text": text})
        ctx.done(i, op, op["at"], new=text, kind="comment")

    # ---- оформление ---
    def _paras_under(self, e: Elem) -> list[Elem]:
        if e.kind == "paragraph":
            return [e]
        pre = e.addr + "."
        return [x for x in self.elems.values() if x.kind == "paragraph" and x.part == e.part and x.addr.startswith(pre)]

    def op_set_style(self, ctx, i, op):
        addr = op["at"]
        if addr in self.elems:
            e = self.elems[addr]
        else:
            # адрес ячейки tN.rI.cJ без абзаца
            m = re.fullmatch(r"((?:[hf]\d+\.)?t\d+\.r\d+\.c\d+)", addr or "")
            if not m:
                raise PatchRejected("unknown_address", "Неизвестный адрес элемента.", i, str(addr)[:40])
            first = next((x for x in self.elems.values() if x.addr.startswith(addr + ".p")), None)
            if first is None:
                raise PatchRejected("unknown_address", "Неизвестный адрес элемента.", i, str(addr)[:40])
            e = Elem(addr, "cell", None, first.part)
        if e.kind == "shape" and e.extra["type"] != "table" or (e.kind == "shape" and not e.editable):
            raise PatchRejected("not_editable", "Оформление этого объекта не меняется.", i, e.addr)
        paras = self._paras_under(e)
        if not paras:
            raise PatchRejected("bad_address", "В элементе нет текста для оформления.", i, e.addr)
        for pe in paras:
            ctx.live(pe, i)
        props = {k: v for k, v in op.items() if k not in ("op", "at")}
        if not props:
            raise PatchRejected("bad_op", "Не указано, что менять.", i, e.addr)
        if "font" in props:
            ctx.check_font(props["font"], self.fonts(), i, e.addr)
        size = props.get("size")
        if size is not None and not (isinstance(size, (int, float)) and not isinstance(size, bool)
                                     and self.opts.min_font_pt <= size <= self.opts.max_font_pt):
            raise PatchRejected("bad_size", "Размер шрифта вне допустимых пределов.", i, e.addr)
        for k in ("bold", "italic"):
            if k in props and not isinstance(props[k], bool):
                raise PatchRejected("bad_type", f"{k} должен быть true/false.", i, e.addr)
        color = parse_color(props["color"], i, e.addr) if "color" in props else None
        if "alignment" in props and props["alignment"] not in ALIGN:
            raise PatchRejected("bad_alignment", "Выравнивание: left, center, right, justify.", i, e.addr)
        for k, lo, hi in (("space_before", 0, 500), ("space_after", 0, 500), ("line_spacing", 50, 400)):
            if k in props and not (isinstance(props[k], (int, float)) and not isinstance(props[k], bool) and lo <= props[k] <= hi):
                raise PatchRejected("bad_spacing", f"{k} вне допустимых пределов.", i, e.addr)
        for pe in paras:
            p = pe.node
            ppr = p.find(w_("pPr"))
            if ppr is None:
                ppr = etree.Element(w_("pPr"))
                p.insert(0, ppr)
            if "alignment" in props:
                set_child(ppr, w_("jc"), PPR_ORDER).set(w_("val"), ALIGN[props["alignment"]])
            if any(k in props for k in ("space_before", "space_after", "line_spacing")):
                sp = set_child(ppr, w_("spacing"), PPR_ORDER)
                if "space_before" in props:
                    sp.set(w_("before"), str(int(props["space_before"] * 20)))
                if "space_after" in props:
                    sp.set(w_("after"), str(int(props["space_after"] * 20)))
                if "line_spacing" in props:
                    sp.set(w_("line"), str(int(240 * props["line_spacing"] / 100)))
                    sp.set(w_("lineRule"), "auto")
            for r in p.iter(w_("r")):
                if run_is_special(r):
                    continue
                rpr = r.find(w_("rPr"))
                if rpr is None:
                    rpr = etree.Element(w_("rPr"))
                    r.insert(0, rpr)
                if "font" in props:
                    rf = set_child(rpr, w_("rFonts"), RPR_ORDER)
                    for att in ("ascii", "hAnsi", "cs", "eastAsia"):
                        rf.set(w_(att), props["font"])
                    for att in ("asciiTheme", "hAnsiTheme", "csTheme", "eastAsiaTheme"):
                        rf.attrib.pop(w_(att), None)
                if size is not None:
                    for tag in ("sz", "szCs"):
                        set_child(rpr, w_(tag), RPR_ORDER).set(w_("val"), str(int(round(size * 2))))
                for k, tag in (("bold", "b"), ("italic", "i")):
                    if k in props:
                        set_child(rpr, w_(tag), RPR_ORDER).set(w_("val"), "1" if props[k] else "0")
                if color:
                    c = set_child(rpr, w_("color"), RPR_ORDER)
                    c.attrib.clear()
                    c.set(w_("val"), color)
        self.pkg.touch(paras[0].part)
        ctx.done(i, op, e.addr, kind="style", props=sorted(props))

    def op_paragraph_style(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="paragraph")
        if not e.editable:
            raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
        want = op["style"]
        sid = next((k for k, v in self.styles.items() if isinstance(want, str) and want.casefold() in (k.casefold(), (v or "").casefold())), None)
        if sid is None:
            raise PatchRejected("unknown_style", "Такого стиля абзаца в документе нет.", i, e.addr)
        ppr = e.node.find(w_("pPr"))
        if ppr is None:
            ppr = etree.Element(w_("pPr"))
            e.node.insert(0, ppr)
        set_child(ppr, w_("pStyle"), PPR_ORDER).set(w_("val"), sid)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, kind="paragraph_style", new=sid)

    def _page_width_twips(self) -> int:
        sect = list(self.root.iter(w_("sectPr")))
        if not sect:
            return 12240
        sz, mar = sect[-1].find(w_("pgSz")), sect[-1].find(w_("pgMar"))
        wd = int(sz.get(w_("w"), 12240)) if sz is not None else 12240
        if mar is not None:
            wd -= int(mar.get(w_("left"), 0)) + int(mar.get(w_("right"), 0))
        return wd

    def op_col_width(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="shape")
        if e.extra["type"] != "table":
            raise PatchRejected("bad_address", "Адрес не указывает на таблицу.", i, e.addr)
        grid = list(e.node.iterfind(f"{w_('tblGrid')}/{w_('gridCol')}"))
        col, wd = op.get("col"), op.get("width")
        if not isinstance(col, int) or isinstance(col, bool) or not 0 <= col < len(grid):
            raise PatchRejected("bad_number", "Нет такого столбца.", i, e.addr)
        if not isinstance(wd, (int, float)) or isinstance(wd, bool) or not 5 <= wd <= self.opts.max_col_width_pt:
            raise PatchRejected("bad_number", "Ширина столбца вне допустимых пределов.", i, e.addr)
        tw = int(round(wd * 20))
        total = sum(int(g.get(w_("w"), 0)) for g in grid) - int(grid[col].get(w_("w"), 0)) + tw
        if total > self._page_width_twips() + 40:
            raise PatchRejected("out_of_bounds", "Таблица выходит за ширину страницы.", i, e.addr)
        grid[col].set(w_("w"), str(tw))
        for tr in e.node.findall(w_("tr")):
            pos = 0
            for tc in tr.findall(w_("tc")):
                pr = tc.find(w_("tcPr"))
                gs = pr.find(w_("gridSpan")) if pr is not None else None
                span = int(gs.get(w_("val"), 1)) if gs is not None else 1
                if pos == col and span == 1 and pr is not None:
                    tcw = pr.find(w_("tcW"))
                    if tcw is None:
                        tcw = etree.Element(w_("tcW"))
                        pr.insert(1 if pr.find(w_("cnfStyle")) is not None else 0, tcw)
                    tcw.set(w_("w"), str(tw))
                    tcw.set(w_("type"), "dxa")
                pos += span
        tblw = e.node.find(f"{w_('tblPr')}/{w_('tblW')}")
        if tblw is not None and tblw.get(w_("type")) == "dxa":
            tblw.set(w_("w"), str(total))
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, kind="col_width")
