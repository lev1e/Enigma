import unittest

from anonymizer import formats
from tests.helpers import Env


class HugeTreeBounded(unittest.TestCase):
    def test_deep_nesting_part_fails_closed(self):
        raw = b"<a>" + b"<b>" * 5000 + b"x" + b"</b>" * 5000 + b"</a>"
        self.assertIsNone(formats.parse_part("word/document.xml", raw))

    def test_normal_part_parses(self):
        raw = b"<a><b>\xd0\x98\xd0\xb2\xd0\xb0\xd0\xbd</b></a>"
        self.assertIsNotNone(formats.parse_part("word/document.xml", raw))


def detect(text):
    env = Env()
    d = env.service.build_detector(env.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


class OrgCue(unittest.TestCase):
    def test_company_cue_org(self):
        for text, org in (("Договор с компанией Техноград расторгнут.", "Техноград"),
                          ("Мы заключили договор с фирмой Вектория на поставку.", "Вектория")):
            hits = [f for f in detect(text) if f.original == org and f.decision.value == "AUTO"]
            self.assertTrue(hits, text)
            self.assertEqual(hits[0].category, "ORG")

    def test_plain_prose_not_org(self):
        text = "Эта компания работает давно, а новая фирма Москва пока молчит."
        self.assertFalse([f for f in detect(text) if f.category == "ORG" and f.original == "Москва"])


if __name__ == "__main__":
    unittest.main()
