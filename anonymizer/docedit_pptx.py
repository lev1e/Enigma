"""pptx: адреса, outline и операции правки (P2A). Правка идёт по XML на месте, python-pptx не используется."""

from __future__ import annotations

import copy
import posixpath
import re

from lxml import etree

from .docedit_core import (EMU_PT, NS_R, Elem, Opts, PatchRejected, Package, check_labels, check_plain_text, drop_child,
                           fingerprint, parse_color, q, set_child, stub_text)

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
RT_SLIDE = "slide"
a_ = lambda n: q(A, n)
p_ = lambda n: q(P, n)

RPR_ORDER = [a_(n) for n in ("ln", "noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill", "effectLst", "effectDag",
                              "highlight", "uLnTx", "uLn", "uFillTx", "uFill", "latin", "ea", "cs", "sym", "hlinkClick",
                              "hlinkMouseOver", "rtl", "extLst")]
FILLS = {a_(n) for n in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")}
PPR_ORDER = [a_(n) for n in ("lnSpc", "spcBef", "spcAft", "buClrTx", "buClr", "buSzTx", "buSzPct", "buSzPts", "buFontTx", "buFont",
                              "buNone", "buAutoNum", "buChar", "buBlip", "tabLst", "defRPr", "extLst")]
SP_ORDER = [a_(n) for n in ("xfrm", "custGeom", "prstGeom", "noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill", "ln")]
ALIGN = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}
ROLE = {"title": "title", "ctrTitle": "title", "subTitle": "subtitle", "body": "body", "dt": "footer", "ftr": "footer",
        "sldNum": "footer"}
KIND_RU = {"image": "изображение", "chart": "диаграмма", "smartart": "SmartArt", "ole": "встроенный объект", "video": "видео",
           "other": "объект", "connector": "линия", "group": "группа"}
SIMPLE_PARA_CHILDREN = {a_("pPr"), a_("r"), a_("br"), a_("endParaRPr")}


def local(tag) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""


def _nv(shape):
    for ch in shape:
        if local(ch.tag).startswith("nv"):
            return ch
    return None


def shape_id(shape) -> str | None:
    nv = _nv(shape)
    c = nv.find(p_("cNvPr")) if nv is not None else None
    return c.get("id") if c is not None else None


def ph_of(shape):
    nv = _nv(shape)
    return nv.find(f".//{p_('ph')}") if nv is not None else None


def para_text(p) -> str:
    out = []
    for ch in p:
        if ch.tag == a_("r"):
            out.append("".join(t.text or "" for t in ch.findall(a_("t"))))
        elif ch.tag == a_("br"):
            out.append("\n")
        elif ch.tag == a_("fld"):
            out.append("".join(t.text or "" for t in ch.findall(a_("t"))))
    return "".join(out)


def para_block(p) -> str:
    """Причина, по которой абзац нельзя править, или пустая строка."""
    for ch in p:
        if ch.tag == a_("fld"):
            return "поле"
        if ch.tag not in SIMPLE_PARA_CHILDREN:
            return "формула или вложенный объект"
    return ""


class PptxHandler:
    fmt = "pptx"
    OPS = {"replace_text", "insert_paragraph", "delete", "comment", "set_style", "move_shape", "resize_shape", "align",
           "set_layout", "col_width"}

    def __init__(self, pkg: Package, opts: Opts):
        self.pkg, self.opts = pkg, opts
        self.pres_part = "ppt/presentation.xml"
        pres = pkg.xml(self.pres_part)
        sz = pres.find(p_("sldSz"))
        self.W = int(sz.get("cx")) if sz is not None else 9144000
        self.H = int(sz.get("cy")) if sz is not None else 6858000
        rels = pkg.rels(self.pres_part)
        self.slides: list[tuple[int, str]] = []
        for i, sid in enumerate(pres.iter(p_("sldId")), 1):
            tgt = rels.get(sid.get(q(NS_R, "id")))
            if tgt and pkg.has(tgt[1]):
                self.slides.append((i, tgt[1]))
        self.elems: dict[str, Elem] = {}
        self.containers: list[dict] = []
        self._fonts: set[str] | None = None
        self._theme = self._theme_fonts()
        for n, part in self.slides:
            self._index_slide(n, part)

    # ---- индекс ---------------------------------------------------------------------------------------
    def _theme_fonts(self) -> dict[str, str]:
        out = {}
        for name in self.pkg.raw:
            if re.fullmatch(r"ppt/theme/theme\d+\.xml", name) and self.pkg.has(name):
                root = self.pkg.xml(name)
                for tag, key in (("majorFont", "+mj-lt"), ("minorFont", "+mn-lt")):
                    el = root.find(f".//{a_(tag)}/{a_('latin')}")
                    if el is not None and el.get("typeface") and key not in out:
                        out[key] = el.get("typeface")
        return out

    def fonts(self) -> set[str]:
        if self._fonts is None:
            fs = set(self._theme.values())
            for name in self.pkg.raw:
                if self.pkg.has(name) and re.fullmatch(r"ppt/(slides|slideLayouts|slideMasters|notesSlides|theme)/[^/]+\.xml", name):
                    for el in self.pkg.xml(name).iter(a_("latin")):
                        tf = el.get("typeface")
                        if tf and not tf.startswith("+"):
                            fs.add(tf)
            self._fonts = fs
        return self._fonts

    def _layout_of(self, part: str):
        for t, tgt in self.pkg.rels(part).values():
            if t.endswith("/slideLayout"):
                return tgt
        return None

    def _inherited_xfrm(self, part: str, shape):
        ph = ph_of(shape)
        if ph is None:
            return None
        layout = self._layout_of(part)
        chain = []
        if layout and self.pkg.has(layout):
            chain.append(layout)
            for t, tgt in self.pkg.rels(layout).values():
                if t.endswith("/slideMaster") and self.pkg.has(tgt):
                    chain.append(tgt)
        for pt in chain:
            for sp in self.pkg.xml(pt).iter(p_("sp")):
                ph2 = ph_of(sp)
                if ph2 is None:
                    continue
                same = (ph.get("idx") is not None and ph.get("idx") == ph2.get("idx")) or \
                       (ph.get("idx") is None and ph2.get("idx") is None and ph.get("type") == ph2.get("type"))
                if same:
                    off, ext = sp.find(f"{p_('spPr')}/{a_('xfrm')}/{a_('off')}"), sp.find(f"{p_('spPr')}/{a_('xfrm')}/{a_('ext')}")
                    if off is not None and ext is not None:
                        return int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))
        return None

    @staticmethod
    def _own_xfrm_el(shape):
        if shape.tag == p_("graphicFrame"):
            return shape.find(p_("xfrm"))
        if shape.tag == p_("grpSp"):
            return shape.find(f"{p_('grpSpPr')}/{a_('xfrm')}")
        sp = shape.find(p_("spPr"))
        return sp.find(a_("xfrm")) if sp is not None else None

    def geom(self, part: str, shape):
        x = self._own_xfrm_el(shape)
        if x is not None:
            off, ext = x.find(a_("off")), x.find(a_("ext"))
            if off is not None and ext is not None:
                return int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy")), "own"
        g = self._inherited_xfrm(part, shape)
        return (*g, "layout") if g else None

    def _shape_kind(self, sh) -> tuple[str, bool, str]:
        t = sh.tag
        if t == p_("sp"):
            body = sh.find(p_("txBody"))
            if body is not None and body.find(f"{a_('bodyPr')}/{a_('prstTxWarp')}") is not None:
                return "other", False, "WordArt"
            return "text", True, ""
        if t == p_("graphicFrame"):
            data = sh.find(f".//{a_('graphicData')}")
            uri = data.get("uri", "") if data is not None else ""
            if uri.endswith("/table"):
                return "table", True, ""
            if uri.endswith("/chart"):
                return "chart", False, "chart"
            if "diagram" in uri:
                return "smartart", False, "smartart"
            if uri.endswith("/ole") or sh.find(f".//{p_('oleObj')}") is not None:
                return "ole", False, "ole"
            return "other", False, "other"
        if t == p_("pic"):
            nv = _nv(sh)
            if nv is not None and (nv.find(f".//{a_('videoFile')}") is not None or nv.find(f".//{a_('audioFile')}") is not None):
                return "video", False, "video"
            return "image", False, "image"
        if t == p_("grpSp"):
            return "group", True, ""
        if t == p_("cxnSp"):
            return "connector", False, "connector"
        return "other", False, "other"

    def _index_slide(self, n: int, part: str) -> None:
        root = self.pkg.xml(part)
        cont = {"addr": f"s{n}", "part": part, "hidden": root.get("show") == "0", "title": "", "layout": "", "elements": []}
        lay = self._layout_of(part)
        if lay and self.pkg.has(lay):
            c = self.pkg.xml(lay).find(p_("cSld"))
            cont["layout"] = c.get("name", "") if c is not None else ""
        cont["layout_part"] = lay
        self.containers.append(cont)
        tree = root.find(f"{p_('cSld')}/{p_('spTree')}")
        if tree is not None:
            self._walk(tree, f"s{n}", "", part, cont)
        for t, tgt in self.pkg.rels(part).values():
            if t.endswith("/notesSlide") and self.pkg.has(tgt):
                nt = self.pkg.xml(tgt).find(f"{p_('cSld')}/{p_('spTree')}")
                for sp in (nt if nt is not None else []):
                    ph = ph_of(sp) if sp.tag == p_("sp") else None
                    if ph is not None and ph.get("type") == "body":
                        self._shape(sp, f"s{n}.notes", f"s{n}", tgt, cont, role="note")
                        break

    def _walk(self, tree, slide_addr: str, path: str, part: str, cont: dict) -> None:
        for sh in tree:
            if sh.tag == q(MC, "AlternateContent"):
                a = f"{slide_addr}.alt{len(cont['elements'])}"
                self._add(Elem(a, "shape", sh, part, editable=False, reason="other", parent=slide_addr, extra={"type": "other"}), cont)
                continue
            if sh.tag not in (p_("sp"), p_("grpSp"), p_("graphicFrame"), p_("pic"), p_("cxnSp"), p_("contentPart")):
                continue
            sid = shape_id(sh)
            if sid is None:
                continue
            seg = f"{path}/sh{sid}" if path else f"sh{sid}"
            self._shape(sh, f"{slide_addr}.{seg}", slide_addr, part, cont, seg=seg)

    def _shape(self, sh, addr: str, slide_addr: str, part: str, cont: dict, role: str = "", seg: str = "") -> None:
        kind, editable, reason = self._shape_kind(sh)
        ph = ph_of(sh)
        role = role or (ROLE.get(ph.get("type") or "body", "text") if ph is not None else ("text" if kind == "text" else kind))
        nv = _nv(sh)
        name = nv.find(p_("cNvPr")).get("name", "") if nv is not None and nv.find(p_("cNvPr")) is not None else ""
        self._add(Elem(addr, "shape", sh, part, editable=editable, reason=reason, parent=slide_addr,
                       extra={"type": kind, "role": role, "name": name}), cont)
        if kind == "group":
            self._walk(sh, slide_addr, seg, part, cont)
        elif kind == "text":
            body = sh.find(p_("txBody"))
            if body is not None:
                self._paras(body, addr, role, part, cont)
        elif kind == "table":
            for ri, tr in enumerate(sh.iterfind(f".//{a_('tr')}")):
                for ci, tc in enumerate(tr.findall(a_("tc"))):
                    body = tc.find(a_("txBody"))
                    if body is not None:
                        self._paras(body, f"{addr}.r{ri}.c{ci}", "table cell", part, cont)

    def _paras(self, body, base: str, role: str, part: str, cont: dict) -> None:
        for k, p in enumerate(body.findall(a_("p"))):
            blocked = para_block(p)
            e = Elem(f"{base}.p{k}", "paragraph", p, part, text=para_text(p), editable=not blocked, reason=blocked,
                     parent=base, extra={"role": role})
            self._add(e, cont)
            if role == "title" and not cont["title"] and e.text:
                cont["title"] = e.text

    def _add(self, e: Elem, cont: dict) -> None:
        if e.addr in self.elems:      # дубли id в файле: адрес неоднозначен — второй не адресуем
            e.addr += f"~dup{len(self.elems)}"
            e.editable, e.reason = False, "дубль идентификатора"
        self.elems[e.addr] = e
        cont["elements"].append(e.addr)

    # ---- outline ---------------------------------------------------------------------------------------
    def _style(self, p) -> dict:
        r = next(iter(p.findall(a_("r"))), None)
        rpr = r.find(a_("rPr")) if r is not None else None
        st: dict = {}
        if rpr is not None:
            lat = rpr.find(a_("latin"))
            if lat is not None and lat.get("typeface"):
                tf = lat.get("typeface")
                st["font"] = self._theme.get(tf, tf)
            if rpr.get("sz"):
                st["size"] = int(rpr.get("sz")) / 100
            for k, a in (("bold", "b"), ("italic", "i")):
                if rpr.get(a) is not None:
                    st[k] = rpr.get(a) in ("1", "true")
            clr = rpr.find(f"{a_('solidFill')}/*")
            if clr is not None:
                st["color"] = clr.get("val")
        ppr = p.find(a_("pPr"))
        if ppr is not None and ppr.get("algn"):
            st["align"] = {v: k for k, v in ALIGN.items()}.get(ppr.get("algn"), ppr.get("algn"))
        return st

    def element_dict(self, e: Elem, stub: bool) -> dict:
        d = {"addr": e.addr, "kind": e.kind, "editable": e.editable}
        if e.kind == "shape":
            t = e.extra["type"]
            d.update(type=t, role=e.extra["role"], name=e.extra["name"])
            g = self.geom(e.part, e.node)
            if g:
                d["geom"] = {"x": round(g[0] / EMU_PT, 1), "y": round(g[1] / EMU_PT, 1), "w": round(g[2] / EMU_PT, 1),
                             "h": round(g[3] / EMU_PT, 1), "src": g[4]}
            if not e.editable:
                d["flags"] = ["not_editable", e.reason]
                d["label"] = f"<{KIND_RU.get(t, 'объект')}: не редактируется>"
            if t == "table":
                grid = [int(c.get("w")) / EMU_PT for c in e.node.iterfind(f".//{a_('gridCol')}")]
                d["cols"] = [round(w, 1) for w in grid]
        else:
            d["role"] = e.extra["role"]
            d["text"] = stub_text(e.text) if stub else e.text
            if not stub:
                d["fp"] = fingerprint(e.text)
            d["style"] = self._style(e.node)
            if not e.editable:
                d["flags"] = ["not_editable", e.reason]
        return d

    def outline(self, stub: bool) -> dict:
        out = {"format": "pptx", "slide_size": {"w": round(self.W / EMU_PT, 1), "h": round(self.H / EMU_PT, 1), "unit": "pt"},
               "fonts": sorted(self.fonts()), "layouts": self.layout_names(), "containers": []}
        for cont in self.containers:
            out["containers"].append({"addr": cont["addr"], "kind": "slide", "title": cont["title"], "layout": cont["layout"],
                                      "hidden": cont["hidden"],
                                      "elements": [self.element_dict(self.elems[a], stub) for a in cont["elements"]]})
        return out

    def all_texts(self):
        for e in self.elems.values():
            if e.text:
                yield e.text

    # ---- слои ------------------------------------------------------------------------------------------
    def layout_names(self) -> list[dict]:
        out = []
        for name in sorted(self.pkg.raw):
            if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", name) and self.pkg.has(name):
                c = self.pkg.xml(name).find(p_("cSld"))
                out.append({"name": c.get("name", "") if c is not None else "", "part": name})
        return out

    # ---- проверки --------------------------------------------------------------------------------------
    def snapshot(self) -> tuple:
        return (tuple(self.slides), tuple((a, e.kind) for a, e in self.elems.items() if e.kind == "shape"),
                tuple(sorted(n for n in self.pkg.raw if not n.startswith("ppt/slides/slide") or n.endswith(".rels"))))

    def need(self, ctx, i: int, addr, *, kind: str | None = None, para: bool | None = None) -> Elem:
        if not isinstance(addr, str) or addr not in self.elems:
            raise PatchRejected("unknown_address", "Неизвестный адрес элемента.", i, str(addr)[:40])
        e = self.elems[addr]
        if kind and e.kind != kind:
            raise PatchRejected("bad_address", "Адрес указывает на элемент другого вида.", i, addr)
        ctx.live(e, i)
        return e

    # ---- операции --------------------------------------------------------------------------------------
    def op_replace_text(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="paragraph")
        if not e.editable:
            raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
        ctx.expect(e, op, i)
        text = check_plain_text(op["text"], i, e.addr, self.opts, allow_newline=True)
        removed = check_labels(e.text, text, ctx.known, i, e.addr)
        ctx.grow(len(e.text), len(text))
        self._set_text(e.node, text)
        ctx.done(i, op, e.addr, old=e.text, new=text, removed_labels=removed)
        self.pkg.touch(e.part)
        e.text = text

    def _set_text(self, p, text: str) -> None:
        """Новый текст кладётся в ПЕРВЫЙ прогон абзаца (с его rPr), остальные прогоны и разрывы удаляются.

        Выбор: поэлементная сверка прогонов (diff) сохраняла бы разное оформление внутри абзаца, но в одном абзаце
        слова чужих прогонов с новым текстом перемешиваются непредсказуемо (границы жирного, гиперссылки). Первый
        прогон — то, что видит человек в начале абзаца (обычно стиль абзаца целиком). Это детерминировано и не ломает схему.
        """
        runs = p.findall(a_("r"))
        if runs:
            first = runs[0]
            pos = list(p).index(first)
        else:
            first = etree.Element(a_("r"))
            end = p.find(a_("endParaRPr"))
            if end is not None:
                rpr = copy.deepcopy(end)
                rpr.tag = a_("rPr")
                first.append(rpr)
            ppr = p.find(a_("pPr"))
            pos = (list(p).index(ppr) + 1) if ppr is not None else 0
            p.insert(pos, first)
        template = first.find(a_("rPr"))
        for ch in list(p):
            if ch is not first and ch.tag in (a_("r"), a_("br")):
                p.remove(ch)
        pos = list(p).index(first)
        lines = text.split("\n")
        self._set_run_text(first, lines[0])
        at = pos + 1
        for line in lines[1:]:
            br = etree.Element(a_("br"))
            if template is not None:
                br.append(copy.deepcopy(template))
            run = etree.Element(a_("r"))
            if template is not None:
                run.append(copy.deepcopy(template))
            self._set_run_text(run, line)
            p.insert(at, br)
            p.insert(at + 1, run)
            at += 2

    @staticmethod
    def _set_run_text(run, text: str) -> None:
        ts = run.findall(a_("t"))
        t = ts[0] if ts else etree.SubElement(run, a_("t"))
        for extra in ts[1:]:
            run.remove(extra)
        t.text = text
        if text != text.strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def op_insert_paragraph(self, ctx, i, op):
        e = self.need(ctx, i, op["after"], kind="paragraph")
        if not e.editable:
            raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
        text = check_plain_text(op["text"], i, e.addr, self.opts, allow_newline=True)
        check_labels(None, text, ctx.known, i, e.addr)
        ctx.insert(len(text))
        new = etree.Element(a_("p"))
        ppr = e.node.find(a_("pPr"))
        if ppr is not None:
            new.append(copy.deepcopy(ppr))
        runs = e.node.findall(a_("r"))
        run = etree.SubElement(new, a_("r"))
        rpr = (runs[-1].find(a_("rPr")) if runs else None)
        if rpr is None:
            end = e.node.find(a_("endParaRPr"))
            if end is not None:
                rpr = copy.deepcopy(end)
                rpr.tag = a_("rPr")
                run.append(rpr)
        else:
            run.append(copy.deepcopy(rpr))
        self._set_run_text(run, "")
        self._set_text(new, text)
        e.node.addnext(new)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, new=text, kind="insert")

    def op_delete(self, ctx, i, op):
        e = self.need(ctx, i, op["at"])
        if e.kind == "paragraph":
            if not e.editable:
                raise PatchRejected("not_editable", f"Абзац не редактируется ({e.reason}).", i, e.addr)
            ctx.expect(e, op, i)
            body = e.node.getparent()
            if len(body.findall(a_("p"))) < 2:
                raise PatchRejected("last_paragraph", "Нельзя удалить последний абзац в фигуре или ячейке.", i, e.addr)
            body.remove(e.node)
            ctx.kill(e)
            ctx.done(i, op, e.addr, old=e.text, kind="delete")
        elif e.kind == "shape":
            if e.extra["type"] not in ("text", "group") or not e.editable:
                raise PatchRejected("not_editable", f"Этот объект не редактируется ({e.reason or e.extra['type']}).", i, e.addr)
            if e.addr.endswith(".notes"):
                raise PatchRejected("not_editable", "Заметки удалить нельзя.", i, e.addr)
            e.node.getparent().remove(e.node)
            ctx.kill(e)
            ctx.done(i, op, e.addr, kind="delete_shape")
        else:
            raise PatchRejected("bad_address", "Нечего удалять по этому адресу.", i, e.addr)
        self.pkg.touch(e.part)

    def op_comment(self, ctx, i, op):
        self.need(ctx, i, op["at"])
        text = check_plain_text(op["text"], i, op["at"], self.opts)
        if len(text) > self.opts.max_comment:
            raise PatchRejected("text_too_long", "Комментарий слишком длинный.", i, op["at"])
        check_labels(None, text, ctx.known, i, op["at"])
        ctx.comments.append({"at": op["at"], "text": text})
        ctx.done(i, op, op["at"], new=text, kind="comment")

    # -- оформление ---
    def _paras_under(self, e: Elem) -> list[Elem]:
        if e.kind == "paragraph":
            return [e]
        pre = e.addr + "."
        return [x for x in self.elems.values() if x.kind == "paragraph" and x.addr.startswith(pre) and x.part == e.part
                and (x.parent == e.addr or x.parent.startswith(pre))]

    def op_set_style(self, ctx, i, op):
        e = self.need(ctx, i, op["at"])
        if e.kind == "shape" and e.extra["type"] not in ("text", "table"):
            raise PatchRejected("not_editable", f"Оформление этого объекта не меняется ({e.reason or e.extra['type']}).", i, e.addr)
        paras = self._paras_under(e)
        if not paras:
            raise PatchRejected("bad_address", "В элементе нет текста для оформления.", i, e.addr)
        props = {k: v for k, v in op.items() if k not in ("op", "at")}
        if not props:
            raise PatchRejected("bad_op", "Не указано, что менять.", i, e.addr)
        font = props.get("font")
        if font is not None:
            ctx.check_font(font, self.fonts(), i, e.addr)
        size = props.get("size")
        if size is not None and not (isinstance(size, (int, float)) and not isinstance(size, bool)
                                     and self.opts.min_font_pt <= size <= self.opts.max_font_pt):
            raise PatchRejected("bad_size", "Размер шрифта вне допустимых пределов.", i, e.addr)
        for k in ("bold", "italic"):
            if k in props and not isinstance(props[k], bool):
                raise PatchRejected("bad_type", f"{k} должен быть true/false.", i, e.addr)
        color = parse_color(props["color"], i, e.addr) if "color" in props else None
        algn = None
        if "alignment" in props:
            algn = ALIGN.get(props["alignment"])
            if algn is None:
                raise PatchRejected("bad_alignment", "Выравнивание: left, center, right, justify.", i, e.addr)
        for k, lo, hi in (("space_before", 0, 500), ("space_after", 0, 500), ("line_spacing", 50, 400)):
            if k in props and not (isinstance(props[k], (int, float)) and not isinstance(props[k], bool) and lo <= props[k] <= hi):
                raise PatchRejected("bad_spacing", f"{k} вне допустимых пределов.", i, e.addr)
        for pe in paras:
            p = pe.node
            if algn or any(k in props for k in ("space_before", "space_after", "line_spacing")):
                ppr = p.find(a_("pPr"))
                if ppr is None:
                    ppr = etree.Element(a_("pPr"))
                    p.insert(0, ppr)
                if algn:
                    ppr.set("algn", algn)
                for key, tag, mk in (("line_spacing", "lnSpc", ("spcPct", lambda v: str(int(v * 1000)))),
                                     ("space_before", "spcBef", ("spcPts", lambda v: str(int(v * 100)))),
                                     ("space_after", "spcAft", ("spcPts", lambda v: str(int(v * 100))))):
                    if key in props:
                        drop_child(ppr, a_(tag))
                        el = set_child(ppr, a_(tag), PPR_ORDER)
                        etree.SubElement(el, a_(mk[0])).set("val", mk[1](props[key]))
            for r in p.findall(a_("r")):
                rpr = r.find(a_("rPr"))
                if rpr is None:
                    rpr = etree.Element(a_("rPr"))
                    r.insert(0, rpr)
                if size is not None:
                    rpr.set("sz", str(int(round(size * 100))))
                if "bold" in props:
                    rpr.set("b", "1" if props["bold"] else "0")
                if "italic" in props:
                    rpr.set("i", "1" if props["italic"] else "0")
                if color:
                    for ch in list(rpr):
                        if ch.tag in FILLS:
                            rpr.remove(ch)
                    sf = set_child(rpr, a_("solidFill"), RPR_ORDER)
                    etree.SubElement(sf, a_("srgbClr")).set("val", color)
                if font:
                    drop_child(rpr, a_("latin"))
                    set_child(rpr, a_("latin"), RPR_ORDER).set("typeface", font)
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, kind="style", props=sorted(props))

    # -- геометрия ---
    def _geom_for_edit(self, e: Elem, i: int):
        if e.kind != "shape":
            raise PatchRejected("bad_address", "Нужен адрес фигуры, а не абзаца.", i, e.addr)
        if "/" in e.addr:
            raise PatchRejected("group_child", "Фигуры внутри группы не двигаются: двигайте группу целиком.", i, e.addr)
        if e.addr.endswith(".notes") or ".alt" in e.addr:
            raise PatchRejected("not_editable", "Этот объект не двигается.", i, e.addr)
        g = self.geom(e.part, e.node)
        if g is None:
            raise PatchRejected("no_geometry", "У фигуры нет положения и размеров (наследуются), укажите x, y, w, h целиком.", i, e.addr)
        return g

    def _write_geom(self, e: Elem, x: int, y: int, cx: int, cy: int, i: int) -> None:
        if x < 0 or y < 0 or cx <= 0 or cy <= 0 or x + cx > self.W or y + cy > self.H:
            raise PatchRejected("out_of_bounds", "Фигура выходит за пределы слайда.", i, e.addr)
        node = e.node
        xf = self._own_xfrm_el(node)
        if xf is None:
            if node.tag in (p_("sp"), p_("pic"), p_("cxnSp")):
                sp = node.find(p_("spPr"))
                if sp is None:
                    raise PatchRejected("no_geometry", "У фигуры нет блока свойств.", i, e.addr)
                xf = set_child(sp, a_("xfrm"), SP_ORDER)
            else:
                raise PatchRejected("no_geometry", "Не удалось записать положение.", i, e.addr)
        off = xf.find(a_("off")) if xf.find(a_("off")) is not None else etree.SubElement(xf, a_("off"))
        ext = xf.find(a_("ext")) if xf.find(a_("ext")) is not None else etree.SubElement(xf, a_("ext"))
        off.set("x", str(x)), off.set("y", str(y)), ext.set("cx", str(cx)), ext.set("cy", str(cy))
        self.pkg.touch(e.part)

    @staticmethod
    def _num(op, key, i, at, lo=-1e6, hi=1e6):
        v = op.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
            raise PatchRejected("bad_number", f"{key}: нужно число в допустимых пределах.", i, at)
        return int(round(v * EMU_PT))

    def op_move_shape(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="shape")
        if not e.editable and e.extra["type"] not in ("image", "chart", "smartart", "ole", "video", "connector"):
            raise PatchRejected("not_editable", "Этот объект не двигается.", i, e.addr)
        x0, y0, cx, cy, _ = self._geom_for_edit(e, i)
        self._write_geom(e, self._num(op, "x", i, e.addr), self._num(op, "y", i, e.addr), cx, cy, i)
        ctx.done(i, op, e.addr, kind="move")

    def op_resize_shape(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="shape")
        x, y, cx, cy, _ = self._geom_for_edit(e, i)
        self._write_geom(e, x, y, self._num(op, "w", i, e.addr, 1), self._num(op, "h", i, e.addr, 1), i)
        ctx.done(i, op, e.addr, kind="resize")

    def op_align(self, ctx, i, op):
        ats = op.get("ats")
        if not isinstance(ats, list) or not ats or len(ats) > 50:
            raise PatchRejected("bad_op", "align: нужен список ats (1..50 фигур).", i)
        mode, to = op.get("mode"), op.get("to", "slide")
        if mode not in ("left", "center", "right", "top", "middle", "bottom") or to not in ("slide", "first"):
            raise PatchRejected("bad_op", "align: mode left/center/right/top/middle/bottom, to slide/first.", i)
        es = [self.need(ctx, i, a, kind="shape") for a in ats]
        gs = [self._geom_for_edit(e, i) for e in es]
        if len({e.part for e in es}) != 1:
            raise PatchRejected("bad_op", "Выравнивать можно фигуры одного слайда.", i)
        ref = (0, 0, self.W, self.H) if to == "slide" else gs[0][:4]
        for e, (x, y, cx, cy, _) in zip(es, gs):
            nx, ny = x, y
            if mode == "left":
                nx = ref[0]
            elif mode == "right":
                nx = ref[0] + ref[2] - cx
            elif mode == "center":
                nx = ref[0] + (ref[2] - cx) // 2
            elif mode == "top":
                ny = ref[1]
            elif mode == "bottom":
                ny = ref[1] + ref[3] - cy
            else:
                ny = ref[1] + (ref[3] - cy) // 2
            self._write_geom(e, nx, ny, cx, cy, i)
        ctx.done(i, op, ",".join(ats), kind="align")

    def op_set_layout(self, ctx, i, op):
        slide = op.get("slide")
        cont = next((c for c in self.containers if c["addr"] == slide), None)
        if cont is None:
            raise PatchRejected("unknown_address", "Неизвестный слайд.", i, str(slide)[:20])
        target = next((l for l in self.layout_names() if l["name"] == op.get("layout")), None)
        if target is None:
            raise PatchRejected("unknown_layout", "Такого макета в презентации нет.", i, slide)
        old = cont["layout_part"]
        master = lambda lp: next((t for ty, t in self.pkg.rels(lp).values() if ty.endswith("/slideMaster")), None)
        if old and master(old) != master(target["part"]):
            raise PatchRejected("layout_master", "Макет другого образца слайдов не допускается.", i, slide)
        relp = self.pkg.rels_name(cont["part"])
        root = self.pkg.xml(relp)
        for rel in root:
            if rel.get("Type", "").endswith("/slideLayout"):
                rel.set("Target", posixpath.relpath(target["part"], posixpath.dirname(cont["part"])))
                self.pkg.touch(relp)
                break
        else:
            raise PatchRejected("bad_file", "У слайда нет связи с макетом.", i, slide)
        cont["layout_part"], cont["layout"] = target["part"], target["name"]
        ctx.done(i, op, slide, kind="layout", new=target["name"])

    def op_col_width(self, ctx, i, op):
        e = self.need(ctx, i, op["at"], kind="shape")
        if e.extra["type"] != "table":
            raise PatchRejected("bad_address", "Адрес не указывает на таблицу.", i, e.addr)
        cols = list(e.node.iterfind(f".//{a_('gridCol')}"))
        col, w = op.get("col"), op.get("width")
        if not isinstance(col, int) or isinstance(col, bool) or not 0 <= col < len(cols):
            raise PatchRejected("bad_number", "Нет такого столбца.", i, e.addr)
        if not isinstance(w, (int, float)) or isinstance(w, bool) or not 5 <= w <= self.opts.max_col_width_pt:
            raise PatchRejected("bad_number", "Ширина столбца вне допустимых пределов.", i, e.addr)
        cols[col].set("w", str(int(round(w * EMU_PT))))
        total = sum(int(c.get("w")) for c in cols)
        g = self.geom(e.part, e.node)
        if g is None or g[0] + total > self.W:
            raise PatchRejected("out_of_bounds", "Таблица выходит за пределы слайда.", i, e.addr)
        xf = e.node.find(p_("xfrm"))
        if xf is not None and xf.find(a_("ext")) is not None:
            xf.find(a_("ext")).set("cx", str(total))
        self.pkg.touch(e.part)
        ctx.done(i, op, e.addr, kind="col_width")
