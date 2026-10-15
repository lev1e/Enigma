"""Регрессии аудита 08.10: кодировки без метки, записи символов в HTML/XML/JSON."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import Env
from anonymizer.util import sniff_encoding

TEXT = "Клиент Смирнов Алексей Петрович, телефон +7 (916) 555-12-34. Адрес: улица Ленина, дом 5. Договор подписан директором."


class Encodings(unittest.TestCase):
    def test_sniff_all(self):
        for enc in ("utf-8", "cp1251", "koi8-r", "cp866", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be", "utf-16", "utf-32"):
            raw = TEXT.encode(enc)
            self.assertEqual(raw.decode(sniff_encoding(raw)).lstrip("﻿"), TEXT, enc)

    def test_no_bom_encodings_are_anonymized_and_restored(self):
        for enc in ("utf-16-le", "utf-16-be", "koi8-r", "cp866", "cp1251"):
            env = Env()
            self.addCleanup(env.close)
            raw = TEXT.encode(enc)
            job = env.anonymize(("a.csv", raw))
            f = job.files[0]
            out = Path(f.out_path).read_bytes()
            self.assertNotIn("Смирнов", out.decode(sniff_encoding(out), errors="replace"), enc)
            back = Path(env.restore(env.as_upload(job)).files[0].out_path).read_bytes()
            self.assertEqual(back.decode(sniff_encoding(back)), TEXT, enc)

    def test_html_cp1251_restored_in_declared_encoding(self):
        env = Env()
        self.addCleanup(env.close)
        raw = ('<meta charset="windows-1251"><p>' + TEXT + "</p>").encode("cp1251")
        job = env.anonymize(("a.html", raw))
        back = Path(env.restore(env.as_upload(job)).files[0].out_path).read_bytes()
        self.assertEqual(back, raw)


class Escapes(unittest.TestCase):
    def test_html_numeric_entities_hide_name(self):
        env = Env()
        self.addCleanup(env.close)
        ref = "".join(f"&#{ord(c)};" for c in "Смирнов Алексей Петрович")
        html = f"<p>Клиент {ref}, smirnov&#64;romashka.ru, тел. +7 (916) 555-12-34&nbsp;&amp; ok</p>"
        out = Path(env.anonymize(("a.html", html)).files[0].out_path).read_text(encoding="utf-8")
        for secret in ("Смирнов", "romashka", "555-12-34", "&#1057"):
            self.assertNotIn(secret, out)
        self.assertIn("&amp;", out)

    def test_json_unicode_escapes_hide_name(self):
        env = Env()
        self.addCleanup(env.close)
        doc = json.dumps({"client": "Смирнов Алексей Петрович", "mail": "a@romashka.ru", "n": 1})
        self.assertIn("\\u0421", doc)
        out = Path(env.anonymize(("a.json", doc)).files[0].out_path).read_text(encoding="utf-8")
        json.loads(out)
        self.assertNotIn("Смирнов", out)
        self.assertNotIn("\\u0421", out)


if __name__ == "__main__":
    unittest.main()


class Secrets(unittest.TestCase):
    def test_log_and_config_secrets(self):
        env = Env()
        self.addCleanup(env.close)
        lines = ["DB_PASSWORD=Zx9!kLm2qWerty", "MYSQL_ROOT_PASSWORD: Zx9kLm2qWerty", "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCY",
                 "X-Auth-Token: abcdef1234567890abcd", "url=http://u:p4ssw0rdZ@host.example.org/x", "API key sk-live-AbCdEfGhIjKl-nOpQrStUvWx"]
        out = Path(env.anonymize(("a.log", "\n".join(lines))).files[0].out_path).read_text(encoding="utf-8")
        for secret in ("Zx9", "wJalr", "abcdef1234", "p4ssw0rdZ", "AbCdEfGh"):
            self.assertNotIn(secret, out)


class KnownIdentifiers(unittest.TestCase):
    def test_bare_repeat_of_labelled_inn(self):
        env = Env()
        self.addCleanup(env.close)
        out = Path(env.anonymize(("a.txt", "ИНН 7707083893. Позже: контрагент 7707083893 оплатил.")).files[0].out_path).read_text(encoding="utf-8")
        self.assertNotIn("7707083893", out)

    def test_xlsx_column_header_inn_passport_card(self):
        from openpyxl import Workbook
        import io
        wb = Workbook()
        ws = wb.active
        ws.append(["Компания", "ИНН", "Паспорт", "Карта"])
        ws.append(["Ромашка", "7707083893", "4509 123456", "4276 3800 1234 5678"])
        buf = io.BytesIO()
        wb.save(buf)
        env = Env()
        self.addCleanup(env.close)
        out = Path(env.anonymize(("t.xlsx", buf.getvalue())).files[0].out_path)
        import zipfile
        blob = b"".join(zipfile.ZipFile(out).read(n) for n in zipfile.ZipFile(out).namelist() if n.startswith("xl/"))
        for secret in (b"7707083893", b"4509 123456", b"4276 3800"):
            self.assertNotIn(secret, blob)
