"""Regression tests for the third quality pass: well-formed XML/JSON after secrets, secret shape, national ids (SSN and others),
bare KPP/INN next to labelled ones, HTML restore and over-redaction of public URLs / adjectives."""
from __future__ import annotations

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.helpers import Env

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "tests" / "eval" / "real"


class DetectV4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def found(self, text: str, name: str = "x.txt"):
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        d.harvest(text, name)
        return [(f.category, f.original) for f in d.scan(text, name, "text") if f.decision.value == "AUTO"]

    def cats(self, text: str, *categories: str):
        return [o for c, o in self.found(text) if c in categories]

    def roundtrip(self, name: str, data: bytes):
        job = self.env.anonymize((name, data))
        out = Path(job.files[0].out_path).read_bytes()
        back = Path(self.env.restore(self.env.as_upload(job)).files[0].out_path).read_bytes()
        return out, back

    # -- 1. markup stays well-formed -------------------------------------------------------------

    def test_xml_secret_does_not_swallow_closing_tag(self):
        src = ("<?xml version='1.0'?><doc><para>password: Rv701!kd9550Pm</para><para>14. The Court rules.</para>"
               "<para>token = sk_live_308005Zq00995607Xw</para><para>15. Next.</para></doc>")
        out, _ = self.roundtrip("m.xml", src.encode())
        root = ET.fromstring(out)
        paras = [p.text for p in root]
        self.assertEqual(paras[1], "14. The Court rules.")
        self.assertEqual(paras[3], "15. Next.")
        self.assertNotIn(b"Rv701", out)
        self.assertNotIn(b"sk_live", out)

    def test_xml_findings_do_not_cross_nodes(self):
        src = ("<doc><row><cell>20 Marchmont Avenue, Halifax</cell></row><row><cell>Phone</cell></row>"
               "<para>call +49 30 254793</para><para>4. The parties agree</para></doc>")
        out, back = self.roundtrip("n.xml", src.encode())
        ET.fromstring(out)
        self.assertIn(b"<cell>Phone</cell>", out)
        self.assertIn(b"4. The parties agree", out)
        ET.fromstring(back)

    def test_xml_attribute_values_are_scanned_but_namespaces_are_not(self):
        src = ('<root xmlns="http://example.org/ns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               'xsi:schemaLocation="http://example.org/ns http://example.org/ns/x.xsd">'
               '<person mail="ivan.petrov@corp-demo.example.com" tel="+7 916 123-45-67">x</person></root>')
        out, _ = self.roundtrip("a.xml", src.encode())
        ET.fromstring(out)
        self.assertIn(b'xmlns="http://example.org/ns"', out)
        self.assertNotIn(b"ivan.petrov", out)
        self.assertNotIn(b"123-45-67", out)

    def test_corpus_xml_json_are_well_formed_and_restore(self):
        cases = sorted((REAL / "_cases").glob("*/case.json")) if (REAL / "_cases").exists() else []
        picked = []
        for cj in cases:
            spec = json.loads(cj.read_text(encoding="utf-8"))
            if spec.get("fmt") in ("xml", "json"):
                picked.append((cj.parent, spec))
        if not picked:
            self.skipTest("evaluation corpus not available")
        for folder, spec in picked:
            data = (folder / spec["file"]).read_bytes()
            out, back = self.roundtrip(spec["file"], data)
            with self.subTest(case=spec["id"]):
                if spec["fmt"] == "xml":
                    ET.fromstring(out)
                    ET.fromstring(back)
                else:
                    json.loads(out)
                    json.loads(back)

    # -- 3. secret shape -------------------------------------------------------------------------

    def test_version_and_setting_values_are_not_secrets(self):
        for text in ('"pbkdf2-password": "1.2.1",', 'password: 2.0.0-beta.1', '"passwordHash": "bcrypt"', "password = ${DB_PASSWORD}",
                     "password: <password>", "password: changeme", '"password": true', "pwd: sha256", 'password=%PASSWORD%',
                     '"bcrypt-password": "3.0.9"', "password: {{ vault_db_password }}", "password: your_password_here"):
            self.assertEqual(self.cats(text, "SECRET"), [], text)

    def test_real_passwords_still_secrets(self):
        for text, value in (("password: Rv701!kd9550Pm", "Rv701!kd9550Pm"), ('"password": "S3cr3t-Pass99"', "S3cr3t-Pass99"),
                            ("пароль: Qw8!zx7Lm", "Qw8!zx7Lm")):
            got = self.cats(text, "SECRET")
            self.assertTrue(got, text)
            if value:
                self.assertIn(value, got[0], text)

    def test_json_secret_keeps_label_and_neighbours(self):
        src = json.dumps({"pbkdf2-password": "1.2.1", "name": "demo", "password": "Rv838!kd7997Pm", "list": ["Rv838!kd7997Pm"]}, indent=1)
        out, _ = self.roundtrip("p.json", src.encode())
        data = json.loads(out)
        self.assertEqual(data["pbkdf2-password"], "1.2.1")
        self.assertEqual(data["name"], "demo")
        self.assertNotIn("Rv838", out.decode())

    # -- 4. national ids --------------------------------------------------------------------------

    def test_ssn_variants(self):
        for text, value in (("SSN 437-86-6666", "437-86-6666"), ("Social Security Number: 437 86 6666", "437 86 6666"),
                            ("ssn 437866666", "437866666"), ("copy Grace (103-93-4128) on file", "103-93-4128"),
                            ("ITIN 912-70-1234", "912-70-1234"), ("SIN 130 692 544", "130 692 544"),
                            ("NI number AB 12 34 56 C", "AB 12 34 56 C"), ("AB123456C", "AB123456C")):
            self.assertEqual(self.cats(text, "NATIONAL_ID"), [value], text)

    def test_invalid_ssn_ranges_rejected(self):
        for text in ("SSN 666-12-3456", "SSN 000-12-3456", "SSN 123-00-3456", "SSN 123-45-0000", "SSN 912-34-5678",
                     "SIN 130 692 545", "NI BG123456C"):
            self.assertEqual(self.cats(text, "NATIONAL_ID"), [], text)

    def test_vat_ein_and_iban(self):
        self.assertEqual(self.cats("VAT ID: DE123456789", "INN_ORG"), ["DE123456789"])
        self.assertEqual(self.cats("USt-IdNr. DE 123 456 789", "INN_ORG"), ["DE 123 456 789"])
        self.assertEqual(self.cats("NL123456789B01 invoice", "INN_ORG"), ["NL123456789B01"])
        self.assertEqual(self.cats("EIN 12-3456789", "INN_ORG"), ["12-3456789"])
        self.assertEqual(self.cats("IBAN DE89 3704 0044 0532 0130 00", "BANK_ACCOUNT"), ["DE89 3704 0044 0532 0130 00"])
        self.assertEqual(self.cats("IBAN DE00 3704 0044 0532 0130 00", "BANK_ACCOUNT"), [])

    def test_ssn_is_protected_kind(self):
        from anonymizer.settings_schema import PROTECTED_KINDS
        self.assertIn("NATIONAL_ID", PROTECTED_KINDS)
        out, back = self.roundtrip("s.txt", b"Applicant paid. SSN 437-86-6666 on file.")
        self.assertNotIn(b"437-86", out)
        self.assertIn(b"437-86-6666", back)


if __name__ == "__main__":
    unittest.main()
