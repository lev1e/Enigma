"""Orchestrator shift 4: regression tests for fixes made while bringing main green."""
import unittest

from tests.helpers import Env, visible


class OrgAfterCueIsLearnedTests(unittest.TestCase):
    TEXT = ("Договор подписан. Стороны: заказчик и поставщик.\n"
            "Поставщик Квантекс отвечает за доставку.\n"
            "Позже, с компанией Квантекс согласован график.\n")

    def test_mention_without_cue_is_replaced_too(self):
        env = Env()
        try:
            job = env.anonymize(("o.txt", self.TEXT))
            out = visible(env.output(job).read_text(encoding="utf-8"))
            self.assertNotIn("Квантекс", out)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
