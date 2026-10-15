"""S9C: подтверждённое одиночное имя, xlsx в два прохода, строгий режим и «не скрывать» (синтетические данные)."""
import unittest

from anonymizer import ner
from anonymizer.detectors import Detector
from anonymizer.models import Decision, Settings
from tests.helpers import Env, xlsx_bytes, xlsx_cells

HAVE = ner.available()
LONE = ("Позже Айтказина спросили о планах. Айтказин добавил, что приедет снова. Б. Айтказин ответил. "
        "Письмо Айтказину пришло утром. Айтказиным остались довольны.")


def rerun(overrides, text=LONE):
    env = Env()
    job = env.anonymize(("a.txt", text), options={"ner_candidates": True})
    job2 = env.service.rerun(job.id, {"ner_candidates": True}, overrides)
    return env, job2, env.output_bytes(job2).decode("utf-8")


@unittest.skipUnless(HAVE, "natasha не установлена")
class ConfirmedLone(unittest.TestCase):
    def test_nominative_confirmed_hides_every_form(self):
        _, _, out = rerun({"Айтказин": "hide"})
        self.assertNotIn("Айтказин", out)

    def test_inflected_form_confirmed_hides_every_form(self):
        _, _, out = rerun({"Айтказина": "hide"})
        self.assertNotIn("Айтказин", out)

    def test_restore_is_exact(self):
        env, job, _ = rerun({"Айтказин": "hide"})
        back = env.restore(env.as_upload(job))
        self.assertEqual(env.output_bytes(back).decode("utf-8"), LONE)

    def test_not_confirmed_stays_in_review(self):
        env = Env()
        job = env.anonymize(("a.txt", LONE), options={"ner_candidates": True})
        self.assertIn("Айтказин", env.output_bytes(job).decode("utf-8"))
        self.assertTrue(job.result["suggestions"])

    def test_hide_term_without_model_evidence_is_not_expanded(self):
        # слово из «скрывать», которое модель человеком не считает, склонением не расширяется
        env = Env()
        job = env.anonymize(("a.txt", "Коробка стоит на столе. Коробки лежат рядом."), options={"hide_terms": ["Коробка"]})
        out = env.output_bytes(job).decode("utf-8")
        self.assertNotIn("Коробка ", out)


class Forms(unittest.TestCase):
    def test_given_name_forms(self):
        forms = Detector([], Settings())._lone_forms("Бекбулату")
        self.assertTrue({"Бекбулат", "Бекбулата", "Бекбулатом"} <= forms, forms)

    def test_surname_forms(self):
        forms = Detector([], Settings())._lone_forms("Айтказина")
        self.assertTrue({"Айтказин", "Айтказиным", "Айтказину"} <= forms, forms)


PROSE_A = "Позже журналисты долго обсуждали планы. Айтказина спросили о поездке и о том, что будет дальше."
PROSE_B = "Вчера журналисты беседовали с Бекбулат Айтказин в Алматы. Позже Айтказин ответил кратко и уехал."


@unittest.skipUnless(HAVE, "natasha не установлена")
class XlsxTwoPass(unittest.TestCase):
    def test_name_found_in_late_cell_hides_early_cell(self):
        env = Env()
        job = env.anonymize(("a.xlsx", xlsx_bytes({"A1": "Комментарий", "A2": PROSE_A, "A3": PROSE_B})),
                            options={"ner_candidates": True})
        blob = repr(xlsx_cells(env.output(job)))
        self.assertNotIn("Айтказин", blob)
        self.assertNotIn("Бекбулат", blob)

    def test_xlsx_confirmed_lone_hides_every_form_in_every_cell(self):
        env = Env()
        src = xlsx_bytes({"A1": "Комментарий", "A2": PROSE_A + " Айтказиным остались довольны, как и всегда.", "A3": PROSE_B})
        job = env.anonymize(("a.xlsx", src), options={"ner_candidates": True})
        job2 = env.service.rerun(job.id, {"ner_candidates": True}, {"Айтказин": "hide"})
        self.assertNotIn("Айтказин", repr(xlsx_cells(env.output(job2))))

    def test_xlsx_restore_exact(self):
        env = Env()
        src = xlsx_bytes({"A1": "Комментарий", "A2": PROSE_A, "A3": PROSE_B})
        job = env.anonymize(("a.xlsx", src), options={"ner_candidates": True})
        back = env.restore(env.as_upload(job))
        self.assertEqual(xlsx_cells(env.output(back)), xlsx_cells(src))


def scan_on(text):
    env = Env()
    d = env.service.build_detector(env.service.settings_for({"ner_candidates": True}))
    d.harvest(text, "x.txt")
    return d, d.scan(text, "x.txt", "text")


@unittest.skipUnless(HAVE, "natasha не установлена")
class NoShadowing(unittest.TestCase):
    """Обучение моделью не сужает то, что скрывали правила."""

    def test_patronymic_only_name_is_not_registered_as_person(self):
        text = ("Позже журналисты долго беседовали. Мария Алексеевна рассказала о поездке и о планах семьи на лето. "
                "Потом пришла Мария Иванова и принесла письмо.")
        d, _ = scan_on(text)
        self.assertFalse([p for p in d.index.people.values() if p.surname.endswith(("евна", "евны", "ович"))])

    def test_partial_overlap_keeps_rule_part_hidden(self):
        text = "Вчера в студии выступил бывший помощник Путина Владислав Сурков и член совета директоров компании."
        _, found = scan_on(text)
        hidden = {f.original for f in found if f.decision == Decision.AUTO}
        covered = " | ".join(hidden)
        self.assertIn("Путина", covered)
        self.assertIn("Сурков", covered)


class StrictAndKeep(unittest.TestCase):
    def test_strict_sentence_initial_repeat_hidden(self):
        env = Env()
        text = "Компания Альфа-Групп и Ромашка подписали договор. Альфа-Групп отгрузила товар."
        job = env.anonymize(("a.txt", text), options={"strict": True})
        self.assertNotIn("Альфа-Групп", env.output_bytes(job).decode("utf-8"))

    def test_keep_surname_does_not_unhide_full_name(self):
        env = Env()
        job = env.anonymize(("a.txt", "Иван Иванов подписал акт. Иванов вернулся."), options={"keep_terms": ["Иванов"]})
        out = env.output_bytes(job).decode("utf-8")
        self.assertNotIn("Иван ", out)                    # полное имя скрыто целиком, фамилия при нём не остаётся
        self.assertIn("Иванов вернулся", out)             # одиночная фамилия открыта по просьбе


if __name__ == "__main__":
    unittest.main()
