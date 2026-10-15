"""W6c: eval harness fixes (html injection without a missing-image reference, worktree-safe case dir, results path) and CI skip guards."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


class HtmlInjectionTests(unittest.TestCase):
    def test_html_injection_has_no_image_reference(self):
        import eval_inject
        import inspect
        src = inspect.getsource(eval_inject)
        self.assertNotIn('<img src="x.png"', src)

    def test_html_injection_keeps_alt_value_on_non_image_element(self):
        import eval_inject
        from eval_ids import dense
        pack = dense("w6c_probe", "en")
        out = eval_inject.inject("html", b"<html><head></head><body><p>x</p></body></html>", pack, "").decode("utf-8")
        self.assertNotIn("<img", out)
        self.assertIn('aria-label="', out)


class CasesDirTests(unittest.TestCase):
    def test_symlinked_cases_dir_is_replaced_not_followed(self):
        import eval_real
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            shared = t / "shared_cases"; shared.mkdir(); (shared / "keep.txt").write_text("x")
            real = t / "real"; real.mkdir()
            link = real / "_cases"; link.symlink_to(shared, target_is_directory=True)
            old = eval_real.CASES
            eval_real.CASES = link
            try:
                eval_real._reset_cases()
            finally:
                eval_real.CASES = old
            self.assertFalse(link.is_symlink())
            self.assertTrue(link.is_dir())
            self.assertTrue((shared / "keep.txt").exists(), "shared corpus must not be touched")


class ResultsPathTests(unittest.TestCase):
    def test_default_results_path_is_not_the_tracked_file(self):
        import os
        if os.environ.get("EVAL_RESULTS"):
            self.skipTest("EVAL_RESULTS set")
        import eval_real
        self.assertNotEqual(eval_real.RESULTS, eval_real.TRACKED_RESULTS)
        self.assertEqual(eval_real.RESULTS.parent.name, "real")


class GuardTests(unittest.TestCase):
    def test_guard_decision_matches_environment(self):
        from tests import _guards
        self.assertIsInstance(_guards.has_pywebview(), bool)


if __name__ == "__main__":
    unittest.main()
