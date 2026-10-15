"""Regressions exposed by the Linux quality gate (no desktop or OCR required)."""
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import ImageFont

from anonymizer.service import safe_name
from tests.font_support import system_font
from tests.helpers import Env
from tests.test_ws_s6b import FORMATS, levels, logo_png


class PortableNames(unittest.TestCase):
    def test_multibyte_names_fit_filesystem_with_output_suffix(self):
        for suffix in (".txt", ".docx", ".xlsx", ".pptx", ".pdf"):
            with self.subTest(suffix=suffix):
                name = safe_name("План " + "очень длинное название " * 20 + suffix)
                self.assertTrue(name.endswith(suffix))
                self.assertLessEqual(len(name), 150)
                self.assertLessEqual(len(name.encode("utf-8")), 200)
                output = Path(name).stem + " (обезличено)" + suffix
                self.assertLessEqual(len(output.encode("utf-8")), 255)

    def test_short_unicode_name_is_preserved(self):
        self.assertEqual(safe_name("План поставок.txt"), "План поставок.txt")


class PortableFonts(unittest.TestCase):
    def test_fixture_font_contains_cyrillic(self):
        font = fitz.Font(fontfile=system_font())
        for letter in "ИвановПётр":
            self.assertNotEqual(font.has_glyph(ord(letter)), 0, letter)
        # Both fixture writers must be able to open the same font.
        ImageFont.truetype(system_font(), 26)


class ImagesWithoutOCR(unittest.TestCase):
    def test_kept_office_images_warn_when_ocr_unavailable(self):
        for ext in ("pptx", "docx", "xlsx"):
            with self.subTest(ext=ext), closing(Env()) as env, patch("anonymizer.formats.ocr.available", return_value=False):
                job = env.anonymize((f"doc.{ext}", FORMATS[ext](logo_png())), options={"image_mode": "redact_text"})
                warnings = [text for level, text in levels(job) if level == "warn"]
                self.assertTrue(any("остаются в файле видимыми" in t and "надписи не закрашены" in t for t in warnings), warnings)
                self.assertFalse(any("закрашен только распознанный текст" in t for t in warnings), warnings)
                self.assertTrue(all(f.status == "attention" for f in job.files))


class PortableRuntime(unittest.TestCase):
    def test_peak_memory_counter_reports_positive_megabytes(self):
        from anonymizer.util import peak_memory_mb
        self.assertGreater(peak_memory_mb(), 0)

    def test_windows_guard_accepts_loaded_dynamic_clr_module(self):
        import sys
        import types
        from tests import _guards
        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"clr": types.ModuleType("clr")}):
            self.assertTrue(_guards.has_pywebview())
