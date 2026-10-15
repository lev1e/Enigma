"""W9: каждое расширение либо поддерживается, либо отклоняется понятной подсказкой; ничего не уходит «как есть»."""
from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from anonymizer import formats, refusals
from anonymizer.service import FORMAT_LABEL, Upload
from tests.helpers import Env, docx_bytes

PII = "Иванов Иван Петрович ivan.ivanov@firma.ru +7 916 123-45-67"
OLE = refusals.OLE_MAGIC


def with_part(data: bytes, name: str, payload: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.writestr(name, payload)
    return out.getvalue()


REFUSED_EXT = [".xls", ".doc", ".ppt", ".rtf", ".odt", ".ods", ".odp", ".xlsb", ".xlsm", ".docm", ".pptm", ".eml", ".msg",
               ".epub", ".zip", ".pages", ".numbers", ".key", ".vsdx", ".mdb", ".7z", ".rar", ".dotx", ".xltx", ".ppsx"]
SUPPORTED_EXT = {".txt", ".csv", ".tsv", ".md", ".json", ".xml", ".log", ".htm", ".html", ".ini", ".yaml", ".yml", ".xlsx",
                 ".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg"}


class RefusalRegistry(unittest.TestCase):
    def test_every_known_refused_extension_has_specific_help(self):
        for ext in REFUSED_EXT:
            with self.subTest(ext=ext):
                self.assertIn(ext, refusals.HELP)
                self.assertNotEqual(refusals.help_for(ext), refusals.GENERIC)
                self.assertLess(len(refusals.help_for(ext)), 200)

    def test_refused_extensions_not_classified_supported(self):
        for ext in REFUSED_EXT:
            with self.subTest(ext=ext):
                self.assertNotIn(formats.classify(Path("x" + ext)), FORMAT_LABEL)

    def test_supported_set_is_exactly_the_documented_one(self):
        candidates = (formats.TEXT_EXTENSIONS | formats.OOXML_EXTENSIONS | formats.ODF_EXTENSIONS | formats.MACRO_EXTENSIONS
                      | formats.OLD_OFFICE | formats.IMAGE_EXTENSIONS | {".pdf"})
        # картинки с содержимым, не похожим на картинку, классифицируются как UNSUPPORTED: здесь смотрим только расширение
        supported = {e for e in candidates if formats.classify(Path("x" + e)) in FORMAT_LABEL}
        self.assertEqual(supported, SUPPORTED_EXT - formats.IMAGE_EXTENSIONS)      # картинки: по содержимому, см. W10


class RefusalThroughService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.addClassData = None

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def refused(self, name: str, data: bytes) -> str:
        job = self.env.anonymize((name, data))
        f = job.files[0]
        self.assertEqual(f.status, "error", name)
        self.assertEqual(f.out_path, "", name)
        out_dir = Path(job.dir) / "out"
        self.assertEqual(list(out_dir.rglob("*")) if out_dir.exists() else [], [], f"{name}: файл остался в out/")
        text = " ".join(m["text"] for m in f.messages)
        self.assertNotIn("ivan.ivanov", text)
        return text

    def test_extensions_refuse_with_their_message(self):
        for ext in REFUSED_EXT:
            with self.subTest(ext=ext):
                text = self.refused("doc" + ext, OLE + PII.encode("utf-16le") if ext in (".xls", ".doc", ".ppt", ".msg")
                                    else PII.encode("utf-8"))
                self.assertIn(refusals.help_for(ext), text)

    def test_unknown_extension_and_no_extension_refused(self):
        for name in ("data.xyz", "noext", "report.docx.bak"):
            with self.subTest(name=name):
                self.assertIn(refusals.GENERIC, self.refused(name, PII.encode()))

    def test_macro_inside_ooxml_is_refused_not_copied(self):
        base = docx_bytes([PII])
        for ext, part in ((".docx", "word/vbaProject.bin"), (".xlsx", "xl/vbaProject.bin")):
            with self.subTest(ext=ext):
                text = self.refused("m" + ext, with_part(base, part, OLE + b"VBA"))
                self.assertIn("макрос", text)

    def test_signed_ooxml_refused(self):
        text = self.refused("s.docx", with_part(docx_bytes([PII]), "_xmlsignatures/sig1.xml", b"<Signature/>"))
        self.assertIn("не был изменён", text)

    def test_password_protected_and_fake_ooxml_refused(self):
        self.assertIn("защищён", self.refused("p.docx", OLE + b"EncryptedPackage" * 40))
        self.assertIn("повреждён", self.refused("f.xlsx", PII.encode()))

    def test_legacy_binary_named_as_text_is_not_passed_through(self):
        job = self.env.anonymize(("legacy.txt", OLE + PII.encode("utf-16le") * 5))
        f = job.files[0]
        self.assertEqual((f.status, f.out_path), ("error", ""))

    def test_peek_reports_refusal(self):
        for ext in (".xls", ".odt", ".eml", ".epub", ".xlsb"):
            with self.subTest(ext=ext):
                info = self.env.service.peek(Upload("p" + ext, PII.encode()))
                self.assertFalse(info["supported"])
                self.assertEqual(info["note"], refusals.help_for(ext))

    def test_restore_refuses_unsupported(self):
        for ext in (".odt", ".rtf", ".xls", ".eml"):
            with self.subTest(ext=ext):
                job = self.env.restore(("r" + ext, b"Name1"))
                f = job.files[0]
                self.assertEqual((f.status, f.out_path), ("error", ""))
                self.assertIn(refusals.help_for(ext), " ".join(m["text"] for m in f.messages))


if __name__ == "__main__":
    unittest.main()
