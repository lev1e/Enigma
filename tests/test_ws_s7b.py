"""S7B: возврат PDF не теряет чужие буквы под метками, склеенные метки, логотип «@ACCESS» не остаток. Все файлы выдуманные."""
from __future__ import annotations

import collections
import re
import unittest
from pathlib import Path

import fitz

from anonymizer import formats
from anonymizer.restore import _glued_tokens
from anonymizer.service import Upload
from tests.helpers import Env


def letters(data: bytes | Path) -> collections.Counter:
    doc = fitz.open(stream=data, filetype="pdf") if isinstance(data, bytes) else fitz.open(data)
    text = "\n".join(p.get_text() for p in doc)
    return collections.Counter(re.sub(r"[\W_]+", "", text.lower()))


class TestOverlappedText(unittest.TestCase):
    """Выдуманная форма: строка сноски, поверх которой набрана строка с почтой (как у шаблонов с впечатанными данными)."""

    def setUp(self):
        self.env = Env(retain_secrets_for_restore=True)
        self.addCleanup(self.env.close)

    def make(self) -> bytes:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((36, 120), "Quarterly inventory report for the warehouse", fontsize=12)
        page.insert_text((36, 765), "For Paperwork Reduction Act Notice, see separate instructions.", fontsize=8)
        page.insert_text((30, 763), "Email: ", fontsize=8)
        page.insert_text((60, 763), "jane.roe42@example-mail.org", fontsize=8)
        return doc.tobytes()

    def test_lost_letters_of_covered_line_come_back(self):
        data = self.make()
        job = self.env.anonymize(("form.pdf", data))
        f = job.files[0]
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])
        anon = Path(f.out_path).read_bytes()
        self.assertNotIn("roe42", "".join(p.get_text() for p in fitz.open(stream=anon, filetype="pdf")))
        res = self.env.restore(Upload("form.pdf", anon))
        rest = Path(res.files[0].out_path).read_bytes()
        got, want = letters(rest), letters(data)
        self.assertEqual(dict(want - got), {}, "потеряны буквы")
        self.assertEqual(dict(got - want), {}, "лишние буквы")


class TestGluedTokens(unittest.TestCase):
    def test_adjacent_tokens_are_split(self):
        self.assertEqual(_glued_tokens("see (Company4Company5) here"), {"Company4", "Company5"})
        self.assertEqual(_glued_tokens("Name1Name2_2Name3"), {"Name1", "Name2_2", "Name3"})

    def test_ordinary_words_and_single_tokens_untouched(self):
        self.assertEqual(_glued_tokens("Company4 accompanying company Namesake1234567"), set())


class TestOcrLogoIsNotResidual(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_open_access_logo_is_not_a_username(self):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        self.assertEqual(formats._residuals(d, "OPEN @ACCESS Freely available online", [], ocr_text=True), [])

    def test_real_handle_still_residual(self):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        self.assertTrue(formats._residuals(d, "mail jane.roe@example.org", [], ocr_text=True))


if __name__ == "__main__":
    unittest.main()
