"""Cross-page replacement must not duplicate overlapping page-local originals."""
from collections import Counter
from dataclasses import replace as replace_finding
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from anonymizer import formats
from anonymizer.models import Decision, Finding
from .helpers import Env
from .test_ws_s7b import letters


def hit(ids, decision=Decision.AUTO):
    return formats.PdfHit(SimpleNamespace(decision=decision), ids)


class SeamOverlapTests(unittest.TestCase):
    def test_seam_supersedes_contained_page_hits_on_both_pages(self):
        a, b = hit({0: [1, 2]}), hit({1: [0, 1]})
        unrelated = hit({1: [7]})
        seam = hit({0: [1, 2, 3], 1: [0, 1, 2]})
        merged = formats._pdf_merge_seam_hit([a, b, unrelated], seam)
        self.assertEqual(merged, [unrelated, seam])
        ids = [(page, cid) for item in merged for page, chars in item.ids.items() for cid in chars]
        self.assertTrue(all(count == 1 for count in Counter(ids).values()))

    def test_partial_overlap_refuses_instead_of_dropping_sensitive_tail(self):
        page_hit = hit({0: [1, 2, 3]})
        seam = hit({0: [3, 4], 1: [0, 1]})
        with self.assertRaises(ValueError):
            formats._pdf_merge_seam_hit([page_hit], seam)

    def test_already_covered_seam_is_not_drawn_twice(self):
        existing = hit({0: [1, 2, 3], 1: [0, 1, 2]})
        seam = hit({0: [2, 3], 1: [0, 1]})
        self.assertEqual(formats._pdf_merge_seam_hit([existing], seam), [existing])

    def test_review_seam_does_not_replace_automatic_page_hit(self):
        existing = hit({0: [1, 2]})
        seam = hit({0: [1, 2], 1: [0]}, Decision.REVIEW)
        self.assertEqual(formats._pdf_merge_seam_hit([existing], seam), [existing, seam])

    def test_partial_overlap_labels_each_uncovered_source_fragment_once(self):
        maps = [SimpleNamespace(chars=[SimpleNamespace(c=c) for c in text], lines=[list(range(len(text)))])
                for text in ("12345", "67890")]
        finding = Finding("seam", "input.pdf", "page:1", "SECRET", "34567", 0, 5,
                          Decision.AUTO, 1.0, permanently_removed=True)
        page_hit = formats.PdfHit(replace_finding(finding, original="123"), {0: [0, 1, 2]})
        seam = formats.PdfHit(finding, {0: [2, 3, 4], 1: [0, 1]})
        merged = formats._pdf_merge_seam_hit([page_hit], seam, maps)
        self.assertIs(merged[0], page_hit)
        self.assertEqual([h.finding.original for h in merged], ["123", "45", "67"])
        self.assertTrue(all(h.finding.category == "SECRET" and h.finding.permanently_removed for h in merged))
        ids = [(page, cid) for h in merged for page, group in h.ids.items() for cid in group]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {(0, i) for i in range(5)} | {(1, 0), (1, 1)})

    def test_overlapping_page_header_keeps_full_page_names_without_refusal(self):
        maps = [SimpleNamespace(chars=[SimpleNamespace(c=c) for c in text], lines=[list(range(len(text)))])
                for text in ("Regional Society ", "Jane Roe")]
        finding = Finding("seam", "input.pdf", "page:1", "ORG", "Regional Society Jane", 0, 21, Decision.AUTO, 1.0)
        first = formats.PdfHit(replace_finding(finding, original="Regional Society"), {0: list(range(16))})
        second = formats.PdfHit(replace_finding(finding, original="Jane Roe"), {1: list(range(8))})
        seam = formats.PdfHit(finding, {0: list(range(17)), 1: list(range(4))})
        self.assertEqual(formats._pdf_merge_seam_hit([first, second], seam, maps), [first, second])

    def test_synthetic_invoice_roundtrip_preserves_original_characters_and_masks_gold(self):
        # Existing public synthetic fixture reproduces a phone at the end of
        # page 0 overlapping a seam phone that also consumes row 31 of page 1.
        from tools.eval_ids import dense
        from tools import eval_inject
        from anonymizer.pdftext import font_for
        import fitz
        sid = "syn_invoice_ru_pdf"
        pack = dense(sid, "ru")
        with tempfile.TemporaryDirectory() as folder:
            font = font_for("Счёт")[1]
            if not font:
                font = str(Path(folder) / "fixture.ttf")
                Path(font).write_bytes(fitz.Font("china-s").buffer)
            with mock.patch.object(eval_inject, "FONT", font):
                data = eval_inject.inject("pdf", eval_inject.synth("invoice", "pdf", pack, sid), pack, "")
        env = Env(retain_secrets_for_restore=True, ner_candidates=False)
        self.addCleanup(env.close)
        job = env.anonymize(("invoice.pdf", data))
        self.assertTrue(job.files[0].out_path, job.files[0].messages)
        anon = env.output_bytes(job)
        with fitz.open(stream=anon, filetype="pdf") as doc:
            visible = "\n".join(page.get_text() for page in doc)
        normalized = re.sub(r"[\W_]+", "", visible.casefold())
        for _category, original in pack.gold:
            value = re.sub(r"[\W_]+", "", original.casefold())
            if value:
                self.assertNotIn(value, normalized)
        restored = env.restore(env.as_upload(job))
        self.assertTrue(restored.files[0].out_path, restored.files[0].messages)
        self.assertEqual(letters(env.output_bytes(restored)), letters(data))

    def test_ambiguous_partial_overlap_does_not_produce_a_downloadable_file(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((40, 80), "Phone +7 912 345-67-89")
        data = doc.tobytes()
        doc.close()
        env = Env(ner_candidates=False)
        self.addCleanup(env.close)

        def conflicting_hits(*_args, **_kwargs):
            return formats._pdf_merge_seam_hit([hit({0: [1, 2, 3]})], hit({0: [3, 4], 1: [0]}))

        with mock.patch.object(formats, "_pdf_hits", side_effect=conflicting_hits):
            job = env.anonymize(("ambiguous.pdf", data))
        self.assertEqual(job.files[0].status, "error")
        self.assertFalse(job.files[0].out_path)


if __name__ == "__main__":
    unittest.main()
