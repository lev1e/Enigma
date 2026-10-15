"""S6C: social networks are not persons, generic quoted phrases are not projects, year-only birth, new token kinds,
number sign outside the OMS span, OOXML macro/signature refusal without a copy, NER-unavailable note. Invented data only."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from anonymizer import formats, ner, service as service_mod
from anonymizer.detectors import Decision
from anonymizer.formats import TransformContext, transform_ooxml
from anonymizer.tokens import KIND_BY_CODE
from tests.helpers import Env, docx_bytes

_E = Env()


def _scan(text, **opts):
    d = _E.service.build_detector(_E.service.settings_for(opts))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


def _hits(text, *cats, **opts):
    return [text[f.start:f.end] for f in _scan(text, **opts) if f.category in cats and f.decision == Decision.AUTO]


class SocialNetworks(unittest.TestCase):
    def test_networks_are_not_persons(self):
        for t in ("Мы в LinkedIn, VK и Telegram.", "Reach us via LinkedIn, VK. Also Facebook, VK.", "VK, LinkedIn"):
            self.assertEqual(_hits(t, "PERSON"), [], t)

    def test_real_initials_stay(self):
        self.assertIn("J. Smith", _hits("Contact: J. Smith, VK.", "PERSON"))


class GenericQuotedPhrases(unittest.TestCase):
    def test_generic_not_project(self):
        t = "Обсудили проект «Дорожная карта» и программу «Ключевые выводы»."
        self.assertEqual(_hits(t, "PROJECT"), [])

    def test_codename_stays(self):
        self.assertIn("Альбатрос", _hits("Код проекта «Альбатрос» утверждён.", "PROJECT"))


class YearOnlyBirth(unittest.TestCase):
    def test_bare_year(self):
        self.assertEqual(_hits("Пациент Рустамов Фарход Абдуллаевич, 1975 г.р.", "BIRTH_DATE"), ["1975"])
        self.assertEqual(_hits("Иванов, 1980 года рождения", "BIRTH_DATE"), ["1980"])

    def test_plain_years_stay(self):
        for t in ("Компания основана в 1999 г.", "Отчёт за 2024 год", "в 1975 году вышел фильм"):
            self.assertEqual(_hits(t, "BIRTH_DATE"), [], t)


class NewKinds(unittest.TestCase):
    def test_kinds_registered_with_groups(self):
        from anonymizer.settings_schema import KIND_LABELS
        for code in ("DEVICE_ID", "MEDICAL_ID", "COMPENSATION"):
            self.assertIn(code, KIND_BY_CODE)
            self.assertIn(code, KIND_LABELS)

    def test_categories(self):
        self.assertEqual(_hits("IMEI: 358099497424747", "DEVICE_ID"), ["358099497424747"])
        self.assertEqual(_hits("MAC address 001a.2b3c.4d5e", "DEVICE_ID"), ["001a.2b3c.4d5e"])
        self.assertEqual(_hits("MRN: 00482913", "MEDICAL_ID"), ["00482913"])
        self.assertEqual(_hits("Оклад 120 000 руб.", "COMPENSATION"), ["120 000 руб."])

    def test_round_trip(self):
        text = "IMEI: 358099497424747\nMRN: 00482913\nОклад 120 000 руб.\nПолис № 7712345678901234 выдан.\n"
        env = Env()
        job = env.anonymize(("a.txt", text))
        out = env.output_bytes(job).decode("utf-8")
        for secret in ("358099497424747", "00482913", "120 000", "7712345678901234"):
            self.assertNotIn(secret, out)
        self.assertIn("Device1", out)
        self.assertIn("Medical1", out)
        self.assertIn("Pay1", out)
        self.assertIn("№ Oms1", out)
        back = env.restore(env.as_upload(job))
        self.assertEqual(env.output_bytes(back).decode("utf-8"), text)


class NumberSign(unittest.TestCase):
    def test_sign_outside_span(self):
        for t, v in (("Страховой полис № 7712345678901234 выдан.", "7712345678901234"), ("полис ОМС №1234567890123456", "1234567890123456")):
            self.assertEqual(_hits(t, "OMS"), [v], t)


def _with_part(data: bytes, name: str, payload: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr(name, payload)
    return out.getvalue()


class OoxmlBlocked(unittest.TestCase):
    def _run(self, part):
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "in.docx", Path(t) / "out" / "out.docx"
            src.write_bytes(_with_part(docx_bytes(["Привет"]), part, b"\xd0\xcf\x11\xe0VBA"))
            d = _E.service.build_detector(_E.service.settings_for({}))
            ctx = TransformContext(_E.vault, _E.service.settings_for({}), d)
            res = transform_ooxml(src, dst, "in.docx", d, ctx)
            return res, dst.exists(), (dst.parent.exists() and any(dst.parent.iterdir()))

    def test_macro_blocked_no_copy(self):
        res, exists, any_file = self._run("word/vbaProject.bin")
        self.assertEqual(res.status.value, "BLOCKED")
        self.assertFalse(exists)
        self.assertFalse(any_file)
        self.assertTrue(any("макрос" in w for w in res.warnings))
        self.assertEqual(res.output_path, "")

    def test_signature_blocked_no_copy(self):
        res, exists, _ = self._run("_xmlsignatures/sig1.xml")
        self.assertEqual(res.status.value, "BLOCKED")
        self.assertFalse(exists)

    def test_service_still_refuses(self):
        env = Env()
        job = env.anonymize(("m.docx", _with_part(docx_bytes(["Привет"]), "word/vbaProject.bin", b"x")))
        f = job.files[0]
        self.assertFalse(f.out_path)
        self.assertTrue(any("макрос" in m["text"] for m in f.messages))


class NerNote(unittest.TestCase):
    TEXT = "Свидетель Тарнов рассказал суду о событиях прошлого года и подробно описал встречу с руководителем отдела. " * 3

    def _infos(self, job):
        out = []
        for f in job.files:
            for m in f.messages:
                out.append(m["text"] if isinstance(m, dict) else str(m))
        return out

    def test_note_once_when_model_missing(self):
        env = Env()
        with mock.patch.object(ner, "available", return_value=False):
            job = env.anonymize(("a.txt", self.TEXT), ("b.txt", self.TEXT), options={"ner_candidates": True})
        notes = [m for m in self._infos(job) if service_mod.NER_UNAVAILABLE_NOTE in m]
        self.assertEqual(len(notes), 1)

    def test_no_note_when_option_off_or_text_english(self):
        env = Env()
        with mock.patch.object(ner, "available", return_value=False):
            job = env.anonymize(("a.txt", self.TEXT), options={"ner_candidates": False})
            self.assertFalse([m for m in self._infos(job) if service_mod.NER_UNAVAILABLE_NOTE in m])
            job = env.anonymize(("e.txt", "The witness described the meeting in detail to the court. " * 5), options={"ner_candidates": True})
            self.assertFalse([m for m in self._infos(job) if service_mod.NER_UNAVAILABLE_NOTE in m])


if __name__ == "__main__":
    unittest.main()
