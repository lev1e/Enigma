"""English detection round 2: cities in free text, Latin initials/hyphen names, US/UK phones, luhn card, IP after «Server», clean prose."""
import unittest

from tests.helpers import Env

_E = Env()


def auto(text):
    d = _E.service.build_detector(_E.service.settings_for({}))
    d.harvest(text, "x.txt")
    return [(f.category, f.original) for f in d.scan(text, "x.txt", "text") if f.decision.value == "AUTO"]


class EnglishRound2(unittest.TestCase):
    def hit(self, text, cat, value):
        self.assertIn((cat, value), auto(text), text)

    def test_city_free_text(self):
        self.hit("She moved to Leeds last spring.", "CITY", "Leeds")
        self.hit("We ship from Austin to Denver and Boston.", "CITY", "Boston")
        self.hit("City: Glasgow", "CITY", "Glasgow")
        self.hit("Offices: Leeds, Bristol and Cardiff.", "CITY", "Cardiff")
        self.hit("The Sheffield office closes at five.", "CITY", "Sheffield")
        self.hit("LEEDS — The council approved the plan.", "CITY", "LEEDS")

    def test_city_not_overreaching(self):
        for t in ("Reading the report took an hour.", "Mobile phones are banned.", "Mark the box and send it to Will.", "Grant funding resumes in May."):
            self.assertEqual([x for x in auto(t) if x[0] == "CITY"], [], t)

    def test_latin_names(self):
        self.hit("Then F.S. McAllister agreed.", "PERSON", "F.S. McAllister")
        self.hit("Witness: O'Connell, Terrence, DOB 1951", "PERSON", "O'Connell, Terrence")
        self.hit("Please send it to REBECCA ABERNATHY at the office.", "PERSON", "REBECCA ABERNATHY")
        self.hit("countersigned by Anna-Marie Smith-Jones.", "PERSON", "Anna-Marie Smith-Jones")
        self.hit("Thanks, Bob.", "PERSON", "Bob")

    def test_phones_and_ids(self):
        self.hit("Fax: 617.555.9512", "PHONE", "617.555.9512")
        self.hit("Call 020 7946 0160 today", "PHONE", "020 7946 0160")
        self.hit("Contact (555-617-8005)", "PHONE", "555-617-8005")
        self.hit("Server 10.141.109.55 is reachable via VPN.", "IP_ADDRESS", "10.141.109.55")
        self.hit("Card on file: 4111111111111111, exp 09/29.", "CARD", "4111111111111111")
        self.hit("with user admin and password Rv806!kd5421Pm on the box", "SECRET", "Rv806!kd5421Pm")

    def test_address(self):
        self.hit("Ship to 3293 Harcourt Terrace, Apt 22A, Columbus, OH.", "ADDRESS", "3293 Harcourt Terrace, Apt 22A, Columbus, OH")
        self.hit("Registered office: 606 Kingsway, Leeds LS1 4AP", "ADDRESS", "606 Kingsway, Leeds LS1 4AP")

    def test_clean_prose_stays(self):
        t = ("Quarterly Report: the Board will meet on Monday to review the Annual Plan. Read the Terms of Service first. "
             "Install the package, open the Settings page and press Save. Hope this helps. The Control Panel shows System Status.")
        self.assertEqual(auto(t), [])


if __name__ == "__main__":
    unittest.main()
