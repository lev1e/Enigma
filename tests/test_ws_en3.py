"""English round 3: column context in txt/pdf tables, ordinal dates, hyphenated surnames, caps dateline city, P.O. Box, common-word false positives."""
import unittest

from tests.helpers import Env


def scan(text):
    env = Env()
    d = env.service.build_detector(env.service.settings_for({}))
    d.harvest(text, "x.txt")
    return [(f.category, f.original.strip()) for f in d.scan(text, "x.txt", "text") if f.decision.value == "AUTO"]


class EnglishRound3(unittest.TestCase):
    def test_hyphen_apostrophe_surname(self):
        self.assertIn(("PERSON", "Jean-Paul Underhill-O'Connell"), scan("The contract was countersigned by Jean-Paul Underhill-O'Connell. Next."))

    def test_caps_dateline_city(self):
        self.assertIn(("CITY", "SACRAMENTO"), scan("SACRAMENTO · The city council approved the plan on Tuesday."))

    def test_po_box_is_address_not_person(self):
        found = scan("Write to us at P.O. Box 7444, Pittsburgh, TX 78701. Thanks.")
        self.assertEqual([c for c, _ in found], ["ADDRESS"])

    def test_common_words_stay(self):
        found = scan("Take Vitamin D. Today is fine. See Plan B. Yesterday we left. I. The keyword is found. He said \"True\" and raised \"TypeError\".")
        self.assertEqual(found, [])

    def test_html_secret_with_entity_fully_hidden(self):
        found = scan("Login with user admin and password Tr0ub4dor&amp;64x on the staging box.")
        self.assertTrue(any(c == "SECRET" and o.endswith("64x") for c, o in found), found)

    def test_passport_token_not_a_passport(self):
        self.assertNotIn("PASSPORT", [c for c, _ in scan("Passport: Passport1, expires 2031.")])


if __name__ == "__main__":
    unittest.main()
