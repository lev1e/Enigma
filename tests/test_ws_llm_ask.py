"""W12 task 2: guard "ask path" (POSSIBLE_* block by default, per-span choice) and the measured false-block rate."""
import os
import tempfile
import unittest
from pathlib import Path

from anonymizer import chat_pipeline, guard
from anonymizer.service import Service
from anonymizer.vault import Vault

from .ai_prompts_sample import EN, RU

SQL = "Напиши SQL-запрос, который выбирает десять самых крупных заказов за прошлый месяц."


class AskPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(Path(self.tmp.name) / "v.bin", key=os.urandom(32))
        self.pipe = chat_pipeline.ChatPipeline(Service(self.vault, Path(self.tmp.name) / "w"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_false_block_rate_on_ordinary_prompts(self):
        rates = {}
        for name, rows in (("RU", RU), ("EN", EN)):
            blocked = sum(1 for t in rows if self.pipe.prepare(t).guard.blocked)
            rates[name] = (blocked, len(rows))
        print(f"\n[ask-path false-block] RU {rates['RU'][0]}/{rates['RU'][1]}  EN {rates['EN'][0]}/{rates['EN'][1]}")
        self.assertLessEqual(rates["RU"][0] / rates["RU"][1], 0.10)
        self.assertLessEqual(rates["EN"][0] / rates["EN"][1], 0.10)

    def test_possible_blocks_then_allow_once_passes_only_that_call(self):
        first = self.pipe.prepare(SQL)
        self.assertTrue(first.guard.blocked)
        ids = [f["id"] for f in first.guard.findings if f["possible"]]
        self.assertTrue(ids)
        allowed = self.pipe.prepare(SQL, resolve={"allow": ids})
        self.assertFalse(allowed.guard.blocked)
        self.assertTrue(self.pipe.prepare(SQL).guard.blocked)          # nothing was remembered

    def test_anonymize_it_replaces_the_span_with_a_label(self):
        first = self.pipe.prepare(SQL)
        ids = [f["id"] for f in first.guard.findings if f["possible"]]
        masked = self.pipe.prepare(SQL, resolve={"anonymize": ids})
        self.assertFalse(masked.guard.blocked)
        self.assertNotEqual(masked.text, first.text)
        self.assertNotIn("SQL", masked.text)

    def test_definite_hit_cannot_be_allowed(self):
        detector = self.pipe.service.build_detector(self.pipe.service.settings_for({}))
        text = "Call +7 913 555-12-34 tomorrow"
        first = guard.check([text], self.vault, detector)
        self.assertTrue(first.blocked)
        again = guard.check([text], self.vault, detector, allow=[f["id"] for f in first.findings])
        self.assertTrue(again.blocked)

    def test_finding_ids_carry_no_values(self):
        first = self.pipe.prepare(SQL)
        for f in first.guard.findings:
            self.assertNotIn("SQL", f["id"])


if __name__ == "__main__":
    unittest.main()
