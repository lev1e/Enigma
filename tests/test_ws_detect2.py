"""Regression tests for the per-kind quality pass (corpus v2): lookalike numbers, Latin names, EN/UK addresses, labels."""
from __future__ import annotations

import time
import unittest

from tests.helpers import Env


class DetectV2(unittest.TestCase):
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

    def cats(self, text: str, category: str):
        return [o for c, o in self.found(text) if c == category]

    def test_version_numbers_are_not_ip(self):
        for text in ("Версия 10.2.3.4 ПО.", "Раздел 2.3.4.5 положения.", "Модель 1.2.3.4 серии."):
            self.assertEqual(self.cats(text, "IP_ADDRESS"), [], text)
        self.assertEqual(self.cats("Сервер 192.168.10.25 недоступен.", "IP_ADDRESS"), ["192.168.10.25"])

    def test_codes_and_amounts_are_not_phone_or_snils(self):
        for text in ("Код ТН ВЭД 8517130000 применяется.", "Сумма 11713348834 рублей.", "Артикул 4601234567890 штрихкод."):
            found = self.found(text)
            self.assertFalse([1 for c, _ in found if c in {"PHONE", "SNILS", "INN_ORG", "INN_PERSON"}], f"{text} {found}")
        self.assertEqual(self.cats("Мой номер 89161234567.", "PHONE"), ["89161234567"])

    def test_plain_digit_table_number_is_not_phone(self):
        self.assertEqual(self.cats("GDP 81658052383 USD", "PHONE"), [])

    def test_latin_initials_names(self):
        self.assertIn(("PERSON", "J. Whitfield"), self.found("Подписал J. Whitfield лично."))
        self.assertIn(("PERSON", "Whitfield J."), self.found("Подписал Whitfield J. лично."))
        self.assertFalse(self.cats("The U.S. Government said", "PERSON"))
        self.assertFalse(self.cats("See Section A. for details", "PERSON"))

    def test_english_addresses_and_uk_plate(self):
        self.assertEqual(self.cats("Ship to 742 Evergreen Terrace, Springfield, OR 97477.", "ADDRESS"),
                         ["742 Evergreen Terrace, Springfield, OR 97477"])
        self.assertEqual(self.cats("Mail: 10 Downing Street, London SW1A 2AA.", "ADDRESS"), ["10 Downing Street, London SW1A 2AA"])
        self.assertEqual(self.cats("Plate AB12 CDE seen.", "VEHICLE_PLATE"), ["AB12 CDE"])

    def test_labels_tin_nick_invoice_driver_licence(self):
        self.assertTrue([1 for c, _ in self.found("TIN: 7707083893") if c.startswith("INN")])
        self.assertEqual(self.cats("GitHub: octo-cat42", "USERNAME"), ["octo-cat42"])
        self.assertEqual(self.cats("Ник dark_wolf_77 в игре.", "USERNAME"), ["dark_wolf_77"])
        self.assertTrue(self.cats("По счёту № 1203-17 оплачено.", "CONTRACT"))
        self.assertTrue(self.cats("Права 77 12 345678 категории B.", "DRIVER_LICENSE"))

    def test_cms_names_are_not_projects(self):
        self.assertFalse(self.cats("Платформа WordPress и Битрикс известны.", "PROJECT"))

    def test_large_text_is_not_quadratic(self):
        line = "ООО «Ромашка», г. Тверь, ул. Мира, д. 5; Иван Петров, тел. +7 (916) 123-45-67, договор №%d\n"

        def run(n):
            text = "".join(line % i for i in range(n))
            d = self.env.service.build_detector(self.env.service.settings_for({}))
            t = time.time()
            d.harvest(text, "x.txt")
            d.scan(text, "x.txt", "text")
            return time.time() - t

        small, big = run(1500), run(6000)
        self.assertLess(big, small * 7, f"1500 lines {small:.1f}s, 6000 lines {big:.1f}s: more than linear + slack")


if __name__ == "__main__":
    unittest.main()
