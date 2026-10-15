"""English detection regressions: people (cues, middle initial, comma form, e-mail header, salutation), organisations (org nouns,
legal forms, label cues), US/UK postal addresses, birth dates, bare passport numbers, and negatives that must stay untouched."""
from __future__ import annotations

import unittest

from tests.helpers import Env


class DetectEnglish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def found(self, text: str):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        d.harvest(text, "x.txt")
        return [(f.category, f.original) for f in d.scan(text, "x.txt", "text") if f.decision.value == "AUTO"]

    def has(self, text: str, category: str, value: str):
        self.assertIn(value, [o for c, o in self.found(text) if c == category], (text, self.found(text)))

    def none(self, text: str, *categories: str):
        self.assertFalse([1 for c, o in self.found(text) if c in categories], (text, self.found(text)))

    def test_person_shapes(self):
        for text, name in (("Contact: Grace T. Okonkwo today", "Grace T. Okonkwo"), ("Mr. Marcus Lindqvist signed", "Marcus Lindqvist"),
                           ("Name\tOliver E. Haverford\t555", "Oliver E. Haverford"), ("alt. contact Haverford, Oliver", "Haverford, Oliver"),
                           ("From: Priya Raman <priya@demo.example.com>", "Priya Raman"), ("Dear Priya, thanks", "Priya"),
                           ("Prepared by Yuki D. Underhill", "Yuki D. Underhill"), ("APPLICANT: MARCUS A. LINDQVIST", "MARCUS A. LINDQVIST"),
                           ("Regards,\nJohn Whitfield", "John Whitfield"), ("Copy Marcus Vandermeer on it", "Marcus Vandermeer")):
            self.has(text, "PERSON", name)

    def test_person_negatives(self):
        for text in ("Section A. Overview", "See Table 3 and Figure 2 for the Annual Report", "Grace Period applies to the Payment Terms",
                     "Customer Support Group meets on Monday"):
            self.none(text, "PERSON")

    def test_organisations(self):
        for text, org in (("Invoice from Northwind Holdings today", "Northwind Holdings"), ("Paid to Redwood Ferris Logistics.", "Redwood Ferris Logistics"),
                          ("Company: Orchard Lane Partners", "Orchard Lane Partners"), ("She works for Halcyon Dynamics in the city", "Halcyon Dynamics"),
                          ("Harbor Point Capital LLC owns it", "Harbor Point Capital LLC"), ("University of Oxford press", "University of Oxford")):
            self.has(text, "ORG", org)

    def test_org_negatives(self):
        for text in ("Send it to Springfield, Halifax and Leeds", "The Project Management Group will meet", "Applicant: Jane"):
            self.none(text, "ORG")

    def test_addresses(self):
        for text, addr in (("1450 Maple Avenue, Suite 12, Springfield, IL 62704", "1450 Maple Avenue, Suite 12, Springfield, IL 62704"),
                           ("Lives at 221B Baker Street, London NW1 6XE", "221B Baker Street, London NW1 6XE"),
                           ("Meet on Fenwick Street", "Fenwick Street")):
            self.has(text, "ADDRESS", addr)

    def test_birth_dates_and_passports(self):
        for text, val in (("born 03/14/1985 in Ohio", "03/14/1985"), ("DOB: 1985-03-14", "1985-03-14"), ("born on March 14, 1985", "March 14, 1985"),
                          ("Date of birth: 14 March 1985", "14 March 1985")):
            self.has(text, "BIRTH_DATE", val)
        for text, val in (("Passport No. 340899782", "340899782"), ("passport: B97369255", "B97369255"), ("Passport number is C35215715", "C35215715")):
            self.has(text, "PASSPORT", val)


if __name__ == "__main__":
    unittest.main()
