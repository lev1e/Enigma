"""W10: картинки целиком по умолчанию. Проверки смотрят в байты ВЫХОДНОГО файла, не в отчёт программы."""
from __future__ import annotations

import base64
import io
import os
import random
import tempfile
import unittest
import zipfile
from pathlib import Path

import fitz
from PIL import Image

from anonymizer import imagereplace
from anonymizer.service import Upload
from tests.helpers import Env, docx_bytes, pdf_bytes

JPEG_MARK = b"\xff\xd8\xff"
SECRET_COMMENT = b"SECRET-GPS-AUTHOR-4711"


def noise_image(seed: int, size=(96, 80)) -> Image.Image:
    rnd = random.Random(seed)
    im = Image.new("RGB", size)
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    return im


def png_bytes(seed: int, alpha: bool = False) -> bytes:
    im = noise_image(seed)
    if alpha:
        im = im.convert("RGBA")
        im.putalpha(Image.new("L", im.size, 128))
    buf = io.BytesIO()
    im.save(buf, "PNG", pnginfo=_pnginfo())
    return buf.getvalue()


def _pnginfo():
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("Author", SECRET_COMMENT.decode())
    return info


def jpg_bytes(seed: int) -> bytes:
    """JPEG с EXIF (GPS-подобная строка, миниатюра), комментарием и ICC-подобным блоком."""
    im = noise_image(seed)
    exif = Image.Exif()
    exif[0x010E] = SECRET_COMMENT.decode()
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90, exif=exif, comment=SECRET_COMMENT)
    return buf.getvalue()


def windows(raw: bytes, n: int = 4) -> list[bytes]:
    """Несколько 24-байтных отрезков из середины файла: по ним ищется утечка оригинальных данных."""
    out = []
    for i in range(n):
        start = len(raw) // 5 + i * len(raw) // 7
        out.append(raw[start:start + 24])
    return out


def all_streams(path: Path) -> bytes:
    """Все байты выходного файла, включая распакованное содержимое zip и потоки PDF."""
    data = path.read_bytes()
    blob = [data]
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(path) as z:
            blob += [z.read(n) for n in z.namelist()]
    elif data[:4] == b"%PDF":
        doc = fitz.open(path)
        for x in range(1, doc.xref_length()):
            try:
                blob.append(doc.xref_stream_raw(x) or b"")
                blob.append(doc.xref_stream(x) or b"")
            except Exception:
                pass
        doc.close()
    return b"\n".join(blob)


class W10Base(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def run_one(self, name: str, data: bytes):
        job = self.env.anonymize((name, data))
        f = job.files[0]
        self.assertTrue(f.out_path, f"нет вывода: {getattr(f, 'messages', None)} {getattr(f, 'status', None)}")
        return job, Path(f.out_path)

    def assertClean(self, out: Path, originals: list[bytes]):
        blob = all_streams(out)
        for raw in originals:
            for w in windows(raw):
                self.assertNotIn(w, blob, "кусок оригинальной картинки остался в выходе")
        self.assertNotIn(SECRET_COMMENT, blob)
        self.assertNotIn(b"Exif\x00\x00", blob)
        self.assertNotIn(b"tEXt", blob)

    def restored(self, out: Path, name: str) -> Path:
        res = self.env.restore(Upload(name, out.read_bytes()))
        return Path(res.files[0].out_path)


class TestStandalone(W10Base):
    def test_png_and_jpg_replaced_and_restored_exactly(self):
        for name, raw in (("a.png", png_bytes(1)), ("b.jpg", jpg_bytes(2))):
            job, out = self.run_one(name, raw)
            data = out.read_bytes()
            self.assertNotEqual(data, raw)
            self.assertClean(out, [raw])
            self.assertEqual(Image.open(io.BytesIO(data)).format, "PNG" if name.endswith("png") else "JPEG")
            back = self.restored(out, out.name)
            self.assertEqual(back.read_bytes(), raw)

    def test_placeholders_are_unique(self):
        raw = png_bytes(3)
        a = imagereplace.placeholder_for(raw, "Image1")
        b = imagereplace.placeholder_for(raw, "Image1")
        self.assertNotEqual(a, b)


class TestOoxml(W10Base):
    def test_docx_xlsx_pptx(self):
        import docx
        from openpyxl import Workbook
        from openpyxl.drawing.image import Image as XImage
        from pptx import Presentation
        from pptx.util import Inches
        png, jpg = png_bytes(10), jpg_bytes(11)
        d = docx.Document()
        d.add_paragraph("hello")
        d.add_picture(io.BytesIO(png))
        d.add_picture(io.BytesIO(jpg))
        b = io.BytesIO(); d.save(b)
        wb = Workbook(); wb.active["A1"] = "x"
        wb.active.add_image(XImage(io.BytesIO(png)), "C3")
        wx = io.BytesIO(); wb.save(wx)
        prs = Presentation(); s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_picture(io.BytesIO(jpg), Inches(1), Inches(1))
        px = io.BytesIO(); prs.save(px)
        for name, data in (("d.docx", b.getvalue()), ("x.xlsx", wx.getvalue()), ("p.pptx", px.getvalue())):
            job, out = self.run_one(name, data)
            self.assertClean(out, [png, jpg])
            with zipfile.ZipFile(out) as z:
                media = [n for n in z.namelist() if "/media/" in n]
                self.assertTrue(media)
                for n in media:
                    self.assertIn(z.read(n)[:4], (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xdb"))
            back = self.restored(out, out.name)
            with zipfile.ZipFile(back) as z:
                got = {z.read(n) for n in z.namelist() if "/media/" in n}
            self.assertTrue(got & {png, jpg}, "оригинал не вернулся побайтно")
            self.assertLessEqual(got, {png, jpg})

    def test_emf_svg_parts_replaced(self):
        emf = imagereplace._emf_placeholder() + b"ORIGINAL-EMF-TEXT-SECRET"
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(["x"]))) as zin, zipfile.ZipFile(buf, "w") as zout:
            for i in zin.infolist():
                zout.writestr(i, zin.read(i.filename))
            zout.writestr("word/media/image9.emf", emf)
        job, out = self.run_one("e.docx", buf.getvalue())
        self.assertNotIn(b"ORIGINAL-EMF-TEXT-SECRET", all_streams(out))


class TestText(W10Base):
    def test_html_and_md_data_uri(self):
        png = png_bytes(20)
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        html = f'<html><body><p>hi</p><img src="{uri}"></body></html>'
        job, out = self.run_one("p.html", html.encode())
        text = out.read_text()
        self.assertNotIn(base64.b64encode(png).decode()[100:160], text)
        back = self.restored(out, out.name)
        self.assertIn(base64.b64encode(png).decode(), back.read_text())
        md = f"# t\n\n![x]({uri})\n"
        job, out = self.run_one("n.md", md.encode())
        self.assertNotIn(base64.b64encode(png).decode()[100:160], out.read_text())
        self.assertIn(base64.b64encode(png).decode(), self.restored(out, out.name).read_text())


class TestLinked(W10Base):
    def test_local_linked_image_refused(self):
        for name, body in (("l.html", '<img src="local.png"><p>x</p>'), ("l.md", "![a](pics/local.jpg)\n")):
            job = self.env.anonymize((name, body.encode()))
            f = job.files[0]
            self.assertFalse(f.out_path)
            self.assertIn("ссылки на файлы картинок", str(f.messages))

    def test_remote_link_not_refused(self):
        job = self.env.anonymize(("r.html", b'<img src="https://example.org/a.png"><p>x</p>'))
        self.assertTrue(job.files[0].out_path)


class TestScannedAndNested(W10Base):
    def test_scanned_pdf_page(self):
        png = png_bytes(60, False)
        big = io.BytesIO(); noise_image(61, (600, 800)).save(big, "PNG"); big = big.getvalue()
        doc = fitz.open(); page = doc.new_page()
        page.insert_image(page.rect, stream=big)
        data = doc.tobytes(); doc.close()
        job, out = self.run_one("scan.pdf", data)
        o = fitz.open(stream=data); samples = [o.xref_stream(i[0]) for i in o[0].get_images()]
        blob = all_streams(out)
        for smp in samples:
            for w in windows(smp):
                self.assertNotIn(w, blob)
        before = o[0].get_pixmap(dpi=40).samples
        after = fitz.open(out)[0].get_pixmap(dpi=40).samples
        self.assertNotEqual(before, after)
        back = fitz.open(self.restored(out, out.name))
        self.assertIn(samples[0], [back.xref_stream(i[0]) for i in back[0].get_images()])

    def test_gif_bmp_webp_parts_and_nested_zip(self):
        raws = {}
        for ext, fmt in (("gif", "GIF"), ("bmp", "BMP"), ("webp", "WEBP")):
            b = io.BytesIO(); noise_image(70 + len(ext)).save(b, fmt); raws[ext] = b.getvalue()
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("pic.png", png_bytes(80))
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(["x"]))) as zin, zipfile.ZipFile(buf, "w") as zout:
            for i in zin.infolist():
                zout.writestr(i, zin.read(i.filename))
            for ext, raw in raws.items():
                zout.writestr(f"word/media/p.{ext}", raw)
        job, out = self.run_one("g.docx", buf.getvalue())
        self.assertClean(out, list(raws.values()))
        with zipfile.ZipFile(out) as z:
            for ext in raws:
                self.assertTrue(z.read(f"word/media/p.{ext}")[:3] in (b"GIF", b"BM\x00", b"BM6") or z.read(f"word/media/p.{ext}")[:4] == b"RIFF" or z.read(f"word/media/p.{ext}")[:2] == b"BM")
        back = self.restored(out, out.name)
        with zipfile.ZipFile(back) as z:
            for ext, raw in raws.items():
                self.assertEqual(z.read(f"word/media/p.{ext}"), raw)

    def test_nested_package_images(self):
        import docx
        inner_doc = docx.Document(); inner_doc.add_picture(io.BytesIO(png_bytes(90)))
        ib = io.BytesIO(); inner_doc.save(ib)
        png = png_bytes(90)
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(["x"]))) as zin, zipfile.ZipFile(buf, "w") as zout:
            for i in zin.infolist():
                zout.writestr(i, zin.read(i.filename))
            zout.writestr("word/embeddings/inner.docx", ib.getvalue())
        job = self.env.anonymize(("n.docx", buf.getvalue()))
        f = job.files[0]
        if f.out_path:
            with zipfile.ZipFile(f.out_path) as z, zipfile.ZipFile(io.BytesIO(z.read("word/embeddings/inner.docx"))) as zi:
                media = [zi.read(n) for n in zi.namelist() if "/media/" in n]
            for m in media:
                self.assertNotIn(windows(png)[0], m)
        else:
            self.assertEqual(f.status, "error")     # отказ допустим; молча пропустить картинку нельзя


class TestPdf(W10Base):
    def make_pdf(self):
        png, jpg, apng = png_bytes(30), jpg_bytes(31), png_bytes(32, alpha=True)
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 60), "Contract", fontsize=12)
        page.insert_image(fitz.Rect(72, 100, 272, 260), stream=png)
        page.insert_image(fitz.Rect(300, 100, 500, 260), stream=jpg)
        page.insert_image(fitz.Rect(72, 300, 272, 460), stream=apng)
        data = doc.tobytes()
        doc.close()
        return data, [png, jpg, apng]

    def test_pdf_images_replaced_and_restored(self):
        data, originals = self.make_pdf()
        job, out = self.run_one("c.pdf", data)
        doc = fitz.open(out)
        before = []
        for x in range(1, doc.xref_length()):
            if doc.xref_get_key(x, "Subtype")[1] == "/Image":
                self.assertEqual(doc.xref_get_key(x, "Width")[1], "1")
                before.append(x)
        self.assertGreaterEqual(len(before), 3)
        pix = doc[0].get_pixmap()
        self.assertEqual(len(doc[0].get_images()), len(doc[0].get_images()))
        doc.close()
        orig_doc = fitz.open(stream=data)
        orig_samples = [orig_doc.xref_stream(i[0]) for i in orig_doc[0].get_images()]
        blob = all_streams(out)
        for s in orig_samples:
            for w in windows(s):
                self.assertNotIn(w, blob)
        self.assertNotIn(SECRET_COMMENT, blob)
        back = fitz.open(self.restored(out, out.name))
        orig_raw = [orig_doc.xref_stream(i[0]) for i in orig_doc[0].get_images()]
        back_raw = [back.xref_stream(i[0]) for i in back[0].get_images()]
        for r in orig_raw:
            self.assertIn(r, back_raw, "поток картинки не вернулся побайтно")

    def test_inline_image_replaced_and_restored(self):
        doc = fitz.open()
        page = doc.new_page()
        rnd = random.Random(5)
        pixels = bytes(rnd.randrange(256) for _ in range(32 * 32))
        content = b"q 100 0 0 100 72 600 cm\nBI /W 32 /H 32 /CS /G /BPC 8 ID " + pixels + b"\nEI Q\n"
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, content, new=True)
        page.set_contents(xref)
        data = doc.tobytes()
        doc.close()
        job, out = self.run_one("i.pdf", data)
        blob = all_streams(out)
        for w in windows(pixels, 3):
            self.assertNotIn(w, blob)
        back = fitz.open(self.restored(out, out.name))
        got = b"".join(back.xref_stream(x) or b"" for x in range(1, back.xref_length()))
        self.assertIn(pixels, got)


class TestStoreLimit(W10Base):
    def test_limit_refuses_clearly(self):
        os.environ["ANON_IMAGE_STORE_MB"] = "0.00001"
        try:
            job = self.env.anonymize(("a.png", png_bytes(40)))
            f = job.files[0]
            self.assertFalse(f.out_path)
            self.assertIn("лимит", str(f.messages))
        finally:
            del os.environ["ANON_IMAGE_STORE_MB"]


class TestMetadataStrip(unittest.TestCase):
    def test_strip_all(self):
        for raw in (png_bytes(50), jpg_bytes(51)):
            out = imagereplace.strip_all_metadata(raw)
            self.assertNotIn(SECRET_COMMENT, out)
            self.assertNotIn(b"Exif", out)
            Image.open(io.BytesIO(out)).load()


if __name__ == "__main__":
    unittest.main()
