"""W3e: foreign ids, VIN/IMEI/MAC, medical ids, policies, labelled pay amounts (invented values only)."""
import unittest

from anonymizer.detectors import (valid_imei, valid_kz_iin, valid_steuer_id, valid_ua_rntrc, valid_vin_check)
from tests.helpers import Env

_E = Env()


def _scan(text):
    d = _E.service.build_detector(_E.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


def _hit(text, value, category=None):
    return any(text[f.start:f.end] == value and (category is None or f.category == category) and f.decision.value == "AUTO" for f in _scan(text))


def _none(text, *categories):
    return not [f for f in _scan(text) if f.category in categories]


class ChecksumTests(unittest.TestCase):
    def test_invented_values_pass(self):
        self.assertTrue(valid_steuer_id("13570869260"))
        self.assertTrue(valid_kz_iin("751018260618"))
        self.assertTrue(valid_ua_rntrc("2754359240"))
        self.assertTrue(valid_vin_check("AYVXY14B87L81DWK1"))
        self.assertTrue(valid_imei("356461678336904"))

    def test_broken_fail(self):
        self.assertFalse(valid_steuer_id("13570869261"))
        self.assertFalse(valid_kz_iin("751018260619"))
        self.assertFalse(valid_ua_rntrc("2754359241"))
        self.assertFalse(valid_vin_check("AYVXY15B87L81DWK1"))


class ForeignIdTests(unittest.TestCase):
    def test_steuer_id(self):
        self.assertTrue(_hit("Steuer-ID: 97041569232", "97041569232", "NATIONAL_ID"))
        self.assertTrue(_hit("Steuer-Identifikationsnummer 13 570 869 260", "13 570 869 260", "NATIONAL_ID"))

    def test_personalausweis(self):
        self.assertTrue(_hit("Personalausweis Nr. T22000129", "T22000129"))

    def test_kz_iin(self):
        self.assertTrue(_hit("ИИН 980821199220", "980821199220", "NATIONAL_ID"))
        self.assertTrue(_hit("IIN: 751018260618", "751018260618", "NATIONAL_ID"))

    def test_ua_rntrc_and_passport(self):
        self.assertTrue(_hit("РНОКПП 6822032233", "6822032233", "NATIONAL_ID"))
        self.assertTrue(_hit("ІПН: 2754359240", "2754359240", "NATIONAL_ID"))
        self.assertTrue(_hit("Паспорт КВ 654321, выдан", "КВ 654321"))

    def test_bare_digit_runs_stay(self):
        for t in ("Заказ 97041569232 отгружен", "Накладная 980821199220 от клиента", "Партия 6822032233 принята", "Steuer 3 Euro 12345"):
            self.assertFalse([f for f in _scan(t) if f.category in ("NATIONAL_ID", "PII")], t)


class DeviceTests(unittest.TestCase):
    def test_vin(self):
        self.assertTrue(_hit("VIN: WVWZZZ1JZXW000001", "WVWZZZ1JZXW000001", "VEHICLE_PLATE"))
        self.assertTrue(_hit("Кузов PLU0VNT27WT1UKJ0D, цвет синий", "PLU0VNT27WT1UKJ0D", "VEHICLE_PLATE"))   # bare, check digit valid

    def test_vin_lookalikes_stay(self):
        self.assertTrue(_none("Код ABCDEFGHJKLMNPRST1 в файле", "VEHICLE_PLATE"))
        self.assertTrue(_none("ключ 12345678901234567", "VEHICLE_PLATE"))

    def test_imei(self):
        self.assertTrue(_hit("IMEI: 358099497424747", "358099497424747", "DEVICE_ID"))
        self.assertTrue(_hit("IMEI 1: 35-646167-833690-4", "35-646167-833690-4", "DEVICE_ID"))

    def test_imei_bare_stays(self):
        self.assertTrue(_none("Заказ 358099497424747 отгружен", "PII", "DEVICE_ID", "NATIONAL_ID"))

    def test_mac(self):
        self.assertTrue(_hit("Адрес 00:1A:2B:3C:4D:5E в таблице", "00:1A:2B:3C:4D:5E", "DEVICE_ID"))
        self.assertTrue(_hit("MAC address 001a.2b3c.4d5e", "001a.2b3c.4d5e", "DEVICE_ID"))

    def test_mac_lookalikes_stay(self):
        for t in ("Время 12:30:45 по Москве", "Хэш abcdef012345 в логе", "IPv6 2001:db8::1 доступен", "00:00:00:00:00:00"):
            self.assertTrue(_none(t, "PII", "DEVICE_ID"), t)


class MedicalTests(unittest.TestCase):
    def test_mrn(self):
        self.assertTrue(_hit("MRN: 00482913", "00482913", "MEDICAL_ID"))
        self.assertTrue(_hit("Medical record number 7731456", "7731456", "MEDICAL_ID"))
        self.assertTrue(_hit("Медицинская карта № 4471/22", "4471/22", "MEDICAL_ID"))

    def test_policies(self):
        self.assertTrue(_hit("Health insurance policy number HX-4421907", "HX-4421907", "OMS"))
        self.assertTrue(_hit("Полис ОМС 1234 5678 9012 3456", "1234 5678 9012 3456", "OMS"))

    def test_negatives(self):
        for t in ("Policy No. 3 applies", "See privacy policy number 5", "Карта № 12 на складе", "Номер заказа 4471"):
            self.assertTrue(_none(t, "OMS", "PII", "MEDICAL_ID"), t)


class PayTests(unittest.TestCase):
    def test_amounts(self):
        for t, v in (("Оклад 120 000 руб.", "120 000 руб."), ("Salary: $85,000 per year", "$85,000"), ("Премия: 15 000 руб", "15 000 руб"),
                     ("Bonus 12,500 EUR", "12,500 EUR"), ("Зарплата 50000", "50000")):
            self.assertTrue(_hit(t, v, "COMPENSATION"), t)
        self.assertIn("Оклад", "Оклад 120 000 руб.")

    def test_unlabelled_or_non_amount_stays(self):
        for t in ("Итого 120 000 руб.", "Бонус 15% скидки", "Зарплата выплачивается 15 числа", "Премия за 2024 год", "Salary review in 2025", "Bonus level 3"):
            self.assertTrue(_none(t, "PII", "COMPENSATION"), t)


if __name__ == "__main__":
    unittest.main()
