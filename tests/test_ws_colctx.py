"""Column-header context: bare passport / birth date / tax id / city values in table columns (csv, xlsx, docx, pptx, markdown), RU and EN."""
from __future__ import annotations

import unittest

from tests.helpers import Env, docx_bytes, docx_text, pptx_bytes, xlsx_bytes, zip_text

EN = [["Employee", "Passport No", "Date of Birth", "SSN", "Tax ID", "City"],
      ["Marcus Lindqvist", "X1234567", "14/03/1985", "123-45-6789", "98-7654321", "Leeds"],
      ["Grace Okonkwo", "C9876543", "1990-07-22", "987-65-4321", "12-3456789", "Boston"],
      ["Oliver Haverford", "123456789", "03/03/1978", "111-22-3333", "55-1234567", "Denver"]]
EN_SECRETS = ["X1234567", "C9876543", "123456789", "14/03/1985", "1990-07-22", "03/03/1978", "123-45-6789", "987-65-4321",
              "111-22-3333", "98-7654321", "12-3456789", "55-1234567", "Leeds", "Boston", "Denver"]
RU = [["Сотрудник", "Паспорт", "Дата рождения", "ИНН", "Город"],
      ["Орлов Максим Сергеевич", "4512 345678", "14.03.1985", "770708389312", "Липецк"],
      ["Громова Анна Ивановна", "4613 987654", "22.07.1990", "500100732259", "Курск"],
      ["Фролов Пётр Андреевич", "4714 111222", "03.03.1978", "780123456789", "Тверь"]]
RU_SECRETS = ["4512 345678", "4613 987654", "4714 111222", "14.03.1985", "22.07.1990", "03.03.1978", "770708389312", "500100732259",
              "780123456789", "Липецк", "Курск", "Тверь"]


def grid_xlsx(rows):
    return xlsx_bytes({f"{chr(65 + c)}{r + 1}": v for r, row in enumerate(rows) for c, v in enumerate(row)}, title="Staff")


class ColumnContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def text_of(self, name, data):
        job = self.env.anonymize((name, data))
        out = self.env.output_bytes(job)
        if name.endswith((".csv", ".md", ".txt")):
            text = out.decode()
        elif name.endswith(".xlsx"):
            text = zip_text(out)
        elif name.endswith(".pptx"):
            text = zip_text(out)
        else:
            text = docx_text(out)
        return job, text

    def check(self, name, data, secrets):
        job, text = self.text_of(name, data)
        self.assertEqual([s for s in secrets if s in text], [], name)
        return job

    def test_english_tables(self):
        csv = "\n".join(",".join(r) for r in EN)
        for name, data in (("e.csv", csv), ("e.xlsx", grid_xlsx(EN)), ("e.docx", docx_bytes(["Staff"], table=EN)),
                           ("e.md", "| " + " | ".join(EN[0]) + " |\n|---|---|---|---|---|---|\n" +
                            "\n".join("| " + " | ".join(r) + " |" for r in EN[1:]))):
            self.check(name, data, EN_SECRETS)

    def test_russian_tables(self):
        csv = "\n".join(";".join(r) for r in RU)
        for name, data in (("r.csv", csv), ("r.xlsx", grid_xlsx(RU)), ("r.docx", docx_bytes(["Список"], table=RU))):
            self.check(name, data, RU_SECRETS)

    def test_restore_is_exact(self):
        csv = "\n".join(",".join(r) for r in EN)
        job = self.env.anonymize(("e.csv", csv))
        back = self.env.restore(self.env.as_upload(job))
        self.assertEqual(self.env.output_bytes(back).decode().strip(), csv.strip())

    def test_other_headers_untouched(self):
        rows = [["Invoice date", "Order No", "Region"], ["14/03/2025", "A-100234", "Remote"], ["15/03/2025", "A-100235", "Remote"]]
        csv = "\n".join(",".join(r) for r in rows)
        _, text = self.text_of("n.csv", csv)
        for value in ("14/03/2025", "A-100234", "Remote"):
            self.assertIn(value, text)

    def test_place_stoplist(self):
        rows = [["Name", "City"], ["Remote", "Remote"], ["Anna Kovalenko", "N/A"], ["Pavel Orlov", "HQ"]]
        _, text = self.text_of("p.csv", "\n".join(",".join(r) for r in rows))
        for value in ("Remote", "N/A", "HQ"):
            self.assertIn(value, text)

    def test_value_repeated_outside_column(self):
        csv = "Name,Passport No\nMarcus Lindqvist,X1234567\n"
        job, text = self.text_of("m.csv", csv)
        self.assertNotIn("X1234567", text)


if __name__ == "__main__":
    unittest.main()
