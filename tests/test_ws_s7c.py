"""S7C: повтор названия в начале фразы (строгий режим) и поведение списка «не скрывать» для фамилии."""
import unittest
from pathlib import Path

from tests.helpers import Env


def run(text, **settings):
    env = Env(**settings)
    try:
        job = env.anonymize(("a.txt", text.encode("utf-8")))
        return Path(job.files[0].out_path).read_text(encoding="utf-8")
    finally:
        env.close()


class StrictSentenceInitialRepeat(unittest.TestCase):
    TEXT = "Компания Вельтрон-Групп и Ромашка подписали договор. Вельтрон-Групп отгрузила товар. Потом Вельтрон-Групп оплатила счёт."

    def test_strict_hides_every_occurrence(self):
        out = run(self.TEXT, strict=True)
        self.assertNotIn("Вельтрон", out)

    def test_ordinary_capitalised_word_not_hidden_by_this_rule(self):
        out = run("Мы купили стол. Стол был красивый. Потом Стол сломался.", strict=True)
        self.assertIn("Стол", out)

    def test_only_initial_occurrences_do_not_count(self):
        out = run("Лампа горит. Лампа не гаснет.", strict=True)
        self.assertIn("Лампа", out)


class KeepSurnameOnly(unittest.TestCase):
    """Решение: список «не скрывать» действует на слово как есть; полное имя с таким словом остаётся скрытым
    целиком (иначе имя «Иван» оставалось бы читаемым рядом с заменой фамилии)."""

    def test_lone_surname_kept_full_name_still_hidden(self):
        out = run("Клиент Иван Иванов пришёл. Потом Иванов ушёл.", keep_terms=["Иванов"])
        self.assertIn("Иванов ушёл", out)
        self.assertNotIn("Иван Иванов", out)


if __name__ == "__main__":
    unittest.main()
