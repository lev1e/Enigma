"""W4c: после возврата PDF не должно оставаться подписей ImageN, нарисованных вместо картинок при обезличивании."""
from __future__ import annotations

import re
import unittest

import fitz

from tests.test_ws_w10 import TestPdf as _W10Pdf, W10Base


def letters(pdf_path_or_bytes) -> str:
    doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf") if isinstance(pdf_path_or_bytes, bytes) else fitz.open(pdf_path_or_bytes)
    txt = "".join(p.get_text() for p in doc)
    doc.close()
    return re.sub(r"[\W_]+", "", txt.lower())


class TestImageLabelRemoved(W10Base):
    make_pdf = _W10Pdf.make_pdf

    def test_label_in_anonymized_and_gone_after_restore(self):
        data, _ = self.make_pdf()
        job, out = self.run_one("c.pdf", data)
        self.assertIn("image1", letters(out))                       # подпись есть в обезличенном файле
        back = self.restored(out, out.name)
        self.assertEqual(letters(back), letters(data))              # после возврата текст слоя совпадает с исходным
        self.assertNotRegex(letters(back), r"image\d")

    def test_real_text_near_images_survives(self):
        data, _ = self.make_pdf()
        job, out = self.run_one("c.pdf", data)
        self.assertIn("contract", letters(self.restored(out, out.name)))


class TestImageSurvivesRedaction(W10Base):
    """Страница с найденным именем и картинкой: заглушка не должна потерять ключ хранилища, картинка возвращается."""

    def test_image_back_with_text_hit(self):
        from tests.test_ws_w10 import png_bytes
        png = png_bytes(40)
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 60), "Contact: Maria Ivanova, maria.ivanova@example.org", fontsize=12)
        page.insert_image(fitz.Rect(72, 100, 272, 260), stream=png)
        data = doc.tobytes()
        doc.close()
        job, out = self.run_one("h.pdf", data)
        an = fitz.open(out)
        self.assertEqual([an.xref_get_key(i[0], "AnonImg")[0] for i in an[0].get_images(full=True)], ["string"])
        an.close()
        back = fitz.open(self.restored(out, out.name))
        self.assertGreater(back[0].get_images(full=True)[0][2], 1)      # ширина картинки: не 1x1 заглушка
        self.assertNotRegex(letters(self.restored(out, out.name)), r"image\d")
        back.close()


del _W10Pdf
if __name__ == "__main__":
    unittest.main()
