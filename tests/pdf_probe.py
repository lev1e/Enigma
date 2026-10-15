"""Проверка PDF «с чёрного хода»: исходные данные ищутся не только в тексте страницы, но и во всех остальных местах файла.

Те же приёмы, что у аудита безопасности 08.10: текст без обрезки по странице, слова и символы, примечания,
поля форм, закладки, вложения, XMP, словари объектов и сырые потоки (в UTF-8, UTF-16 и HEX).
"""
from __future__ import annotations

import fitz

from tests.font_support import system_font

FONT = system_font()

NAME = "Иванов Иван Петрович"
ORG = "Ромашка"
INN = "7707083893"
EMAIL = "ivan.petrov@mail.ru"
PHONE = "+7 (495) 123-45-67"
SENSITIVE = [NAME, "Иванов", "Петрович", ORG, INN, EMAIL, PHONE, "пример.рф", "москва.рф"]
LINE = f"{NAME}, ООО «{ORG}», ИНН {INN}, {EMAIL}"      # помещается в страницу A4 (595pt) при кегле 12


def put(page, xy, text, size=12, rotate=0, color=(0, 0, 0), **kw):
    page.insert_text(xy, text, fontname="arial", fontfile=FONT, fontsize=size, color=color, rotate=rotate, **kw)


def views(data: bytes) -> dict[str, str]:
    doc = fitz.open(stream=data, filetype="pdf")
    big = fitz.Rect(-5000, -5000, 5000, 5000)
    v: dict[str, str] = {
        "text": "\n".join(p.get_text("text") for p in doc),
        "noclip": "\n".join(p.get_text("text", flags=fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_MEDIABOX_CLIP, clip=big) for p in doc),
        "words": " ".join(w[4] for p in doc for w in p.get_text("words")),
        "meta": str(doc.metadata),
        "xmp": doc.get_xml_metadata() or "",
        "toc": str(doc.get_toc(simple=False)),
        "labels": str(doc.get_page_labels()),
        "links": str([lk for p in doc for lk in p.get_links()]),
        "embedded": str([(n, doc.embfile_info(n)) for n in doc.embfile_names()]),
        "widgets": str([(w.field_name, w.field_value, w.field_label) for p in doc for w in (p.widgets() or [])]),
        "annots": str([(a.type, a.info) for p in doc for a in (p.annots() or [])]),
    }
    raw_chars = []
    for p in doc:
        for block in p.get_text("rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_MEDIABOX_CLIP, clip=big)["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    raw_chars.append("".join(c["c"] for c in span["chars"]))
    v["rawdict"] = "\n".join(raw_chars)
    # словари всех объектов: подписи, подсказки, значения по умолчанию, пути в закладках
    v["objects"] = "\n".join(doc.xref_object(x) for x in range(1, doc.xref_length()))
    return v


def raw_hits(data: bytes, probes: list[str]) -> list[str]:
    """Сырые байты и распакованные потоки: UTF-8, UTF-16 (обе последовательности) и HEX-строки."""
    doc = fitz.open(stream=data, filetype="pdf")
    blobs = [data]
    for x in range(1, doc.xref_length()):
        try:
            blobs.append(doc.xref_stream_raw(x) or b"")
            blobs.append(doc.xref_stream(x) or b"")
        except Exception:
            pass
    found = []
    for probe in probes:
        patterns = [probe.encode(), probe.encode("utf-16-be"), probe.encode("utf-16-le"),
                    probe.encode("utf-16-be").hex().encode(), probe.encode("utf-16-be").hex().upper().encode()]
        if any(p in b for b in blobs for p in patterns):
            found.append(probe)
    return found


def leaks(data: bytes, probes: list[str] | None = None) -> list[str]:
    probes = probes or SENSITIVE
    found = []
    for name, text in views(data).items():
        found += [f"{name}:{p}" for p in probes if p in text]
    found += [f"raw:{p}" for p in raw_hits(data, probes)]
    return sorted(set(found))
