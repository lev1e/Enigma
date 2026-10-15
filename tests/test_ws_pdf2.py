"""PDF restore fidelity (real-document eval): lost Ukrainian letters, overlapping equal tokens, text under a token rectangle,
free room to the right of a token, repaired-file warning."""
from __future__ import annotations

import collections
import re
import unittest
from pathlib import Path

import fitz

from anonymizer import pdftext
from anonymizer.restore import _inside_longer
from tests.helpers import Env

from tests.font_support import system_font

FONT = system_font()


def letters(data: bytes) -> collections.Counter:
    flags = fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE
    text = "\n".join(p.get_text(flags=flags) for p in fitz.open(stream=data, filetype="pdf"))
    return collections.Counter(re.sub(r"[\W_]+", "", text.replace("\xad", "")).lower())


def make_pdf(lines: list[str], size: float = 11) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        pdftext.put_text(page, (50, 80 + i * 22), line, size)
    return doc.tobytes()


class FontChoice(unittest.TestCase):
    def test_builtin_fonts_lose_letters_system_font_does_not(self):
        text = "Віталій Їжак Єгор ґанок «x» ß"
        doc = fitz.open()
        page = doc.new_page()
        pdftext.put_text(page, (50, 100), text, 12)
        got = re.sub(r"\s+", "", page.get_text())
        self.assertEqual(got, re.sub(r"\s+", "", text))


class RestoreTokens(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def roundtrip(self, src: bytes):
        job = self.env.anonymize(("t.pdf", src))
        self.assertTrue(job.files[0].out_path, [m["text"] for m in job.files[0].messages])
        anon = self.env.output_bytes(job)
        back = self.env.output_bytes(self.env.restore(self.env.as_upload(job)))
        return anon, back

    def test_ukrainian_letters_survive_restore(self):
        src = make_pdf(["Заявитель: Чернобаев Віталій Борисович", "Телефон +7 (912) 345-67-89",
                        "Примітка: єдиний їжак з ґанку"])
        anon, back = self.roundtrip(src)
        self.assertNotIn("Чернобаев", "".join(p.get_text() for p in fitz.open(stream=anon, filetype="pdf")))
        self.assertEqual(letters(back), letters(src))

    def test_text_under_token_rectangle_is_kept(self):
        # a second line overlaps the first (tight leading): removing the token must not eat the neighbour line
        doc = fitz.open()
        page = doc.new_page()
        pdftext.put_text(page, (50, 100), "Телефон +7 (912) 345-67-89 конец", 11)
        pdftext.put_text(page, (140, 104), "соседний текст не теряется", 8)
        src = doc.tobytes()
        anon, back = self.roundtrip(src)
        self.assertEqual(letters(back), letters(src))

    def test_equal_tokens_with_touching_rectangles_both_restore(self):
        a, b = fitz.Rect(100, 100, 150, 112), fitz.Rect(120, 111, 170, 123)
        self.assertFalse(_inside_longer(b, "Country1_2", a, "Country1_2"))
        self.assertTrue(_inside_longer(fitz.Rect(100, 100, 120, 112), "Country1", a, "Country1_2"))

    def test_restore_does_not_glue_to_next_word(self):
        # the original is longer than its token: it must be fitted into the free room before the next word
        src = make_pdf(["Контакт: Чернобаев Пётр Сергеевич Тест"])
        anon, back = self.roundtrip(src)
        words = [w[4] for w in fitz.open(stream=back, filetype="pdf")[0].get_text("words")]
        self.assertIn("Тест", words)


class RepairedWarning(unittest.TestCase):
    def test_truncated_pdf_carries_repair_warning(self):
        src = make_pdf(["Заявитель: Чернобаев Пётр Сергеевич", "ИНН 500100732259"] + ["строка %d" % i for i in range(60)])
        cut = src[:-int(len(src) * .08)]
        if not fitz.open(stream=cut, filetype="pdf").is_repaired:
            self.skipTest("PyMuPDF did not need to repair this cut")
        env = Env()
        self.addCleanup(env.close)
        job = env.anonymize(("cut.pdf", cut))
        f = job.files[0]
        if f.out_path:
            self.assertTrue(any("повреждён" in m["text"] for m in f.messages), [m["text"] for m in f.messages])


if __name__ == "__main__":
    unittest.main()
