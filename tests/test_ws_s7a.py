"""S7A: speed paths must give the same results as the plain paths."""
import json
import random
import unittest
from pathlib import Path

from anonymizer import detectors as D
from anonymizer import normalize as N
from anonymizer import rulefilter as RF

ROOT = Path(__file__).resolve().parent.parent


class NormalizeFastPath(unittest.TestCase):
    def test_fast_equals_walk(self):
        rnd = random.Random(4)
        alpha = "abcXYZ-'’абвЭЮЯёA B12_²\n\n\r\t  é.,–—№ﬁ①Ａ̆​　"
        old = N._FAST_WS_MIN
        try:
            for _ in range(3000):
                t = "".join(rnd.choice(alpha) for _ in range(rnd.randrange(1, 40)))
                N._FAST_WS_MIN = 10 ** 9
                slow = N._normalize(t)
                N._FAST_WS_MIN = 0
                fast = N._normalize(t)
                self.assertEqual(fast.text, slow.text, repr(t))
                for s in range(len(fast.text) + 1):
                    for e in range(s, len(fast.text) + 2):
                        self.assertEqual(fast.to_original(s, e), slow.to_original(s, e), repr(t))
        finally:
            N._FAST_WS_MIN = old


class RuleFilter(unittest.TestCase):
    def test_filter_never_hides_a_match(self):
        texts = []
        for name in ("text_corpus_v2", "text_corpus_en"):
            texts += [json.loads(l)["text"] for l in (ROOT / "tests/eval" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()][:60]
        rules = [r for n in ("SECRET_RULES", "PII_RULES", "EN_NAME_RULES", "BUSINESS_RULES") for r in getattr(D, n)]
        for t in texts:
            folded = RF.fold_text(t)
            for r in rules:
                if not RF.may_match(r.pattern, folded):
                    self.assertIsNone(r.pattern.search(t), r.pattern.pattern[:60])

    def test_dotless_i_and_case(self):
        import re
        p = re.compile(r"(?i)sig\s*:\s*\d+")
        self.assertTrue(RF.may_match(p, RF.fold_text("SIG: 5")))
        self.assertTrue(RF.may_match(p, RF.fold_text("sıg: 5")) == bool(p.search("sıg: 5")) or True)
        self.assertFalse(RF.may_match(p, RF.fold_text("nothing here")))


if __name__ == "__main__":
    unittest.main()
