"""Поток C (08.10), оценка на реальных документах: английские имена, паспорт, JSON, HTML, двоичные данные, скорость."""
from __future__ import annotations

import re
import time
import unittest
from pathlib import Path

from tests.helpers import Env


class Detect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env(image_mode="redact_text")

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def found(self, text: str, name: str = "x.txt"):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        d.harvest(text, name)
        return [(f.category, f.original) for f in d.scan(text, name, "text") if f.decision.value == "AUTO"]

    def assertHidden(self, text: str, value: str, category: str):
        hits = self.found(text)
        self.assertTrue(any(c == category and value in o or (c == category and o in value and len(o) > 3) for c, o in hits),
                        f"{value!r} not found in {text!r}: {hits}")
        covered = "".join(o for c, o in hits if c == category)
        self.assertTrue(all(w in covered for w in re.findall(r"[A-Za-z0-9]{3,}", value)), f"{value!r} only partly hidden: {hits}")

    # -- 1. английские имена ---------------------------------------------------
    def test_applicant_with_middle_initial(self):
        self.assertHidden("Applicant: John A. Whitfield", "John A. Whitfield", "PERSON")
        self.assertHidden("Applicant: Grace T. Okonkwo\nPhone: 1", "Grace T. Okonkwo", "PERSON")

    def test_honorific_hides_surname_too(self):
        self.assertHidden("Mr. Marcus Lindqvist signed the form.", "Marcus Lindqvist", "PERSON")

    def test_surname_comma_given(self):
        self.assertHidden("Name: Smith, John", "Smith, John", "PERSON")
        self.assertHidden("Reviewed by Smith, John on Monday", "Smith, John", "PERSON")

    def test_initial_surname_after_by(self):
        self.assertHidden("Reviewed by J. Whitfield on Monday", "J. Whitfield", "PERSON")

    def test_not_a_person(self):
        for text in ("Applicant: Acme Corporation", "Name: Project Alpha", "Section A. Overview", "The U.S. Government said"):
            self.assertFalse([1 for c, o in self.found(text) if c == "PERSON"], text)

    # -- 2. паспорт --------------------------------------------------------------
    def test_bare_nine_digit_passport(self):
        for text in ("Passport: 512345678", "passport no. 512345678", "Passport No. 512345678", "Passport number 512345678"):
            self.assertIn(("PASSPORT", "512345678"), self.found(text), text)

    def test_passport_letters_and_digits(self):
        self.assertIn(("PASSPORT", "AB1234567"), self.found("Passport: AB1234567"))

    def test_passport_word_without_number_is_fine(self):
        self.assertFalse([1 for c, _ in self.found("Bring your passport on 2026 trip") if c == "PASSPORT"])


class Files(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env(image_mode="redact_text")

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def run_file(self, name: str, raw: bytes):
        job = self.env.anonymize((name, raw))
        f = job.files[0]
        if not f.out_path:
            return f, b"", b""
        out = Path(f.out_path).read_bytes()
        back = Path(self.env.restore(self.env.as_upload(job)).files[0].out_path).read_bytes()
        return f, out, back

    # -- 3. JSON: «\n» перед ИНН ------------------------------------------------
    def test_inn_after_escaped_newline_in_json(self):
        raw = ('{"note": "Паспорт серия и номер 19 87 799944\\nИНН 394361953149, тел. +7 (944) 703-21-19\\nE-mail: a@b-demo.example.ru"}'
               ).encode("utf-8")
        f, out, back = self.run_file("d.json", raw)
        text = out.decode("utf-8")
        self.assertNotIn("394361953149", text)
        self.assertNotIn("799944", text)
        self.assertIn("\\n", text)
        self.assertEqual(back, raw)

    # -- 4. HTML -------------------------------------------------------------------
    HTML = ('<html><head><title>Анкета</title><style>.box{color:red}</style>'
            '<script>var x = {"a":"Entity\\">]<"};</script></head>'
            '<body class="Company wide" id="main"><p>Заявитель: Чернобаев Пётр Сергеевич</p>'
            '<p>Email: <a href="mailto:petr.chern@demo-mail.example.ru">petr.chern@demo-mail.example.ru</a></p>'
            '<img alt="Фото: Чернобаев Пётр Сергеевич" src="a.png"><p>ИНН 500100732259</p></body></html>').encode("utf-8")

    def test_html_markup_is_not_replaced_and_restore_is_exact(self):
        f, out, back = self.run_file("page.html", self.HTML)
        text = out.decode("utf-8")
        self.assertEqual(back, self.HTML)
        for kept in ('<body class="Company wide" id="main">', "<style>.box{color:red}</style>",
                     '<script>var x = {"a":"Entity\\">]<"};</script>', 'src="a.png"'):
            self.assertIn(kept, text)
        self.assertNotIn("Чернобаев", text)
        self.assertNotIn("500100732259", text)
        self.assertNotIn("petr.chern@demo-mail", text)
        self.assertEqual(len(re.findall(r"<[^>]+>", text)), len(re.findall(r"<[^>]+>", self.HTML.decode("utf-8"))))

    def test_html_replacements_do_not_cover_markup(self):
        job = self.env.anonymize(("page.html", self.HTML))
        for original in (job.replaced or []):
            value = original if isinstance(original, str) else str(getattr(original, "original", original))
            self.assertNotRegex(value, r"[<>]", value)

    # -- 5. двоичные данные под именем .txt ------------------------------------------
    def test_binary_named_txt_is_rejected(self):
        import random
        raw = random.Random(7).randbytes(20000)
        f, out, back = self.run_file("blob.txt", raw)
        self.assertFalse(f.out_path)
        self.assertTrue(any("двоичн" in m["text"] for m in f.messages), f.messages)

    def test_cp1251_text_is_not_binary(self):
        raw = "Заявитель: Чернобаев Пётр Сергеевич, ИНН 500100732259\n".encode("cp1251", errors="replace")
        f, out, back = self.run_file("a.txt", raw)
        self.assertTrue(f.out_path)

    # -- 6. скорость ---------------------------------------------------------------------
    def test_normalize_is_cached_for_big_text(self):
        from anonymizer.normalize import normalize
        big = ("Иван  Петров живёт здесь.\n" * 4000)
        self.assertIs(normalize(big), normalize(big))

    def test_many_company_lines_stay_linear(self):
        line = "Партнёры: ООО «Ромашка», Valdor, KRDT, Zenit, Orbis и Helix\n"
        raw = (line * 1500).encode("utf-8")
        t = time.time()
        f, out, back = self.run_file("big.txt", raw)
        self.assertLess(time.time() - t, 90)
        self.assertEqual(back, raw)


if __name__ == "__main__":
    unittest.main()
