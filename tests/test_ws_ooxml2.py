"""OOXML leak closure: real output archives are unzipped and every part is grepped for each original sensitive value
(utf-8 and utf-16, nested archives included); restore must give the original text back."""
from __future__ import annotations

import io
import unittest
import zipfile

from openpyxl import Workbook

from tests.helpers import Env, docx_bytes, pptx_bytes, xlsx_bytes

NAME = "Лебедев Тимофей Андреевич"
SURNAME = "Лебедев"
ORG = "Вектор-Пром"
INN = "770708389312"
MAIL = "lebedev@vektor-prom.ru"
WORD_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SS_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = {
    "xml": "application/xml",
}


def rebuild(data: bytes, parts: dict[str, bytes | None] | None = None, rels: dict[str, str] | None = None,
            overrides: dict[str, str] | None = None, edit: dict | None = None) -> bytes:
    """Copy of the package with extra/replaced parts, extra relationships and content-type overrides.
    `edit` maps part name -> function(bytes) -> bytes."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        seen = set()
        for item in src.infolist():
            name = item.filename
            raw = src.read(name)
            seen.add(name)
            if parts and name in parts:
                if parts[name] is None:
                    continue
                raw = parts[name]
            if edit and name in edit:
                raw = edit[name](raw)
            if rels and name in rels:
                raw = raw.decode("utf-8").replace("</Relationships>", rels[name] + "</Relationships>").encode()
            if name == "[Content_Types].xml":
                extra = "".join(f'<Override PartName="/{p}" ContentType="{c}"/>' for p, c in (overrides or {}).items())
                extra += '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>' \
                    if b'Extension="vml"' not in raw else ""
                raw = raw.decode("utf-8").replace("</Types>", extra + "</Types>").encode()
            z.writestr(item, raw)
        for name, raw in (parts or {}).items():
            if name not in seen and raw is not None:
                z.writestr(name, raw)
        for name, raw in (rels or {}).items():
            if name not in seen:
                z.writestr(name, ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
                                  'openxmlformats.org/package/2006/relationships">' + raw + "</Relationships>").encode())
    return out.getvalue()


def rel(rid: str, kind: str, target: str, mode: str = "") -> str:
    return f'<Relationship Id="{rid}" Type="{REL_NS}/{kind}" Target="{target}"{mode}/>'


def blobs(data: bytes, prefix: str = "") -> dict[str, bytes]:
    """Every part of the archive, recursing into nested zips."""
    result: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            raw = z.read(n)
            if raw[:4] == b"PK\x03\x04":
                result.update(blobs(raw, prefix + n + "!"))
            else:
                result[prefix + n] = raw
    return result


def leaks(data: bytes, values) -> list[str]:
    found = []
    for part, raw in blobs(data).items():
        for v in values:
            if v.encode("utf-8") in raw or v.encode("utf-16-le") in raw or v.encode("utf-16-be") in raw:
                found.append(f"{part}: {v}")
        # names are matched in the part name itself too
        for v in values:
            if v in part:
                found.append(f"part name {part}: {v}")
    return found


def blob_text(data: bytes) -> str:
    return "\n".join(r.decode("utf-8", "ignore") for r in blobs(data).values())


class Base(unittest.TestCase):
    VALUES = (SURNAME, "Тимофей", "Андреевич", ORG, INN, MAIL, "vektor-prom")

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def run_file(self, data: bytes, name: str, values=None, restore_check=True):
        job = self.env.anonymize((name, data))
        f = job.files[0]
        self.assertTrue(f.out_path, list(f.messages))
        out = self.env.output_bytes(job)
        found = leaks(out, values or self.VALUES)
        self.assertEqual(found, [], list(f.messages))
        back = None
        if restore_check:
            back = self.env.restore(self.env.as_upload(job, name=name))
            self.assertTrue(back.files[0].out_path, list(back.files[0].messages))
        return job, out, back


def base_xlsx() -> bytes:
    return xlsx_bytes({"A1": f"Контрагент {NAME}", "A2": f"ООО «{ORG}», ИНН {INN}", "A3": MAIL})


def base_docx() -> bytes:
    return docx_bytes([f"Договор с {NAME}, ООО «{ORG}», ИНН {INN}, {MAIL}"])


def base_pptx() -> bytes:
    return pptx_bytes([f"Контрагент {NAME}, ООО «{ORG}», {MAIL}"])


class XlsxParts(Base):
    def test_external_link(self):
        link = (f'<?xml version="1.0" encoding="UTF-8"?><externalLink {SS_NS}><externalBook xmlns:r="{REL_NS}" r:id="rId1">'
                f'<sheetNames><sheetName val="Контрагенты {SURNAME}"/></sheetNames><sheetDataSet><sheetData sheetId="0">'
                f'<row r="1"><cell r="A1" t="str"><v>{NAME}</v></cell><cell r="B1" t="str"><v>ООО «{ORG}»</v></cell></row>'
                f'</sheetData></sheetDataSet></externalBook></externalLink>').encode()
        data = rebuild(base_xlsx(), {"xl/externalLinks/externalLink1.xml": link,
                                     "xl/externalLinks/_rels/externalLink1.xml.rels": (
                                         '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                                         'package/2006/relationships">' + rel("rId1", "externalLinkPath",
                                         f"file:///C:/Users/{SURNAME}/Desktop/{ORG}/книга.xlsx", ' TargetMode="External"')
                                         + "</Relationships>").encode()},
                       {"xl/_rels/workbook.xml.rels": rel("rIdX1", "externalLink", "externalLinks/externalLink1.xml")},
                       {"xl/externalLinks/externalLink1.xml":
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml"})
        self.run_file(data, "a.xlsx")

    def test_connections(self):
        conn = (f'<?xml version="1.0" encoding="UTF-8"?><connections {SS_NS}><connection id="1" name="Подключение {SURNAME}" '
                f'description="Выгрузка {NAME}" type="1"><dbPr connection="Provider=SQLOLEDB;Data Source=srv-{ORG};User ID={SURNAME};'
                f'Password=Zq9x-secret" command="SELECT * FROM клиенты WHERE фио=\'{NAME}\'"/></connection></connections>').encode()
        data = rebuild(base_xlsx(), {"xl/connections.xml": conn},
                       {"xl/_rels/workbook.xml.rels": rel("rIdX2", "connections", "connections.xml")},
                       {"xl/connections.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.connections+xml"})
        self.run_file(data, "a.xlsx", self.VALUES + ("Zq9x-secret",))

    def test_pivot_cache(self):
        pc = (f'<?xml version="1.0" encoding="UTF-8"?><pivotCacheDefinition {SS_NS} refreshedBy="{NAME}" '
              f'refreshedDate="45000" recordCount="1"><cacheSource type="worksheet"><worksheetSource ref="A1:A2" sheet="Лист1"/>'
              f'</cacheSource><cacheFields count="1"><cacheField name="Клиент {SURNAME}" numFmtId="0"><sharedItems count="2">'
              f'<s v="{NAME}"/><s v="ООО «{ORG}»"/></sharedItems></cacheField></cacheFields></pivotCacheDefinition>').encode()
        data = rebuild(base_xlsx(), {"xl/pivotCache/pivotCacheDefinition1.xml": pc},
                       {"xl/_rels/workbook.xml.rels": rel("rIdX3", "pivotCacheDefinition",
                                                          "pivotCache/pivotCacheDefinition1.xml")},
                       {"xl/pivotCache/pivotCacheDefinition1.xml":
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"})
        self.run_file(data, "a.xlsx")

    def test_numfmt_cellstyle_autofilter(self):
        def styles(raw):
            s = raw.decode("utf-8")
            s = s.replace("<fonts", f'<numFmts count="2"><numFmt numFmtId="170" formatCode="0 &quot;руб. {ORG}&quot;"/>'
                                    f'<numFmt numFmtId="171" formatCode="[Red]0.00&quot; {SURNAME}&quot;"/></numFmts><fonts', 1)
            s = s.replace("</cellStyles>", f'<cellStyle name="Стиль {SURNAME}" xfId="0"/></cellStyles>', 1)
            return s.encode()

        def sheet(raw):
            s = raw.decode("utf-8")
            return s.replace("</sheetData>", f'</sheetData><autoFilter ref="A1:A3"><filterColumn colId="0"><filters>'
                             f'<filter val="{NAME}"/></filters></filterColumn><filterColumn colId="1"><customFilters>'
                             f'<customFilter operator="equal" val="*{ORG}*"/></customFilters></filterColumn></autoFilter>',
                             1).encode()
        data = rebuild(base_xlsx(), edit={"xl/styles.xml": styles, "xl/worksheets/sheet1.xml": sheet})
        self.run_file(data, "a.xlsx")

    def test_vml_and_comment_authors(self):
        wb = Workbook()
        ws = wb.active
        ws["A1"] = f"Контрагент {NAME}"
        from openpyxl.comments import Comment
        ws["A1"].comment = Comment(f"Проверить {NAME}", NAME)
        buf = io.BytesIO(); wb.save(buf)
        data = buf.getvalue()
        vml = (f'<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
               f'<v:shape id="s1" alt="Подпись {NAME}" o:title="{ORG}"><v:textpath string="КОНФИДЕНЦИАЛЬНО {ORG} {SURNAME}"/>'
               f'<v:textbox><div>{NAME} {MAIL}</div></v:textbox></v:shape></xml>').encode()
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        vml_name = next((n for n in names if n.endswith(".vml")), "xl/drawings/extra.vml")
        data = rebuild(data, {vml_name: vml} if vml_name == "xl/drawings/extra.vml" else {vml_name: vml})
        self.run_file(data, "a.xlsx")

    def test_cached_formula_string(self):
        def sheet(raw):
            s = raw.decode("utf-8")
            cell = (f'<c r="D1" t="str"><f>A1&amp;" "&amp;A2</f><v>{NAME} {ORG}</v></c>'
                    f'<c r="D2" t="str"><f>IF(1,"{NAME}","x")</f><v>{NAME}</v></c>')
            return s.replace("</row>", cell + "</row>", 1).encode()
        data = rebuild(base_xlsx(), edit={"xl/worksheets/sheet1.xml": sheet})
        self.run_file(data, "a.xlsx")

    def test_docprops(self):
        core = (f'<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/'
                f'2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/'
                f'terms/"><dc:title>Отчёт для {ORG}</dc:title><dc:creator>{NAME}</dc:creator><cp:lastModifiedBy>{NAME}'
                f'</cp:lastModifiedBy><dc:subject>{SURNAME}</dc:subject><cp:keywords>{ORG}</cp:keywords></cp:coreProperties>').encode()
        custom = (f'<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
                  f'2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                  f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="Клиент {SURNAME}"><vt:lpwstr>{NAME}'
                  f'</vt:lpwstr></property></Properties>').encode()
        app = (f'<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
               f'extended-properties"><Company>{ORG}</Company><Manager>{NAME}</Manager></Properties>').encode()
        data = rebuild(base_xlsx(), {"docProps/core.xml": core, "docProps/custom.xml": custom, "docProps/app.xml": app},
                       {"_rels/.rels": rel("rIdC", "custom-properties", "docProps/custom.xml")},
                       {"docProps/custom.xml": "application/vnd.openxmlformats-officedocument.custom-properties+xml"})
        self.run_file(data, "a.xlsx")

    def test_threaded_comments_persons(self):
        persons = (f'<?xml version="1.0" encoding="UTF-8"?><personList xmlns="http://schemas.microsoft.com/office/spreadsheetml/'
                   f'2018/threadedcomments"><person displayName="{NAME}" id="{{1}}" userId="{MAIL}" providerId="None"/></personList>').encode()
        data = rebuild(base_xlsx(), {"xl/persons/person.xml": persons})
        self.run_file(data, "a.xlsx")


class DocxParts(Base):
    def test_glossary_ffdata_sdt_placeholder(self):
        glossary = (f'<?xml version="1.0" encoding="UTF-8"?><w:glossaryDocument {WORD_NS}><w:docParts><w:docPart><w:docPartPr>'
                    f'<w:name w:val="Блок {NAME}"/><w:category><w:name w:val="General"/><w:gallery w:val="placeholder"/></w:category>'
                    f'<w:description w:val="Автор {SURNAME}"/></w:docPartPr><w:docPartBody><w:p><w:r><w:t>{NAME} {MAIL}</w:t></w:r>'
                    f'</w:p></w:docPartBody></w:docPart></w:docParts></w:glossaryDocument>').encode()

        def body(raw):
            s = raw.decode("utf-8")
            extra = (f'<w:p><w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Поле {SURNAME}"/>'
                     f'<w:helpText w:type="text" w:val="Введите {NAME}"/><w:statusText w:type="text" w:val="{ORG}"/>'
                     f'<w:textInput><w:default w:val="{NAME}"/></w:textInput></w:ffData></w:fldChar></w:r></w:p>'
                     f'<w:sdt><w:sdtPr><w:alias w:val="{NAME}"/><w:tag w:val="{ORG}"/><w:placeholder><w:docPart w:val="Блок {NAME}"/>'
                     f'</w:placeholder><w:showingPlcHdr/><w:text/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>{NAME}</w:t></w:r></w:p>'
                     f'</w:sdtContent></w:sdt>')
            return s.replace("<w:sectPr", extra + "<w:sectPr", 1).encode()
        data = rebuild(base_docx(), {"word/glossary/document.xml": glossary}, {"word/_rels/document.xml.rels":
                       rel("rIdG", "glossaryDocument", "glossary/document.xml")},
                       {"word/glossary/document.xml":
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml"},
                       edit={"word/document.xml": body})
        self.run_file(data, "a.docx")

    def test_comments_revisions_authors(self):
        comments = (f'<?xml version="1.0" encoding="UTF-8"?><w:comments {WORD_NS}><w:comment w:id="0" w:author="{NAME}" '
                    f'w:initials="ЛТА" w:date="2024-01-01T00:00:00Z"><w:p><w:r><w:t>Проверить {ORG}</w:t></w:r></w:p></w:comment>'
                    f'</w:comments>').encode()

        def body(raw):
            s = raw.decode("utf-8")
            extra = (f'<w:p><w:ins w:id="5" w:author="{NAME}" w:date="2024-01-01T00:00:00Z"><w:r><w:t xml:space="preserve">добавлено </w:t></w:r></w:ins>'
                     f'<w:del w:id="6" w:author="{MAIL}" w:date="2024-01-01T00:00:00Z"><w:r><w:delText>{ORG}</w:delText></w:r></w:del>'
                     f'<w:commentRangeStart w:id="0"/><w:r><w:t xml:space="preserve"> x</w:t></w:r><w:commentRangeEnd w:id="0"/></w:p>')
            return s.replace("<w:sectPr", extra + "<w:sectPr", 1).encode()
        data = rebuild(base_docx(), {"word/comments.xml": comments}, {"word/_rels/document.xml.rels":
                       rel("rIdCm", "comments", "comments.xml")},
                       {"word/comments.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"},
                       edit={"word/document.xml": body})
        self.run_file(data, "a.docx")

    def test_vml_textpath_alt_header(self):
        def body(raw):
            s = raw.decode("utf-8")
            extra = (f'<w:p><w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:'
                     f'office:office" id="w1" alt="Печать {NAME}" o:title="{ORG}"><v:textpath string="КОНФИДЕНЦИАЛЬНО {ORG} {SURNAME}"/>'
                     f'</v:shape></w:pict></w:r></w:p>')
            return s.replace("<w:sectPr", extra + "<w:sectPr", 1).encode()
        data = rebuild(base_docx(), edit={"word/document.xml": body})
        self.run_file(data, "a.docx")

    def test_docprops_thumbnail(self):
        core = (f'<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/'
                f'2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Для {ORG}</dc:title>'
                f'<dc:creator>{NAME}</dc:creator><cp:lastModifiedBy>{NAME}</cp:lastModifiedBy></cp:coreProperties>').encode()
        custom = (f'<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
                  f'2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                  f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="Клиент"><vt:lpwstr>{NAME}'
                  f'</vt:lpwstr></property></Properties>').encode()
        png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        data = rebuild(base_docx(), {"docProps/core.xml": core, "docProps/custom.xml": custom,
                                     "docProps/thumbnail.png": png},
                       {"_rels/.rels": rel("rIdC", "custom-properties", "docProps/custom.xml")
                        + '<Relationship Id="rIdT" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
                          'thumbnail" Target="docProps/thumbnail.png"/>'},
                       {"docProps/custom.xml": "application/vnd.openxmlformats-officedocument.custom-properties+xml"})
        job, out, _ = self.run_file(data, "a.docx")
        self.assertNotIn("docProps/thumbnail.png", blobs(out))

    def test_zwsp_and_soft_hyphen_names(self):
        for glue in ("\u200b", "\u00ad", "\u2060", "\u200c"):
            with self.subTest(glue=repr(glue)):
                name = f"Леб{glue}едев Тимо{glue}фей Андреевич"
                data = docx_bytes([f"Подписант: {name}. ООО «{ORG}»", f"{NAME}"])
                job = self.env.anonymize(("a.docx", data))
                out = self.env.output_bytes(job)
                text = blob_text(out)
                self.assertNotIn("едев", text.replace("Лебедев", "едев"))
                for frag in ("Леб", "Тимо", "Андреевич", "Тимофей", "едев"):
                    self.assertNotIn(frag, text, frag)


class PptxParts(Base):
    def test_tags_custshow_comment_authors(self):
        tag = (f'<?xml version="1.0" encoding="UTF-8"?><p:tagLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/'
               f'main"><p:tag name="CLIENT" val="{ORG}, {NAME}"/><p:tag name="MAIL" val="{MAIL}"/></p:tagLst>').encode()
        authors = (f'<?xml version="1.0" encoding="UTF-8"?><p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/'
                   f'presentationml/2006/main"><p:cmAuthor id="0" name="{NAME}" initials="ЛТА" lastIdx="1" clrIdx="0"/>'
                   f'</p:cmAuthorLst>').encode()
        comments = (f'<?xml version="1.0" encoding="UTF-8"?><p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/'
                    f'2006/main"><p:cm authorId="0" dt="2024-01-01T00:00:00.000" idx="1"><p:pos x="10" y="10"/><p:text>Позвонить '
                    f'{NAME} по {MAIL}</p:text></p:cm></p:cmLst>').encode()

        def pres(raw):
            s = raw.decode("utf-8")
            return s.replace("</p:presentation>", f'<p:custShowLst><p:custShow name="Показ для {SURNAME}" id="0"><p:sldLst/>'
                             f'</p:custShow></p:custShowLst></p:presentation>', 1).encode() if "custShowLst" not in s else raw
        data = rebuild(base_pptx(), {"ppt/tags/tag1.xml": tag, "ppt/commentAuthors.xml": authors,
                                     "ppt/comments/comment1.xml": comments},
                       {"ppt/_rels/presentation.xml.rels": rel("rIdTg", "tags", "tags/tag1.xml")
                        + rel("rIdCa", "commentAuthors", "commentAuthors.xml"),
                        "ppt/slides/_rels/slide1.xml.rels": rel("rIdCm", "comments", "../comments/comment1.xml")},
                       {"ppt/tags/tag1.xml": "application/vnd.openxmlformats-officedocument.presentationml.tags+xml",
                        "ppt/commentAuthors.xml": "application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml",
                        "ppt/comments/comment1.xml": "application/vnd.openxmlformats-officedocument.presentationml.comments+xml"},
                       edit={"ppt/presentation.xml": pres})
        self.run_file(data, "a.pptx")


class Embedded(Base):
    def test_embedded_xlsx_in_docx(self):
        inner = xlsx_bytes({"A1": NAME, "A2": f"ИНН {INN}", "A3": MAIL, "A4": f"ООО «{ORG}»"})
        data = rebuild(base_docx(), {"word/embeddings/Microsoft_Excel_Sheet1.xlsx": inner},
                       {"word/_rels/document.xml.rels": rel("rIdE", "package", "embeddings/Microsoft_Excel_Sheet1.xlsx")},
                       {"word/embeddings/Microsoft_Excel_Sheet1.xlsx":
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        self.run_file(data, "a.docx")

    def test_embedded_docx_in_pptx(self):
        inner = docx_bytes([f"{NAME} {MAIL}", f"ИНН {INN}"], author=NAME)
        data = rebuild(base_pptx(), {"ppt/embeddings/Microsoft_Word_Document1.docx": inner},
                       {"ppt/slides/_rels/slide1.xml.rels": rel("rIdE", "package", "../embeddings/Microsoft_Word_Document1.docx")},
                       {"ppt/embeddings/Microsoft_Word_Document1.docx":
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})
        self.run_file(data, "a.pptx")

    def test_embedded_inside_nested_zip(self):
        inner = xlsx_bytes({"A1": NAME, "A2": f"ИНН {INN}"})
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w") as z:
            z.writestr("inner.xlsx", inner)
            z.writestr("note.txt", f"{NAME} {MAIL}")
        data = rebuild(base_docx(), {"word/embeddings/pack.zip": zbuf.getvalue()},
                       {"word/_rels/document.xml.rels": rel("rIdZ", "package", "embeddings/pack.zip")})
        job = self.env.anonymize(("a.docx", data))
        f = job.files[0]
        if f.out_path:
            self.assertEqual(leaks(self.env.output_bytes(job), self.VALUES), [], list(f.messages))


class SmartArt(Base):
    def test_restore_no_false_data1_warning(self):
        diagram = (f'<?xml version="1.0" encoding="UTF-8"?><dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/'
                   f'2006/diagram" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dgm:ptLst><dgm:pt modelId="1">'
                   f'<dgm:t><a:p><a:r><a:t>{NAME}</a:t></a:r></a:p></dgm:t></dgm:pt></dgm:ptLst></dgm:dataModel>').encode()
        data = rebuild(base_docx(), {"word/diagrams/data1.xml": diagram},
                       {"word/_rels/document.xml.rels": rel("rIdD", "diagramData", "diagrams/data1.xml")},
                       {"word/diagrams/data1.xml": "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml"})
        job, out, back = self.run_file(data, "a.docx")
        msgs = " ".join(str(m) for m in back.files[0].messages)
        self.assertNotIn("Data1", msgs)
        self.assertEqual(str(back.files[0].status.value if hasattr(back.files[0].status, "value") else back.files[0].status)
                         .lower().count("attention"), 0, msgs)


class XmlBareId(Base):
    def test_bare_inn_in_named_element(self):
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><client><name>{NAME}</name><inn>{INN}</inn>'
               f'<contact inn="500100732259" passport="4512345678"/><kpp>770701001</kpp></client>')
        job = self.env.anonymize(("c.xml", xml))
        out = self.env.output_bytes(job).decode("utf-8")
        for v in (INN, "500100732259", "4512345678", "770701001"):
            self.assertNotIn(v, out)
        back = self.env.restore(self.env.as_upload(job, name="c.xml"))
        self.assertEqual(self.env.output_bytes(back).decode("utf-8"), xml)


if __name__ == "__main__":
    unittest.main()
