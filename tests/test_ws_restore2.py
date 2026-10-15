"""Exact restore of token-shaped literals and damaged tokens (workstream restore2)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from anonymizer.service import Upload
from anonymizer.tokens import TOKEN_RE
from tests.helpers import Env

SRC = ("Иванов Иван Иванович подписал договор. ИНН 7707083893. Позвонить Иванову Ивану Ивановичу. "
       "Сотрудник Петров Пётр Петрович тоже.\n")
FIO, FIO_DAT = "Иванов Иван Иванович", "Иванову Ивану Ивановичу"


class RestoreVariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        job = cls.env.anonymize(("a.md", SRC.encode()))
        cls.out = Path(job.files[0].out_path).read_text(encoding="utf-8")
        cls.name = next(m.group(0) for m in TOKEN_RE.finditer(cls.out) if m.group(0).startswith("Name"))
        cls.inn = next(m.group(0) for m in TOKEN_RE.finditer(cls.out) if m.group(0).startswith("Inn"))

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def restore_line(self, line: str):
        data = (self.out.rstrip("\n") + "\n" + line + "\n").encode("utf-8")
        job = self.env.restore(Upload("a (обезличено).md", data))
        f = job.files[0]
        return Path(f.out_path).read_text(encoding="utf-8").splitlines()[-1], f

    def test_markdown_emphasis_and_identifiers(self):
        n = self.name
        for src, want in [(f"x _{n}_ y", f"x _{FIO}_ y"), (f"x __{n}__ y", f"x __{FIO}__ y"), (f"a_{n}_b", f"a_{FIO}_b"),
                          (f"**{n}**", f"**{FIO}**"), (f"_{n}_2_", f"_{FIO_DAT}_"), (f"a_{n}_2_b", f"a_{FIO_DAT}_b"),
                          (f"{n}_total", f"{FIO}_total"), (f"{n}_2024", f"{FIO}_2024"), ("_Name99_", "_Name99_")]:
            with self.subTest(src=src):
                self.assertEqual(self.restore_line(src)[0], want)

    def test_damaged_forms(self):
        n = self.name
        stem, digits = n[:4], n[4:]
        for sep in (" ", " ", "​", "-", "‑", " "):
            with self.subTest(sep=repr(sep)):
                self.assertEqual(self.restore_line(stem + sep + digits)[0], FIO)
        self.assertEqual(self.restore_line("в" + n)[0], "в" + FIO)
        self.assertEqual(self.restore_line("NAME" + digits)[0], FIO)

    def test_inn_glued_to_name(self):
        n, i = self.name, self.inn
        self.assertEqual(self.restore_line(f"{i}{n}")[0], f"7707083893{FIO}")
        self.assertEqual(self.restore_line(f"{i}​{n}")[0], f"7707083893{FIO}")
        self.assertEqual(self.restore_line(f"{n}{i}")[0], f"{FIO}7707083893")

    def test_literal_lookalikes_are_not_restored(self):
        n = self.name
        stem, digits = n[:4], n[4:]
        for lit in (f"Moscow-{stem} 0{digits}.jpg", f"file_{stem} {digits}.png", f"{stem} {digits}.txt"):
            with self.subTest(lit=lit):
                self.assertEqual(self.restore_line(lit)[0], lit)
        self.assertEqual(self.restore_line(f"City 05 {n}")[0], f"City 05 {FIO}")

    def test_report_names_missing_token(self):
        _, f = self.restore_line("и Name77 тоже")
        self.assertTrue(any("Name77" in m["text"] for m in f.messages), [m["text"] for m in f.messages])


class LiteralLookalikeRoundTrip(unittest.TestCase):
    def test_source_literal_roundtrip(self):
        env = Env()
        try:
            src = ("Иванов Иван Иванович, фото Moscow-City 05.jpg и City2015.jpg, снимок Phone 05.png.\n").encode("utf-8")
            job = env.anonymize(("b.md", src))
            back = Path(env.restore(env.as_upload(job)).files[0].out_path).read_text(encoding="utf-8")
            self.assertIn("Moscow-City 05.jpg", back)
            self.assertIn("City2015.jpg", back)
            self.assertIn("Phone 05.png", back)
            self.assertIn("Иванов Иван Иванович", back)
        finally:
            env.close()


class EvalHarness(unittest.TestCase):
    def test_natural_secret_alignment(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import eval_real as er
        a = "use (`https://user:pass@proxy:8080`), Requests and more"
        b = "use (`https://user:Secret1@proxy:8080`), Requests and more"
        self.assertEqual(er.natural_secrets(a, b), ["pass"])
        self.assertEqual(er.restore_equal("md", a.encode(), b.encode(), []), (False, True))
        self.assertFalse(er.restore_equal("md", a.encode(), b.replace("more", "mor").encode(), [])[1])


if __name__ == "__main__":
    unittest.main()
