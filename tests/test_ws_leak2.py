"""Leak sweep 09.10: real output files are unzipped and grepped for every original sensitive value, then restored and compared."""
from __future__ import annotations

import datetime
import io
import unittest
import zipfile

from openpyxl import Workbook, load_workbook

from tests.helpers import Env


def all_parts(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return "\n".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist())


def numeric_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Staff"
    ws.append(["Сотрудник", "ИНН", "Паспорт", "Дата рождения", "СНИЛС", "Карта", "Оклад"])
    ws.append(["Орлов Максим Сергеевич", 770708389312, 4512345678, datetime.date(1985, 3, 14), 11223344595, 4276380012345678, 120000])
    ws.append(["Громова Анна Ивановна", 500100732259, 4613987654, datetime.date(1990, 7, 22), 12345678964, 4276380012345678, 95000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class NumericXlsx(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def test_numeric_ids_and_date_serials_do_not_leak_and_restore_equal(self):
        original = numeric_workbook()
        job = self.env.anonymize(("staff.xlsx", original))
        out = self.env.output_bytes(job)
        blob = all_parts(out)
        leaked = [s for s in ("770708389312", "4512345678", "500100732259", "4613987654", "31120", "33076",
                              "11223344595", "Орлов", "Громова") if s in blob]
        self.assertEqual(leaked, [])
        self.assertIn("120000", blob)          # суммы не идентификаторы и остаются числами
        restored = self.env.restore(self.env.as_upload(job, name="staff.xlsx"))
        got = load_workbook(io.BytesIO(self.env.output_bytes(restored))).active
        want = load_workbook(io.BytesIO(original)).active
        for row in want.iter_rows():
            for cell in row:
                back = got[cell.coordinate]
                self.assertEqual(back.value, cell.value, cell.coordinate)
                self.assertEqual(back.data_type, cell.data_type, cell.coordinate)
                self.assertEqual(back.number_format, cell.number_format, cell.coordinate)

    def test_text_digits_stay_text_on_restore(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Сотрудник", "ИНН"])
        ws.append(["Орлов Максим Сергеевич", "770708389312"])
        buf = io.BytesIO()
        wb.save(buf)
        job = self.env.anonymize(("t.xlsx", buf.getvalue()))
        self.assertNotIn("770708389312", all_parts(self.env.output_bytes(job)))
        restored = self.env.restore(self.env.as_upload(job, name="t.xlsx"))
        cell = load_workbook(io.BytesIO(self.env.output_bytes(restored))).active["B2"]
        self.assertEqual((cell.value, cell.data_type), ("770708389312", "s"))


if __name__ == "__main__":
    unittest.main()


RU_GRID = [["Сотрудник", "Паспорт", "Дата рождения", "ИНН", "Город"],
           ["Орлов Максим Сергеевич", "4512 345678", "14.03.1985", "770708389312", "Липецк"],
           ["Громова Анна Ивановна", "4613 987654", "22.07.1990", "500100732259", "Курск"]]
RU_SECRETS = ["4512 345678", "4613 987654", "14.03.1985", "22.07.1990", "770708389312", "500100732259", "Липецк", "Курск"]


class TableText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def roundtrip(self, name, text):
        job = self.env.anonymize((name, text))
        out = self.env.output_bytes(job).decode("utf-8", "ignore")
        self.assertEqual([s for s in RU_SECRETS if s in out], [], name)
        restored = self.env.output_bytes(self.env.restore(self.env.as_upload(job, name=name))).decode("utf-8", "ignore")
        from tests.helpers import visible
        self.assertEqual(visible(restored).strip(), text.strip())

    def test_comma_csv_numeric_id_next_to_date(self):
        self.roundtrip("a.csv", "\n".join(",".join(r) for r in RU_GRID))

    def test_html_table_header_context(self):
        rows = "".join("<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{c}</{'th' if i == 0 else 'td'}>" for c in r) + "</tr>"
                       for i, r in enumerate(RU_GRID))
        self.roundtrip("t.html", f"<html><body><table>{rows}</table></body></html>")


class LabelBesideNumber(unittest.TestCase):
    def test_numeric_inn_next_to_label_and_birth_date_before_word(self):
        env = Env()
        try:
            wb = Workbook()
            ws = wb.active
            ws.append(["INN", 6547100017])
            ws.append(["INN", 2655101243])
            ws.append(["Гражданин Орлов Максим Сергеевич, 20.10.1974 года рождения"])
            buf = io.BytesIO()
            wb.save(buf)
            job = env.anonymize(("l.xlsx", buf.getvalue()))
            blob = all_parts(env.output_bytes(job))
            self.assertEqual([s for s in ("6547100017", "2655101243", "20.10.1974") if s in blob], [])
            back = load_workbook(io.BytesIO(env.output_bytes(env.restore(env.as_upload(job, name="l.xlsx"))))).active
            self.assertEqual((back["B1"].value, back["B2"].value), (6547100017, 2655101243))
            self.assertIn("20.10.1974", back["A3"].value)
        finally:
            env.close()
