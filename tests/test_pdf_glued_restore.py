"""Generated adjacent PDF labels must restore exact IDs, including email labels."""
import re
import unittest

import fitz

from anonymizer.restore import Restorer, _glued_tokens, restore_pdf
from anonymizer.tokens import RELAXED_TOKEN_RE
from tests.helpers import Env


class AdjacentLabelRestoration(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.vault = self.env.vault
        for i in range(1, 52):
            self.vault.token_for("ORG", str(i), f"OriginalCompany{i}")
        for i in range(1, 5):
            self.vault.token_for("EMAIL", str(i), f"contact{i}@fictional.invalid")
        self.vault.token_for("PERSON", "one", "Fictional Person")

    def test_general_followed_by_email_uses_full_number(self):
        self.assertEqual(Restorer(self.vault).substitute("Company51email4@example.com"),
                         "OriginalCompany51contact4@fictional.invalid")

    def test_email_followed_by_general_and_three_labels(self):
        for text, expected in [
            ("email4@example.comCompany51", "contact4@fictional.invalidOriginalCompany51"),
            ("Company51email4@example.comName1", "OriginalCompany51contact4@fictional.invalidFictional Person"),
            ("(Company51email4@example.com).", "(OriginalCompany51contact4@fictional.invalid)."),
        ]:
            with self.subTest(text=text):
                self.assertEqual(Restorer(self.vault).substitute(text), expected)

    def test_unknown_numeric_id_cannot_backtrack_to_known_prefix(self):
        for text in ("Company519email4@example.com", "Company519x", "Company51999999x"):
            with self.subTest(text=text):
                self.assertEqual(Restorer(self.vault).substitute(text), text)
        self.assertIsNone(RELAXED_TOKEN_RE.search("Company519x"))

    def test_unknown_token_invalidates_complete_adjacent_run(self):
        text = "Company51email99@example.com"
        self.assertEqual(Restorer(self.vault).substitute(text), text)
        self.assertEqual(_glued_tokens(text, self.vault), set())

    def test_non_token_suffix_and_login_are_untouched(self):
        for text in ("Company51email4@example.comSuffix", "Company51email4@example.com.evil", "n0name321"):
            with self.subTest(text=text):
                self.assertEqual(Restorer(self.vault).substitute(text), text)

    def test_pdf_inventory_keeps_full_mixed_labels(self):
        self.assertEqual(_glued_tokens("Company51email4@example.com", self.vault),
                         {"Company51", "email4@example.com"})

    def test_real_pdf_restores_both_adjacent_labels(self):
        src, dst = self.env.base / "adjacent.pdf", self.env.base / "restored.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 100), "Company51email4@example.com")
            document.save(src)
        restore_pdf(src, dst, Restorer(self.vault))
        with fitz.open(dst) as document:
            text = "".join(page.get_text() for page in document)
        compact = re.sub(r"\s+", "", text)
        self.assertIn("OriginalCompany51", compact)
        self.assertIn("contact4@fictional.invalid", compact)
        self.assertNotIn("Company51email4", compact)

    def test_pdf_known_label_does_not_consume_unknown_id_prefix_elsewhere(self):
        src, dst = self.env.base / "prefix.pdf", self.env.base / "prefix-restored.pdf"
        unknown = ("Company512", "Company512email4@example.com", "Company51email99@example.com")
        with fitz.open() as document:
            page = document.new_page()
            for i, line in enumerate(("Company51", *unknown)):
                page.insert_text((72, 100 + i * 40), line)
            document.save(src)
        restore_pdf(src, dst, Restorer(self.vault))
        with fitz.open(dst) as document:
            text = "".join(page.get_text() for page in document)
        compact = re.sub(r"\s+", "", text)
        self.assertEqual(compact.count("OriginalCompany51"), 1)
        for label in unknown:
            self.assertIn(label, compact)
        self.assertNotIn("contact4@fictional.invalid", compact)

    def test_wrapped_image_caption_removed_only_for_exact_known_image(self):
        import io
        from types import SimpleNamespace
        from PIL import Image
        from anonymizer import imagereplace

        src, dst = self.env.base / "wrapped.pdf", self.env.base / "wrapped-restored.pdf"
        area = fitz.Rect(100, 50, 152.7, 120.85)
        unknown_area = fitz.Rect(220, 50, 272.7, 120.85)
        image = Image.new("RGB", (53, 71), (123, 41, 87))
        stream = io.BytesIO()
        image.save(stream, "PNG")
        with fitz.open() as document:
            page = document.new_page()
            known_xref = page.insert_image(area, stream=stream.getvalue())
            image.paste((22, 88, 122), (0, 0, 53, 71))
            stream = io.BytesIO()
            image.save(stream, "PNG")
            unknown_xref = page.insert_image(unknown_area, stream=stream.getvalue())
            expected_samples = fitz.Pixmap(document, known_xref).samples
            page.insert_text((72, 210), "Image1")  # original natural text outside both placeholders
            context = SimpleNamespace(vault=self.vault)
            imagereplace.replace_pdf_images(document, context)
            imagereplace.draw_pending_labels(document, context)
            # Exact random image identity is missing, so neither image nor its
            # cosmetic wrapped caption may be removed by restoration.
            document.xref_set_key(unknown_xref, imagereplace.PDF_ID_KEY, "(missing-original)")
            self.assertIn("Image\n1", page.get_text())
            page.insert_text((unknown_area.x0, unknown_area.y1 - 2), "Image999", fontsize=7)
            document.save(src)
        restore_pdf(src, dst, Restorer(self.vault))
        with fitz.open(dst) as document:
            page = document[0]
            self.assertNotIn("Image", page.get_text(clip=area))
            self.assertIn("Image", page.get_text(clip=unknown_area))
            self.assertIn("Image999", page.get_text(clip=unknown_area))
            self.assertIn("Image1", page.get_text(clip=fitz.Rect(50, 180, 180, 230)))
            known_images = [info for info in page.get_image_info(xrefs=True)
                            if abs(info["bbox"][0] - area.x0) < 1]
            self.assertEqual(len(known_images), 1)
            self.assertEqual(fitz.Pixmap(document, known_images[0]["xref"]).samples, expected_samples)

    def test_pdf_rejoins_split_number_without_guessing_unknown_longer_ids(self):
        for i in (52, 53):
            self.vault.token_for("ORG", str(i), f"OriginalCompany{i}")
        src, dst = self.env.base / "split.pdf", self.env.base / "split-restored.pdf"
        with fitz.open() as document:
            page = document.new_page()
            for y, number in ((100, "53"), (150, "539")):
                page.insert_text((72, y), "Company", fontsize=3)
                page.insert_text((300, y), "Separate text block", fontsize=8)
                x = 72 + fitz.get_text_length("Company", fontname="helv", fontsize=3)
                page.insert_text((x, y), number, fontsize=3, fontname="china-s")
            document.save(src)
        restore_pdf(src, dst, Restorer(self.vault))
        with fitz.open(dst) as document:
            page = document[0]
            first = re.sub(r"\s+", "", page.get_text(clip=fitz.Rect(60, 80, 250, 115)))
            second = re.sub(r"\s+", "", page.get_text(clip=fitz.Rect(60, 130, 250, 165)))
            self.assertEqual(first, "OriginalCompany53")
            self.assertEqual(second, "Company539")
