"""PDF: места, где исходные данные оставались после обезличивания (найдено аудитом 08.10)."""
from __future__ import annotations

import unittest

import fitz

from tests.helpers import Env
from tests.test_review_fixes import make_app, run_job

from tests.font_support import system_font

FONT = system_font()
NAME, EMAIL = "Иванов Иван Петрович", "ivan.petrov@mail.ru"


def base() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"Директор {NAME}, ИНН: 7707083893", fontname="arial", fontfile=FONT, fontsize=12)
    return doc


class PdfLeaks(unittest.TestCase):
    def setUp(self):
        self.env = Env(); self.addCleanup(self.env.close)
        self.app = make_app(self.env); self.addCleanup(self.app.cleanup_open)

    def run_pdf(self, doc):
        chat = self.app.chats.create("p", keep_originals=True)["id"]
        run_job(self.app, "anonymize", [("a.pdf", doc.tobytes())], chat_id=chat, options={})
        rec = self.app.chats.get(chat)["files"][-1]
        return self.app.chats.read_blob(chat, rec["id"], "anon"), rec

    def leaks(self, data) -> bool:
        out = fitz.open(stream=data, filetype="pdf")
        blob = data + b"".join((out.xref_object(x) or "").encode("utf-8", "ignore") for x in range(1, out.xref_length()))
        probes = [NAME, EMAIL, "Ромашка", "Иванов"]
        found = [p for p in probes if any(v in blob for v in (p.encode(), p.encode("utf-16-be"), p.encode("utf-16-be").hex().encode()))]
        for page in out:
            text = page.get_text("text") + " ".join(str(a.info) for a in (page.annots() or []))
            found += [p for p in probes if p in text]
        found += [p for p in probes if p in str(out.metadata)]
        return found

    def test_hidden_layer_text_is_hidden_and_replaced(self):
        doc = base()
        page = doc[0]
        layer = doc.add_ocg("Скрытый слой", on=False)
        page.insert_text((72, 200), f"Секрет: {NAME}", fontname="arial", fontfile=FONT, fontsize=12, oc=layer)
        data, _ = self.run_pdf(doc)
        self.assertEqual(self.leaks(data), [])

    def test_attachments_removed(self):
        doc = base()
        doc.embfile_add("список.txt", f"{NAME} {EMAIL}".encode(), desc=NAME)
        data, rec = self.run_pdf(doc)
        out = fitz.open(stream=data, filetype="pdf")
        self.assertEqual(out.embfile_count(), 0)
        self.assertEqual(self.leaks(data), [])

    def test_file_annotation_removed(self):
        doc = base()
        doc[0].add_file_annot((300, 300), f"{NAME}".encode(), "x.txt")
        data, _ = self.run_pdf(doc)
        out = fitz.open(stream=data, filetype="pdf")
        self.assertFalse([a for a in out[0].annots() or [] if a.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT])
        self.assertEqual(self.leaks(data), [])

    def test_custom_info_keys_cleared(self):
        doc = base()
        doc.set_metadata({"author": "Автор"})
        info = int(doc.xref_get_key(-1, "Info")[1].split()[0])
        doc.xref_set_key(info, "Company", "(ООО Ромашка)")
        data, _ = self.run_pdf(doc)
        self.assertEqual(self.leaks(data), [])

    def test_link_uri_with_email_removed(self):
        doc = base()
        doc[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 300, 200, 320), "uri": f"mailto:{EMAIL}"})
        data, _ = self.run_pdf(doc)
        out = fitz.open(stream=data, filetype="pdf")
        self.assertFalse([l for l in out[0].get_links() if EMAIL in (l.get("uri") or "")])
        self.assertEqual(self.leaks(data), [])


if __name__ == "__main__":
    unittest.main()
