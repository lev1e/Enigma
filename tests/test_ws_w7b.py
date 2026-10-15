"""W7b: NER как второе мнение: продвижение полных имён, шум, мягкий отказ без модели."""
import unittest
from unittest import mock

from anonymizer import ner
from anonymizer.models import Decision
from tests.helpers import Env

HAVE = ner.available()


def scan(text):
    env = Env()
    d = env.service.build_detector(env.service.settings_for({"ner_candidates": True}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


class DecideRules(unittest.TestCase):
    def test_full_names_promote_only_with_confidence(self):
        self.assertEqual(ner.decide("Джо Байденом", .95), "auto")
        self.assertEqual(ner.decide("Д. К. Бурлака", .95), "auto")
        self.assertEqual(ner.decide("Джо Байденом", .8), "review")

    def test_lone_and_role_words_stay_review_or_drop(self):
        self.assertEqual(ner.decide("Байрон", .99), "review")
        self.assertEqual(ner.decide("Доктор Вера", .99), "review")
        self.assertEqual(ner.decide("Стих Бейрона", .99), "review")
        for noise in ("Что", "См", "Коллежский", "Климатологическая", "Опорно-двигательная", "Name1"):
            self.assertIsNone(ner.decide(noise, .99), noise)

    def test_label_like_words_are_dropped(self):
        self.assertIsNone(ner.decide("Name12", .99))
        self.assertFalse(ner.is_full_name("Name1 Иван"))

    def test_too_long_text_skipped(self):
        self.assertEqual(ner.person_spans("Иван Петров " * (ner.MAX_TEXT // 8)), [])


class MissingModel(unittest.TestCase):
    def test_fail_soft_and_one_log_line(self):
        with mock.patch.object(ner, "_model", None), mock.patch.dict("sys.modules", {"natasha": None}):
            with self.assertLogs("anonymizer.ner", level="WARNING") as cm:
                self.assertFalse(ner.available())
                self.assertEqual(ner.person_spans("Свидетель Тарнов подтвердил показания."), [])
                self.assertEqual(ner.review_candidates("Свидетель Тарнов подтвердил показания.", lambda *a: None, 1), [])
            self.assertEqual(len(cm.output), 1)

    def test_detector_runs_without_model(self):
        with mock.patch.object(ner, "_model", False):
            found = scan("Директор Иван Тарнов подписал договор в Москве.")
        self.assertTrue(all(f.reason != "Полное имя по модели NER" for f in found))


@unittest.skipUnless(HAVE, "natasha не установлена")
class WithModel(unittest.TestCase):
    TEXT = "Вчера в Кремле встретились Джо Байден и Эммануэль Гриншпан. Затем выступил Байден."

    def test_full_names_become_auto_lone_stays_review(self):
        found = scan(self.TEXT)
        auto = {f.original for f in found if f.decision == Decision.AUTO}
        self.assertTrue(auto & {"Джо Байден", "Эммануэль Гриншпан"}, found)
        for f in found:
            if f.reason == "Имя по модели NER":
                self.assertEqual(f.decision, Decision.REVIEW)

    def test_no_label_spans(self):
        for f in scan("Name1 Name2 встретились с Иваном Петровым. Name3 ушёл."):
            if "NER" in f.reason:
                self.assertNotRegex(f.original, r"Name\d")

    def test_english_untouched(self):
        self.assertEqual([f for f in scan("Yesterday John Smith met Anna Brown in London.") if "NER" in f.reason], [])


if __name__ == "__main__":
    unittest.main()
