"""Hand-written OOXML finance workbooks that mimic files saved by Excel (SYNTHETIC; no real company data).

    python tools/make_finance_realistic.py [out_dir]     # writes the .xlsx files and verifies them with openpyxl

`build_all() -> {name: {"bytes", "origin", "desc", "features", "secrets", "money_cells"}}`

Unlike tools/make_finance_corpus.py (openpyxl writer) the parts here are written by hand with zipfile, so the packages contain what Excel
itself writes and openpyxl never does: sharedStrings (t="s"), styles with custom numFmts (currency + a number-format literal that holds an
amount), cached <v> on formulas, shared formulas (t="shared" si), array formulas, tables, merged cells, defined names (numeric constants,
hidden, print area), conditional formatting (cellIs thresholds, colorScale cfvo), data validation (decimal bound, list "3100000,3200000"),
comments + vmlDrawing with amounts in the text, a drawing with a text box, a chart with numCache/strCache and a fixed axis maximum,
hidden / veryHidden sheets, hidden rows, calcChain, docProps.

"secrets" = every real amount planted (inputs, cached formula results, and amounts that live only in CF / DV / names / comments / drawing /
chart / format literal), as numbers: none of them may survive in a masked output. "money_cells" = the key input constants {"Sheet!A1": v}.
"""
from __future__ import annotations

import io
import random
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl.utils import column_index_from_string as CI
from openpyxl.utils import get_column_letter as CL
from openpyxl.utils.cell import coordinate_from_string

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DOCREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

PRESET = {
    "rub": '#,##0\\ [$₽-419]', "rub2": '#,##0.00\\ [$₽-419]', "usd": '[$$-409]#,##0.00', "usd0": '[$$-409]#,##0', "eur": '#,##0.00\\ [$€-2]',
    "acct": '_-* #,##0.00\\ _₽_-;\\-* #,##0.00\\ _₽_-;_-* "-"??\\ _₽_-;_-@_-', "int": "#,##0", "pct": "0.0%", "date": "dd\\.mm\\.yyyy",
    "dec": "0.0000", "x2": "0.00",
}
BUILTIN = {"General": 0, "0": 1, "0.00": 2, "#,##0": 3, "#,##0.00": 4, "0%": 9, "0.00%": 10}


def esc(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def ru(n) -> str:                                  # 3 150 000 with NBSP, as typed in a Russian Excel
    return f"{n:,.0f}".replace(",", " ")


def en(n) -> str:
    return f"{n:,.0f}"


def num(v) -> str:
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v))
    return repr(round(float(v), 8))


def q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def serial(y, m, d) -> int:
    return (date(y, m, d) - date(1899, 12, 30)).days


def _norm(v):
    v = float(v)
    return int(v) if v.is_integer() else round(v, 8)


class Sheet:
    def __init__(self, book: "Book", name: str, state: str | None):
        self.book, self.name, self.state = book, name, state
        self.cells: dict[tuple[int, int], dict] = {}
        self.vals: dict[str, object] = {}
        self.merges: list[str] = []
        self.hidden_rows: set[int] = set()
        self.widths: list[tuple[int, int, float]] = []
        self.cfs: list[str] = []
        self.dvs: list[str] = []
        self.comments: list[tuple[str, str, str]] = []
        self.shapes: list[dict] = []
        self.charts: list[dict] = []
        self.tables: list[dict] = []
        self.si = 0
        self.prio = 0

    # ---- cells
    def _put(self, ref, **kw):
        c, r = coordinate_from_string(ref)
        self.cells[(r, CI(c))] = dict(ref=ref, **kw)

    def text(self, ref, s, fmt=None, font="n", fill=0, wrap=False):
        self._put(ref, kind="s", v=self.book.sst(s), s=self.book.xf(fmt, font, fill, wrap))
        self.vals[ref] = s

    def num(self, ref, v, fmt=None, font="n", fill=0):
        self._put(ref, kind="n", v=v, s=self.book.xf(fmt, font, fill))
        self.vals[ref] = v

    def inp(self, ref, v, fmt="rub", font="in", fill=0):
        """money constant typed by a person: a secret and a key input."""
        self.num(ref, v, fmt, font, fill)
        self.book.money_cells[f"{self.name}!{ref}"] = _norm(v)
        self.book.secret(v)

    def fx(self, ref, formula, v, fmt=None, font="n", money=False, fill=0, attrs=""):
        self._put(ref, kind="f", f=formula, fattrs=attrs, v=v, s=self.book.xf(fmt, font, fill))
        self.vals[ref] = v
        if money:
            self.book.secret(v)

    def arr(self, ref, formula, v, fmt=None, money=False, font="n"):
        self.fx(ref, formula, v, fmt, font, money, attrs=f' t="array" ref="{ref}"')
        self.book.feature("array formula")

    def sf(self, rng, formula, values, fmt=None, money=False, font="n"):
        """shared formula: master text for the first cell of rng (one row or one column), `values` are the cached results."""
        a, b = rng.split(":")
        (c1, r1), (c2, r2) = coordinate_from_string(a), coordinate_from_string(b)
        c1, c2 = CI(c1), CI(c2)
        cells = [(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        assert len(cells) == len(values), (rng, len(values))
        si = self.si
        self.si += 1
        for i, ((r, c), v) in enumerate(zip(cells, values)):
            ref = f"{CL(c)}{r}"
            if i == 0:
                self._put(ref, kind="f", f=formula, fattrs=f' t="shared" ref="{rng}" si="{si}"', v=v, s=self.book.xf(fmt, font, 0))
            else:
                self._put(ref, kind="f", f=None, fattrs=f' t="shared" si="{si}"', v=v, s=self.book.xf(fmt, font, 0))
            self.vals[ref] = v
            if money:
                self.book.secret(v)
        self.book.feature("shared formulas")

    # ---- layout
    def merge(self, rng):
        self.merges.append(rng)
        self.book.feature("merged cells")

    def hide_row(self, r):
        self.hidden_rows.add(r)
        self.book.feature("hidden rows")

    def width(self, cols, w):
        a, _, b = cols.partition(":")
        self.widths.append((CI(a), CI(b or a), w))

    # ---- rules
    def cf_cell(self, sqref, op, val, dxf=0, money=True):
        self.prio += 1
        self.cfs.append(f'<conditionalFormatting sqref="{sqref}"><cfRule type="cellIs" dxfId="{dxf}" priority="{self.prio}" operator="{op}">'
                        f'<formula>{num(val)}</formula></cfRule></conditionalFormatting>')
        if money:
            self.book.secret(val)
        self.book.feature("CF cellIs")

    def cf_scale(self, sqref, lo, hi, money=True):
        self.prio += 1
        self.cfs.append(f'<conditionalFormatting sqref="{sqref}"><cfRule type="colorScale" priority="{self.prio}"><colorScale>'
                        f'<cfvo type="num" val="{num(lo)}"/><cfvo type="num" val="{num(hi)}"/><color rgb="FFF8696B"/><color rgb="FF63BE7B"/></colorScale></cfRule>'
                        f'</conditionalFormatting>')
        if money:
            self.book.secret(lo, hi)
        self.book.feature("CF colorScale")

    def dv_decimal(self, sqref, op, f1, f2=None, msg="", money=True):
        f2x = f"<formula2>{num(f2)}</formula2>" if f2 is not None else ""
        self.dvs.append(f'<dataValidation type="decimal" operator="{op}" allowBlank="1" showInputMessage="1" showErrorMessage="1" errorTitle="Check" '
                        f'error="{esc(msg)}" sqref="{sqref}"><formula1>{num(f1)}</formula1>{f2x}</dataValidation>')
        if money:
            self.book.secret(f1, *([f2] if f2 is not None else []))
        self.book.feature("DV decimal")

    def dv_list(self, sqref, items: str, secrets=()):
        self.dvs.append(f'<dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1" sqref="{sqref}">'
                        f'<formula1>"{esc(items)}"</formula1></dataValidation>')
        self.book.secret(*secrets)
        self.book.feature("DV list")

    def comment(self, ref, text, author="Бухгалтерия", secrets=()):
        self.comments.append((ref, author, text))
        self.book.secret(*secrets)
        self.book.feature("comments")

    def textbox(self, text, frm, to, secrets=()):
        self.shapes.append(dict(text=text, frm=frm, to=to))
        self.book.secret(*secrets)
        self.book.feature("drawing text box")

    def chart(self, frm, to, title, cat, series, axis_max=None, axis_min=None, kind="col", secrets=()):
        self.charts.append(dict(frm=frm, to=to, title=title, cat=cat, series=series, axis_max=axis_max, axis_min=axis_min, kind=kind))
        self.book.secret(*secrets, *([axis_max] if axis_max else []), *([axis_min] if axis_min else []))
        self.book.feature("chart (numCache/strCache, fixed axis)")

    def table(self, name, ref, style="TableStyleMedium2"):
        self.tables.append(dict(name=name, ref=ref, style=style))
        self.book.feature("tables")


class Book:
    def __init__(self, title, creator, company, desc, lang="ru"):
        self.title, self.creator, self.company, self.desc, self.lang = title, creator, company, desc, lang
        self.sheets: list[Sheet] = []
        self._sst: list[str] = []
        self._sst_idx: dict[str, int] = {}
        self._fmts: list[str] = []
        self._xfs: list[tuple] = [(0, "n", 0, False)]
        self.names: list[str] = []
        self.money_cells: dict[str, float] = {}
        self._secrets: set = set()
        self.features: set[str] = {"sharedStrings", "custom numFmts", "cached values", "calcChain", "docProps"}

    def feature(self, f):
        self.features.add(f)

    def secret(self, *vals):
        for v in vals:
            if isinstance(v, (int, float)) and abs(v) >= 1000:
                self._secrets.add(_norm(v))

    def sheet(self, name, state=None) -> Sheet:
        s = Sheet(self, name, state)
        self.sheets.append(s)
        if state == "hidden":
            self.feature("hidden sheet")
        if state == "veryHidden":
            self.feature("veryHidden sheet")
        return s

    def sst(self, s) -> int:
        if s not in self._sst_idx:
            self._sst_idx[s] = len(self._sst)
            self._sst.append(s)
        return self._sst_idx[s]

    def fmt_id(self, fmt) -> int:
        if fmt is None:
            return 0
        code = PRESET.get(fmt, fmt)
        if code in BUILTIN:
            return BUILTIN[code]
        if code not in self._fmts:
            self._fmts.append(code)
        return 164 + self._fmts.index(code)

    def xf(self, fmt=None, font="n", fill=0, wrap=False) -> int:
        key = (self.fmt_id(fmt), font, fill, wrap)
        if key not in self._xfs:
            self._xfs.append(key)
        return self._xfs.index(key)

    def name(self, name, value, hidden=False, local=None, money=False):
        """defined name: value is a reference text or a numeric constant."""
        attrs = (' hidden="1"' if hidden else "") + (f' localSheetId="{local}"' if local is not None else "")
        self.names.append(f'<definedName name="{esc(name)}"{attrs}>{esc(value)}</definedName>')
        self.feature("defined names")
        if hidden:
            self.feature("hidden defined name")
        if money:
            self.secret(float(value))

    # ------------------------------------------------------------------ serialisation
    def _styles(self) -> str:
        fonts = ['<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>',
                 '<font><b/><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>',
                 '<font><b/><sz val="14"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>',
                 '<font><sz val="11"/><color rgb="FF0000FF"/><name val="Calibri"/><family val="2"/></font>']
        fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>',
                 '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>',
                 '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>']
        fid = {"n": 0, "b": 1, "t": 2, "in": 3}
        xfs = []
        for nf, font, fill, wrap in self._xfs:
            al = '><alignment wrapText="1" vertical="top"/></xf>' if wrap else "/>"
            xfs.append(f'<xf numFmtId="{nf}" fontId="{fid[font]}" fillId="{fill}" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1" '
                       f'applyFill="1"{" applyAlignment=" + chr(34) + "1" + chr(34) if wrap else ""}{al}')
        nf = "".join(f'<numFmt numFmtId="{164 + i}" formatCode="{esc(c)}"/>' for i, c in enumerate(self._fmts))
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{NS}">'
                f'<numFmts count="{len(self._fmts)}">{nf}</numFmts><fonts count="{len(fonts)}">{"".join(fonts)}</fonts>'
                f'<fills count="{len(fills)}">{"".join(fills)}</fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                f'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                '<dxfs count="2"><dxf><font><color rgb="FF9C0006"/></font><fill><patternFill><bgColor rgb="FFFFC7CE"/></patternFill></fill></dxf>'
                '<dxf><font><color rgb="FF006100"/></font><fill><patternFill><bgColor rgb="FFC6EFCE"/></patternFill></fill></dxf></dxfs>'
                '<tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/></styleSheet>')

    def _sheet_xml(self, s: Sheet, first: bool, rels: list, ctr: dict) -> str:
        rows: dict[int, list] = {}
        for (r, c), cell in sorted(s.cells.items()):
            rows.setdefault(r, []).append((c, cell))
        for r in s.hidden_rows:
            rows.setdefault(r, [])
        out = []
        for r in sorted(rows):
            cs = []
            for c, cell in rows[r]:
                st = f' s="{cell["s"]}"' if cell["s"] else ""
                if cell["kind"] == "s":
                    cs.append(f'<c r="{cell["ref"]}"{st} t="s"><v>{cell["v"]}</v></c>')
                elif cell["kind"] == "n":
                    cs.append(f'<c r="{cell["ref"]}"{st}><v>{num(cell["v"])}</v></c>')
                else:
                    f = f'<f{cell["fattrs"]}>{esc(cell["f"])}</f>' if cell["f"] is not None else f'<f{cell["fattrs"]}/>'
                    if isinstance(cell["v"], str):
                        cs.append(f'<c r="{cell["ref"]}"{st} t="str">{f}<v>{esc(cell["v"])}</v></c>')
                    else:
                        cs.append(f'<c r="{cell["ref"]}"{st}>{f}<v>{num(cell["v"])}</v></c>')
            hid = ' hidden="1"' if r in s.hidden_rows else ""
            out.append(f'<row r="{r}"{hid}>{"".join(cs)}</row>' if cs else f'<row r="{r}"{hid}/>')
        keys = list(s.cells) or [(1, 1)]
        dim = f"{CL(min(c for _, c in keys))}{min(r for r, _ in keys)}:{CL(max(c for _, c in keys))}{max(r for r, _ in keys)}"
        cols = "".join(f'<col min="{a}" max="{b}" width="{w}" customWidth="1"/>' for a, b, w in s.widths)
        x = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{NS}" xmlns:r="{RELNS}"><dimension ref="{dim}"/>',
             f'<sheetViews><sheetView{" tabSelected=" + chr(34) + "1" + chr(34) if first else ""} workbookViewId="0"/></sheetViews>',
             '<sheetFormatPr defaultRowHeight="15"/>', f"<cols>{cols}</cols>" if cols else "", f'<sheetData>{"".join(out)}</sheetData>']
        if s.merges:
            x.append(f'<mergeCells count="{len(s.merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in s.merges) + "</mergeCells>")
        x.extend(s.cfs)
        if s.dvs:
            x.append(f'<dataValidations count="{len(s.dvs)}">' + "".join(s.dvs) + "</dataValidations>")
        x.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>')
        if s.shapes or s.charts:
            ctr["drawing"] += 1
            n = ctr["drawing"]
            rels.append(("drawing", f"../drawings/drawing{n}.xml"))
            x.append(f'<drawing r:id="rId{len(rels)}"/>')
            s._drawing_n = n
        if s.comments:
            ctr["comments"] += 1
            n = ctr["comments"]
            rels.append(("comments", f"../comments{n}.xml"))
            rels.append(("vmlDrawing", f"../drawings/vmlDrawing{n}.vml"))
            x.append(f'<legacyDrawing r:id="rId{len(rels)}"/>')
            s._comments_n = n
        if s.tables:
            x.append(f'<tableParts count="{len(s.tables)}">')
            for t in s.tables:
                ctr["table"] += 1
                t["n"] = ctr["table"]
                rels.append(("table", f"../tables/table{t['n']}.xml"))
                x.append(f'<tablePart r:id="rId{len(rels)}"/>')
            x.append("</tableParts>")
        x.append("</worksheet>")
        return "".join(x)

    @staticmethod
    def _anchor(frm, to):
        return (f'<xdr:from><xdr:col>{frm[0]}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{frm[1]}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
                f'<xdr:to><xdr:col>{to[0]}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{to[1]}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>')

    def _rng_vals(self, s: Sheet, rng):
        a, _, b = rng.partition(":")
        (c1, r1), (c2, r2) = coordinate_from_string(a), coordinate_from_string(b or a)
        return [s.vals.get(f"{CL(c)}{r}") for r in range(r1, r2 + 1) for c in range(CI(c1), CI(c2) + 1)]

    @staticmethod
    def _abs(rng):
        parts = []
        for p in rng.split(":"):
            c, r = coordinate_from_string(p)
            parts.append(f"${c}${r}")
        return ":".join(parts)

    def _chart_xml(self, s: Sheet, ch: dict) -> str:
        sn = q(s.name)

        def strref(rng, vals):
            pts = "".join(f'<c:pt idx="{i}"><c:v>{esc(v)}</c:v></c:pt>' for i, v in enumerate(vals))
            return f"<c:strRef><c:f>{esc(sn)}!{self._abs(rng)}</c:f><c:strCache><c:ptCount val=\"{len(vals)}\"/>{pts}</c:strCache></c:strRef>"

        def numref(rng, vals):
            pts = "".join(f'<c:pt idx="{i}"><c:v>{num(v)}</c:v></c:pt>' for i, v in enumerate(vals))
            return (f"<c:numRef><c:f>{esc(sn)}!{self._abs(rng)}</c:f><c:numCache><c:formatCode>General</c:formatCode>"
                    f'<c:ptCount val="{len(vals)}"/>{pts}</c:numCache></c:numRef>')

        sers = []
        cats = self._rng_vals(s, ch["cat"])
        for i, (name_ref, val_rng) in enumerate(ch["series"]):
            sers.append(f'<c:ser><c:idx val="{i}"/><c:order val="{i}"/><c:tx>{strref(name_ref, [s.vals[name_ref]])}</c:tx>'
                        f'<c:invertIfNegative val="0"/><c:cat>{strref(ch["cat"], cats)}</c:cat><c:val>{numref(val_rng, self._rng_vals(s, val_rng))}</c:val></c:ser>')
        mx = f'<c:max val="{num(ch["axis_max"])}"/>' if ch["axis_max"] is not None else ""
        mn = f'<c:min val="{num(ch["axis_min"])}"/>' if ch["axis_min"] is not None else ""
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
                f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="{RELNS}"><c:roundedCorners val="0"/><c:chart>'
                f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ru-RU"/><a:t>{esc(ch["title"])}</a:t></a:r></a:p></c:rich></c:tx>'
                f'<c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/><c:plotArea><c:layout/><c:barChart><c:barDir val="col"/>'
                f'<c:grouping val="clustered"/><c:varyColors val="0"/>{"".join(sers)}<c:gapWidth val="150"/><c:axId val="50010001"/><c:axId val="50010002"/>'
                f'</c:barChart><c:catAx><c:axId val="50010001"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/>'
                f'<c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="low"/>'
                f'<c:crossAx val="50010002"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/>'
                f'</c:catAx><c:valAx><c:axId val="50010002"/><c:scaling><c:orientation val="minMax"/>{mx}{mn}</c:scaling><c:delete val="0"/><c:axPos val="l"/>'
                f'<c:majorGridlines/><c:numFmt formatCode="#,##0" sourceLinked="0"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/>'
                f'<c:tickLblPos val="nextTo"/><c:crossAx val="50010001"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx></c:plotArea>'
                f'<c:legend><c:legendPos val="r"/><c:overlay val="0"/></c:legend><c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart></c:chartSpace>')

    def _drawing_xml(self, s: Sheet, chart_rids: list[str]) -> str:
        parts = []
        oid = 1
        for sh in s.shapes:
            oid += 1
            parts.append(
                f'<xdr:twoCellAnchor>{self._anchor(sh["frm"], sh["to"])}<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="{oid}" name="TextBox {oid - 1}"/>'
                f'<xdr:cNvSpPr txBox="1"/></xdr:nvSpPr><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
                f'</a:prstGeom><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ln w="9525"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>'
                f'</xdr:spPr><xdr:txBody><a:bodyPr vertOverflow="clip" horzOverflow="clip" wrap="square" rtlCol="0" anchor="t"/><a:lstStyle/><a:p><a:r>'
                f'<a:rPr lang="ru-RU" sz="1100"/><a:t>{esc(sh["text"])}</a:t></a:r></a:p></xdr:txBody></xdr:sp><xdr:clientData/></xdr:twoCellAnchor>')
        for ch, rid in zip(s.charts, chart_rids):
            oid += 1
            parts.append(
                f'<xdr:twoCellAnchor>{self._anchor(ch["frm"], ch["to"])}<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{oid}" name="Chart {oid - 1}"/>'
                f'<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic>'
                f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
                f'r:id="{rid}"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
                f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="{RELNS}">{"".join(parts)}</xdr:wsDr>')

    def _comments_xml(self, s: Sheet):
        authors = sorted({a for _, a, _ in s.comments})
        cl = []
        shapes = []
        for i, (ref, a, text) in enumerate(s.comments):
            c, r = coordinate_from_string(ref)
            cl.append(f'<comment ref="{ref}" authorId="{authors.index(a)}" shapeId="0"><text><r><rPr><b/><sz val="9"/><color indexed="81"/><rFont val="Tahoma"/>'
                      f'<family val="2"/><charset val="204"/></rPr><t>{esc(a)}:</t></r><r><rPr><sz val="9"/><color indexed="81"/><rFont val="Tahoma"/><family val="2"/>'
                      f'<charset val="204"/></rPr><t xml:space="preserve">\n{esc(text)}</t></r></text></comment>')
            col = CI(c) - 1
            shapes.append(
                f'<v:shape id="_x0000_s{1025 + i}" type="#_x0000_t202" style="position:absolute;margin-left:80pt;margin-top:2pt;width:140pt;height:70pt;z-index:{i + 1};'
                f'visibility:hidden" fillcolor="#ffffe1" o:insetmode="auto"><v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/><v:path o:connecttype="none"/>'
                f'<v:textbox style="mso-direction-alt:auto"><div style="text-align:left"></div></v:textbox><x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/>'
                f'<x:Anchor>{col + 1}, 15, {max(r - 2, 0)}, 2, {col + 3}, 15, {r + 3}, 16</x:Anchor><x:AutoFill>False</x:AutoFill><x:Row>{r - 1}</x:Row>'
                f'<x:Column>{col}</x:Column></x:ClientData></v:shape>')
        cx = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<comments xmlns="{NS}"><authors>' + "".join(f"<author>{esc(a)}</author>" for a in authors)
              + f'</authors><commentList>{"".join(cl)}</commentList></comments>')
        vml = ('<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">'
               '<o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="1"/></o:shapelayout><v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" '
               'path="m,l,21600r21600,l21600,xe"><v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>' + "".join(shapes) + "</xml>")
        return cx, vml

    def _table_xml(self, s: Sheet, t: dict) -> str:
        a, b = t["ref"].split(":")
        (c1, r1), (c2, _) = coordinate_from_string(a), coordinate_from_string(b)
        cols = [s.vals[f"{CL(c)}{r1}"] for c in range(CI(c1), CI(c2) + 1)]
        tc = "".join(f'<tableColumn id="{i + 1}" name="{esc(n)}"/>' for i, n in enumerate(cols))
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<table xmlns="{NS}" id="{t["n"]}" name="{t["name"]}" displayName="{t["name"]}" '
                f'ref="{t["ref"]}" totalsRowShown="0"><autoFilter ref="{t["ref"]}"/><tableColumns count="{len(cols)}">{tc}</tableColumns>'
                f'<tableStyleInfo name="{t["style"]}" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/></table>')

    def to_bytes(self) -> bytes:
        from openpyxl.writer.theme import theme_xml
        files: dict[str, str | bytes] = {}
        ctr = {"drawing": 0, "comments": 0, "table": 0, "chart": 0}
        ct = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
              '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>']
        wb_rels = []
        sheets_xml = []
        calc = []
        RT = {"drawing": "drawing", "comments": "comments", "vmlDrawing": "vmlDrawing", "table": "table"}
        for i, s in enumerate(self.sheets, start=1):
            rels: list = []
            files[f"xl/worksheets/sheet{i}.xml"] = self._sheet_xml(s, i == 1, rels, ctr)
            ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            wb_rels.append(f'<Relationship Id="rId{i}" Type="{DOCREL}/worksheet" Target="worksheets/sheet{i}.xml"/>')
            st = f' state="{s.state}"' if s.state else ""
            sheets_xml.append(f'<sheet name="{esc(s.name)}" sheetId="{i}"{st} r:id="rId{i}"/>')
            for (r, c), cell in sorted(s.cells.items()):
                if cell["kind"] == "f":
                    calc.append(f'<c r="{cell["ref"]}" i="{i}"/>')
            if getattr(s, "_drawing_n", None) and (s.shapes or s.charts):
                n = s._drawing_n
                drels = []
                for ch in s.charts:
                    ctr["chart"] += 1
                    cn = ctr["chart"]
                    files[f"xl/charts/chart{cn}.xml"] = self._chart_xml(s, ch)
                    ct.append(f'<Override PartName="/xl/charts/chart{cn}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>')
                    drels.append(f'<Relationship Id="rId{len(drels) + 1}" Type="{DOCREL}/chart" Target="../charts/chart{cn}.xml"/>')
                files[f"xl/drawings/drawing{n}.xml"] = self._drawing_xml(s, [f"rId{k + 1}" for k in range(len(s.charts))])
                files[f"xl/drawings/_rels/drawing{n}.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">{"".join(drels)}</Relationships>'
                ct.append(f'<Override PartName="/xl/drawings/drawing{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
            if s.comments:
                n = s._comments_n
                files[f"xl/comments{n}.xml"], files[f"xl/drawings/vmlDrawing{n}.vml"] = self._comments_xml(s)
                ct.append(f'<Override PartName="/xl/comments{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>')
            for t in s.tables:
                files[f"xl/tables/table{t['n']}.xml"] = self._table_xml(s, t)
                ct.append(f'<Override PartName="/xl/tables/table{t["n"]}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>')
            if rels:
                files[f"xl/worksheets/_rels/sheet{i}.xml.rels"] = (
                    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">'
                    + "".join(f'<Relationship Id="rId{k}" Type="{DOCREL}/{RT[t]}" Target="{tg}"/>' for k, (t, tg) in enumerate(rels, start=1)) + "</Relationships>")
        n = len(self.sheets)
        wb_rels += [f'<Relationship Id="rId{n + 1}" Type="{DOCREL}/styles" Target="styles.xml"/>',
                    f'<Relationship Id="rId{n + 2}" Type="{DOCREL}/theme" Target="theme/theme1.xml"/>',
                    f'<Relationship Id="rId{n + 3}" Type="{DOCREL}/sharedStrings" Target="sharedStrings.xml"/>',
                    f'<Relationship Id="rId{n + 4}" Type="{DOCREL}/calcChain" Target="calcChain.xml"/>']
        files["xl/_rels/workbook.xml.rels"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">{"".join(wb_rels)}</Relationships>'
        dn = f"<definedNames>{''.join(self.names)}</definedNames>" if self.names else ""
        files["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{NS}" xmlns:r="{RELNS}"><fileVersion appName="xl" '
                                    'lastEdited="7" lowestEdited="7" rupBuild="22228"/><workbookPr defaultThemeVersion="166925"/><bookViews><workbookView xWindow="0" '
                                    f'yWindow="0" windowWidth="28800" windowHeight="12300"/></bookViews><sheets>{"".join(sheets_xml)}</sheets>{dn}<calcPr calcId="191029"/></workbook>')
        files["xl/styles.xml"] = self._styles()
        files["xl/theme/theme1.xml"] = theme_xml
        total = sum(1 for s in self.sheets for c in s.cells.values() if c["kind"] == "s")
        files["xl/sharedStrings.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="{NS}" count="{total}" uniqueCount="{len(self._sst)}">'
                                         + "".join(f'<si><t xml:space="preserve">{esc(t)}</t></si>' for t in self._sst) + "</sst>")
        files["xl/calcChain.xml"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<calcChain xmlns="{NS}">{"".join(calc)}</calcChain>'
        files["docProps/core.xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                                      'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
                                      f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{esc(self.title)}</dc:title><dc:creator>{esc(self.creator)}</dc:creator>'
                                      f'<cp:lastModifiedBy>{esc(self.creator)}</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">2025-02-03T09:15:00Z</dcterms:created>'
                                      '<dcterms:modified xsi:type="dcterms:W3CDTF">2025-02-10T16:42:00Z</dcterms:modified></cp:coreProperties>')
        files["docProps/app.xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                                     f'<Application>Microsoft Excel</Application><DocSecurity>0</DocSecurity><ScaleCrop>false</ScaleCrop><Company>{esc(self.company)}</Company>'
                                     '<LinksUpToDate>false</LinksUpToDate><SharedDoc>false</SharedDoc><HyperlinksChanged>false</HyperlinksChanged><AppVersion>16.0300</AppVersion></Properties>')
        files["_rels/.rels"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{DOCREL}/officeDocument" '
                                'Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
                                'Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
                                'Target="docProps/app.xml"/></Relationships>')
        ct = (['<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
               '<Override PartName="/xl/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
               '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>',
               '<Override PartName="/xl/calcChain.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml"/>',
               '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
               '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'] + ct)
        files["[Content_Types].xml"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{"".join(ct)}</Types>'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ["[Content_Types].xml", "_rels/.rels"] + sorted(k for k in files if k not in ("[Content_Types].xml", "_rels/.rels")):
                zi = zipfile.ZipInfo(name, (2025, 2, 10, 16, 42, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                v = files[name]
                z.writestr(zi, v.encode("utf-8") if isinstance(v, str) else v)
        return buf.getvalue()

    def result(self) -> dict:
        data = self.to_bytes()
        return {"bytes": data, "origin": "synthetic-excel-style", "desc": self.desc, "features": sorted(self.features),
                "secrets": sorted(self._secrets), "money_cells": dict(self.money_cells)}


def _hdr(s: Sheet, row, labels, start=1, fill=2):
    for i, h in enumerate(labels):
        s.text(f"{CL(start + i)}{row}", h, font="b", fill=fill)


# =================================================================================== workbooks
def wb_pl_quarterly() -> Book:
    b = Book("ОПУ 2024", "Петрова Е.В.", "ООО «Северный ветер»", "Отчёт о прибылях и убытках по кварталам (RU): shared formulas, ROUND с именованной ставкой, скрытая строка и лист.")
    s = b.sheet("ОПУ")
    s.width("A", 36)
    s.width("B:F", 17)
    s.text("A1", "Отчёт о прибылях и убытках за 2024 год, руб.", font="t")
    s.merge("A1:F1")
    _hdr(s, 3, ["Статья", "1 кв.", "2 кв.", "3 кв.", "4 кв.", "Год"])
    rev = [11842650, 12306410, 13118975, 14927380]
    cogs = [7105590, 7384846, 7871385, 8956428]
    comm = [1421118, 1476769, 1574277, 1791286]
    mgmt = [1183204, 1190332, 1203118, 1240971]
    for i, c in enumerate("BCDE"):
        s.inp(f"{c}4", rev[i])
        s.inp(f"{c}5", cogs[i])
        s.inp(f"{c}7", comm[i])
        s.inp(f"{c}8", mgmt[i])
    gp = [a - c for a, c in zip(rev, cogs)]
    op = [g - a - m for g, a, m in zip(gp, comm, mgmt)]
    tax = [round(o * 0.2) for o in op]
    net = [o - t for o, t in zip(op, tax)]
    for r, t in [(4, "Выручка"), (5, "Себестоимость"), (6, "Валовая прибыль"), (7, "Коммерческие расходы"), (8, "Управленческие расходы"),
                 (9, "Операционная прибыль"), (10, "Налог на прибыль"), (11, "Чистая прибыль")]:
        s.text(f"A{r}", t, font="b" if r in (6, 9, 11) else "n")
    s.sf("B6:E6", "B4-B5", gp, "rub", True)
    s.sf("B9:E9", "B6-B7-B8", op, "rub", True)
    s.sf("B10:E10", "ROUND(B9*TaxRate,0)", tax, "rub", True)
    s.sf("B11:E11", "B9-B10", net, "rub", True)
    rows = [rev, cogs, gp, comm, mgmt, op, tax, net]
    s.sf("F4:F11", "SUM(B4:E4)", [sum(x) for x in rows], "rub", True, font="b")
    s.text("A13", "Резерв по сомнительным долгам (скрыто)")
    s.hide_row(13)
    s.num("B13", 1875000, '#,##0" из 2 900 000"')
    b.secret(1875000, 2900000)
    s.cf_cell("B11:F11", "greaterThan", 6500000, 1)
    s.cf_scale("B4:E4", 9000000, 15000000)
    s.dv_decimal("B4:E4", "lessThanOrEqual", 25000000, msg=f"Выручка квартала не должна превышать {ru(25000000)} руб.")
    s.dv_list("G4", "3100000,3200000", (3100000, 3200000))
    s.text("G3", "Лимит овердрафта", font="b")
    s.comment("B4", f"План на квартал: {ru(11400000)} руб. Факт выше плана.", secrets=(11400000,))
    s.comment("F9", "Проверить после закрытия года, см. ЛСП 2024", secrets=())
    b.name("TaxRate", "0.2")
    b.name("Выручка", f"{q('ОПУ')}!$B$4:$E$4")
    b.name("_ЛимитДолга", "6200000", hidden=True, money=True)
    b.name("_xlnm.Print_Area", f"{q('ОПУ')}!$A$1:$F$13", local=0)
    n = b.sheet("Заметки", "hidden")
    n.text("A1", f"Согласованный бюджет на 2025 год: {ru(41300000)} руб. (протокол №4)")
    b.secret(41300000)
    return b


def wb_balance_sheet() -> Book:
    b = Book("Бухгалтерский баланс", "Крылов Д.И.", "АО «Береговые системы»", "Баланс (RU) на две даты, контроль баланса = 0, таблица, veryHidden служебный лист, DV-список лимитов.")
    s = b.sheet("Баланс")
    s.width("A", 38)
    s.width("B:C", 18)
    s.text("A1", "Бухгалтерский баланс, руб.", font="t")
    s.merge("A1:C1")
    s.text("A2", "Дата составления")
    s.num("B2", serial(2025, 1, 31), "date")
    _hdr(s, 4, ["Актив", "31.12.2023", "31.12.2024"])
    assets = {"Основные средства": (18420780, 19655340), "Нематериальные активы": (2315640, 2290415), "Запасы": (6847215, 7432960),
              "Дебиторская задолженность": (5129380, 5873725), "Денежные средства": (2784195, 3418860)}
    for i, (k, (a, c)) in enumerate(assets.items(), start=5):
        s.text(f"A{i}", k)
        s.inp(f"B{i}", a)
        s.inp(f"C{i}", c)
    ta = [sum(v[0] for v in assets.values()), sum(v[1] for v in assets.values())]
    s.text("A10", "ИТОГО АКТИВОВ", font="b")
    s.fx("B10", "SUM(B5:B9)", ta[0], "rub", "b", True)
    s.fx("C10", "SUM(C5:C9)", ta[1], "rub", "b", True)
    s.table("tblAssets", "A4:C9")
    _hdr(s, 12, ["Пассив", "31.12.2023", "31.12.2024"])
    liab = {"Уставный капитал": (5000000, 5000000), "Кредиты и займы": (9650000, 8725450), "Кредиторская задолженность": (7216340, 8310915)}
    for i, (k, (a, c)) in enumerate(liab.items(), start=13):
        s.text(f"A{i}", k)
        s.inp(f"B{i}", a)
        s.inp(f"C{i}", c)
    re_ = [ta[0] - sum(v[0] for v in liab.values()), ta[1] - sum(v[1] for v in liab.values())]
    s.text("A16", "Нераспределённая прибыль")
    s.inp("B16", re_[0])
    s.inp("C16", re_[1])
    tl = [sum(v[0] for v in liab.values()) + re_[0], sum(v[1] for v in liab.values()) + re_[1]]
    s.text("A17", "ИТОГО ПАССИВОВ", font="b")
    s.fx("B17", "SUM(B13:B16)", tl[0], "rub", "b", True)
    s.fx("C17", "SUM(C13:C16)", tl[1], "rub", "b", True)
    s.text("A19", "Контроль баланса (активы - пассивы)")
    s.fx("B19", "B10-B17", 0, "rub")
    s.fx("C19", "C10-C17", 0, "rub")
    s.hide_row(11)
    s.cf_cell("B19:C19", "notEqual", 0, 0, money=False)
    s.cf_scale("B5:C9", 2000000, 20000000)
    s.text("E4", "Лимит овердрафта", font="b")
    s.dv_list("E5", "3100000,3200000", (3100000, 3200000))
    s.dv_decimal("C9", "between", 0, 9500000, f"Остаток денежных средств в диапазоне 0 - {ru(9500000)}")
    s.comment("C9", f"Включая депозит {ru(1250000)} руб. до 15.03.2025", secrets=(1250000,))
    s.textbox(f"Ковенант: долг / активы не более 40%. Кредитный лимит банка {ru(12000000)} руб.", (4, 7), (8, 12), (12000000,))
    b.name("ЛимитБанка", "12000000", money=True)
    b.name("Активы", f"{q('Баланс')}!$B$5:$C$9")
    sv = b.sheet("Служебный", "veryHidden")
    sv.text("A1", "Резерв под обесценение")
    sv.inp("B1", 482915)
    return b


def wb_cash_flow() -> Book:
    b = Book("Cash Flow Statement FY2024", "Mark Delgado", "Harborview Logistics LLC", "Cash flow statement (EN), USD, direct method; array formula, number-format literal with amount, chart with fixed axis range.", "en")
    s = b.sheet("Cash Flow")
    s.width("A", 40)
    s.width("B:C", 18)
    s.text("A1", "Statement of cash flows (direct method), USD", font="t")
    s.merge("A1:C1")
    _hdr(s, 3, ["Line item", "FY2023", "FY2024"])
    lines = [("Receipts from customers", 41286750, 46912380), ("Payments to suppliers", -24731420, -27384915), ("Payroll and benefits", -9816240, -10529770),
             ("Taxes paid", -2418395, -2763140)]
    for i, (k, a, c) in enumerate(lines, start=4):
        s.text(f"A{i}", k)
        s.inp(f"B{i}", a, "usd0")
        s.inp(f"C{i}", c, "usd0")
    no = [sum(x[1] for x in lines), sum(x[2] for x in lines)]
    s.text("A8", "Net cash from operating activities", font="b")
    s.fx("B8", "SUM(B4:B7)", no[0], "usd0", "b", True)
    s.fx("C8", "SUM(C4:C7)", no[1], "usd0", "b", True)
    inv = [("Purchase of equipment", -3846210, -5128745), ("Proceeds from asset sales", 612480, 947315)]
    for i, (k, a, c) in enumerate(inv, start=10):
        s.text(f"A{i}", k)
        s.inp(f"B{i}", a, "usd0")
        s.inp(f"C{i}", c, "usd0")
    ni = [sum(x[1] for x in inv), sum(x[2] for x in inv)]
    s.text("A12", "Net cash from investing activities", font="b")
    s.fx("B12", "SUM(B10:B11)", ni[0], "usd0", "b", True)
    s.fx("C12", "SUM(C10:C11)", ni[1], "usd0", "b", True)
    fin = [("Loan proceeds", 2500000 + 137, 1850000 + 321), ("Loan repayments", -1913660, -2174830), ("Dividends paid", -1250000 - 73, -1400000 - 91)]
    for i, (k, a, c) in enumerate(fin, start=14):
        s.text(f"A{i}", k)
        s.inp(f"B{i}", a, "usd0")
        s.inp(f"C{i}", c, "usd0")
    nf = [sum(x[1] for x in fin), sum(x[2] for x in fin)]
    s.text("A17", "Net cash from financing activities", font="b")
    s.fx("B17", "SUM(B14:B16)", nf[0], "usd0", "b", True)
    s.fx("C17", "SUM(C14:C16)", nf[1], "usd0", "b", True)
    net = [no[0] + ni[0] + nf[0], no[1] + ni[1] + nf[1]]
    s.text("A19", "Net change in cash")
    s.fx("B19", "B8+B12+B17", net[0], "usd0", money=True)
    s.fx("C19", "C8+C12+C17", net[1], "usd0", money=True)
    s.text("A20", "Opening cash")
    s.inp("B20", 3295880, "usd0")
    s.fx("C20", "B21", 3295880 + net[0], "usd0", money=True)
    s.text("A21", "Closing cash", font="b")
    cl = [3295880 + net[0], 3295880 + net[0] + net[1]]
    s.fx("B21", "B20+B19", cl[0], '#,##0" of 18 500 000 target"', "b", True)
    s.fx("C21", "C20+C19", cl[1], '#,##0" of 18 500 000 target"', "b", True)
    b.secret(18500000)
    s.text("A23", "Total cash outflows (array formula)")
    s.arr("B23", "SUM(IF(B4:B7<0,B4:B7,0))", sum(x[1] for x in lines if x[1] < 0), "usd0", True)
    s.arr("C23", "SUM(IF(C4:C7<0,C4:C7,0))", sum(x[2] for x in lines if x[2] < 0), "usd0", True)
    s.hide_row(22)
    s.cf_cell("B19:C19", "lessThan", -750000, 0)
    s.dv_decimal("C4", "lessThanOrEqual", 60000000, msg="Receipts cannot exceed USD 60 000 000")
    s.comment("C15", "Includes early repayment of the Series B facility, USD 640 275", "Treasury", (640275,))
    s.text("E3", "Activity", font="b")
    s.text("E4", "Operating")
    s.text("E5", "Investing")
    s.text("E6", "Financing")
    s.num("F3", 0)
    s.fx("F4", "C8", no[1], "usd0", money=True)
    s.fx("F5", "C12", ni[1], "usd0", money=True)
    s.fx("F6", "C17", nf[1], "usd0", money=True)
    s.text("F3", "FY2024", font="b")
    s.chart((7, 2), (14, 18), "FY2024 cash flow by activity", "E4:E6", [("F3", "F4:F6")], axis_max=30000000, axis_min=-12000000)
    b.name("CashTarget", "18500000", money=True)
    return b


def wb_cash_forecast_13w() -> Book:
    b = Book("13-week cash forecast", "Ольга Н.", "Meridian Trade Ltd", "13-недельный прогноз денежных средств (RU/EN): shared formulas по строкам, порог CF и DV, именованные константы.", "ru")
    s = b.sheet("13 weeks")
    s.width("A", 30)
    s.width("B:N", 14)
    s.text("A1", "13-week cash forecast / Прогноз ДДС на 13 недель, руб.", font="t")
    s.merge("A1:H1")
    _hdr(s, 3, ["Показатель / Item"] + [f"W{i}" for i in range(1, 14)])
    rnd = random.Random(1307)
    rec = [rnd.randint(2_100_000, 4_700_000) for _ in range(13)]
    pay = [rnd.randint(900_000, 1_400_000) for _ in range(13)]
    sup = [rnd.randint(1_100_000, 2_300_000) for _ in range(13)]
    oth = [rnd.randint(210_000, 560_000) for _ in range(13)]
    cols = [CL(2 + i) for i in range(13)]
    labels = {4: "Остаток на начало / Opening", 5: "Поступления от клиентов / Receipts", 6: "Зарплата / Payroll", 7: "Поставщики / Suppliers",
              8: "Прочее (аренда, налоги) / Other", 9: "Чистый поток / Net flow", 10: "Остаток на конец / Closing", 12: "Сценарий -15% (скрыто)"}
    for r, t in labels.items():
        s.text(f"A{r}", t, font="b" if r in (4, 10) else "n")
    for i, c in enumerate(cols):
        s.inp(f"{c}5", rec[i])
        s.inp(f"{c}6", pay[i])
        s.inp(f"{c}7", sup[i])
        s.inp(f"{c}8", oth[i])
    opening0 = 5250000 + 311
    s.fx("B4", "OpeningCash", opening0, "rub", "b", True)
    netv = [rec[i] - pay[i] - sup[i] - oth[i] for i in range(13)]
    closing, op = [], opening0
    opens = []
    for i in range(13):
        opens.append(op)
        op += netv[i]
        closing.append(op)
    s.sf("C4:N4", "B10", opens[1:], "rub", True, font="b")
    s.sf("B9:N9", "B5-B6-B7-B8", netv, "rub", True)
    s.sf("B10:N10", "B4+B9", closing, "rub", True, font="b")
    s.sf("B12:N12", "ROUND(B5*0.85,0)", [round(x * 0.85) for x in rec], "rub", True)
    s.hide_row(12)
    s.cf_cell("B10:N10", "lessThan", 1500000, 0)
    s.cf_scale("B5:N5", 2000000, 5000000)
    s.dv_decimal("B5:N5", "between", 0, 4800000, f"Поступления за неделю: от 0 до {ru(4800000)}")
    s.comment("B4", f"Остаток по выписке банка на 06.01: {ru(opening0)} руб.", "Казначей", (opening0,))
    s.comment("F7", f"Выплата по договору поставки №48, аванс {ru(1135000 + 17)}", "Казначей", (1135017,))
    b.name("OpeningCash", str(opening0), money=True)
    b.name("MinCash", "1500000", money=True)
    b.name("_Credit_Line", "4650000", hidden=True, money=True)
    b.name("Receipts", f"{q('13 weeks')}!$B$5:$N$5")
    s.textbox(f"Минимальный остаток {ru(1500000)} руб.; кредитная линия {ru(4650000)} руб. не включена", (1, 13), (8, 17), (1500000, 4650000))
    return b


def wb_budget_vs_actual() -> Book:
    b = Book("Бюджет vs факт, 2024", "Smirnova A.", "ЗАО «Альфа-Маркет»", "Бюджет и факт (RU/EN mix): таблица tblBudget, shared variance, CF, текстбокс с лимитом, скрытый лист Archive.")
    s = b.sheet("Budget vs Actual")
    s.width("A", 32)
    s.width("B:F", 16)
    s.text("A1", "Budget vs Actual — Бюджет и факт, руб.", font="t")
    s.merge("A1:F1")
    _hdr(s, 3, ["Статья", "Budget", "Actual", "Variance", "Var %", "Status"])
    items = [("Маркетинг / Marketing", 3200000 + 450, 3874310), ("Аренда / Rent", 2160000 + 90, 2160090), ("ИТ и лицензии / IT", 1475000 + 20, 1839925),
             ("Командировки / Travel", 684000 + 15, 531840), ("Обучение / Training", 412500 + 11, 389225), ("Юридические услуги / Legal", 560000 + 32, 1083560)]
    for i, (k, bg, ac) in enumerate(items, start=4):
        s.text(f"A{i}", k)
        s.inp(f"B{i}", bg)
        s.inp(f"C{i}", ac)
        s.text(f"F{i}", "Утверждено" if ac <= bg * 1.1 else "На согласовании")
    var = [ac - bg for _, bg, ac in items]
    s.sf("D4:D9", "C4-B4", var, "rub", True)
    s.sf("E4:E9", "D4/B4", [v / bg for v, (_, bg, _) in zip(var, items)], "pct")
    s.table("tblBudget", "A3:F9")
    tb, ta = sum(x[1] for x in items), sum(x[2] for x in items)
    s.text("A10", "ИТОГО / Total", font="b")
    s.fx("B10", "SUM(B4:B9)", tb, "rub", "b", True)
    s.fx("C10", "SUM(C4:C9)", ta, "rub", "b", True)
    s.fx("D10", "C10-B10", ta - tb, "rub", "b", True)
    s.fx("E10", "D10/B10", (ta - tb) / tb, "pct", "b")
    s.cf_cell("D4:D9", "greaterThan", 487500, 0)
    s.cf_scale("E4:E9", -0.2, 0.9, money=False)
    s.dv_list("F4:F9", "Утверждено,На согласовании,Отклонено")
    s.dv_decimal("C4:C9", "greaterThanOrEqual", 0, msg="Сумма не может быть отрицательной")
    s.comment("C9", f"Перерасход: судебные издержки {ru(402750)} руб. не были запланированы", "Финансовый директор", (402750,))
    s.textbox(f"Порог перерасхода по статье: {ru(487500)} руб. Квартальный лимит {ru(2250000)}", (7, 2), (11, 7), (487500, 2250000))
    b.name("OverrunLimit", "487500", money=True)
    b.name("BudgetTable", f"{q('Budget vs Actual')}!$B$4:$B$9")
    a = b.sheet("Archive", "hidden")
    a.text("A1", "Бюджет 2023 (архив)")
    a.inp("B1", 14952380)
    return b


def wb_dcf_npv() -> Book:
    b = Book("DCF valuation", "Priya Nair", "Cobalt Peak Capital", "DCF with NPV (EN): cross-sheet refs to Assumptions, named WACC/growth, array PV sum, chart FCF vs PV with fixed axis max.", "en")
    a = b.sheet("Assumptions")
    a.width("A", 32)
    a.width("B", 18)
    a.text("A1", "Assumptions", font="t")
    a.text("A2", "WACC")
    a.num("B2", 0.115, "pct", "in")
    a.text("A3", "Terminal growth")
    a.num("B3", 0.025, "pct", "in")
    a.text("A4", "Initial investment (USD)")
    a.inp("B4", 18750000 + 245, "usd0")
    a.text("A5", "Net debt (USD)")
    a.inp("B5", 6130480, "usd0")
    a.dv_decimal("B2", "between", 0.05, 0.25, "WACC must be between 5% and 25%", money=False)
    a.dv_decimal("B5", "lessThanOrEqual", 9800000, msg="Net debt above USD 9 800 000 needs board approval")
    a.comment("B4", f"Capex plan v7: USD {en(18750245)} incl. contingency {en(1137500)}", "Deal team", (1137500,))
    s = b.sheet("DCF")
    s.width("A", 34)
    s.width("B:F", 16)
    s.text("A1", "Discounted cash flow, USD", font="t")
    s.merge("A1:F1")
    _hdr(s, 3, ["Year", "2025", "2026", "2027", "2028", "2029"])
    s.text("A4", "Period")
    for i, c in enumerate("BCDEF", start=1):
        s.num(f"{c}4", i)
    fcf = [4215380, 6382915, 8147260, 9764835, 11230470]
    s.text("A5", "Free cash flow")
    for c, v in zip("BCDEF", fcf):
        s.inp(f"{c}5", v, "usd0")
    w, g, inv, nd = 0.115, 0.025, 18750245, 6130480
    df = [1 / (1 + w) ** t for t in range(1, 6)]
    pv = [f * d for f, d in zip(fcf, df)]
    s.text("A6", "Discount factor")
    s.sf("B6:F6", "1/(1+WACC)^B4", df, "dec")
    s.text("A7", "PV of FCF")
    s.sf("B7:F7", "B5*B6", pv, "usd0", True)
    s.hide_row(8)
    s.text("A8", "Sanity (hidden)")
    s.num("B8", 0)
    s.text("A10", "Sum of PV (array formula)")
    s.arr("B10", "SUM(B5:F5*B6:F6)", sum(pv), "usd0", True)
    tv = fcf[-1] * (1 + g) / (w - g)
    s.text("A11", "Terminal value")
    s.fx("B11", "F5*(1+TermGrowth)/(WACC-TermGrowth)", tv, "usd0", money=True)
    s.text("A12", "PV of terminal value")
    s.fx("B12", "B11*F6", tv * df[-1], "usd0", money=True)
    ev = sum(pv) + tv * df[-1]
    s.text("A13", "Enterprise value", font="b")
    s.fx("B13", "B10+B12", ev, "usd0", "b", True)
    s.text("A14", "Equity value")
    s.fx("B14", "B13-Assumptions!B5", ev - nd, "usd0", money=True)
    npv = sum(f / (1 + w) ** t for t, f in enumerate(fcf, start=1)) - inv
    s.text("A15", "NPV of 5-year FCF less investment", font="b")
    s.fx("B15", "NPV(WACC,B5:F5)-Assumptions!B4", npv, '#,##0" vs cap 31 450 000"', "b", True)
    b.secret(31450000)
    s.text("A16", "Verdict")
    s.fx("B16", 'IF(B15>0,"Accept","Reject")', "Accept" if npv > 0 else "Reject")
    s.cf_scale("B7:F7", 3000000, 9000000)
    s.cf_cell("B15", "lessThan", 0, 0, money=False)
    s.text("A18", "Chart data", font="b")
    s.text("B18", "FCF", font="b")
    s.text("C18", "PV", font="b")
    for i, y in enumerate("BCDEF"):
        s.text(f"A{19 + i}", str(2025 + i))
        s.fx(f"B{19 + i}", f"{y}5", fcf[i], "usd0", money=True)
        s.fx(f"C{19 + i}", f"{y}7", pv[i], "usd0", money=True)
    s.chart((7, 2), (15, 18), "FCF vs PV, USD", "A19:A23", [("B18", "B19:B23"), ("C18", "C19:C23")], axis_max=20000000, axis_min=0)
    b.name("WACC", "Assumptions!$B$2")
    b.name("TermGrowth", "Assumptions!$B$3")
    b.name("InitialInvestment", "18750245", money=True)
    b.name("_scenario_cap", "31450000", hidden=True, money=True)
    return b


def wb_loan_amortization() -> Book:
    b = Book("График платежей по кредиту", "Захарова Н.", "ИП Захаров", "Аннуитетный график (RU): shared formulas, ROUND, форматы-литералы с суммой лимита, DV на сумму и срок.")
    s = b.sheet("График")
    s.width("A", 24)
    s.width("B:F", 17)
    s.text("A1", "Кредитный договор: график платежей", font="t")
    s.merge("A1:F1")
    s.text("A2", "Сумма кредита")
    P, rate, n = 6480000 + 255, 0.1325, 12
    s.inp("B2", P, '#,##0\\ "₽ из 9 150 000"')
    b.secret(9150000)
    s.text("A3", "Ставка годовая")
    s.num("B3", rate, "pct", "in")
    s.text("A4", "Срок, мес.")
    s.num("B4", n, None, "in")
    r = rate / 12
    pay = round(P * r / (1 - (1 + r) ** -n), 2)
    s.text("A5", "Ежемесячный платёж")
    s.fx("B5", "ROUND(-PMT(B3/12,B4,B2),2)", pay, "rub2", "b", True)
    _hdr(s, 7, ["Месяц", "Остаток на начало", "Платёж", "Проценты", "Основной долг", "Остаток на конец"])
    openb, ints, prins, closes = [], [], [], []
    bal = P
    for i in range(n):
        openb.append(bal)
        it = round(bal * r, 2)
        pr = round(pay - it, 2)
        bal = round(bal - pr, 2)
        ints.append(it)
        prins.append(pr)
        closes.append(bal)
        s.num(f"A{8 + i}", i + 1)
    s.fx("B8", "$B$2", P, "rub2", money=True)
    s.sf("B9:B19", "F8", openb[1:], "rub2", True)
    s.sf("C8:C19", "$B$5", [pay] * n, "rub2", True)
    s.sf("D8:D19", "ROUND(B8*$B$3/12,2)", ints, "rub2", True)
    s.sf("E8:E19", "C8-D8", prins, "rub2", True)
    s.sf("F8:F19", "B8-E8", closes, "rub2", True)
    s.text("A20", "Итого", font="b")
    s.fx("C20", "SUM(C8:C19)", round(pay * n, 2), "rub2", "b", True)
    s.fx("D20", "SUM(D8:D19)", round(sum(ints), 2), "rub2", "b", True)
    s.fx("E20", "SUM(E8:E19)", round(sum(prins), 2), "rub2", "b", True)
    s.cf_cell("D8:D19", "greaterThan", 60000, 0)
    s.dv_decimal("B2", "lessThanOrEqual", 9150000, msg=f"Сумма не может превышать лимит {ru(9150000)} руб.")
    s.dv_list("B4", "12,24,36")
    s.comment("B2", f"Кредит по договору №К-118/24, транш {ru(3000000 + 55)} + {ru(3480200)}", "Заёмщик", (3000055, 3480200))
    s.hide_row(6)
    b.name("LoanAmount", str(P), money=True)
    b.name("Rate", "0.1325")
    return b


def wb_cap_table() -> Book:
    b = Book("Cap table", "Elena Voss", "Lumen Robotics Inc.", "Cap table (EN): table tblCap, ownership %, value at round price, text box with post-money, veryHidden term sheet.", "en")
    s = b.sheet("Cap Table")
    s.width("A", 26)
    s.width("B:F", 17)
    s.text("A1", "Capitalization table — Series A, USD", font="t")
    s.merge("A1:F1")
    s.text("A2", "Round price per share")
    s.num("B2", 4.85, "x2", "in")
    _hdr(s, 4, ["Holder", "Class", "Shares", "Invested (USD)", "Ownership", "Value @ round"])
    rows = [("Founder A", "Common", 5000000, 25000 + 4), ("Founder B", "Common", 3200000, 16000 + 9), ("Seed fund", "Preferred A", 1450000, 1450000 + 61),
            ("Angel syndicate", "Preferred A", 620000, 612480), ("Series A lead", "Preferred B", 2750000, 13337500 + 37), ("ESOP pool", "Options", 980000, 0)]
    total_sh = sum(r[2] for r in rows)
    for i, (h, cl, sh, inv) in enumerate(rows, start=5):
        s.text(f"A{i}", h)
        s.text(f"B{i}", cl)
        s.num(f"C{i}", sh, "int", "in")
        s.inp(f"D{i}", inv, "usd0")
    s.table("tblCap", "A4:F10")
    s.sf("E5:E10", "C5/$C$11", [r[2] / total_sh for r in rows], "pct")
    vals = [r[2] * 4.85 for r in rows]
    s.sf("F5:F10", "C5*$B$2", vals, "usd0", True)
    s.text("A11", "Total", font="b")
    s.fx("C11", "SUM(C5:C10)", total_sh, "int", "b")
    s.fx("D11", "SUM(D5:D10)", sum(r[3] for r in rows), "usd0", "b", True)
    s.fx("E11", "SUM(E5:E10)", 1.0, "pct", "b")
    s.fx("F11", "SUM(F5:F10)", sum(vals), "usd0", "b", True)
    s.text("A13", "Post-money valuation")
    s.fx("B13", "F11", sum(vals), '[$$-409]#,##0" (cap 38 750 000)"', money=True)
    b.secret(38750000)
    s.cf_scale("E5:E10", 0, 0.5, money=False)
    s.cf_cell("F5:F10", "greaterThan", 10000000, 1)
    s.dv_list("B5:B10", "Common,Preferred A,Preferred B,Options")
    s.dv_decimal("D5:D10", "lessThanOrEqual", 15000000, msg="Single-holder investment cap is USD 15 000 000")
    s.comment("D7", f"Includes SAFE note converted at the round, principal USD {en(410000 + 55)}", "Legal", (410055,))
    s.textbox(f"Post-money valuation: USD {en(38750000)}. Option pool refresh budget USD {en(1275000)}", (7, 3), (12, 8), (38750000, 1275000))
    b.name("PostMoney", "38750000", money=True)
    b.name("RoundPrice", f"{q('Cap Table')}!$B$2")
    t = b.sheet("Term sheet", "veryHidden")
    t.text("A1", f"Liquidation preference 1x on USD {en(6250000)}; participation cap USD {en(18750000)}")
    b.secret(6250000, 18750000)
    return b


def wb_payroll_register() -> Book:
    b = Book("Платёжная ведомость", "Лебедева К.А.", "ООО «Горизонт-Сервис»", "Ведомость (RU): таблица tblPayroll, НДФЛ shared, скрытая строка уволенного, комментарии с суммами, CF/DV на оклад.")
    s = b.sheet("Ведомость")
    s.width("A", 5)
    s.width("B", 30)
    s.width("C", 24)
    s.width("D:H", 15)
    s.text("A1", "Расчётная ведомость за март 2025", font="t")
    s.merge("A1:H1")
    _hdr(s, 4, ["№", "ФИО", "Должность", "Оклад", "Премия", "Начислено", "НДФЛ", "К выплате"])
    emp = [("Иванов Пётр Сергеевич", "Директор", 248600 + 17, 74580 + 3), ("Смирнова Анна Викторовна", "Главный бухгалтер", 132600 + 5, 26520 + 1),
           ("Кузнецов Дмитрий Олегович", "Руководитель отдела продаж", 156350 + 9, 93810 + 5), ("Попова Мария Игоревна", "Менеджер", 94250 + 3, 18850 + 7),
           ("Васильев Андрей Николаевич", "Инженер", 118900 + 11, 11890 + 9), ("Морозова Елена Павловна", "Юрист", 127400 + 2, 0),
           ("Орлов Сергей Анатольевич", "Водитель", 71300 + 6, 7130 + 4), ("Новикова Татьяна Юрьевна", "Секретарь", 58400 + 8, 5840 + 2)]
    for i, (n, p, sal, bon) in enumerate(emp, start=5):
        s.num(f"A{i}", i - 4)
        s.text(f"B{i}", n)
        s.text(f"C{i}", p)
        s.inp(f"D{i}", sal, "rub")
        s.inp(f"E{i}", bon, "rub")
    s.table("tblPayroll", "A4:H12")
    acc = [e[2] + e[3] for e in emp]
    ndfl = [round(a * 0.13) for a in acc]
    pay = [a - t for a, t in zip(acc, ndfl)]
    s.sf("F5:F12", "D5+E5", acc, "rub", True)
    s.sf("G5:G12", "ROUND(F5*NDFL,0)", ndfl, "rub", True)
    s.sf("H5:H12", "F5-G5", pay, "rub", True)
    s.text("B13", "ИТОГО", font="b")
    for c, v in zip("DEFGH", [sum(e[2] for e in emp), sum(e[3] for e in emp), sum(acc), sum(ndfl), sum(pay)]):
        s.fx(f"{c}13", f"SUM({c}5:{c}12)", v, "rub", "b", True)
    s.hide_row(10)
    s.cf_cell("D5:D12", "greaterThan", 150000, 1)
    s.cf_scale("H5:H12", 50000, 250000)
    s.dv_decimal("D5:D12", "lessThanOrEqual", 450000, msg=f"Оклад не должен превышать {ru(450000)} руб.")
    s.dv_list("C5:C12", "Директор,Главный бухгалтер,Менеджер,Инженер,Юрист,Водитель,Секретарь,Руководитель отдела продаж")
    s.comment("D6", f"Оклад повышен с {ru(118400)} до {ru(132605)} руб. с 01.03.2025 (приказ №14-К)", "Кадры", (118400,))
    s.comment("E7", f"Квартальная премия по KPI: {ru(93815)} руб.", "Кадры", ())
    s.textbox(f"Фонд оплаты труда утверждён: {ru(2310000)} руб. в месяц", (9, 3), (13, 8), (2310000,))
    b.name("NDFL", "0.13")
    b.name("ФОТ_лимит", "2310000", money=True)
    b.name("_Prev_Month_Total", "1982640", hidden=True, money=True)
    return b


def wb_kpi_dashboard() -> Book:
    b = Book("KPI dashboard H1", "Анна Борисова / Boris Ivanov", "Nordlicht Retail GmbH", "KPI dashboard (RU/EN): Data + Dashboard + hidden Calc, cross-sheet refs, str-formula, array, chart with caches and fixed axis, text box.")
    d = b.sheet("Data")
    d.width("A:E", 16)
    _hdr(d, 1, ["Month", "Revenue", "Costs"])
    mon = ["Янв / Jan", "Фев / Feb", "Мар / Mar", "Апр / Apr", "Май / May", "Июн / Jun"]
    rev = [10482350, 11237915, 12905680, 12116440, 13874205, 14952730]
    cost = [8213460, 8590330, 9348715, 9612080, 10127945, 10531880]
    for i in range(6):
        d.text(f"A{2 + i}", mon[i])
        d.inp(f"B{2 + i}", rev[i])
        d.inp(f"C{2 + i}", cost[i])
    d.dv_decimal("B2:C7", "greaterThan", 0, msg="Value must be positive")
    s = b.sheet("Dashboard")
    s.width("A", 22)
    s.width("B:F", 16)
    s.text("A1", "KPI dashboard — H1 2025", font="t")
    s.merge("A1:F1")
    _hdr(s, 3, ["Month", "Revenue", "Costs", "Margin", "Margin %"])
    marg = [r - c for r, c in zip(rev, cost)]
    for i in range(6):
        r = 4 + i
        s.fx(f"A{r}", f"Data!A{2 + i}", mon[i])
        s.fx(f"B{r}", f"Data!B{2 + i}", rev[i], "rub", money=True)
        s.fx(f"C{r}", f"Data!C{2 + i}", cost[i], "rub", money=True)
    s.sf("D4:D9", "B4-C4", marg, "rub", True)
    s.sf("E4:E9", "D4/B4", [m / r for m, r in zip(marg, rev)], "pct")
    s.text("A11", "Total revenue")
    s.fx("B11", "SUM(B4:B9)", sum(rev), "rub", "b", True)
    s.text("A12", "Average margin")
    s.fx("B12", "AVERAGE(D4:D9)", sum(marg) / 6, "rub", money=True)
    s.text("A13", "Total margin (array)")
    s.arr("B13", "SUM(B4:B9-C4:C9)", sum(marg), "rub", True)
    best = mon[marg.index(max(marg))]
    s.text("A14", "Best month")
    s.fx("B14", "INDEX(A4:A9,MATCH(MAX(D4:D9),D4:D9,0))", best)
    s.text("A15", "vs target")
    s.fx("B15", "B11-Target", sum(rev) - 70000000, '#,##0" (план 70 000 000)"', money=True)
    b.secret(70000000)
    s.cf_cell("D4:D9", "lessThan", 3000000, 0)
    s.cf_scale("E4:E9", 0.1, 0.35, money=False)
    s.dv_list("G4", "3100000,3200000", (3100000, 3200000))
    s.comment("B9", f"Рекорд полугодия: {ru(14952730)} руб. Целевой показатель на июль {ru(15500000)}", "Аналитик", (15500000,))
    s.textbox(f"Target H1 revenue: RUB {en(70000000)}; stretch {en(76500000)}", (7, 2), (12, 6), (76500000,))
    s.chart((0, 16), (7, 33), f"Выручка и затраты (лимит оси {ru(16000000)})", "A4:A9", [("B3", "B4:B9"), ("C3", "C4:C9")], axis_max=16000000, axis_min=0, secrets=(16000000,))
    b.name("Target", "70000000", money=True)
    b.name("Revenue", f"{q('Data')}!$B$2:$B$7")
    b.name("_calc_flag", "1", hidden=True)
    c = b.sheet("Calc", "hidden")
    c.text("A1", "Internal growth factor")
    c.num("B1", 1.05, "x2")
    c.text("A2", "Stretch revenue")
    c.fx("B2", "Dashboard!B11*Calc!B1", sum(rev) * 1.05, "rub", money=True)
    return b


def wb_consolidated() -> Book:
    b = Book("Консолидация 2024", "Group Finance", "Северный холдинг / Nordic Holding", "Консолидация (RU/EN): Sub A (RUB), Sub B (EUR), Elim, Consolidated; межлистовые ссылки, имена на ячейки, shared по столбцу.")
    sa = b.sheet("Sub A (RUB)")
    sb = b.sheet("Sub B (EUR)")
    el = b.sheet("Elim")
    co = b.sheet("Consolidated")
    for sh in (sa, sb, el, co):
        sh.width("A", 30)
        sh.width("B:D", 18)
    labels = ["Revenue / Выручка", "COGS / Себестоимость", "Opex / Операционные расходы", "Interest / Проценты", "Tax / Налог"]
    A = [48215360, 29718045, 6841290, 1127415, 2326118]
    B = [3126480, 1904215, 418670, 63915, 148372]
    E = [1250000 + 335, 1250000 + 335, 0, 0, 0]
    FX = 97.4
    sa.text("A1", "Subsidiary A, RUB", font="t")
    sb.text("A1", "Subsidiary B, EUR", font="t")
    el.text("A1", "Intercompany eliminations, RUB", font="t")
    co.text("A1", "Consolidated P&L, RUB", font="t")
    co.merge("A1:C1")
    for sh in (sa, sb, el, co):
        _hdr(sh, 2, ["Line", "FY2024"])
    for i, t in enumerate(labels):
        r = 3 + i
        for sh in (sa, sb, el, co):
            sh.text(f"A{r}", t)
        sa.inp(f"B{r}", A[i], "rub")
        sb.inp(f"B{r}", B[i], "eur")
        el.inp(f"B{r}", E[i], "rub") if E[i] else el.num(f"B{r}", 0, "rub")
    cons = [round(a + bb * FX - e, 2) for a, bb, e in zip(A, B, E)]
    co.sf("B3:B7", "'Sub A (RUB)'!B3+'Sub B (EUR)'!B3*EURRUB-Elim!B3", cons, "rub2", True)
    co.text("A8", "Net result", font="b")
    nr = cons[0] - cons[1] - cons[2] - cons[3] - cons[4]
    co.fx("B8", "B3-B4-B5-B6-B7", nr, "rub2", "b", True)
    co.text("A10", "EUR/RUB rate")
    co.num("B10", FX, "x2", "in")
    co.text("A11", "Share of Sub B in revenue")
    co.fx("B11", "'Sub B (EUR)'!B3*EURRUB/B3", B[0] * FX / cons[0], "pct")
    co.text("A12", "Sub A revenue (name)")
    co.fx("B12", "SubA_Revenue", A[0], "rub", money=True)
    co.hide_row(9)
    co.table("tblConsol", "A2:B7")
    co.cf_cell("B8", "lessThan", 5000000, 0)
    co.cf_scale("B3:B7", 1000000, 50000000)
    co.dv_decimal("B10", "between", 60, 130, "Rate range 60-130 RUB per EUR", money=False)
    co.dv_list("C3", "3100000,3200000", (3100000, 3200000))
    co.comment("B8", f"Без учёта резерва {ru(2480000)} руб. по судебному спору", "Group Finance", (2480000,))
    co.textbox(f"Целевой консолидированный результат: {ru(9600000)} руб.", (4, 2), (9, 7), (9600000,))
    sa.comment("B5", f"Включая единовременный платёж {ru(1050000 + 90)} руб.", "Sub A CFO", (1050090,))
    b.name("EURRUB", "Consolidated!$B$10")
    b.name("SubA_Revenue", f"{q('Sub A (RUB)')}!$B$3")
    b.name("Elim_Cap", "1250335", money=True)
    b.name("_old_rate", "93.1", hidden=True)
    mp = b.sheet("Mapping", "veryHidden")
    mp.text("A1", "Счёт 90.1 → Revenue; лимит интеркомпани")
    mp.inp("B1", 3875420)
    return b


BUILDERS = {
    "pl_quarterly_ru": wb_pl_quarterly, "balance_sheet_ru": wb_balance_sheet, "cash_flow_en": wb_cash_flow, "cash_forecast_13w": wb_cash_forecast_13w,
    "budget_vs_actual": wb_budget_vs_actual, "dcf_npv_en": wb_dcf_npv, "loan_amortization_ru": wb_loan_amortization, "cap_table_en": wb_cap_table,
    "payroll_register_ru": wb_payroll_register, "kpi_dashboard": wb_kpi_dashboard, "consolidated_multisheet": wb_consolidated,
}


def build_all() -> dict[str, dict]:
    return {name: fn().result() for name, fn in BUILDERS.items()}


def _verify(name: str, r: dict):
    from openpyxl import load_workbook
    for data_only in (False, True):
        wb = load_workbook(io.BytesIO(r["bytes"]), data_only=data_only)
        assert wb.sheetnames, name
    with zipfile.ZipFile(io.BytesIO(r["bytes"])) as z:
        assert z.testzip() is None
        names = z.namelist()
    return names


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    for nm, res in build_all().items():
        parts = _verify(nm, res)
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{nm}.xlsx").write_bytes(res["bytes"])
        print(f"{nm}: {len(res['bytes'])} bytes, {len(parts)} parts, {len(res['secrets'])} secrets, {len(res['money_cells'])} inputs")
