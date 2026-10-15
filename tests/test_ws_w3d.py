"""W3d residuals: bare KPP, birth-date variants, contract after colon, public sites (invented values only)."""
import unittest

from tests.helpers import Env

_E = Env()


def _scan(text):
    d = _E.service.build_detector(_E.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


def _hit(text, value, category, auto=True):
    return any(f.category == category and text[f.start:f.end] == value and (f.decision.value == "AUTO" or not auto)
               for f in _scan(text))


class KppTests(unittest.TestCase):
    def test_bare_pair_with_valid_inn(self):
        t = "Реквизиты: 7728168971 / 772801001, ООО Тест"
        self.assertTrue(_hit(t, "7728168971", "INN_ORG"))
        self.assertTrue(_hit(t, "772801001", "KPP"))

    def test_kpp_after_labelled_inn_with_comma(self):
        t = "Покупатель: ИНН 7728168971, 772801001"
        self.assertTrue(_hit(t, "772801001", "KPP"))

    def test_plain_number_pair_stays(self):
        self.assertFalse([f for f in _scan("Партия 1234567890 / 12 штук") if f.category == "KPP"])


class BirthTests(unittest.TestCase):
    def test_variants(self):
        for t, v in (("д.р. 05.03.80", "05.03.80"), ("ДР: 05.03.80", "05.03.80"), ("дата рожд. 05.03.1980", "05.03.1980"),
                     ("Петрова А.В., 05.03.1980 г.р., паспорт", "05.03.1980"), ("Ильин, 12.04.1975 г. р.", "12.04.1975"),
                     ("14 марта 1987 г.р.", "14 марта 1987"), ("5 марта 1980 года рождения", "5 марта 1980")):
            self.assertTrue(_hit(t, v, "BIRTH_DATE"), t)

    def test_ordinary_date_stays(self):
        self.assertFalse([f for f in _scan("Акт подписан 05.03.1980 в офисе.") if f.category == "BIRTH_DATE"])


class ContractTests(unittest.TestCase):
    def test_colon_number(self):
        self.assertTrue(_hit("Договор: ДП-77/2024", "ДП-77/2024", "CONTRACT"))
        self.assertFalse([f for f in _scan("Договор: оферта принята") if f.category == "CONTRACT"])


class PublicSiteTests(unittest.TestCase):
    def test_public_link_not_hidden(self):
        self.assertFalse([f for f in _scan("См. https://www.gov.ru/news и https://www.wikidata.org/wiki/Q649") if f.category == "DOMAIN"])

    def test_query_with_data_still_hidden(self):
        self.assertTrue([f for f in _scan("https://www.gov.ru/lk?user=ivanov") if f.category == "DOMAIN"])


if __name__ == "__main__":
    unittest.main()
