"""S6A: PDF-картинки с /JBIG2Globals и /Metadata; скорость без изменения вывода."""
from __future__ import annotations

import unittest
from pathlib import Path

import fitz

from tests.test_ws_w10 import W10Base, all_streams, jpg_bytes

GLOBALS_RAW = b"GLOBALS-SYMBOL-DICT-\x00\x01\x02-4711-" * 5
IMAGE_RAW = b"JBIG2-IMAGE-DATA-\x03\x04\x05-9090-" * 7


def pdf_with_jbig2(images: int = 2, metadata: bool = True) -> bytes:
    """PDF, у которого картинки ссылаются на общий /JBIG2Globals и на /Metadata (содержимое потока не декодируется)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Purchase order", fontsize=12)
    for i in range(images):
        page.insert_image(fitz.Rect(72, 100 + 170 * i, 272, 260 + 170 * i), stream=jpg_bytes(40 + i))
    globs = doc.get_new_xref()
    doc.update_object(globs, "<< >>")
    doc.update_stream(globs, GLOBALS_RAW, new=True, compress=False)
    meta = doc.get_new_xref()
    doc.update_object(meta, "<< /Type /Metadata /Subtype /XML >>")
    doc.update_stream(meta, b"<x:xmpmeta>SECRET-XMP-AUTHOR-77</x:xmpmeta>", new=True, compress=False)
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Subtype")[1] == "/Image":
            doc.update_stream(xref, IMAGE_RAW + bytes([xref]), new=True, compress=False)
            doc.xref_set_key(xref, "Filter", "/JBIG2Decode")
            doc.xref_set_key(xref, "DecodeParms", f"<< /JBIG2Globals {globs} 0 R >>")
            doc.xref_set_key(xref, "ColorSpace", "/DeviceGray")
            doc.xref_set_key(xref, "BitsPerComponent", "1")
            if metadata:
                doc.xref_set_key(xref, "Metadata", f"{meta} 0 R")
    data = doc.tobytes()
    doc.close()
    return data


def image_dicts(path_or_bytes) -> list[tuple[str, bytes]]:
    doc = fitz.open(stream=path_or_bytes) if isinstance(path_or_bytes, bytes) else fitz.open(path_or_bytes)
    out = []
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Subtype")[1] == "/Image":
            out.append((xref, doc))
    return out


class TestJbig2AndMetadata(W10Base):
    def test_jbig2_globals_and_metadata_are_replaced_and_restored(self):
        data = pdf_with_jbig2(2)
        job, out = self.run_one("jb.pdf", data)
        blob = all_streams(out)
        self.assertNotIn(IMAGE_RAW[:24], blob)
        self.assertNotIn(GLOBALS_RAW[:24], blob)
        self.assertNotIn(b"SECRET-XMP-AUTHOR-77", blob)
        doc = fitz.open(out)
        for xref in range(1, doc.xref_length()):
            if doc.xref_get_key(xref, "Subtype")[1] == "/Image":
                self.assertEqual(doc.xref_get_key(xref, "Width")[1], "1")
        doc.close()
        back = fitz.open(self.restored(out, "jb.pdf"))
        found = 0
        for xref in range(1, back.xref_length()):
            if back.xref_get_key(xref, "Subtype")[1] != "/Image":
                continue
            self.assertTrue(back.xref_stream_raw(xref).startswith(IMAGE_RAW) and len(back.xref_stream_raw(xref)) == len(IMAGE_RAW) + 1)
            self.assertEqual(back.xref_get_key(xref, "Filter")[1], "/JBIG2Decode")
            self.assertEqual(back.xref_get_key(xref, "Metadata")[0], "null")
            ref = back.xref_get_key(xref, "DecodeParms")[1]
            gx = int(__import__("re").search(r"/JBIG2Globals\s+(\d+)\s+0\s+R", ref).group(1))
            self.assertEqual(back.xref_stream(gx), GLOBALS_RAW)
            found += 1
        self.assertEqual(found, 2)

    def test_metadata_only_image(self):
        data = pdf_with_jbig2(1, metadata=True)
        doc = fitz.open(stream=data)
        for xref in range(1, doc.xref_length()):
            if doc.xref_get_key(xref, "Subtype")[1] == "/Image":
                doc.xref_set_key(xref, "DecodeParms", "null")
                doc.xref_set_key(xref, "Filter", "null")
                doc.xref_set_key(xref, "ColorSpace", "/DeviceGray")
        data = doc.tobytes()
        job, out = self.run_one("md.pdf", data)
        self.assertNotIn(b"SECRET-XMP-AUTHOR-77", all_streams(out))


if __name__ == "__main__":
    unittest.main()


class TestResidualOwnLabel(unittest.TestCase):
    def test_value_inside_own_email_label_is_not_residual(self):
        from anonymizer import formats
        from anonymizer.models import Decision

        class F:
            def __init__(self, original, category="ORG"):
                self.original, self.category, self.decision = original, category, Decision.AUTO

        class Det:
            def verify(self, text):
                return []
        self.assertEqual(formats._residuals(Det(), "mail email1@example.com end", [F("com")]), [])
        self.assertEqual(formats._residuals(Det(), "mail com end", [F("com")]), ["com"])
        self.assertEqual(formats._residuals(Det(), "mail email1@example.com and com", [F("com")]), ["com"])


class TestPortableLength(unittest.TestCase):
    def test_indirect_length_is_resolved(self):
        from anonymizer import imagereplace
        doc = fitz.open()
        n = doc.get_new_xref()
        doc.update_object(n, "1234")
        obj, keep = imagereplace._portable(doc, f"<< /Length {n} 0 R /Subtype /Image >>")
        self.assertIn("/Length 1234", obj)
        self.assertEqual(keep, [])
