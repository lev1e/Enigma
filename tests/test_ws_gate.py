"""W6: quality-gate comparison logic, noise corpus presence, eval_real needle fix. Pure logic, no detector runs."""
import sys
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import quality_gate as qg          # noqa: E402

TEXT = {"gold": 100, "full": 98, "partial": 0, "miss": 2, "wrongcat": 5, "leak": 2, "fp": 1, "failing_kinds": []}


class CompareTests(unittest.TestCase):
    def test_equal_passes(self):
        bad, _ = qg.compare("text_v1", dict(TEXT), TEXT, False)
        self.assertEqual(bad, [])

    def test_leak_increase_fails(self):
        cur = dict(TEXT, leak=3, miss=3)
        bad, _ = qg.compare("text_v1", cur, TEXT, False)
        self.assertTrue(any("leak" in b for b in bad))

    def test_fp_within_budget_passes_beyond_fails(self):
        self.assertEqual(qg.compare("text_en", dict(TEXT, fp=3), TEXT, False)[0], [])
        self.assertTrue(qg.compare("text_en", dict(TEXT, fp=4), TEXT, False)[0])

    def test_new_failing_kind_fails(self):
        self.assertTrue(qg.compare("text_v2", dict(TEXT, failing_kinds=["ORG"]), TEXT, False)[0])

    def test_noise_replacement_fails(self):
        self.assertTrue(qg.compare("noise", {"files": 14, "replaced": 1, "files_hit": 1}, {"files": 14, "replaced": 0, "files_hit": 0}, False)[0])

    def test_refusals_tracked_separately(self):
        base = {"cases": 16, "leaked_values": 0, "blocked": 0, "restore_exact": 16}
        cur = dict(base, blocked=2)
        self.assertTrue(qg.compare("images", cur, base, False)[0])
        bad, notes = qg.compare("images", cur, base, True)
        self.assertEqual(bad, [])
        self.assertTrue(any("REFUSALS" in n for n in notes))

    def test_restore_equality_drop_fails(self):
        base = {"cases": 2, "missing": [], "gold": 10, "leaked": 0, "leaking_cases": [], "refused": 0, "crashed": 0, "fp_strings": 10, "restore_content_equal": 2}
        self.assertTrue(qg.compare("real", dict(base, restore_content_equal=1), base, False)[0])
        self.assertTrue(qg.compare("real", dict(base, leaked=1, leaking_cases=["x"]), base, False)[0])

    def test_missing_baseline_and_error_fail_closed(self):
        self.assertTrue(qg.compare("noise", {"files": 1, "replaced": 0, "files_hit": 0}, {}, False)[0])
        self.assertTrue(qg.compare("noise", {"error": "boom"}, {"replaced": 0}, False)[0])


class NoiseCorpusTests(unittest.TestCase):
    def test_noise_files_exist_ru_and_en(self):
        names = [p.name for p in (ROOT / "tests" / "eval" / "noise").iterdir()]
        self.assertGreaterEqual(len(names), 12)
        self.assertTrue(any(n.endswith("_ru.txt") for n in names) and any(n.endswith("_en.txt") for n in names))


class EvaluationIsolationTests(unittest.TestCase):
    def test_gate_triage_receives_only_current_pinned_results(self):
        current = {"id": "current", "gold": 1, "cats": {"PERSON": [1, 1]}}
        stale = {"id": "stale", "gold": 999, "cats": {"PERSON": [999, 999]}}
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "results.json"
            def run_subset(*args):
                results.write_text(json.dumps([stale, current]))
                return ""
            with patch.object(qg, "REAL_PINNED", ["current"]), patch.object(qg, "sh", side_effect=run_subset):
                measured = qg.m_real(2, results)
            self.assertEqual(json.loads(results.read_text()), [current])
            self.assertEqual(measured["cases"], 1)
            self.assertEqual(measured["leaked"], 1)
            self.assertEqual(measured["leaking_cases"], ["current"])

    def test_original_view_uses_shared_corpus_directory(self):
        import eval_real
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp)
            case = corpus / "public_case"
            case.mkdir()
            (case / "source.txt").write_text("Synthetic natural phrase.")
            with patch.object(eval_real, "REAL", corpus):
                self.assertEqual(eval_real.original_view({"id": "public_case", "source": "real"}, "txt"),
                                 eval_real.canon("Synthetic natural phrase."))


class NeedleTests(unittest.TestCase):
    def setUp(self):
        import eval_real
        self.er = eval_real

    def test_surname_only_needle_when_surname_not_in_base(self):
        self.assertEqual(self.er.needles("PERSON", "Grace R. Lindqvist", "someotherdocument"), ["lindqvist"])

    def test_ambiguous_surname_uses_full_name(self):
        base = self.er.canon("Thanks to Bjorn Lindqvist and Grace R. Lindqvist")
        self.assertEqual(self.er.needles("PERSON", "Grace R. Lindqvist", base), [self.er.canon("Grace R. Lindqvist")])

    def test_injected_only_surname_stays_surname(self):
        base = self.er.canon("Grace R. Lindqvist")
        self.assertEqual(self.er.needles("PERSON", "Grace R. Lindqvist", base), ["lindqvist"])


class NaturalWordLeakTests(unittest.TestCase):
    """The leak check must not flag natural words that contain an injected value, and must still flag real leaks."""
    def setUp(self):
        import eval_real
        self.er = eval_real
        self.c = eval_real.canon

    def leaked(self, cat, value, out, orig, injected=""):
        return self.er.is_leaked(cat, value, self.c(out), self.c(orig + injected), self.c(orig))

    def test_natural_word_is_not_a_leak(self):
        orig = "Зарубежные партнёры."
        inj = " Компания Рубеж подписала договор."
        self.assertFalse(self.leaked("ORG", "Рубеж", "Зарубежные партнёры. Компания Company1 подписала договор.", orig, inj))

    def test_real_leak_next_to_natural_word_is_detected(self):
        orig = "Зарубежные партнёры."
        inj = " Компания Рубеж подписала договор."
        self.assertTrue(self.leaked("ORG", "Рубеж", orig + inj, orig, inj))

    def test_leak_without_natural_occurrence_is_detected(self):
        orig = "Текст."
        inj = " Адрес: ул. Мира 5"
        self.assertTrue(self.leaked("ADDRESS", "Мира", orig + inj, orig, inj))
        self.assertFalse(self.leaked("ADDRESS", "Мира", "Текст. Адрес: Address1", orig, inj))

    def test_natural_phrase_kept_injected_replaced(self):
        orig = "Вознесенская церковь."
        inj = " ул. Вознесенская, д. 30"
        self.assertFalse(self.leaked("ADDRESS", "Вознесенская", "Вознесенская церковь. Address1", orig, inj))
        self.assertTrue(self.leaked("ADDRESS", "Вознесенская", "Вознесенская церковь. ул. Вознесенская, д. 30", orig, inj))

    def test_without_original_old_rule(self):
        self.assertTrue(self.er.is_leaked("ORG", "Рубеж", self.c("зарубежные"), self.c("зарубежные Рубеж"), ""))


if __name__ == "__main__":
    unittest.main()
