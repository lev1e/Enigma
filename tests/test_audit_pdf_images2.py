"""Аудит 08.10 (вторая волна): миниатюры страниц, списки выбора в формах, хвосты и частные блоки картинок, английский паспорт."""
from __future__ import annotations

import io
import struct
import unittest
import zlib
from pathlib import Path

import fitz

from anonymizer.formats import strip_image_metadata
from tests import pdf_probe as P
from tests.helpers import Env
from tests.test_eval_leaks import scan

NAME = "Смирнов Алексей Петрович"
LINE = f"{NAME}, ООО «Ромашка», ИНН 7707083893, ivan@romashka.ru"


class PdfStructure(unittest.TestCase):
    def setUp(self):
        self.env = Env(); self.addCleanup(self.env.close)

    def run_pdf(self, doc):
        job = self.env.anonymize(("a.pdf", doc.tobytes()))
        f = job.files[0]
        return f, (Path(f.out_path).read_bytes() if f.out_path else None)

    @unittest.skipUnless(Path(P.FONT).exists(), "нужен Arial")
    def test_page_thumbnail_removed(self):
        d = fitz.open(); p = d.new_page(); P.put(p, (72, 100), LINE)
        pm = p.get_pixmap(dpi=96)
        th = d.get_new_xref()
        d.update_object(th, f"<</Type/XObject/Subtype/Image/Width {pm.width}/Height {pm.height}/ColorSpace/DeviceRGB/BitsPerComponent 8>>")
        d.update_stream(th, pm.samples)
        d.xref_set_key(p.xref, "Thumb", f"{th} 0 R")
        f, out = self.run_pdf(d)
        self.assertIsNotNone(out)
        dd = fitz.open(stream=out, filetype="pdf")
        self.assertEqual(dd.xref_get_key(dd[0].xref, "Thumb")[0], "null")

    @unittest.skipUnless(Path(P.FONT).exists(), "нужен Arial")
    def test_choice_widget_options_scrubbed(self):
        d = fitz.open(); p = d.new_page(); P.put(p, (72, 100), "Форма")
        w = fitz.Widget()
        w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w.field_name = "who"; w.rect = fitz.Rect(72, 200, 300, 220)
        w.choice_values = [NAME, "ivan@romashka.ru", "Другое"]
        w.field_value = "Другое"
        p.add_widget(w)
        f, out = self.run_pdf(d)
        self.assertIsNotNone(out)
        dd = fitz.open(stream=out, filetype="pdf")
        blob = "\n".join(dd.xref_object(x) for x in range(1, dd.xref_length()))
        utf16 = lambda s: s.encode("utf-16-be").hex().upper()
        for secret in ("Смирнов", "romashka"):
            self.assertNotIn(secret, blob)
            self.assertNotIn(utf16(secret), blob.upper())


@unittest.skipUnless(Path(P.FONT).exists(), "нужен Arial")
class VectorText(unittest.TestCase):
    def test_outlined_text_is_recognised_and_hidden(self):
        from anonymizer import ocr
        if not ocr.available():
            self.skipTest("нет OCR")
        d = fitz.open(); p = d.new_page(); P.put(p, (72, 100), LINE, size=14)
        src = fitz.open("svg", p.get_svg_image(text_as_path=True).encode())
        pdf = fitz.open("pdf", src.convert_to_pdf())
        self.assertEqual(pdf[0].get_text().strip(), "")
        env = Env(); self.addCleanup(env.close)
        job = env.anonymize(("a.pdf", pdf.tobytes()))
        f = job.files[0]
        if not f.out_path:                  # отказ выдать файл тоже безопасен
            self.assertTrue(f.messages)
            return
        out = Path(f.out_path).read_bytes()
        page = fitz.open(stream=out, filetype="pdf")[0]
        words, _ = ocr.ocr_page_words(page, page.rect)
        text = " ".join(w.text for w in words).lower()
        for secret in ("смирнов", "romashka", "7707083893"):
            self.assertNotIn(secret, text)


def png_with(chunk=None, trailer=b""):
    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff")
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", ihdr) + (ch(*chunk) if chunk else b"") + ch(b"IDAT", idat) + ch(b"IEND", b"") + trailer


class ImageTrailers(unittest.TestCase):
    def test_png_private_chunk_and_trailer_removed(self):
        raw = png_with((b"prVt", "Смирнов romashka".encode()), "TRAILER Смирнов".encode())
        out = strip_image_metadata(raw, ".png")
        self.assertNotIn("Смирнов".encode(), out)
        self.assertNotIn(b"prVt", out)
        self.assertTrue(out.startswith(b"\x89PNG") and b"IDAT" in out and out.endswith(b"IEND\xaeB`\x82"))

    def test_jpeg_trailer_removed(self):
        from PIL import Image
        b = io.BytesIO(); Image.new("RGB", (8, 8), "white").save(b, "JPEG")
        out = strip_image_metadata(b.getvalue() + "TRAILER Смирнов".encode(), ".jpg")
        self.assertNotIn("Смирнов".encode(), out)
        self.assertTrue(out.endswith(b"\xff\xd9"))
        Image.open(io.BytesIO(out)).load()


class EnglishPassport(unittest.TestCase):
    def test_forms(self):
        for t, v in (("Passport 4512 345678 issued", "4512 345678"), ("Passport No. 4512345678 issued", "4512345678"),
                     ("passport number: 45 12 345678.", "45 12 345678")):
            start = t.index(v); end = start + len(v)
            hits = [f for f in scan(t) if f.decision.value == "AUTO" and f.category == "PASSPORT"]
            self.assertTrue(any(f.start <= start and f.end >= end for f in hits), t)


if __name__ == "__main__":
    unittest.main()
