"""W3: Russian residuals and text formats. Tests are pattern based (no corpus strings inside rules)."""
from __future__ import annotations

import unittest

from tests.helpers import Env


def run(name: str, text: str) -> str:
    env = Env()
    job = env.anonymize((name, text.encode("utf-8")))
    return env.output(job).read_text(encoding="utf-8", errors="replace")


class BareIdsBeforeLabel(unittest.TestCase):
    """A bare INN/passport in a table row that appears BEFORE its labelled mention in the same file must still go."""

    CSV = ("ФИО,Телефон,ИНН_и_паспорт\n"
           "Иванов Пётр Сергеевич,+7 912 345-67-89,458277305514,4898 519757\n"
           "Петров Олег Игоревич,+7 912 345-67-90,454889623869,4612 333444\n"
           "\n"
           "Реквизиты: ИНН 458277305514, тел. +7 912 345-67-89\n"
           "Директор Петров Олег Игоревич, ИНН 454889623869, паспорт 4898 519757\n")

    def test_csv_bare_before_label(self):
        out = run("a.csv", self.CSV)
        for secret in ("458277305514", "454889623869", "4898 519757"):
            self.assertNotIn(secret, out)

    def test_txt_bare_before_label(self):
        out = run("a.txt", self.CSV.replace(",", " ; "))
        for secret in ("458277305514", "454889623869", "4898 519757"):
            self.assertNotIn(secret, out)


if __name__ == "__main__":
    unittest.main()


class TabSeparatedIds(unittest.TestCase):
    """Adjacent id cells separated by tabs must not merge into one unknown long number."""

    def test_log_tabs(self):
        text = ("2026-10-06 13:58:04 INFO  Иванов Пётр\tx@example.com\t332658166951\t9529 145774\t832-026-569 79\n"
                "2026-10-07 13:58:04 INFO  Петров Олег\ty@example.com\t681230958485\t4612 333444\t002-627-271 08\n"
                "Реквизиты: ИНН 332658166951, ИНН 681230958485, паспорт 9529 145774, паспорт 4612 333444\n")
        out = run("a.log", text)
        for secret in ("332658166951", "681230958485", "9529 145774", "4612 333444"):
            self.assertNotIn(secret, out)
