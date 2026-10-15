"""PDF performance: same-line redaction slivers are merged, but never across a foreign character."""
from __future__ import annotations

import unittest
from pathlib import Path

import fitz

from anonymizer import colctx, pdftext
from tests.helpers import Env
from tests.pdf_probe import leaks


def page_with(text: str) -> tuple[fitz.Document, fitz.Page]:
    doc = fitz.open()
    page = doc.new_page()
    pdftext.put_text(page, (40, 60), text, 11)
    return doc, page


class SliverMerge(unittest.TestCase):
    def test_value_slivers_become_one_rect(self):
        _, page = page_with("write to oliver.abernathy98@demo-mail.example.com today")
        pc = pdftext.PageChars(page)
        flat = "".join(c.c for c in pc.chars)
        first = flat.index("oliver")
        ids = list(range(first, first + len("oliver.abernathy98@demo-mail.example.com")))
        rects = pc.slivers(ids)
        self.assertLessEqual(len(rects), 2)
        for cid in ids:                      # every character of the value is still covered
            c = pc.chars[cid]
            if c.c.strip():
                mid = fitz.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)
                self.assertTrue(any(r.contains(mid) for r in rects), c.c)

    def test_merge_never_touches_a_foreign_char(self):
        doc, page = page_with("ABCDE")
        pc = pdftext.PageChars(page)
        b, d = pc.chars[1], pc.chars[3]
        # B and D only (C is foreign and lies between them): the gap must not be bridged over C
        rects = pc.slivers([1, 3])
        c = pc.chars[2]
        for r in rects:
            self.assertFalse(c.x0 < r.x1 and c.x1 > r.x0 and c.y0 < r.y1 and c.y1 > r.y0, "foreign char hit")
        self.assertEqual(2, len(rects))

    def test_dense_page_anonymizes_and_is_leak_free(self):
        doc = fitz.open()
        page = doc.new_page()
        rows = [f"Person{n} Surname{n}   user{n}.surname{n}@demo-mail.example.com" for n in range(40)]
        for n, row in enumerate(rows):
            pdftext.put_text(page, (30, 40 + n * 17), row, 9)
        env = Env()
        try:
            job = env.anonymize(("d.pdf", doc.tobytes()))
            out = Path(job.files[0].out_path).read_bytes()
        finally:
            env.close()
        self.assertEqual([], leaks(out, ["user7.surname7", "user39.surname39@demo-mail.example.com"]))


class TableBudget(unittest.TestCase):
    def test_zero_budget_skips_find_tables(self):
        class Det:
            entities = None
        doc, _ = page_with("plain text")
        self.assertEqual(0, colctx.learn_pdf_tables(doc, Det(), char_budget=0))


if __name__ == "__main__":
    unittest.main()
