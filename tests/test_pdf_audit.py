"""PDF: воспроизведения из аудита безопасности 08.10 (каждый файл собран так же, как в аудите).

Проверка идёт по всем «чёрным ходам» (tests/pdf_probe.py): текст без обрезки, символы, примечания, поля, закладки,
вложения, XMP, словари объектов, сырые потоки. Если файл нельзя обезличить надёжно, результат не выдаётся совсем.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import fitz

from tests import pdf_probe as P
from tests.helpers import Env

HAS_FONT = Path(P.FONT).exists()


@unittest.skipUnless(HAS_FONT, "нужен Arial для кириллицы")
class PdfAuditBase(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def anonymize(self, doc_or_bytes, **options):
        data = doc_or_bytes if isinstance(doc_or_bytes, bytes) else doc_or_bytes.tobytes()
        job = self.env.anonymize(("a.pdf", data), options=options or None)
        f = job.files[0]
        out = Path(f.out_path).read_bytes() if f.out_path else None
        return job, f, out

    def assertClean(self, doc, probes=None, **options):
        job, f, out = self.anonymize(doc, **options)
        if out is None:      # отказ выдать файл — допустимый безопасный исход, но причина должна быть названа
            self.assertTrue(f.messages, "файл не выдан, а причины нет")
            return job, f, None
        self.assertEqual(P.leaks(out, probes), [], [m["text"] for m in f.messages])
        return job, f, out

    def restore(self, job):
        rj = self.env.restore(self.env.as_upload(job))
        rf = rj.files[0]
        return rf, (Path(rf.out_path).read_bytes() if rf.out_path else None)

    def assertRoundTrip(self, job, original_doc, must=None):
        rf, back = self.restore(job)
        self.assertIsNotNone(back, [m["text"] for m in rf.messages])
        text = "\n".join(p.get_text("text", flags=fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_MEDIABOX_CLIP,
                                    clip=fitz.Rect(-5000, -5000, 5000, 5000)) for p in fitz.open(stream=back, filetype="pdf"))
        norm = lambda s: "".join(s.split())
        for probe in must or [P.NAME, P.EMAIL]:
            self.assertIn(norm(probe), norm(text), f"после возврата нет «{probe}»")
        self.assertEqual(len(fitz.open(stream=back, filetype="pdf")), len(original_doc))


def page_doc(*lines, rotate=0):
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        P.put(page, (72, 100 + 20 * i), line, rotate=rotate)
    return doc


class HiddenContent(PdfAuditBase):
    def test_hidden_layer_form_xobject(self):
        """Из аудита: текст в скрытом слое (OCG), положенный как форма-XObject. Старый код не видел его в get_text."""
        doc = fitz.open()
        page = doc.new_page()
        P.put(page, (72, 72), "Видимый текст.")
        layer = doc.add_ocg("Скрытый слой", on=False)
        inner = fitz.open()
        P.put(inner.new_page(), (72, 100), P.LINE)
        page.show_pdf_page(page.rect, inner, 0, oc=layer)
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out)

    def test_white_tiny_and_invisible_render_mode(self):
        doc = fitz.open()
        page = doc.new_page()
        P.put(page, (72, 72), "Видимый текст без данных.")
        P.put(page, (72, 100), P.LINE, color=(1, 1, 1))
        P.put(page, (72, 130), P.LINE, size=0.8)
        P.put(page, (72, 160), P.LINE, render_mode=3)
        self.assertClean(doc)

    def test_off_page_text(self):
        doc = fitz.open()
        page = doc.new_page()
        P.put(page, (72, 72), "Видимый текст.")
        P.put(page, (-300, 100), P.LINE)
        P.put(page, (72, 1200), P.LINE)
        P.put(page, (400, 140), P.LINE)       # начинается на странице, заканчивается за её краем
        self.assertClean(doc)

    def test_text_under_black_rectangle(self):
        doc = fitz.open()
        page = doc.new_page()
        P.put(page, (72, 100), P.LINE)
        page.draw_rect(fitz.Rect(60, 80, 560, 120), color=None, fill=(0, 0, 0))
        self.assertClean(doc)


class Metadata(PdfAuditBase):
    def make(self):
        doc = page_doc(f"Договор. Подписант: {P.NAME} ({P.EMAIL}).")
        doc.set_metadata({"title": "Договор " + P.NAME, "author": P.NAME, "subject": f"ООО «{P.ORG}» ИНН {P.INN}",
                          "keywords": f"{P.EMAIL}, {P.PHONE}", "creator": P.NAME, "producer": "Word " + P.NAME})
        doc.set_xml_metadata('<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
                             '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
                             'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator><rdf:Seq><rdf:li>'
                             f'{P.NAME}</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')
        info = int(doc.xref_get_key(-1, "Info")[1].split()[0])
        doc.xref_set_key(info, "Company", f"(ООО {P.ORG})")
        doc.xref_set_key(info, "CustomOwner", "<" + ("﻿" + P.NAME).encode("utf-16-be").hex() + ">")
        return doc

    def test_info_xmp_and_custom_keys(self):
        _, _, out = self.assertClean(self.make())
        self.assertIsNotNone(out)

    def test_toc_labels_and_producer(self):
        doc = page_doc(f"Подписант {P.NAME}")
        doc.new_page()
        doc.set_toc([[1, "Раздел: " + P.NAME, 1], [2, "Контакт " + P.EMAIL, 2]])
        doc.set_page_labels([{"startpage": 0, "prefix": "Иванов-", "style": "D", "firstpagenum": 1}])
        self.assertClean(doc)


class Annotations(PdfAuditBase):
    def test_annotations_widgets_links(self):
        doc = page_doc(f"Подписант {P.NAME} ({P.EMAIL}).")
        page = doc[0]
        a = page.add_text_annot((300, 300), f"Комментарий: позвонить {P.NAME} {P.EMAIL}")
        a.set_info(title=P.NAME, subject=f"ИНН {P.INN}")
        a.update()
        h = page.add_highlight_annot(fitz.Rect(72, 60, 200, 80))
        h.set_info(content="Это " + P.NAME)
        h.update()
        page.add_freetext_annot(fitz.Rect(72, 200, 400, 240), f"Тел. {P.PHONE} {P.NAME}", fontname="helv").update()
        page.add_freetext_annot(fitz.Rect(72, 260, 400, 300), P.NAME, fontname="china-s").update()
        w = fitz.Widget()
        w.field_type, w.field_name, w.rect, w.field_value = fitz.PDF_WIDGET_TYPE_TEXT, "fio", fitz.Rect(72, 320, 400, 350), P.NAME
        w.field_label = "Почта " + P.NAME
        page.add_widget(w)
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 60, 300, 80), "uri": f"mailto:{P.EMAIL}?subject=Иванов"})
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 100, 300, 120), "uri": "https://example.com/users/ivan"})
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 130, 300, 150), "uri": "https://пример.рф/страница"})
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out, "примечания, поля и ссылки обезличиваются, а не блокируют файл")

    def test_annotation_text_is_restored(self):
        doc = page_doc("Страница.")
        a = doc[0].add_text_annot((300, 300), f"Позвонить {P.NAME}")
        a.update()
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out)
        rf, back = self.restore(job)
        self.assertIsNotNone(back)
        contents = " ".join(x.info.get("content", "") for x in fitz.open(stream=back, filetype="pdf")[0].annots())
        self.assertIn(P.NAME, contents)

    def test_form_default_and_tooltip(self):
        doc = page_doc("Форма")
        w = fitz.Widget()
        w.field_type, w.field_name, w.rect, w.field_value = fitz.PDF_WIDGET_TYPE_TEXT, "fio", fitz.Rect(72, 200, 400, 230), "x"
        doc[0].add_widget(w)
        xref = [x for x in doc[0].widgets()][0].xref
        doc.xref_set_key(xref, "DV", f"({P.EMAIL})")
        doc.xref_set_key(xref, "TU", f"(Фио: {P.NAME})")
        self.assertClean(doc)

    def test_attachments_and_file_annotations_removed(self):
        doc = page_doc("Страница.")
        doc.embfile_add("договор.txt", f"{P.NAME} {P.EMAIL}".encode(), filename="Иванов.txt", desc=P.NAME)
        doc[0].add_file_annot((300, 400), f"{P.NAME} {P.EMAIL}".encode(), "иванов.txt", desc=P.NAME)
        _, _, out = self.assertClean(doc)
        self.assertIsNotNone(out)
        self.assertEqual(fitz.open(stream=out, filetype="pdf").embfile_count(), 0)


class Geometry(PdfAuditBase):
    def test_rotated_text_every_direction(self):
        for rotate in (90, 180, 270):
            with self.subTest(rotate=rotate):
                doc = fitz.open()
                page = doc.new_page()
                P.put(page, (500, 400), P.LINE, rotate=rotate)
                job, f, out = self.assertClean(doc)
                self.assertIsNotNone(out, "повёрнутый текст обезличивается, а не блокирует файл")

    def test_rotated_text_placeholder_visible_and_restorable(self):
        doc = fitz.open()
        page = doc.new_page()
        P.put(page, (500, 400), f"Подписант {P.NAME}", rotate=90)
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out)
        text = "".join(fitz.open(stream=out, filetype="pdf")[0].get_text("text").split())
        self.assertRegex(text, r"Name1", "метка должна читаться, иначе значение не вернуть")
        self.assertNotIn("не удалось вставить метки", " ".join(m["text"] for m in f.messages))
        self.assertRoundTrip(job, doc, must=[P.NAME])

    def test_page_rotation_attribute(self):
        doc = page_doc(P.LINE)
        doc[0].set_rotation(90)
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out)
        self.assertRoundTrip(job, doc, must=[P.NAME, P.EMAIL])

    def test_name_split_across_lines(self):
        doc = page_doc("Директор Иванов Иван", "Петрович подписал договор.")
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out)
        self.assertRoundTrip(job, doc, must=[P.NAME])

    def test_inn_and_phone_split_by_hyphen(self):
        doc = page_doc("ИНН 7707-", "083893 подтверждён", "Телефон +7 (495) 123-", "45-67 рабочий")
        _, _, out = self.assertClean(doc, probes=[P.INN, "7707083893", P.PHONE])
        if out is not None:
            joined = "".join(fitz.open(stream=out, filetype="pdf")[0].get_text("text").split())
            for tail in ("7707", "083893", "123-", "45-67"):
                self.assertNotIn(tail, joined)

    def test_soft_hyphen_in_email(self):
        doc = page_doc("Почта ivan.petrov@­mail.ru, а также ivan.pe­trov@mail.ru")
        _, _, out = self.assertClean(doc, probes=[P.EMAIL, "ivan.petrov"])

    def test_name_split_across_pages(self):
        doc = fitz.open()
        for text in ("Директор Иванов Иван", "Петрович подписал договор."):
            page = doc.new_page()
            P.put(page, (72, 740 if text.startswith("Дир") else 72), text)
        job, f, out = self.assertClean(doc)
        self.assertIsNotNone(out)


class Images(PdfAuditBase):
    def scan(self, hidden_text_layer=False):
        src = page_doc(*[ln for ln in (P.LINE, "Адрес: Россия, г. Москва, ул. Тверская, д. 7")])
        pix = src[0].get_pixmap(dpi=150)
        scan = fitz.open()
        page = scan.new_page()
        page.insert_image(page.rect, pixmap=pix)
        if hidden_text_layer:
            for i, line in enumerate((P.LINE,)):
                P.put(page, (72, 100 + 20 * i), line, render_mode=3)
        return scan

    def test_image_only_scan_is_not_returned_unchanged(self):
        """Скан с ФИО на изображении: файл либо обезличен по пикселям, либо не выдаётся совсем."""
        job, f, out = self.anonymize(self.scan())
        if out is not None:
            self.assertTrue(self.pixels_cleared(out), "изображение со скана выдано без изменений")
        else:
            self.assertTrue(any("скан" in m["text"].lower() or "изображ" in m["text"].lower() for m in f.messages))

    def test_scan_with_invisible_text_layer_keeps_pixels_private(self):
        """Скан + невидимый слой распознанного текста: слой заменён, а пиксели по-прежнему несут ФИО."""
        job, f, out = self.anonymize(self.scan(hidden_text_layer=True))
        if out is not None:
            self.assertTrue(self.pixels_cleared(out), "слой текста заменён, а имя осталось на картинке")

    def pixels_cleared(self, data: bytes) -> bool:
        """Картинка в результате отличается от исходной либо удалена."""
        doc = fitz.open(stream=data, filetype="pdf")
        original = self.scan().tobytes()
        src = fitz.open(stream=original, filetype="pdf")
        src_images = {fitz.Pixmap(src, x).digest for x in (i[0] for i in src[0].get_images(full=True))}
        out_images = {fitz.Pixmap(doc, x).digest for x in (i[0] for i in doc[0].get_images(full=True))}
        return not (out_images & src_images)


if __name__ == "__main__":
    unittest.main()
