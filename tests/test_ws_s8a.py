"""S8A: NER работает вместе с правилами: обучение, подтверждение, вето, все форматы, восстановление."""
import re
import unittest

from anonymizer import ner
from anonymizer.models import Decision
from tests.helpers import Env, docx_bytes, docx_text, pdf_bytes, pptx_bytes, xlsx_bytes, xlsx_cells

HAVE = ner.available()
PROSE = ("Вчера журналисты беседовали с Бекбулат Айтказин в Алматы. Позже Айтказина спросили о планах. "
         "Б. Айтказин ответил кратко. Айтказин добавил, что приедет снова. Письмо Айтказину пришло утром.")
NAME_WORDS = ("Бекбулат", "Айтказин")


def detector(**extra):
    env = Env()
    return env, env.service.build_detector(env.service.settings_for({"ner_candidates": True, **extra}))


def scan(text, **extra):
    env, d = detector(**extra)
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


@unittest.skipUnless(HAVE, "natasha не установлена")
class Learning(unittest.TestCase):
    def test_all_mentions_share_one_person(self):
        found = scan(PROSE)
        persons = [f for f in found if f.category == "PERSON"]
        self.assertEqual(len(persons), 5, [(f.original, f.reason) for f in found])
        self.assertEqual(len({f.person_id for f in persons}), 1)
        self.assertTrue(all(f.decision == Decision.AUTO for f in persons))

    def test_surname_first_order(self):
        text = PROSE.replace("Бекбулат Айтказин в", "Айтказин Бекбулат в")
        persons = [f for f in scan(text) if f.category == "PERSON"]
        self.assertGreaterEqual(len(persons), 5)
        self.assertEqual(len({f.person_id for f in persons}), 1)

    def test_first_name_never_left_next_to_replaced_surname(self):
        for f in scan(PROSE):
            if f.original.endswith("Айтказин") and f.start < 50:
                self.assertEqual(f.original, "Бекбулат Айтказин")

    def test_same_token_end_to_end_and_restore(self):
        env = Env()
        job = env.anonymize(("a.txt", PROSE))
        out = env.output_bytes(job).decode("utf-8")
        for w in NAME_WORDS + ("Айтказина", "Айтказину"):
            self.assertNotIn(w, out)
        self.assertEqual(len(set(re.findall(r"Name\d+", out))), 1, out)
        back = env.restore(env.as_upload(job))
        self.assertEqual(env.output_bytes(back).decode("utf-8"), PROSE)

    def test_learning_reaches_later_document_in_job(self):
        env = Env()
        job = env.anonymize(("a.txt", PROSE), ("b.txt", "Решение по заявке принял Айтказин лично."))
        self.assertNotIn("Айтказин", env.output_bytes(job, 1).decode("utf-8"))


@unittest.skipUnless(HAVE, "natasha не установлена")
class VetoAndCorroboration(unittest.TestCase):
    def test_common_words_never_auto(self):
        found = scan("Бухгалтер выставил Счёт Фактура на оплату. Директор подписал Счёт Фактура вовремя.")
        for f in found:
            if f.original == "Счёт Фактура":
                self.assertNotEqual(f.decision, Decision.AUTO)

    def test_keep_terms_win(self):
        found = scan("Вчера встретились Джо Байден и Эммануэль Гриншпан.", keep_terms=["Джо Байден"])
        self.assertFalse([f for f in found if f.original == "Джо Байден" and f.decision == Decision.AUTO])

    def test_rule_auto_is_never_demoted(self):
        found = scan("Директор Иван Петрович Тарнов подписал договор. Позже Тарнов уехал.")
        self.assertTrue([f for f in found if f.category == "PERSON" and f.decision == Decision.AUTO])

    def test_reason_strings_are_russian(self):
        for r in (ner.REASON_AUTO, ner.REASON_REVIEW, ner.REASON_BOTH):
            self.assertTrue(re.search("[А-Яа-я]", r))


@unittest.skipUnless(HAVE, "natasha не установлена")
class AllPaths(unittest.TestCase):
    def check(self, env, job, original_check):
        out = env.output(job)
        return out

    def test_docx_round_trip(self):
        env = Env()
        job = env.anonymize(("a.docx", docx_bytes(PROSE.split(". "))))
        text = docx_text(env.output(job))
        self.assertNotIn("Айтказин", text)
        back = env.restore(env.as_upload(job))
        self.assertIn("Бекбулат Айтказин", docx_text(env.output(back)))

    def test_pptx_and_html_md(self):
        env = Env()
        for name, data in (("a.pptx", pptx_bytes([PROSE])), ("a.html", f"<html><body><p>{PROSE}</p></body></html>"),
                           ("a.md", PROSE)):
            job = env.anonymize((name, data))
            blob = env.output(job).read_bytes()
            self.assertNotIn("Айтказин".encode("utf-8"), blob if not name.endswith("pptx") else _zip_all(blob), name)

    def test_xlsx_long_cell(self):
        env = Env()
        job = env.anonymize(("a.xlsx", xlsx_bytes({"A1": "Комментарий", "A2": PROSE, "A3": PROSE.split(". ")[3]})))
        cells = xlsx_cells(env.output(job))
        self.assertNotIn("Айтказин", repr(cells))

    def test_pdf_text_layer_round_trip(self):
        env = Env()
        job = env.anonymize(("a.pdf", pdf_bytes(PROSE.replace(". ", ".\n"), cyrillic=True)))
        import fitz
        out = "".join(p.get_text() for p in fitz.open(env.output(job)))
        self.assertNotIn("Айтказин", out)

    def test_ocr_like_hard_wrapped_lines(self):
        wrapped = PROSE.replace(" с ", "\nс ").replace("Позже ", "Позже\n")
        persons = [f for f in scan(wrapped) if f.category == "PERSON"]
        self.assertGreaterEqual(len(persons), 4)
        self.assertEqual(len({f.person_id for f in persons}), 1)

    def test_xlsx_register_has_no_residual(self):
        """Реестр процессов: имена в прозе рядом с глаголами и названиями компаний; проверка после записи не должна находить остаток."""
        rows = {"A1": "Процесс", "B1": "Описание", "C1": "Компания"}
        prose = ["Попроси Бекбулат Айтказин подписать акт, Айтказин знает детали.",
                 "Согласовал Тимоти Снайдер с Ромашка; позже Снайдера спросили о сроках.",
                 "Передай Договор в бухгалтерию, ответственный Лев Хасис.",
                 "Звонил Витя из бухгалтерии, Хасису ответили."]
        for i, t in enumerate(prose, start=2):
            rows[f"A{i}"] = f"Процесс {i}"
            rows[f"B{i}"] = t
            rows[f"C{i}"] = "ООО «Ромашка»" if i % 2 else "Альфа-Групп"
        env = Env()
        job = env.anonymize(("reg.xlsx", xlsx_bytes(rows)))
        bad = [m["text"] for f in job.files for m in f.messages if "критические" in m["text"]]
        self.assertFalse(bad, bad)
        blob = repr(xlsx_cells(env.output(job)))
        for w in ("Айтказин", "Снайдер", "Хасис", "Хасису"):
            self.assertNotIn(w, blob)


def _zip_all(blob):
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(blob))
    return b"".join(z.read(n) for n in z.namelist())


if __name__ == "__main__":
    unittest.main()
