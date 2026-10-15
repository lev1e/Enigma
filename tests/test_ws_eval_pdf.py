"""Workstream A (eval failures): nested containers fail closed, PDF restore fidelity, signature test,
verify false residuals, OCR confidence, remaining PDF leak surfaces."""
from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from tests.helpers import Env

HERE = Path(__file__).resolve().parent
NEST4 = HERE / "eval" / "failures" / "adv_nested_zip4_xlsx" / "nest4.xlsx"
SECRETS = ["Мирошкин", "738080", "850764715606", "u528.8862", "4276 9578 1474 0578"]
NOTE = ("Заявитель: Мирошкин Алла Игоревна\nПаспорт серия и номер 15 54 738080, СНИЛС 378-000-367 66\n"
        "ИНН 850764715606, тел. +7 (911) 848-45-42\nE-mail: u528.8862@mail-demo.example.ru\n"
        "Банковская карта 4276 9578 1474 0578\n").encode()


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return out.getvalue()


def nest_xlsx(levels: int) -> bytes:
    """Book whose xl/embeddings/deep.zip holds `levels` nested zips with note.txt at the bottom."""
    inner = _zip({"note.txt": NOTE})
    for i in range(levels - 1):
        inner = _zip({f"inner{i}.zip": inner})
    src = zipfile.ZipFile(NEST4)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            raw = src.read(item.filename)
            if item.filename != "xl/embeddings/deep.zip":
                z.writestr(item, raw)
        z.writestr("xl/embeddings/deep.zip", inner)
    return out.getvalue()


def all_bytes(data: bytes) -> bytes:
    """Everything readable in a container, recursively."""
    acc = [data]
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return data
    for n in z.namelist():
        acc.append(all_bytes(z.read(n)))
    return b"\n".join(acc)


class NestedContainers(unittest.TestCase):
    def setUp(self):
        self.env = Env(image_mode="redact_text")
        self.addCleanup(self.env.close)

    def test_four_levels_are_processed_no_secret_left(self):
        job = self.env.anonymize(("nest4.xlsx", NEST4.read_bytes()))
        f = job.files[0]
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])
        blob = all_bytes(self.env.output_bytes(job)).decode("utf-8", "ignore")
        for secret in SECRETS:
            self.assertFalse(secret in blob, secret)

    def test_over_depth_is_blocked_without_output(self):
        job = self.env.anonymize(("deep.xlsx", nest_xlsx(12)))
        f = job.files[0]
        self.assertFalse(f.out_path)
        self.assertEqual(f.status, "error")

    def test_nested_package_beyond_old_limit_is_processed(self):
        job = self.env.anonymize(("nest5.xlsx", nest_xlsx(5)))
        f = job.files[0]
        self.assertTrue(f.out_path)
        blob = all_bytes(self.env.output_bytes(job)).decode("utf-8", "ignore")
        for secret in SECRETS:
            self.assertFalse(secret in blob, secret)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# (3) signature test
# ---------------------------------------------------------------------------
import fitz  # noqa: E402

from tests import pdf_probe as P  # noqa: E402


def pdf_with_text(text="Контакт: Смирнов Алексей Петрович, ivan@romashka.ru") -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontname="helv" if text.isascii() else "F0",
                     fontfile=P.FONT if not text.isascii() else None, fontsize=12)
    return doc


def add_sig(doc, *, ur3: bool, signed_field: bool, sigflags: int = 3) -> bytes:
    cat = doc.pdf_catalog()
    sig = doc.get_new_xref()
    ref = "/Reference [<< /Type /SigRef /TransformMethod /UR3 /TransformParams << /Type /TransformParams /V /2.2 >> >>] " if ur3 else ""
    doc.update_object(sig, "<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached "
                           f"/ByteRange [0 10 20 30] /Contents <{'00' * 16}> {ref}>>")
    doc.xref_set_key(cat, "AcroForm", f"<< /SigFlags {sigflags} /Fields [] >>")
    if ur3:
        doc.xref_set_key(cat, "Perms", f"<< /UR3 {sig} 0 R >>")
    if signed_field:
        field = doc.get_new_xref()
        doc.update_object(field, f"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Sig1) /Rect [10 10 100 40] /V {sig} 0 R "
                                  f"/P {doc[0].xref} 0 R >>")
        doc.xref_set_key(doc[0].xref, "Annots", f"[{field} 0 R]")
    return doc.tobytes()


@unittest.skipUnless(Path(P.FONT).exists(), "Arial нужен для кириллицы")
class SignatureTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(image_mode="redact_text")
        self.addCleanup(self.env.close)

    def run_pdf(self, data):
        job = self.env.anonymize(("a.pdf", data))
        return job.files[0]

    def test_usage_rights_signature_does_not_block(self):
        f = self.run_pdf(add_sig(pdf_with_text(), ur3=True, signed_field=False))
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])

    def test_empty_signature_field_does_not_block(self):
        doc = pdf_with_text()
        cat = doc.pdf_catalog()
        field = doc.get_new_xref()
        doc.update_object(field, f"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Sig1) /Rect [10 10 100 40] /P {doc[0].xref} 0 R >>")
        doc.xref_set_key(doc[0].xref, "Annots", f"[{field} 0 R]")
        doc.xref_set_key(cat, "AcroForm", f"<< /SigFlags 1 /Fields [{field} 0 R] >>")
        f = self.run_pdf(doc.tobytes())
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])

    def test_real_signature_with_byterange_still_blocks(self):
        f = self.run_pdf(add_sig(pdf_with_text(), ur3=False, signed_field=True))
        self.assertFalse(f.out_path)
        self.assertIn("подпис", " ".join(m["text"] for m in f.messages))


# ---------------------------------------------------------------------------
# (2) PDF restore fidelity: words drawn for OCR-redacted scan regions must not remain after restore
# ---------------------------------------------------------------------------
import collections  # noqa: E402
import re  # noqa: E402

from anonymizer import ocr  # noqa: E402


def scan_pdf_bytes() -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1240, 400), "white")
    font = ImageFont.truetype(P.FONT, 44)
    d = ImageDraw.Draw(img)
    d.text((40, 60), "Иванов Иван Петрович", font=font, fill="black")
    d.text((40, 160), "ИНН 7707083893  ivan.petrov@mail.ru", font=font, fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = fitz.open()
    page = doc.new_page(width=620, height=200)
    page.insert_image(page.rect, stream=buf.getvalue())
    page.insert_text((20, 190), "Native line 1", fontsize=8)
    return doc.tobytes()


def page_words(data: bytes) -> list[str]:
    doc = fitz.open(stream=data, filetype="pdf")
    return sorted(re.findall(r"\w+", "\n".join(p.get_text() for p in doc).lower()))


@unittest.skipUnless(Path(P.FONT).exists() and ocr.available(), "нужны Arial и OCR")
class RestoreFidelity(unittest.TestCase):
    def setUp(self):
        self.env = Env(image_mode="redact_text")
        self.addCleanup(self.env.close)

    def test_scan_restore_has_no_extra_words(self):
        src = scan_pdf_bytes()
        job = self.env.anonymize(("scan.pdf", src))
        f = job.files[0]
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])
        anon = self.env.output_bytes(job)
        self.assertNotIn("7707083893", " ".join(page_words(anon)))
        back = self.env.restore(self.env.as_upload(job))
        restored = self.env.output_bytes(back)
        self.assertEqual(page_words(restored), page_words(src))
        # the pixels are back: same picture as in the source
        def picture(data):
            d = fitz.open(stream=data, filetype="pdf")
            return fitz.Pixmap(d.extract_image(d[0].get_images(full=True)[0][0])["image"]).samples
        self.assertEqual(picture(restored), picture(src))


# ---------------------------------------------------------------------------
# (4) residual after OCR verify: second pass instead of blocking
# ---------------------------------------------------------------------------
import anonymizer.formats as F  # noqa: E402


@unittest.skipUnless(Path(P.FONT).exists() and ocr.available(), "нужны Arial и OCR")
class OcrSecondPass(unittest.TestCase):
    def setUp(self):
        self.env = Env(image_mode="redact_text")
        self.addCleanup(self.env.close)

    def test_verify_residual_triggers_second_pass_not_block(self):
        real = F._residuals
        calls = {"n": 0, "passes": 0}
        real_transform = F.transform_pdf

        def counting(*a, **k):
            calls["passes"] += 1
            return real_transform(*a, **k)

        def fake(detector, text, findings, ocr_text=False, *a, **k):
            calls["n"] += 1
            out = real(detector, text, findings, ocr_text, *a, **k)
            return (out or ["Иванов Иван Петрович"]) if calls["n"] == 1 else out
        F._residuals, F.transform_pdf = fake, counting
        try:
            job = self.env.anonymize(("scan.pdf", scan_pdf_bytes()))
        finally:
            F._residuals, F.transform_pdf = real, real_transform
        f = job.files[0]
        self.assertTrue(f.out_path, [m["text"] for m in f.messages])
        self.assertGreaterEqual(calls["passes"], 1)
        self.assertNotIn("7707083893", " ".join(page_words(self.env.output_bytes(job))))
