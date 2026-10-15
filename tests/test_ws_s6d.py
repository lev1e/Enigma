"""S6D: заголовки форм не организации; подпись ImageN не обрезается редактированием текста; разреженный PDF."""
from __future__ import annotations

import re
import time
import unittest

import fitz

from anonymizer import en_rules
from tests.test_ws_w10 import W10Base, jpg_bytes


class TestHeadings(unittest.TestCase):
    def test_form_headings_are_not_organisations(self):
        for t in ("Check Form for Common Errors & Reminders", "Terms & Conditions apply"):
            self.assertEqual(en_rules.org_spans(t), [], t)
        self.assertTrue(en_rules.org_spans("Smith & Wesson"))


class TestLabelAfterRedaction(W10Base):
    def test_label_survives_text_redaction_and_restores(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, 595, 400), stream=jpg_bytes(5))
        page.insert_text((300, 40), "Contact: Robert Hargrove, robert.hargrove@example.org", fontsize=9)
        data = doc.tobytes()
        job, out = self.run_one("lab.pdf", data)
        words = [w[4] for w in fitz.open(out)[0].get_text("words")]
        self.assertTrue(any(re.fullmatch(r"Image\d+", w) for w in words), words)
        self.assertNotIn("Hargrove", " ".join(words))


class TestSparse(W10Base):
    def test_sparse_100_pages(self):
        doc = fitz.open()
        for i in range(100):
            p = doc.new_page()
            p.insert_text((72, 100), f"Page {i + 1}", fontsize=14)
            p.insert_text((72, 140), f"Contact Maria Sidorova tel +1 415 555 {1000 + i}", fontsize=11)
        t = time.time()
        job, out = self.run_one("sparse.pdf", doc.tobytes())
        took = time.time() - t
        self.assertLess(took, 90, f"{took:.1f}s")      # target 30 s on an idle machine; bound is loose for shared CI


if __name__ == "__main__":
    unittest.main()
