"""Имя листа Excel короче 31 знака: отчество в нём обрезано («Смирнов Алексей Петрови»). Остаток не должен остаться открытым."""
import re
import unittest

from .helpers import Env, xlsx_bytes, zip_text

PERSON = "Смирнов Алексей Петрович"
SHEET = ("Скрытый " + PERSON)[:31]          # Excel не принимает больше 31 знака


class TruncatedPatronymic(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def sheet_names(self, data):
        return re.findall(r'<sheet [^>]*? name="([^"]*)"', zip_text(data))

    def test_cut_patronymic_in_a_sheet_name_is_hidden_with_the_whole_name(self):
        data = xlsx_bytes({"A1": "ФИО", "A2": PERSON}, extra_sheets={SHEET: {"A1": 1}})
        self.assertEqual(self.sheet_names(data)[1], SHEET)
        job = self.env.anonymize(("a.xlsx", data), options={"numbers": False})
        names = self.sheet_names(self.env.output_bytes(job))
        self.assertEqual(len(names), 2, names)
        for fragment in ("Смирнов", "Алексей", "Петр"):
            self.assertNotIn(fragment, names[1])
        self.assertTrue(names[1].startswith("Скрытый Name"), names[1])

    def test_unrelated_capitalised_word_after_a_name_stays(self):
        data = xlsx_bytes({"A1": "ФИО", "A2": PERSON}, extra_sheets={"Смирнов Алексей Квартал": {"A1": 1}})
        job = self.env.anonymize(("a.xlsx", data), options={"numbers": False})
        self.assertIn("Квартал", self.sheet_names(self.env.output_bytes(job))[1])


if __name__ == "__main__":
    unittest.main()
