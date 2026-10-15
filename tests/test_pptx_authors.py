"""PowerPoint: авторы примечаний (ppt/authors.xml, commentAuthors.xml) и тексты примечаний не оставляют имени в файле."""
import unittest

from .helpers import Env, pptx_bytes, zip_text
from .test_round3_containers import add_parts, rezip

SEC = "Смирнов Алексей Петрович"
MAIL = "smirnov.a@romashka.ru"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
P188 = "http://schemas.microsoft.com/office/powerpoint/2018/8/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
GUID = "{11111111-2222-3333-4444-555555555555}"

AUTHORS = (f'{HEAD}<p188:authorLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="{REL}" '
           f'xmlns:p188="{P188}"><p188:author id="{GUID}" name="{SEC}" initials="СА" '
           f'userId="S::{MAIL}::aaaa" providerId="AD"/></p188:authorLst>')
MODERN = (f'{HEAD}<p188:cmLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="{REL}" '
          f'xmlns:p188="{P188}"><p188:cm id="{{AAAAAAAA-2222-3333-4444-555555555555}}" '
          f'authorId="{GUID}" created="2024-01-01T00:00:00.000">'
          f'<p188:txBody><a:bodyPr/><a:p><a:r><a:t>Проверить с {SEC}</a:t></a:r></a:p></p188:txBody></p188:cm></p188:cmLst>')
LEGACY_AUTHORS = (f'{HEAD}<p:cmAuthorLst xmlns:p="{P}"><p:cmAuthor id="0" name="{SEC}" initials="СА" lastIdx="1" clrIdx="0"/></p:cmAuthorLst>')
LEGACY = (f'{HEAD}<p:cmLst xmlns:p="{P}"><p:cm authorId="0" dt="2020-01-01T00:00:00.000" idx="1"><p:pos x="10" y="10"/>'
          f'<p:text>Комментарий {SEC}</p:text></p:cm></p:cmLst>')


def fixture() -> bytes:
    data = pptx_bytes(["Итоги квартала"])

    def change(name, raw):
        if name not in ("[Content_Types].xml", "ppt/_rels/presentation.xml.rels"):
            return raw
        text = raw.decode("utf-8")
        if name == "[Content_Types].xml":
            ov = ('<Override PartName="/ppt/authors.xml" ContentType="application/vnd.ms-powerpoint.authors+xml"/>'
                  '<Override PartName="/ppt/commentAuthors.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml"/>')
            return text.replace("</Types>", ov + "</Types>").encode()
        if name == "ppt/_rels/presentation.xml.rels":
            rel = ('<Relationship Id="rIdAu1" Type="http://schemas.microsoft.com/office/2018/10/relationships/authors" Target="authors.xml"/>'
                   f'<Relationship Id="rIdAu2" Type="{REL}/commentAuthors" Target="commentAuthors.xml"/>')
            return text.replace("</Relationships>", rel + "</Relationships>").encode()
        return raw
    data = rezip(data, change)
    return add_parts(data, {"ppt/authors.xml": AUTHORS.encode(), "ppt/commentAuthors.xml": LEGACY_AUTHORS.encode(),
                            "ppt/comments/modernComment_100_1.xml": MODERN.encode(), "ppt/comments/comment1.xml": LEGACY.encode()})


class PptxCommentAuthors(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.data = fixture()

    def test_fixture_really_contains_the_name(self):
        text = zip_text(self.data)
        self.assertIn(f'name="{SEC}"', text)
        self.assertIn('initials="СА"', text)

    def test_no_original_remains_in_any_part_and_restore_round_trips(self):
        job = self.env.anonymize(("c.pptx", self.data))
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(self.env.output_bytes(job))) as z:
            for part in z.namelist():
                raw = z.read(part).decode("utf-8", "ignore")
                for needle in ("Смирнов", "Алексей", "Петрович", MAIL, 'initials="СА"'):
                    self.assertNotIn(needle, raw, f"{needle!r} осталось в {part}")
        restored = self.env.restore(self.env.as_upload(job))
        back = zip_text(self.env.output_bytes(restored))
        self.assertIn(f'name="{SEC}"', back)
        self.assertIn('initials="СА"', back)
        self.assertIn(MAIL, back)
        self.assertIn(f"Проверить с {SEC}", back)


if __name__ == "__main__":
    unittest.main()
