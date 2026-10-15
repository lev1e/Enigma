"""S9B: PDF leftovers. Все файлы выдуманные, маленькие.

1. _mask_drawn_chars работает по сетке (раньше квадратично: 130 с на большой странице).
2. Слово распознавания, лежащее на знаках текстового слоя, не добавляется второй раз (двойная метка на одном слове).
3. Остаток, который находит только проверка, ведёт ко второму проходу (strict), а не сразу к отказу.
"""
from __future__ import annotations

import time
import unittest

import fitz

from anonymizer import formats, ocr
from anonymizer.models import Decision, Finding
from anonymizer.pdftext import PageChars


def one_page(text_lines: list[str]) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page()
    for n, line in enumerate(text_lines):
        page.insert_text((50, 80 + 14 * n), line, fontsize=10)
    return doc


class TestMaskDrawnGrid(unittest.TestCase):
    def test_masks_only_chars_under_marks(self):
        doc = one_page(["alpha Company1 omega", "beta gamma"])
        maps = [PageChars(p) for p in doc]
        box = [(r, "Company1") for r in doc[0].search_for("Company1")]
        before = "".join(c.c for c in maps[0].chars)
        masked = formats._mask_drawn_chars(maps, {0: box})
        after = "".join(c.c for c in maps[0].chars)
        self.assertEqual(masked, len("Company1"))
        self.assertEqual(after.count("Company1"), 0)
        self.assertIn("alpha", after)
        self.assertIn("omega", after)
        self.assertEqual(len(before), len(after))

    def test_many_marks_many_chars_is_fast(self):
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        marks = []
        for row in range(55):
            page.insert_text((20, 20 + row * 14), "x" * 95, fontsize=6)
            marks.append((fitz.Rect(20 + (row % 9) * 60, 12 + row * 14, 70 + (row % 9) * 60, 22 + row * 14), f"Name{row}"))
        maps = [PageChars(page)]
        extra = [(fitz.Rect(500, 5 + i * 3, 505, 8 + i * 3), "Name1") for i in range(250)]
        t0 = time.time()
        formats._mask_drawn_chars(maps, {0: marks + extra})
        self.assertLess(time.time() - t0, 5.0)


class TestOcrWordOverNativeText(unittest.TestCase):
    def test_word_over_text_layer_is_not_added_twice(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 80), "AAAAAAAAAA", fontsize=10)
        page.insert_text((130, 80), "BBBBBBBBBB", fontsize=10)
        chars = PageChars(page)
        native = len(chars.chars)
        x0 = min(c.x0 for c in chars.chars)
        x1 = max(c.x1 for c in chars.chars)
        y0 = min(c.y0 for c in chars.chars)
        y1 = max(c.y1 for c in chars.chars)
        centre = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
        self.assertFalse(any(fitz.Rect(c.x0, c.y0, c.x1, c.y1).contains(centre) for c in chars.chars), "setup: centre must be in the gap")
        # Центр слова распознавания в просвете между знаками, но рамка почти целиком лежит на знаках слоя.
        word = ocr.Word("AAAAAAAAAABBBBBBBBBB", x0, y0, x1, y1, 0)
        self.assertEqual(ocr.add_ocr_chars(chars, [word]), 0)
        self.assertEqual(len(chars.chars), native)

    def test_word_on_empty_place_is_still_added(self):
        doc = one_page(["Group on Research and Development"])
        chars = PageChars(doc[0])
        word = ocr.Word("Hidden", 50, 300, 100, 312, 0)
        self.assertEqual(ocr.add_ocr_chars(chars, [word]), 1)
        self.assertTrue(chars.has_ocr)


class _FakeDetector:
    """scan ничего не находит, verify находит «7th Street»: как плохой слой распознавания, который основной проход не разобрал."""

    def scan(self, text, rel, loc):
        return []

    def verify(self, text):
        i = text.find("7th Street")
        if i < 0:
            return []
        return [Finding("f1", "x.pdf", "page", "ADDRESS", "7th Street", i, i + len("7th Street"), Decision.AUTO, .9)]


class TestStrictRetryHits(unittest.TestCase):
    def test_strict_adds_verify_findings_to_native_pages(self):
        doc = one_page(["meet at 7th Street in town"])
        maps = [PageChars(p) for p in doc]
        plain = formats._pdf_hits(_FakeDetector(), None, "x.pdf", maps)
        self.assertEqual(plain, [])
        # ctx=None отключает проверочные находки (как для обычного прохода); strict работает и с ctx
        class Ctx:
            def apply_overrides(self, items):
                return items
        strict = formats._pdf_hits(_FakeDetector(), Ctx(), "x.pdf", maps, True)
        self.assertEqual([h.finding.original for h in strict], ["7th Street"])
        loose = formats._pdf_hits(_FakeDetector(), Ctx(), "x.pdf", maps, False)
        self.assertEqual(loose, [])

    def test_residual_still_refused_when_retry_cannot_remove_it(self):
        """Если и второй проход не убрал значение, файл по-прежнему не выдаётся."""
        from tests.helpers import Env
        env = Env(retain_secrets_for_restore=True)
        self.addCleanup(env.close)
        doc = one_page(["meet at 7th Street in town"])
        data = doc.tobytes()
        orig = formats._residuals
        formats._residuals = lambda *a, **k: ["7th Street"]
        self.addCleanup(setattr, formats, "_residuals", orig)
        job = env.anonymize(("a.pdf", data))
        f = job.files[0]
        self.assertFalse(f.out_path)


if __name__ == "__main__":
    unittest.main()
