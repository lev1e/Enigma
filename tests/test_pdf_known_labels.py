"""PDF retries must preserve exact known labels without hiding adjacent data."""
import unittest
from types import SimpleNamespace

import fitz

from anonymizer.formats import TransformContext, _pdf_page_hits
from anonymizer.models import Decision, Finding, Settings
from anonymizer.pdftext import PageChars
from tests.helpers import Env


class KnownLabelRetries(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.assertEqual(self.env.vault.token_for("DOMAIN", "fictional", "fictional.example"), "Domain1")

    def hits(self, text, original, end, category="PERSON"):
        finding = Finding("test", "input.pdf", "page:1", category, original, 0, end,
                          Decision.AUTO, 1.0, permanently_removed=category == "SECRET")
        detector = SimpleNamespace(scan=lambda *_args: [finding])
        ctx = TransformContext(self.env.vault, Settings(), detector)
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 100), text)
            return _pdf_page_hits(detector, ctx, "input.pdf", 1, PageChars(page))

    def test_known_label_prefix_is_not_replaced(self):
        self.assertEqual(self.hits("Domain1", "Domain", 6), [])

    def test_unknown_label_does_not_hide_a_finding(self):
        self.assertEqual(len(self.hits("Domain2", "Domain", 6)), 1)

    def test_data_beyond_label_is_still_removed(self):
        hits = self.hits("Domain1 private", "Domain1 private", 15, "SECRET")
        self.assertEqual(len(hits), 1)
        finding, ids = hits[0]
        self.assertEqual(finding.original.strip(), "private")
        self.assertEqual(finding.category, "SECRET")
        self.assertTrue(finding.permanently_removed)
        self.assertEqual(ids, set(range(7, 15)))
