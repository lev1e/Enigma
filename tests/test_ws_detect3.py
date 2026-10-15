"""Regression tests for the second per-kind quality pass: labelled INN variants, nicknames after imperatives, oriental names,
street after a bare city, sub-domains of company domains, contract numbers glued to the sign, PII-ish text, CSV column logic."""
from __future__ import annotations

import unittest

from tests.helpers import Env


class DetectV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def found(self, text: str, name: str = "x.txt"):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        d.harvest(text, name)
        return [(f.category, f.original) for f in d.scan(text, name, "text") if f.decision.value == "AUTO"]

    def cats(self, text: str, *categories: str):
        return [o for c, o in self.found(text) if c in categories]

    def test_labelled_inn_variants(self):
        for text, value in (("ИНН: 7707 083 893", "7707 083 893"), ("ИНН 77 07 083893", "77 07 083893"),
                            ("ИНН 500 100 732 259", "500 100 732 259"), ("Tax ID: 7707083893", "7707083893"),
                            ("Taxpayer Identification Number: 7707083893", "7707083893"),
                            ("Идентификационный номер налогоплательщика 7707083893", "7707083893"),
                            ("ИНН/КПП 7707083893/770701001", "7707083893")):
            self.assertEqual(self.cats(text, "INN_ORG", "INN_PERSON"), [value], text)
            self.assertFalse(self.cats(text, "PASSPORT"), text)
        self.assertEqual(self.cats("ИНН (КПП): 7707083893 (770701001)", "KPP"), ["770701001"])
        self.assertEqual(self.cats("ИНН, КПП: 7707083893, 770701001", "KPP"), ["770701001"])

    def test_bare_checksum_number_is_still_not_inn(self):
        self.assertFalse(self.cats("Номер заказа 7707083893 принят.", "INN_ORG", "INN_PERSON"))

    def test_contract_number_glued_to_sign(self):
        self.assertEqual(self.cats("Контракт №ДП-778 подписан.", "CONTRACT"), ["ДП-778"])
        self.assertEqual(self.cats("Договор №123 подписан.", "CONTRACT"), ["123"])

    def test_nickname_after_imperative(self):
        for text, name in (("Позвони Саша и узнай.", "Саша"), ("Позвони Серёга и узнай.", "Серёга"),
                           ("Позвони Димон и узнай.", "Димон"), ("Попроси Тоню, она знает.", "Тоню"),
                           ("Звонил Витя из бухгалтерии.", "Витя")):
            self.assertEqual(self.cats(text, "PERSON"), [name], text)
        self.assertFalse(self.cats("Передай Договор в бухгалтерию.", "PERSON"))

    def test_oglu_and_vietnamese_names(self):
        self.assertEqual(self.cats("Мамедов Эльчин Рашид оглы подписал.", "PERSON"), ["Мамедов Эльчин Рашид оглы"])
        self.assertEqual(self.cats("Доверенное лицо — Нгуен Ван Тханг.", "PERSON"), ["Нгуен Ван Тханг"])

    def test_street_after_bare_city(self):
        found = self.found("Казань, пр. Победы, 15-41")
        self.assertIn(("ADDRESS", "пр. Победы, 15-41"), found)
        self.assertIn(("CITY", "Казань"), found)

    def test_company_subdomain_hidden_whole(self):
        self.assertEqual(self.cats("Откройте https://crm.nordlicht-handel.de/login", "DOMAIN")[0].split("/")[0], "crm.nordlicht-handel.de")
        self.assertEqual(self.cats("Адрес http://intranet.vektor-m.com", "DOMAIN"), ["intranet.vektor-m.com"])
        self.assertFalse(self.cats("Смотрите docs.google.com", "DOMAIN"))

    def csv_found(self, text: str):
        from anonymizer.textstruct import Structure
        st = Structure(text, ".csv")
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        d.harvest(st.masked, "a.csv")
        return [(f.category, f.original) for f in st.clip(st.column_filter(d.scan(st.masked, "a.csv", "text")))
                if f.decision.value == "AUTO"]

    def test_csv_numeric_and_code_columns(self):
        rows = "".join(f"Land{i},XY{i % 9},{2000 + i},{80000000000 + i * 1234567891}.5\n" for i in range(8))
        found = self.csv_found("Country,ISO,Year,GDP\n" + rows)
        self.assertFalse([c for c, _ in found if c in {"PHONE", "SNILS", "CARD", "INN_ORG", "INN_PERSON", "ORG"}], found)

    def test_csv_labelled_phone_column_is_kept(self):
        found = self.csv_found("Name,Телефон\n" + "".join(f"A{i},8916123456{i}\n" for i in range(5)))
        self.assertTrue([1 for c, _ in found if c == "PHONE"], found)

    def test_csv_text_after_closing_quote_is_scanned(self):
        found = self.csv_found('a,b\n1,2\n"Applicant: Ivan";"Email: ivan.petrov22@demo-mail.example.com"\n')
        self.assertIn(("EMAIL", "ivan.petrov22@demo-mail.example.com"), found)


if __name__ == "__main__":
    unittest.main()
