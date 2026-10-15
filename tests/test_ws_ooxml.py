"""Workstream B: OOXML parts that used to leave the container untouched (printer settings, raw text parts,
unknown binaries). Each case: no secret in the output, restore returns the original value."""
from __future__ import annotations

import io
import unittest
import zipfile

from tests.helpers import Env, docx_bytes, zip_text

NAME = "Смирнов Алексей Петрович"
MAIL = "ivan@romashka.ru"


def add_parts(data: bytes, parts: dict[str, bytes], rels: dict[str, str] | None = None) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            raw = src.read(item.filename)
            if rels and item.filename in rels:
                raw = raw.decode("utf-8").replace("</Relationships>", rels[item.filename] + "</Relationships>").encode()
            if item.filename == "[Content_Types].xml":
                raw = raw.decode("utf-8").replace(
                    "</Types>", '<Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.'
                               'spreadsheetml.printerSettings"/><Default Extension="htm" ContentType="text/html"/></Types>').encode()
            z.writestr(item, raw)
        for name, raw in parts.items():
            z.writestr(name, raw)
    return out.getvalue()


class RawParts(unittest.TestCase):
    def run_file(self, data, name="a.docx"):
        env = Env(); self.addCleanup(env.close)
        job = env.anonymize((name, data))
        f = job.files[0]
        self.assertTrue(f.out_path, list(f.messages))
        return env, job, env.output_bytes(job)

    def test_printer_settings_dropped(self):
        blob = f"Принтер {NAME} {MAIL}".encode("utf-16-le")
        rel = ('<Relationship Id="rIdP" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
               'printerSettings" Target="printerSettings/printerSettings1.bin"/>')
        data = add_parts(docx_bytes(["Тело"]), {"word/printerSettings/printerSettings1.bin": blob},
                         {"word/_rels/document.xml.rels": rel})
        _, _, out = self.run_file(data)
        names = zipfile.ZipFile(io.BytesIO(out)).namelist()
        self.assertFalse([n for n in names if "printersettings" in n.lower()], names)
        raw_all = b"".join(zipfile.ZipFile(io.BytesIO(out)).read(n) for n in names)
        self.assertNotIn(NAME.encode("utf-16-le"), raw_all)
        self.assertNotIn(b"printerSettings", zipfile.ZipFile(io.BytesIO(out)).read("word/_rels/document.xml.rels"))

    def test_html_part_is_anonymized_and_restored(self):
        html = f"<html><body><p>Контакт: {NAME}, {MAIL}</p></body></html>".encode("utf-8")
        rel = ('<Relationship Id="rIdA" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
               'aFChunk" Target="afchunk.htm"/>')
        data = add_parts(docx_bytes([NAME]), {"word/afchunk.htm": html}, {"word/_rels/document.xml.rels": rel})
        env, job, out = self.run_file(data)
        raw_all = zip_text(out) + zipfile.ZipFile(io.BytesIO(out)).read("word/afchunk.htm").decode("utf-8")
        self.assertNotIn("Смирнов", raw_all)
        self.assertNotIn("romashka", raw_all)
        back = env.restore(env.as_upload(job))
        restored = env.output_bytes(back)
        self.assertIn(NAME, zipfile.ZipFile(io.BytesIO(restored)).read("word/afchunk.htm").decode("utf-8"))

    def test_unknown_binary_part_is_reported(self):
        data = add_parts(docx_bytes(["Тело"]), {"word/mystery.dat": f"{NAME}".encode("utf-8")})
        env = Env(); self.addCleanup(env.close)
        job = env.anonymize(("a.docx", data))
        f = job.files[0]
        text = " ".join(str(m) for m in f.messages)
        self.assertIn("mystery.dat", text)


if __name__ == "__main__":
    unittest.main()
