"""S12A: PDF-проверка не считает остатком наши собственные метки, склеенные без пробела.

Раньше «Company51email4@example.com» (две наши метки подряд) находила detector.verify как адрес почты; остаток
запускал второй (strict) проход, а он по ~100 мелким контурам страницы читал все 66 страниц OCR (~420 с CPU).
Тесты без приватных файлов.
"""
from __future__ import annotations

import unittest

from anonymizer import formats
from anonymizer.models import Decision, Finding


class _Detector:
    def __init__(self, found: str, text: str):
        self.found, self.text = found, text

    def verify(self, text):
        i = text.find(self.found)
        return [Finding("v1", "x.pdf", "page", "EMAIL", self.found, i, i + len(self.found), Decision.AUTO, .9)]


class TestOwnLabelChain(unittest.TestCase):
    def test_glued_own_labels_are_not_residual(self):
        for s in ("Company51email4@example.com", "Name1email2@example.com", "Company50Address7", "email3@example.com"):
            self.assertTrue(formats._only_own_labels(s), s)

    def test_glued_real_word_is_still_residual(self):
        for s in ("Gaboremail4@example.com", "Company51xemail4@example.com", "ivanov@mail.ru", "", "  "):
            self.assertFalse(formats._only_own_labels(s), s)

    def test_residuals_skips_glued_labels(self):
        text = "Phone7\nCompany51email4@example.com\nPhone8"
        det = _Detector("Company51email4@example.com", text)
        self.assertEqual(formats._residuals(det, text, []), [])

    def test_residuals_keeps_real_leftover(self):
        text = "Phone7\nGaboremail4@example.com\nPhone8"
        det = _Detector("Gaboremail4@example.com", text)
        self.assertEqual(formats._residuals(det, text, []), ["Gaboremail4@example.com"])


if __name__ == "__main__":
    unittest.main()
