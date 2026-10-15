"""W3f: slide-style Russian text must not be over-redacted as ORG/REGION (invented examples only)."""
import unittest

from tests.helpers import Env

_E = Env()


def _scan(text):
    d = _E.service.build_detector(_E.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


def _auto(text, *categories):
    return [text[f.start:f.end] for f in _scan(text) if f.category in categories and f.decision.value == "AUTO"]


class GenericDeckTextStaysVisible(unittest.TestCase):
    def test_direction_adjective_before_office_or_warehouse(self):
        self.assertEqual(_auto("Центральный офис и Северный склад работают.", "REGION", "CITY", "ORG"), [])

    def test_plain_word_company_not_spread_to_other_forms(self):
        # Однокоренные прилагательные не прячем. Падежные формы названия, опознанного явно (АО «Перспектива» → «Перспективы»),
        # скрываем: утечка названия хуже лишнего слова (решение ведущего 13.10, см. test_entities).
        text = "Партнер: АО «Перспектива». Перспективная отрасль и перспективный рынок."
        auto = _auto(text, "ORG")
        self.assertNotIn("Перспективная", auto)
        self.assertNotIn("перспективный", auto)

    def test_generic_headings_and_metrics(self):
        text = "Ключевые выводы. Рынок и тренды. Дорожная карта. KPI, CRM, B2B, NPS."
        self.assertEqual(_auto(text, "ORG", "REGION", "CITY"), [])


class RealEntitiesStayHidden(unittest.TestCase):
    def test_legal_form_company(self):
        self.assertIn("СтройГарант", _auto("Подрядчик: ООО «СтройГарант» выполнил работы.", "ORG"))

    def test_branch_with_region_adjective(self):
        self.assertIn("Дальневосточный", _auto("Дальневосточный филиал компании открыт.", "REGION"))

    def test_city_and_address(self):
        text = "Офис: г. Казань, ул. Баумана, д. 5."
        self.assertTrue(_auto(text, "ADDRESS", "CITY"))

    def test_plain_word_company_exact_name_still_hidden(self):
        text = "Партнер: АО «Перспектива». Перспектива выиграла тендер."
        self.assertEqual(_auto(text, "ORG").count("Перспектива"), 2)


if __name__ == "__main__":
    unittest.main()
