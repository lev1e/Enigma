"""S12B: a token-shaped literal glued to a digit (`n0name321`) is not a placeholder (regression of the relaxed restore pass)."""
from __future__ import annotations

import unittest
from pathlib import Path

from anonymizer.service import Upload
from anonymizer.tokens import TOKEN_RE
from tests.helpers import Env

SRC = "Иванов Иван Иванович подписал договор. ИНН 7707083893.\n"
FIO = "Иванов Иван Иванович"


class DigitGluedLiteral(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        job = cls.env.anonymize(("a.md", SRC.encode()))
        cls.out = Path(job.files[0].out_path).read_text(encoding="utf-8")
        cls.name = next(m.group(0) for m in TOKEN_RE.finditer(cls.out) if m.group(0).startswith("Name"))

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def restore_last(self, line: str) -> str:
        data = (self.out.rstrip("\n") + "\n" + line + "\n").encode("utf-8")
        f = self.env.restore(Upload("a (обезличено).md", data)).files[0]
        return Path(f.out_path).read_text(encoding="utf-8").splitlines()[-1]

    def test_digit_before_token_shaped_literal_is_kept(self):
        for lit in (f"n0{self.name.lower()} on github", f"x9{self.name} y", f"0{self.name.lower()}"):
            self.assertEqual(self.restore_last(lit), lit)

    def test_damaged_tokens_still_restore(self):
        n = self.name
        self.assertEqual(self.restore_last(f"x _{n}_ y"), f"x _{FIO}_ y")
        self.assertEqual(self.restore_last(f"a_{n}_b"), f"a_{FIO}_b")
        self.assertEqual(self.restore_last(f"в{n}"), f"в{FIO}")


if __name__ == "__main__":
    unittest.main()
