"""W7: необязательный источник кандидатов-имён (anonymizer/ner.py, natasha). Только список проверки."""
import random
import unittest
from unittest import mock

from anonymizer import ner
from anonymizer.models import Settings
from tests.helpers import Env

HAVE = ner.available()


def probe_units():
    """Синтетическая проба незнакомых русских фамилий (слоги, а не реальные люди): (текст, подстрока-имя)."""
    r = random.Random(11)
    first = ["Андрей", "Сергей", "Павел", "Игорь", "Олег", "Виктор", "Николай", "Максим"]
    patr = ["Петрович", "Иванович", "Сергеевич", "Андреевич", "Олегович", "Викторович"]
    s1 = ["Тарн", "Кувш", "Жер", "Бельск", "Нехл", "Прот", "Зав", "Ляп", "Гун", "Сыр", "Остр", "Мерц", "Дроб", "Хвал", "Пегов", "Стрел"]
    s2 = ["ов", "ин", "ский", "енко", "ук", "ев", "ич", "цов"]
    seen, surnames = set(), []
    while len(surnames) < 60:
        n = r.choice(s1) + r.choice(s2)
        if n not in seen:
            seen.add(n)
            surnames.append(n)
    tpls = ["Договор подписал директор {x} в присутствии свидетелей.", "Свидетель {x} подтвердил показания, данные ранее.",
            "{x}\tдиректор\tМосква", "С уважением,\n{x}", "Заявитель: {x}"]
    out = []
    for i, s in enumerate(surnames):
        full = f"{r.choice(first)} {r.choice(patr)} {s}" if i < 30 else s
        for t in tpls:
            out.append((t.format(x=full), full))
    return out


def detect(text, ner_on):
    env = Env()
    d = env.service.build_detector(env.service.settings_for({"ner_candidates": ner_on}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


class Gate(unittest.TestCase):
    def test_default_off(self):
        self.assertTrue(Settings().ner_candidates)

    def test_eligibility_skips_tables_markup_code_english(self):
        self.assertFalse(ner.eligible("Иванов\tдиректор\tМосква\nПетров\tбухгалтер\tТверь"))
        self.assertFalse(ner.eligible("a;b;c\n1;2;3\n4;5;6"))
        self.assertFalse(ner.eligible("<td>Свидетель Тарнов подтвердил</td>"))
        self.assertFalse(ner.eligible("INV-2024_01"))
        self.assertFalse(ner.eligible("Witness Smith confirmed the statement."))
        self.assertTrue(ner.eligible("Свидетель Тарнов подтвердил показания."))

    def test_missing_natasha_degrades_silently(self):
        with mock.patch.object(ner, "_model", False):
            self.assertEqual(ner.person_spans("Свидетель Тарнов подтвердил показания."), [])
            self.assertFalse(ner.available())
        with mock.patch.object(ner, "_model", None), mock.patch.dict("sys.modules", {"natasha": None}):
            self.assertEqual(ner.person_spans("Свидетель Тарнов подтвердил показания."), [])

    def test_off_means_no_ner_calls(self):
        with mock.patch.object(ner, "person_spans", side_effect=AssertionError("must not run")):
            detect("Свидетель Тарнов подтвердил показания.", False)


@unittest.skipUnless(HAVE, "natasha is not installed")
class WithModel(unittest.TestCase):
    def test_review_only_never_auto(self):
        for text, full in probe_units()[:60]:
            for f in detect(text, True):
                if f.reason == "Имя по модели NER":
                    self.assertEqual(f.decision.value, "REVIEW")
                    self.assertEqual(f.category, "POSSIBLE_PERSON")
                    self.assertGreaterEqual(f.confidence, ner.MIN_CONF)

    def test_auto_set_unchanged(self):
        for text, full in probe_units()[::7]:
            a = {(f.start, f.end, f.category) for f in detect(text, False) if f.decision.value == "AUTO"}
            b = {(f.start, f.end, f.category) for f in detect(text, True) if f.decision.value == "AUTO"}
            self.assertTrue(a <= b or all(any(x[0] < y[1] and y[0] < x[1] for y in b) for x in a))   # S8A: NER может сдвинуть границу (убрать «Свидетель» из имени), но не снять находку

    def test_every_occurrence_is_a_candidate(self):
        text = "Свидетель Тарнов подтвердил показания. Позже Тарнов добавил подробности."
        spans = [s for s in ner.person_spans(text) if text[s[0]:s[1]] == "Тарнов"]
        self.assertEqual(len(spans), 2)

    def test_long_text_is_chunked(self):
        text = ("Свидетель Тарнов подтвердил показания. " * 1300)[:45000]
        self.assertGreater(len(list(ner._chunks(text))), 2)
        self.assertTrue(ner.person_spans(text))

    def test_probe_review_gain(self):
        units = probe_units()
        off = sum(1 for t, full in units if not self._flagged(detect(t, False), t, full))
        on = sum(1 for t, full in units if not self._flagged(detect(t, True), t, full))
        self.assertLess(on, off)

    @staticmethod
    def _flagged(findings, text, full):
        a = text.index(full)
        return any(f.start < a + len(full) and f.end > a for f in findings)


if __name__ == "__main__":
    unittest.main()
