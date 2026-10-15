"""Аудит 08.10: атрибуты и теги Word/Excel/PowerPoint, которые раньше пропускались (элементы управления, свойства таблицы,
переменные документа, VML, подсказки гиперссылок, комментарии XML)."""
from __future__ import annotations

import io
import unittest
import zipfile

from tests.helpers import Env, docx_bytes, pptx_bytes, zip_text

SECRETS = ("Смирнов", "romashka")


def patch(data: bytes, part: str, fn) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            raw = src.read(item.filename)
            if item.filename == part:
                raw = fn(raw.decode("utf-8")).encode("utf-8")
            z.writestr(item, raw)
    return out.getvalue()


class Ooxml2(unittest.TestCase):
    def run_file(self, name, data):
        env = Env(); self.addCleanup(env.close)
        job = env.anonymize((name, data))
        f = job.files[0]
        self.assertTrue(f.out_path, [m for m in f.messages])
        return env, job, env.output_bytes(job)

    def assertNoSecret(self, out):
        text = zip_text(out)
        for s in SECRETS:
            self.assertNotIn(s, text)

    def test_docx_attributes(self):
        W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        extra = ('<w:p><w:r><w:t>Служебный текст о проекте</w:t></w:r></w:p>'
                 '<w:sdt><w:sdtPr><w:dropDownList><w:listItem w:displayText="Смирнов Алексей Петрович" w:value="ivan@romashka.ru"/>'
                 '</w:dropDownList></w:sdtPr><w:sdtContent><w:r><w:t>x</w:t></w:r></w:sdtContent></w:sdt>'
                 '<w:tbl><w:tblPr><w:tblCaption w:val="Смирнов Алексей Петрович"/><w:tblDescription w:val="ivan@romashka.ru"/></w:tblPr>'
                 '<w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>'
                 '<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:helpText w:type="text" w:val="Смирнов Алексей Петрович"/>'
                 '<w:statusText w:type="text" w:val="ivan@romashka.ru"/></w:ffData></w:fldChar></w:r>')
        data = patch(docx_bytes(["Тело"]), "word/document.xml", lambda x: x.replace("<w:sectPr", extra + "<w:sectPr", 1))
        data = patch(data, "word/settings.xml", lambda x: x.replace(
            "</w:settings>", '<w:docVars><w:docVar w:name="c" w:val="Смирнов Алексей Петрович, ivan@romashka.ru"/></w:docVars></w:settings>'))
        _, _, out = self.run_file("a.docx", data)
        self.assertNoSecret(out)

    def test_xml_comment_does_not_fail_file(self):
        data = patch(docx_bytes(["Смирнов Алексей Петрович"]), "word/document.xml",
                     lambda x: x.replace("<w:body>", "<w:body><!-- ivan@romashka.ru -->", 1))
        _, _, out = self.run_file("a.docx", data)
        self.assertNoSecret(out)

    def test_pptx_hyperlink_tooltip(self):
        data = pptx_bytes(["Привет"])
        name = [n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("ppt/slides/slide")][0]
        data = patch(data, name, lambda x: x.replace("<a:r>", '<a:r><a:rPr><a:hlinkClick r:id="" tooltip="Смирнов Алексей Петрович"/></a:rPr>', 1)
                     if "xmlns:r=" in x else x)
        _, _, out = self.run_file("a.pptx", data)
        self.assertNoSecret(out)


if __name__ == "__main__":
    unittest.main()
