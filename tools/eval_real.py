"""Real-document evaluation: tests/eval/real_manifest.json (+ adversarial synthetic cases) through the real service pipeline.

  python tools/eval_real.py run [--only substr] [--limit N]    -> tests/eval/real/_results.json (git-ignored; `publish` copies it to tracked real_results.json)  (one subprocess per case)
  python tools/eval_real.py report                              -> docs/superpowers/quality-matrix.md + eval-failures.md (auto part)

Ground truth is independent of the product: synthetic identities are INJECTED into a copy of every real document (text layer,
table cell, header, new slide, or rasterised banner for scans/images). Leakage is checked on the OUTPUT with other tools
(zip parts, python-docx/openpyxl/python-pptx, PyMuPDF, poppler pdftotext, tesseract OCR re-run), after folding
zero-width characters, spacing/punctuation and Latin/Cyrillic look-alikes. Recall here = share of injected values that
no longer appear in the output (end-to-end, stricter than span recall). Precision = share of replaced values that overlap an
injected value; replaced values from the native document (real names in laws, etc.) count as unverified false positives.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
IMG_FMTS = ("png", "jpg", "tiff", "webp", "bmp")
from anonymizer.util import peak_memory_mb
from eval_ids import dense                                      # noqa: E402
from eval_inject import inject as dinject, synth                # noqa: E402
TEXT_FMTS = ("txt", "csv", "tsv", "md", "json", "xml", "log", "ini", "yaml", "yml", "html", "htm")
SYNTH_KINDS = ("contract", "invoice", "resume", "ruling", "minutes", "mail")
# synthetic complex documents: (kind, lang, fmt, extra traits); every one is long, structured and carries ~50 injected values
SYNTH_PLAN = [("contract", "ru", "docx", ""), ("contract", "en", "docx", ""), ("invoice", "ru", "xlsx", ""), ("invoice", "en", "xlsx", ""), ("resume", "ru", "docx", ""),
              ("resume", "en", "pdf", ""), ("ruling", "ru", "pdf", ""), ("ruling", "en", "docx", ""), ("minutes", "ru", "pptx", ""), ("minutes", "en", "pptx", ""),
              ("mail", "ru", "txt", ""), ("mail", "en", "html", ""), ("contract", "ru", "pdf", ""), ("contract", "en", "pdf", ""), ("invoice", "ru", "pdf", ""),
              ("invoice", "ru", "pdf", "scanned"), ("contract", "ru", "pdf", "scanned"), ("resume", "en", "pdf", "scanned"), ("ruling", "ru", "pdf", "scanned"),
              ("invoice", "ru", "csv", ""), ("invoice", "en", "tsv", ""), ("contract", "ru", "md", ""), ("contract", "en", "md", ""), ("mail", "ru", "json", ""),
              ("minutes", "en", "xml", ""), ("minutes", "ru", "xml", ""), ("mail", "en", "log", ""), ("mail", "ru", "log", ""), ("contract", "en", "ini", ""),
              ("contract", "ru", "yaml", ""), ("mail", "en", "yml", ""), ("invoice", "ru", "png", "scan"), ("invoice", "en", "jpg", "scan"), ("resume", "ru", "jpg", "scan"),
              ("ruling", "en", "png", "scan"), ("minutes", "ru", "tiff", "scan"), ("mail", "en", "webp", "screenshot"), ("mail", "ru", "png", "screenshot"),
              ("contract", "ru", "xlsx", ""), ("resume", "en", "xlsx", ""), ("invoice", "ru", "docx", ""), ("invoice", "en", "pptx", ""), ("ruling", "ru", "html", ""),
              ("minutes", "ru", "csv", ""), ("resume", "ru", "txt", ""), ("ruling", "en", "txt", ""), ("contract", "ru", "json", ""), ("contract", "ru", "html", "")]
REAL = Path(os.environ.get("EVAL_REAL_DIR") or ROOT / "tests" / "eval" / "real")      # raw corpus (large, untracked); override to share one copy between worktrees
MANIFEST = ROOT / "tests" / "eval" / "real_manifest.json"
TRACKED_RESULTS = ROOT / "tests" / "eval" / "real_results.json"      # committed reference; only `publish` writes it, never `run`
RESULTS = Path(os.environ.get("EVAL_RESULTS") or ROOT / "tests" / "eval" / "real" / "_results.json")      # working copy (git-ignored dir); quality_gate points this at a temp file


def _load_results() -> list[dict]:
    """Working results if present, else the committed reference (so a subset run still merges into the full table)."""
    for p in (RESULTS, TRACKED_RESULTS):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return []
CASES = ROOT / "tests" / "eval" / "real" / "_cases"      # per checkout, so parallel worktrees never delete each other's inputs
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
PY = sys.executable

# ---------------------------------------------------------------- synthetic identities (independent ground truth)
SUR = ["Чернобаев", "Мирошкин", "Яхонтова", "Вересовский", "Кудашкина", "Зарубина", "Лопатинский", "Бирюкова", "Тимонин", "Шалимова"]
GIV = [("Пётр", "Сергеевич", "m"), ("Алла", "Игоревна", "f"), ("Матвей", "Олегович", "m"), ("Вера", "Павловна", "f")]
EN = [("Whitfield", "John", "A."), ("Okonkwo", "Grace", "T."), ("Lindqvist", "Marcus", "J."), ("Haverford", "Elena", "R.")]


def luhn(prefix: str) -> str:
    d = [int(c) for c in prefix]
    s = sum((x * 2 - 9 if x * 2 > 9 else x * 2) if i % 2 == 0 else x for i, x in enumerate(reversed(d + [0])))
    return prefix + str((10 - s % 10) % 10)


def inn12(r: random.Random) -> str:
    d = [r.randrange(10) for _ in range(10)]
    d.append(sum(a * b for a, b in zip(d, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8])) % 11 % 10)
    d.append(sum(a * b for a, b in zip(d, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])) % 11 % 10)
    return "".join(map(str, d))


def snils(r: random.Random) -> str:
    n = [r.randrange(10) for _ in range(9)]
    s = sum(a * b for a, b in zip(n, range(9, 0, -1)))
    c = s % 101 % 100 if s % 101 not in (100,) else 0
    return f"{n[0]}{n[1]}{n[2]}-{n[3]}{n[4]}{n[5]}-{n[6]}{n[7]}{n[8]} {c:02d}"


def identities(seed: str, lang: str) -> tuple[list[str], list[tuple[str, str]]]:
    """-> (lines of text to inject, gold [(category, value)])"""
    r = random.Random(seed)
    if lang == "ru":
        sur = r.choice(SUR); giv, pat, sex = r.choice(GIV)
        sur = sur if sex == "m" or not sur.endswith(("ий", "ин", "ев")) else sur
        fio = f"{sur} {giv} {pat}"
        gold = [("PERSON", fio), ("INN", inn12(r)), ("PHONE", f"+7 (9{r.randrange(10)}{r.randrange(10)}) {r.randrange(100, 999)}-{r.randrange(10, 99)}-{r.randrange(10, 99)}"),
                ("EMAIL", f"{giv.lower() if giv.isascii() else 'u' + str(r.randrange(100, 999))}.{r.randrange(1000, 9999)}@mail-demo.example.ru"),
                ("PASSPORT", f"{r.randrange(10, 99)} {r.randrange(10, 99)} {r.randrange(100000, 999999)}"), ("SNILS", snils(r)),
                ("CARD", " ".join(luhn("4276" + "".join(str(r.randrange(10)) for _ in range(11)))[i:i + 4] for i in range(0, 16, 4)))]
        lines = [f"Заявитель: {gold[0][1]}", f"Паспорт серия и номер {gold[4][1]}, СНИЛС {gold[5][1]}", f"ИНН {gold[1][1]}, тел. {gold[2][1]}",
                 f"E-mail: {gold[3][1]}", f"Банковская карта {gold[6][1]}"]
    else:
        sur, giv, mid = r.choice(EN)
        gold = [("PERSON", f"{giv} {mid} {sur}"), ("PHONE", f"+44 20 7{r.randrange(100, 999)} {r.randrange(1000, 9999)}"),
                ("EMAIL", f"{giv.lower()}.{sur.lower()}{r.randrange(10, 99)}@demo-mail.example.com"),
                ("CARD", " ".join(luhn("5500" + "".join(str(r.randrange(10)) for _ in range(11)))[i:i + 4] for i in range(0, 16, 4))),
                ("PASSPORT", f"{r.randrange(100, 999)}{r.randrange(100000, 999999)}")]
        lines = [f"Applicant: {gold[0][1]}", f"Phone: {gold[1][1]}  Email: {gold[2][1]}", f"Card {gold[3][1]}, passport no. {gold[4][1]}"]
    return lines, gold


# ---------------------------------------------------------------- injection
def render_banner(lines: list[str], width: int) -> "Image.Image":
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(FONT, 28)
    img = Image.new("RGB", (max(width, 900), 60 + 46 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((24, 24 + i * 46), line, font=f, fill=(15, 15, 15))
    return img


def inject(fmt: str, data: bytes, lines: list[str], traits: str) -> bytes:
    text = "\n".join(lines)
    if fmt in ("pdf",):
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        if "scanned" in traits:
            img = render_banner(lines, 900); buf = io.BytesIO(); img.save(buf, "PNG")
            page = doc.new_page(width=595, height=842)
            page.insert_image(fitz.Rect(30, 30, 565, 30 + 535 * img.height / img.width), stream=buf.getvalue())
        else:
            # Строки вставляются на отдельную страницу в конце: поверх родного текста они затирали бы его при замене и
            # при возврате, и сравнение «восстановлено == исходное» мерило бы артефакт вставки, а не продукт.
            first = doc[0].rect
            page = doc.new_page(width=first.width, height=first.height)
            font = fitz.Font(fontfile=FONT)
            size = 10.0
            while size > 4 and max(font.text_length(line, fontsize=size) for line in lines) > first.width - 60:
                size -= .5
            for i, line in enumerate(lines):
                page.insert_text((30, 40 + i * (size + 4)), line, fontname="arial", fontfile=FONT, fontsize=size)
        return doc.tobytes()
    if fmt in ("png", "jpg"):
        from PIL import Image
        base = Image.open(io.BytesIO(data)).convert("RGB")
        ban = render_banner(lines, base.width)
        out = Image.new("RGB", (max(base.width, ban.width), base.height + ban.height), "white")
        out.paste(base, (0, 0)); out.paste(ban, (0, base.height))
        buf = io.BytesIO(); out.save(buf, "PNG" if fmt == "png" else "JPEG", **({} if fmt == "png" else {"quality": 88}))
        return buf.getvalue()
    if fmt == "docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        doc.sections[0].header.paragraphs[0].text = lines[0]
        for line in lines[1:]:
            doc.add_paragraph(line)
        t = doc.add_table(rows=1, cols=1); t.cell(0, 0).text = lines[-1]
        buf = io.BytesIO(); doc.save(buf); return buf.getvalue()
    if fmt == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data)); ws = wb.active
        row = ws.max_row + 2
        for i, line in enumerate(lines):
            ws.cell(row + i, 1, line)
        wb.create_sheet("Contacts").append([text])
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
    if fmt == "pptx":
        from pptx import Presentation
        from pptx.util import Inches
        prs = Presentation(io.BytesIO(data))
        slide = prs.slides.add_slide(prs.slide_layouts[min(6, len(prs.slide_layouts) - 1)])
        for j, line in enumerate(lines):
            slide.shapes.add_textbox(Inches(.5), Inches(.5 + j * .6), Inches(9), Inches(.5)).text_frame.text = line
        buf = io.BytesIO(); prs.save(buf); return buf.getvalue()
    if fmt == "csv":
        return data + (b"\n" if not data.endswith(b"\n") else b"") + ";".join(f'"{x}"' for x in lines).encode()
    if fmt == "html":
        s = data.decode("utf-8", "replace")
        block = "".join(f"<p>{x}</p>" for x in lines)
        return (s.replace("</body>", block + "</body>", 1) if "</body>" in s else s + block).encode()
    if fmt == "json":
        d = json.loads(data); d = {"results": d, "contact_note": text}
        return json.dumps(d, ensure_ascii=False).encode()
    raise ValueError(fmt)


# ---------------------------------------------------------------- adversarial synthetic cases
def adv_cases() -> list[dict]:
    from docx import Document
    from openpyxl import Workbook
    out = []
    def docx_of(lines):
        d = Document()
        for line in lines:
            d.add_paragraph(line)
        b = io.BytesIO(); d.save(b); return b.getvalue()
    def case(id, name, data, gold, expect="anonymize", note=""):
        out.append(dict(id=id, name=name, data=data, gold=gold, expect=expect, note=note, adv=True))
    lines, gold = identities("adv", "ru")
    zw = lambda s, ch="​": ch.join(s)            # noqa: E731
    sur = gold[0][1].split()[0]
    zl = [f"Заявитель: {sur[:3]}​{sur[3:]} {gold[0][1].split()[1]} {gold[0][1].split()[2]}",
          f"ИНН {gold[1][1][:4]}​{gold[1][1][4:8]}‌{gold[1][1][8:]}", f"E-mail: {gold[3][1].replace('@', chr(0x200b) + '@')}",
          f"Тел. {gold[2][1]}"]
    case("adv_zerowidth_txt", "zw.txt", "\n".join(zl).encode(), [g for g in gold if g[0] in ("PERSON", "INN", "EMAIL", "PHONE")])
    case("adv_zerowidth_docx", "zw.docx", docx_of(zl), [g for g in gold if g[0] in ("PERSON", "INN", "EMAIL", "PHONE")])
    lat = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x"})
    hl = [f"Заявитель: {gold[0][1].translate(lat)}", f"E-mail: {gold[3][1].replace('a', 'а').replace('e', 'е')}", f"ИНН {gold[1][1]}"]
    case("adv_homoglyph_txt", "hg.txt", "\n".join(hl).encode(), [g for g in gold if g[0] in ("PERSON", "INN", "EMAIL")])
    case("adv_homoglyph_docx", "hg.docx", docx_of(hl), [g for g in gold if g[0] in ("PERSON", "INN", "EMAIL")])
    enc = "\n".join(lines)
    case("adv_cp1251_txt", "cp.txt", enc.encode("cp1251"), gold)
    case("adv_utf16_txt", "u16.txt", enc.encode("utf-16"), gold)
    # nested containers
    inner = docx_of(lines)
    z = io.BytesIO(docx_of(["Hello"]))
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr("word/embeddings/oleObject1.docx", inner)
    case("adv_nested_docx", "nest.docx", z.getvalue(), gold, note="PII only inside an embedded docx part")
    deep = enc.encode()
    for depth in range(4):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"inner{depth}.zip" if depth else "note.txt", deep)
        deep = b.getvalue()
    wb = Workbook(); wb.active["A1"] = "x"; xb = io.BytesIO(); wb.save(xb)
    xz = io.BytesIO(xb.getvalue())
    with zipfile.ZipFile(xz, "a") as zf:
        zf.writestr("xl/embeddings/deep.zip", deep)
    case("adv_nested_zip4_xlsx", "nest4.xlsx", xz.getvalue(), gold, note="PII four zip levels deep inside an xlsx part")
    bomb = io.BytesIO(docx_of(["bomb"]))
    with zipfile.ZipFile(bomb, "a", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("word/media/bomb.bin", "w", force_zip64=True) as h:
            chunk = bytes(1 << 20)
            for _ in range(1200):
                h.write(chunk)
    case("adv_zipbomb_docx", "bomb.docx", bomb.getvalue(), [], "reject", "1.2 GB inflated")
    # huge cells / sizes
    wb = Workbook(); ws = wb.active
    ws["A1"] = ("lorem ipsum " * 1500)[:15000] + " " + gold[3][1] + " " + ("dolor sit " * 1500)[:15000] + " Заявитель " + gold[0][1]
    for i in range(2, 20002):
        ws.cell(i, 1, f"row {i} note"); ws.cell(i, 2, i * 3)
    ws["C20003"] = gold[1][1]
    xb = io.BytesIO(); wb.save(xb)
    case("adv_hugecell_xlsx", "huge.xlsx", xb.getvalue(), [gold[0], gold[1], gold[3]], note="30k-char cell + 20k rows")
    big = ("Lorem ipsum dolor sit amet, consectetur. " * 25 + "\n") * 12000
    parts = big.split("\n")
    for k in range(10):
        parts[k * 1000 + 7] += f" Contact {gold[0][1]} {gold[2][1]}"
    case("adv_huge_txt", "big.txt", "\n".join(parts).encode(), [gold[0], gold[2]], note="~12 MB text, 10 occurrences")
    # malformed
    good = docx_of(lines)
    case("adv_trunc_docx", "trunc.docx", good[: len(good) // 2], [], "reject")
    case("adv_empty_pdf", "empty.pdf", b"", [], "reject")
    case("adv_garbage_pdf", "garbage.pdf", b"%PDF-1.4\n" + os.urandom(3000), [], "reject")
    import fitz
    d = fitz.open(); d.new_page().insert_text((50, 80), "Passport 45 12 345678", fontsize=12); pdfb = d.tobytes()
    case("adv_trunc_pdf", "trunc.pdf", pdfb[: len(pdfb) * 2 // 3], [], "reject")
    zi = zipfile.ZipFile(io.BytesIO(good)); bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, b"<<<not xml" if n == "word/document.xml" else zi.read(n))
    case("adv_badxml_docx", "badxml.docx", bio.getvalue(), gold, "reject", "document.xml replaced by garbage")
    case("adv_text_as_docx", "fake.docx", enc.encode(), gold, "reject", "plain text with .docx extension")
    case("adv_random_png", "rnd.png", os.urandom(5000), [], "reject")
    case("adv_binary_as_txt", "bin.txt", os.urandom(20000), [], "any")
    return out


# ---------------------------------------------------------------- independent extraction + matching
HOMO = str.maketrans("aeopcxy", "аеорсху")


def canon(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().translate(HOMO)
    return re.sub(r"[^0-9a-zа-яё@]", "", s)


def needles(cat: str, value: str, base_view: str = "") -> list[str]:
    if cat == "PERSON":                      # the surname stem: first token in Russian order (declension-proof), last in Latin order
        if value.isascii():
            n = canon(value.split()[-1])
        else:
            c = canon(value.split()[0])
            n = c[:max(5, len(c) - 2)]
        # a surname-only needle is ambiguous when the unmodified document already contains it outside the injected
        # identity (real "Lindqvist", town "Haverfordwest"): then only the full injected name counts as a leak
        full = canon(value)
        if n and base_view and n in base_view.replace(full, ""):
            return [full]
        return [n]
    return [canon(value)]


def is_leaked(cat: str, value: str, view: str, base_view: str = "", orig_view: str = "") -> bool:
    """True when the injected value is still visible in the output view (all views are canon() strings).

    PERSON: see needles(). Other kinds: a needle that also occurs naturally in the ORIGINAL document before injection
    ("Рубеж" in "зарубежные", "Вознесенская" in "Вознесенская церковь") only counts as a leak when the output holds MORE
    occurrences than the original has (injected occurrences are extra). Without an original the old rule applies."""
    ns = [n for n in needles(cat, value, base_view) if n]
    if cat == "PERSON" or not orig_view:
        return any(n in view for n in ns)
    return any(view.count(n) > orig_view.count(n) for n in ns)


def original_view(spec: dict, fmt: str) -> str:
    """canon() text of the untouched source document of a real-corpus case, "" when it cannot be found."""
    if spec.get("source") != "real":
        return ""
    d = REAL / spec["id"]
    try:
        files = [f for f in d.iterdir() if f.is_file()]
        return canon(plain_text(fmt, files[0].read_bytes())) if len(files) == 1 else ""
    except Exception:                                                  # noqa: BLE001
        return ""


def zip_parts(data: bytes, depth: int = 0) -> list[bytes]:
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.file_size > 60 << 20:
                    continue
                b = z.read(info)
                out.append(b)
                if depth < 6 and b[:2] == b"PK":
                    out += zip_parts(b, depth + 1)
    except Exception:                                                  # noqa: BLE001
        pass
    return out


def tess(png: bytes) -> str:
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "p.png"; p.write_bytes(png)
        r = subprocess.run(["tesseract", str(p), "-", "-l", "rus+eng", "--psm", "6"], capture_output=True, timeout=240)
        return r.stdout.decode("utf-8", "ignore")


def output_views(fmt: str, data: bytes) -> str:
    parts = [data.decode("utf-8", "ignore"), data.decode("utf-16le", "ignore"), data.decode("cp1251", "ignore")]
    for b in zip_parts(data):
        parts += [b.decode("utf-8", "ignore"), b.decode("utf-16le", "ignore")]
    try:
        if fmt == "docx":
            from docx import Document
            doc = Document(io.BytesIO(data))
            parts += [p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells]
        elif fmt == "xlsx":
            from openpyxl import load_workbook
            parts += [str(c.value) for ws in load_workbook(io.BytesIO(data)).worksheets for row in ws.iter_rows() for c in row if c.value is not None]
        elif fmt == "pptx":
            from pptx import Presentation
            parts += [sh.text_frame.text for s in Presentation(io.BytesIO(data)).slides for sh in s.shapes if sh.has_text_frame]
        elif fmt == "pdf":
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            parts += [p.get_text("text") for p in doc] + [str(doc.metadata)]
            with tempfile.TemporaryDirectory() as t:
                p = Path(t) / "o.pdf"; p.write_bytes(data)
                parts.append(subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "ignore"))
            for i in sorted({0, 1, 2, len(doc) - 1}):
                if 0 <= i < len(doc):
                    parts.append(tess(doc[i].get_pixmap(dpi=200).tobytes("png")))
        elif fmt in IMG_FMTS:
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            for sc in (1, 2):
                b = io.BytesIO(); img.resize((img.width * sc, img.height * sc)).save(b, "PNG"); parts.append(tess(b.getvalue()))
    except Exception as ex:                                            # noqa: BLE001
        parts.append(f"<<view error {type(ex).__name__}>>")
    return "\n".join(parts)


TOKEN_LEFT = re.compile(r"\b(?:Name|Phone|Email|Company|Address|Card|Passport|Inn|Snils|Birthdate|Ip|Account|Kpp|Ogrn|Bik|Plate|Secret|Ssn|Iban|Person|Org|Date|Number)\d+(?:_\d+)?\b")


def plain_text(fmt: str, data: bytes) -> str:
    """cheap text view (no OCR) used to find placeholder tokens that survived a restore"""
    try:
        if fmt == "pdf":
            import fitz
            return "\n".join(p.get_text() for p in fitz.open(stream=data, filetype="pdf"))
        if data[:2] == b"PK":
            return "\n".join(b.decode("utf-8", "ignore") for b in zip_parts(data))
    except Exception:                                                  # noqa: BLE001
        return ""
    return data.decode("utf-8", "ignore")


def opens(fmt: str, data: bytes, ref_pages: int | None, ref_dims) -> str | bool:
    try:
        if fmt == "docx":
            from docx import Document; Document(io.BytesIO(data))
        elif fmt == "xlsx":
            from openpyxl import load_workbook; load_workbook(io.BytesIO(data))
        elif fmt == "pptx":
            from pptx import Presentation; Presentation(io.BytesIO(data))
        elif fmt == "pdf":
            import fitz
            doc = fitz.open(stream=data, filetype="pdf"); [p.get_text() for p in doc]
            if ref_pages is not None and len(doc) != ref_pages:
                return f"page count {ref_pages}->{len(doc)}"
        elif fmt in IMG_FMTS:
            from PIL import Image
            im = Image.open(io.BytesIO(data)); im.load()
            if ref_dims and im.size != tuple(ref_dims):
                return f"dims {ref_dims}->{im.size}"
        elif fmt == "json":
            json.loads(data)
        elif fmt == "xml":
            import xml.etree.ElementTree as ET
            ET.fromstring(data)
        return True
    except Exception as ex:                                            # noqa: BLE001
        return f"{type(ex).__name__}: {str(ex)[:80]}"


def _mask(text: str, secrets: list[str], restored: bool) -> str:
    """Passwords/keys are removed irreversibly BY DESIGN (retain_secrets_for_restore is off by default) and the product may also drop their label
    ("password: X" -> "Secret1"). Mask the value (and an immediately preceding label) on both sides so only the intended loss is ignored; anything the
    secret rule swallows beyond that (closing tags, the next sentence) still shows up as a restore difference."""
    if restored:
        text = re.sub(r"(?i)(?:[\w\-]*(?:password|passwd|pwd|token|api[ _-]?key|secret)[\w\-\"']*\s*[:=]\s*)?\"?Secret\d+", "<S>", text)
        # retain_secrets_for_restore: the real secret comes back, so it is masked like in the original
    for sec in sorted({x for x in secrets if x}, key=len, reverse=True):
        text = re.sub(r"(?i)(?:[\w\-]*(?:password|passwd|pwd|token|api[ _-]?key|secret)[\w\-\"']*\s*[:=]\s*)?\"?" + re.escape(sec), "<S>", text)
    if restored:
        return text
    for sec in sorted({x for x in secrets if x}, key=len, reverse=True):
        text = re.sub(r"(?i)(?:[\w\-]*(?:password|passwd|pwd|token|api[ _-]?key|secret)[\w\-\"']*\s*[:=]\s*)?\"?" + re.escape(sec), "<S>", text)
    return text


def natural_secrets(a_text: str, b_text: str) -> list[str]:
    """Secrets the product itself found in the source (not injected gold) are removed irreversibly by design and come back as `SecretN`.
    Recover the original value by aligning the text around each leftover marker, so _mask can ignore exactly that value."""
    found = []
    for m in re.finditer(r"(.{0,12})\bSecret\d+\b(.{0,12})", b_text):
        pre, post = m.group(1), m.group(2)
        hit = re.search(re.escape(pre) + r"(.{1,200}?)" + re.escape(post), a_text) if (pre or post) else None
        val = hit.group(1) if hit else ""
        if len(val) >= 4 and "Secret" not in val and not re.search(r"\s", val):
            found.append(val)
    return sorted(set(found))


def restore_equal(fmt: str, a: bytes, b: bytes, secrets: list[str] | None = None) -> tuple[bool, bool]:
    """-> (byte_equal, content_equal); content_equal ignores lines carrying irreversibly removed secrets (see _mask)"""
    if a == b:
        return True, True
    secrets = list(secrets or [])
    if fmt in TEXT_FMTS:
        secrets += natural_secrets(a.decode("utf-8", "ignore"), b.decode("utf-8", "ignore"))
    try:
        if fmt in ("docx", "xlsx", "pptx"):
            from tests.helpers import content_units
            with tempfile.TemporaryDirectory() as t:
                pa, pb = Path(t) / f"a.{fmt}", Path(t) / f"b.{fmt}"; pa.write_bytes(a); pb.write_bytes(b)
                ua, ub = content_units(pa), content_units(pb)
                if ua == ub:
                    return False, True
                if secrets and isinstance(ua, dict) and isinstance(ub, dict):
                    ma = {k: _mask(str(v), secrets, False) for k, v in ua.items()}
                    mb = {k: _mask(str(v), secrets, True) for k, v in ub.items()}
                    if ma == mb:
                        return False, True
                    ma = {k: v for k, v in ma.items() if "<S>" not in v}
                    mb = {k: v for k, v in mb.items() if "<S>" not in v}
                    return False, ma == mb
                return False, False
        if fmt == "pdf":
            import fitz
            # Содержимое PDF = мультимножество букв и цифр текстового слоя (регистр и порядок не важны): дорисованный при
            # возврате текст может иметь другие интервалы, но ни одна буква не должна потеряться или появиться лишней.
            # Секреты стираются необратимо по замыслу: они маскируются в обеих сторонах.
            flags = fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE

            def words(x, restored):
                txt = "\n".join(p.get_text(flags=flags) for p in fitz.open(stream=x, filetype="pdf"))
                txt = _mask(txt, secrets, restored).replace("<S>", " ")
                if secrets:                       # restored text is extracted away from its label: drop the labels on both sides
                    txt = re.sub(r"(?i)\b(?:password|passwd|pwd|api[ _-]?key|token)\b", " ", txt)
                txt = re.sub("[\xad\u200b-\u200f\u2060\ufeff]", "", txt).lower()
                return sorted(re.sub(r"[\W_]+", "", txt))
            return False, words(a, False) == words(b, True)
        if fmt in TEXT_FMTS:
            strip = lambda x, r: re.sub(r"[\U000e0000-\U000e007f\s]+", "", _mask(x.decode("utf-8", "ignore"), secrets, r))   # noqa: E731
            return False, strip(a, False) == strip(b, True)
    except Exception:                                                  # noqa: BLE001
        pass
    return False, False


# ---------------------------------------------------------------- worker (one case, one process)
def worker(case_dir: Path) -> dict:
    spec = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    data = (case_dir / spec["file"]).read_bytes()
    fmt = spec["fmt"]
    gold = [tuple(g) for g in spec["gold"]]
    from tests.helpers import Env
    ref_pages = ref_dims = None
    try:
        if fmt == "pdf":
            import fitz; ref_pages = len(fitz.open(stream=data, filetype="pdf"))
        if fmt in IMG_FMTS:
            from PIL import Image; ref_dims = Image.open(io.BytesIO(data)).size
    except Exception:                                                  # noqa: BLE001
        pass
    res = {"id": spec["id"], "fmt": fmt, "lang": spec["lang"], "size": len(data), "gold": len(gold), "expect": spec.get("expect", "anonymize")}
    env = Env(**({"retain_secrets_for_restore": True} if fmt == "pdf" else {}), **json.loads(os.environ.get("EVAL_PREFS") or "{}"))      # EVAL_PREFS='{"image_mode": "redact_text"}' runs the opt-in modes
    t0 = time.time()
    try:
        # Пароли и ключи по умолчанию не сохраняются и не возвращаются (так задумано); чтобы проверить саму механику возврата PDF
        # без этого исключения, в PDF-прогоне они сохраняются.
        job = env.anonymize((spec["file"], data))
    except Exception as ex:                                            # noqa: BLE001
        res.update(crash=f"{type(ex).__name__}: {str(ex)[:160]}", t_anon=round(time.time() - t0, 2))
        return res
    res["t_anon"] = round(time.time() - t0, 2)
    f = job.files[0]
    res.update(status=f.status, blocked=not f.out_path, msgs=[m["text"][:120] for m in f.messages][:3], replaced_total=f.total)
    replaced = [r if isinstance(r, str) else str(getattr(r, "original", r[0] if isinstance(r, (tuple, list)) and r else r)) for r in (job.replaced or [])]
    if f.out_path:
        out = Path(f.out_path).read_bytes()
        res["out_size"] = len(out)
        view = canon(output_views(fmt, out))
        by_cat: dict[str, list] = {}
        try:
            base_view = canon(plain_text(fmt, data))
        except Exception:                                              # noqa: BLE001
            base_view = ""
        orig_view = original_view(spec, fmt)
        for cat, val in gold:
            leaked = is_leaked(cat, val, view, base_view, orig_view)
            by_cat.setdefault(cat, []).append(leaked)
        res["cats"] = {c: [len(v), sum(v)] for c, v in by_cat.items()}
        gold_c = [canon(v) for _, v in gold]
        tp = fp = 0; fps = []
        for r in set(replaced):
            rc = canon(r)
            if not rc:
                continue
            if any(rc in g or (len(g) >= 4 and g in rc) or any(part and part in rc for part in [canon(w) for w in str(r).split()] if len(part) >= 5 and part in gc) for gc in gold_c for g in [gc]):
                tp += 1
            else:
                fp += 1; fps.append(str(r)[:40])
        res.update(tp=tp, fp=fp, fp_samples=fps[:8])
        # second metric: natural entities (not injected) that were replaced -> precision sampling list for human/agent triage
        nat, nat_counts = [], {}
        try:
            for label, items in (job.result.get("groups") or {}).items():
                for it in items:
                    oc = canon(str(it["original"]))
                    if not oc or any(oc in gc or (len(gc) >= 4 and gc in oc) or any(len(part) >= 5 and part in gc for part in [canon(w) for w in str(it["original"]).split()]) for gc in gold_c):
                        continue
                    nat_counts[label] = nat_counts.get(label, 0) + 1
                    nat.append([label, it.get("kind", ""), str(it["original"])[:70], it.get("count", 1), it.get("reason", "")[:50]])
        except Exception:                                                  # noqa: BLE001
            pass
        nat.sort(key=lambda x: -x[3])
        res.update(natural_counts=nat_counts, natural=nat[:80], natural_total=sum(nat_counts.values()))
        res["opens"] = opens(fmt, out, ref_pages, ref_dims)
        t1 = time.time()
        try:
            rj = env.restore(env.as_upload(job))
            rf = rj.files[0]
            res["t_restore"] = round(time.time() - t1, 2)
            if rf.out_path:
                rb = Path(rf.out_path).read_bytes()
                if fmt not in IMG_FMTS:
                    left = TOKEN_LEFT.findall(plain_text(fmt, rb)); base = set(TOKEN_LEFT.findall(plain_text(fmt, data)))
                    left = [t for t in left if t not in base and not t.startswith("Secret")]
                    res["restore_tokens_left"] = len(left); res["restore_tokens_sample"] = sorted(set(left))[:6]
                res["restore_byte_equal"], res["restore_content_equal"] = restore_equal(fmt, data, Path(rf.out_path).read_bytes(), [v for c, v in gold if c == "SECRET"])
            else:
                res["restore_byte_equal"] = res["restore_content_equal"] = False; res["restore_msg"] = [m["text"][:100] for m in rf.messages][:2]
                res["restore_na"] = True                  # restore refused (fail-closed): not counted as a mismatch
        except Exception as ex:                                        # noqa: BLE001
            res["restore_error"] = f"{type(ex).__name__}: {str(ex)[:100]}"
    res["peak_mb"] = round(peak_memory_mb(), 0)
    env.close()
    return res


# ---------------------------------------------------------------- driver
def _reset_cases() -> None:
    """Fresh per-checkout CASES dir. In a git worktree tests/eval/real/ holds per-entry symlinks to the shared corpus; if
    `_cases` itself is such a symlink (older setup), unlink it instead of rmtree-ing through it (that would wipe or reuse the
    main checkout's inputs)."""
    if CASES.is_symlink():
        CASES.unlink()
    shutil.rmtree(CASES, ignore_errors=True)
    CASES.mkdir(parents=True)


def prepare() -> list[Path]:
    _reset_cases()
    dirs = []
    def put(spec: dict, data: bytes):
        d = CASES / spec["id"]; d.mkdir()
        (d / spec["file"]).write_bytes(data)
        (d / "case.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        dirs.append(d)
    for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]:
        if not (REAL / e["path"]).exists():
            continue
        raw = (REAL / e["path"]).read_bytes()
        lang = "ru" if e["lang"] == "ru" else "en"
        pack = dense(e["id"], lang)
        gold = pack.gold
        fmt = e["fmt"]
        if fmt == "jpeg":
            fmt = "jpg"
        try:
            data = dinject(fmt, raw, pack, e["traits"])
            note = f"dense injection ({len(gold)} values)"
        except Exception as ex:                                        # noqa: BLE001
            data, gold, note = raw, [], f"injection failed ({type(ex).__name__}: {str(ex)[:60]}); measured without gold"
        put(dict(id=e["id"], file=f"input.{fmt}", fmt=fmt, lang=e["lang"], traits=e["traits"], gold=gold, note=note, source="real", licence=e.get("licence", "")), data)
        # derived: image-only PDF of every scan image (no text layer at all)
        if fmt in IMG_FMTS and gold:
            import fitz
            doc = fitz.open(); im = fitz.Pixmap(data)
            page = doc.new_page(width=min(im.width, 1200), height=min(im.width, 1200) * im.height / im.width)
            page.insert_image(page.rect, stream=data)
            put(dict(id=e["id"] + "_aspdf", file="input.pdf", fmt="pdf", lang=e["lang"], traits="scanned,derived", gold=gold, note="image-only PDF"), doc.tobytes())
    # derived Russian Office/CSV files from real Russian public-domain legal text
    ru_pdf = REAL / "_disabled_thin_derived"      # thin derived docs replaced by the dense synthetic set (SYNTH_PLAN)
    try:
        import fitz
        src = next(ru_pdf.glob("*.pdf"))
        paras = [p.strip() for p in "\n".join(pg.get_text() for pg in fitz.open(src)).split("\n\n") if len(p.strip()) > 40][:60]
        from docx import Document
        from openpyxl import Workbook
        from pptx import Presentation
        from pptx.util import Inches
        d = Document(); [d.add_paragraph(p) for p in paras]; b = io.BytesIO(); d.save(b)
        wb = Workbook(); ws = wb.active; [ws.append([i, p[:200]]) for i, p in enumerate(paras)]; xb = io.BytesIO(); wb.save(xb)
        prs = Presentation()
        for k in range(0, 12, 3):
            s = prs.slides.add_slide(prs.slide_layouts[5])
            for j, p in enumerate(paras[k:k + 3]):
                s.shapes.add_textbox(Inches(.5), Inches(1.5 + j * 1.5), Inches(9), Inches(1.4)).text_frame.text = p[:300]
        pb = io.BytesIO(); prs.save(pb)
        csv = "\n".join(f'{i};"{p[:150].replace(chr(34), "")}"' for i, p in enumerate(paras)).encode()
        for name, fmt, raw in [("ru_derived_docx", "docx", b.getvalue()), ("ru_derived_xlsx", "xlsx", xb.getvalue()),
                               ("ru_derived_pptx", "pptx", pb.getvalue()), ("ru_derived_csv", "csv", csv)]:
            lines, gold = identities(name, "ru")
            put(dict(id=name, file=f"input.{fmt}", fmt=fmt, lang="ru", traits="derived from real ru legal text", gold=gold, note="injected"), inject(fmt, raw, lines, ""))
    except StopIteration:
        pass
    for kind, lang, sfmt, extra in SYNTH_PLAN:                           # synthetic long messy documents with dense gold
        sid = f"syn_{kind}_{lang}_{sfmt}{'_' + extra.replace(',', '_') if extra else ''}"
        pack = dense(sid, lang)
        try:
            base_fmt = "pdf_scan" if (sfmt == "pdf" and "scanned" in extra) else sfmt
            raw = synth(kind, base_fmt, pack, sid)
            data = dinject(sfmt, raw, pack, extra)
            put(dict(id=sid, file=f"input.{sfmt}", fmt=sfmt, lang=lang, traits=("synthetic," + kind + ("," + extra if extra else "")), gold=pack.gold,
                     note=f"synthetic {kind}, dense ({len(pack.gold)} values)", source="synthetic", licence="generated"), data)
        except Exception as ex:                                        # noqa: BLE001
            print("synth failed", sid, type(ex).__name__, str(ex)[:100], flush=True)
    for a in adv_cases():
        ext = Path(a["name"]).suffix.lstrip(".")
        put(dict(id=a["id"], file=a["name"], fmt=ext, lang="ru", traits="adversarial", gold=a["gold"], expect=a["expect"], note=a["note"]), a["data"])
    return dirs


def run(only: str | None, limit: int | None, fmts: str | None = None, lang: str | None = None, jobs: int = 4, source: str | None = None) -> None:
    dirs = prepare()
    specs = {d: json.loads((d / "case.json").read_text(encoding="utf-8")) for d in dirs}
    if only:
        keys = only.split(",")
        dirs = [d for d in dirs if any(k in d.name for k in keys)]
    if fmts:
        dirs = [d for d in dirs if specs[d]["fmt"] in fmts.split(",")]
    if lang:
        dirs = [d for d in dirs if specs[d]["lang"] == lang]
    if source:                                           # real | synthetic | adversarial
        dirs = [d for d in dirs if specs[d].get("source", "adversarial" if "adversarial" in specs[d]["traits"] else "real") == source]
    if limit:
        dirs = dirs[:limit]
    # largest inputs first so the long tail does not run alone at the end
    dirs.sort(key=lambda d: -next(p for p in d.iterdir() if p.name not in ("case.json", "result.json")).stat().st_size)
    from concurrent.futures import ThreadPoolExecutor
    results: list[dict] = []
    ENV = {**os.environ, "PYTHONPATH": str(ROOT), "OMP_THREAD_LIMIT": "1"}

    def one(d: Path) -> dict:
        out = d / "result.json"
        t0 = time.time()
        try:
            p = subprocess.run([PY, "-I", __file__, "worker", str(d)], capture_output=True, timeout=900, cwd=ROOT, env=ENV)
            line = [x for x in p.stdout.decode("utf-8", "ignore").splitlines() if x.startswith("RESULT ")]
            if line:
                res = json.loads(line[-1][7:])
            else:
                res = {"id": d.name, "crash": f"worker died rc={p.returncode}: {p.stderr.decode('utf-8', 'ignore')[-200:]}"}
        except subprocess.TimeoutExpired:
            res = {"id": d.name, "crash": "timeout 900s"}
        spec = json.loads((d / "case.json").read_text(encoding="utf-8"))
        res.setdefault("fmt", spec["fmt"]); res.setdefault("lang", spec["lang"]); res["traits"] = spec["traits"]; res["note"] = spec["note"]
        res["wall"] = round(time.time() - t0, 1)
        res["source"] = spec.get("source", "adversarial" if "adversarial" in spec["traits"] else "real"); res["licence"] = spec.get("licence", "")
        out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        leaks = sum(v[1] for v in res.get("cats", {}).values())
        print(f"{res['id']:<34}{res['fmt']:<6} gold={res.get('gold', 0):<3} leaked={leaks:<3} opens={res.get('opens')} restore={res.get('restore_content_equal')} "
              f"{res.get('t_anon', '-')}s {res.get('crash', '')}", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(one, dirs))
    old = _load_results()
    new_ids = {r["id"] for r in results}
    merged = [r for r in old if r["id"] not in new_ids] + results      # subset runs update their rows and keep the rest
    RESULTS.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")


OWNER = {"pdf": "A (PDF/OCR)", "png": "A (PDF/OCR)", "jpg": "A (PDF/OCR)", "tiff": "A (PDF/OCR)", "webp": "A (PDF/OCR)", "bmp": "A (PDF/OCR)", "docx": "B (OOXML)", "xlsx": "B (OOXML)", "pptx": "B (OOXML)",
         "txt": "C (detect/restore/text)", "csv": "C (detect/restore/text)", "html": "C (detect/restore/text)", "json": "C (detect/restore/text)"}


def failures(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        why = []
        owner = OWNER.get(r["fmt"], "C (detect/restore/text)")
        adv = "adversarial" in r.get("traits", "")
        if adv and any(k in r["id"] for k in ("zip", "bomb", "trunc", "badxml", "empty", "garbage", "fake", "random")):
            owner = "D (security)"
        if r.get("crash"):
            why.append(("crash/hang", "no crash, clean error", r["crash"]))
        leaks = {c: v for c, v in r.get("cats", {}).items() if v[1]}
        if leaks:
            warned = " (file carries a warning: status=attention)" if r.get("status") == "attention" else " (status=%s, no warning)" % r.get("status")
            why.append(("leak", "all injected values absent from output", ", ".join(f"{c}: {v[1]}/{v[0]}" for c, v in leaks.items()) + warned))
        if r.get("expect") == "reject" and r.get("status") and not r.get("blocked") and r.get("status") == "ok" and r.get("gold"):
            why.append(("silent pass", "refuse or report error", f"status=ok, output written"))
        if r.get("expect") == "reject" and r.get("status") == "ok" and not r.get("gold") and not r.get("blocked"):
            why.append(("malformed accepted", "error/blocked", "status=ok"))
        if r.get("expect", "anonymize") == "anonymize" and r.get("blocked") and not r.get("crash"):
            why.append(("blocked", "output file produced", "; ".join(r.get("msgs", []))[:160]))
        if r.get("opens") not in (None, True):
            why.append(("integrity", "output opens, same pages/dims", str(r["opens"])))
        if "restore_content_equal" in r and not r["restore_content_equal"] and r.get("gold") and not r.get("restore_na"):
            why.append(("restore", "restored == original", f"byte_equal={r.get('restore_byte_equal')} content_equal=False {r.get('restore_msg', '')}"))
        if r.get("restore_tokens_left"):
            why.append(("restore", "no placeholder tokens left after restore", f"{r['restore_tokens_left']} tokens survive, e.g. {r.get('restore_tokens_sample')}"))
        if "restore_error" in r:
            why.append(("restore", "restore works", r["restore_error"]))
        if r.get("fp", 0) > 20:
            why.append(("over-redaction", "few replacements outside injected values", f"{r['fp']} non-injected replacements, e.g. {r.get('fp_samples', [])[:4]}"))
        for kind, exp, act in why:
            out.append(dict(id=r["id"], fmt=r["fmt"], kind=kind, expected=exp, actual=act, owner=owner))
    return out


def report() -> None:
    rows = _load_results()
    real = [r for r in rows if "adversarial" not in r.get("traits", "")]
    adv = [r for r in rows if "adversarial" in r.get("traits", "")]
    L = ["# Quality matrix: real documents + adversarial cases", "",
         f"Generated by `tools/eval_real.py report` from `tests/eval/real_results.json` ({len(rows)} cases: {len(real)} real-document copies with injected "
         f"synthetic identities, {len(adv)} adversarial synthetic). Corpus: `tests/eval/real_manifest.json` (fetch with `tools/fetch_real_corpus.py`).", "",
         "Method and caveats are at the bottom. Leakage = injected value still readable in the output by an independent reader.", "",
         "## Per format (real documents)", "",
         "| format | cases | gold values | leaked | recall | replaced TP / FP-unverified | opens | restore content-equal | restore byte-equal | blocked/crash | median s | max s | max peak MB |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def stats(group: list[dict]):
        g = sum(r.get("gold", 0) for r in group if "cats" in r); lk = sum(v[1] for r in group for v in r.get("cats", {}).values())
        tp = sum(r.get("tp", 0) for r in group); fp = sum(r.get("fp", 0) for r in group)
        done = [r for r in group if "cats" in r]
        ts = sorted(r.get("t_anon", 0) for r in group if "t_anon" in r) or [0]
        return g, lk, tp, fp, done, ts
    for fmt in sorted({r["fmt"] for r in real}):
        grp = [r for r in real if r["fmt"] == fmt]
        g, lk, tp, fp, done, ts = stats(grp)
        pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "n/a"          # noqa: E731
        L.append(f"| {fmt} | {len(grp)} | {g} | {lk} | {pct(g - lk, g)} | {tp} / {fp} | {pct(sum(1 for r in done if r.get('opens') is True), len(done))} | "
                 f"{pct(sum(1 for r in done if r.get('restore_content_equal')), sum(1 for r in done if not r.get('restore_na')))} | {pct(sum(1 for r in done if r.get('restore_byte_equal')), sum(1 for r in done if not r.get('restore_na')))} | "
                 f"{sum(1 for r in grp if r.get('blocked'))}/{sum(1 for r in grp if r.get('crash'))} | {ts[len(ts) // 2]} | {ts[-1]} | {max((r.get('peak_mb', 0) for r in grp), default=0):.0f} |")
    L += ["", "## Per entity category (real documents, all formats)", "", "| category | injected | leaked | recall |", "|---|---|---|---|"]
    cat: dict[str, list[int]] = {}
    for r in real:
        for c, (n, k) in r.get("cats", {}).items():
            cat.setdefault(c, [0, 0]); cat[c][0] += n; cat[c][1] += k
    for c, (n, k) in sorted(cat.items()):
        L.append(f"| {c} | {n} | {k} | {100 * (n - k) / n:.0f}% |")
    L += ["", "## Category x format leaked / injected", ""]
    fmts = sorted({r["fmt"] for r in real})
    L += ["| category | " + " | ".join(fmts) + " |", "|---|" + "---|" * len(fmts)]
    for c in sorted(cat):
        cells = []
        for fmt in fmts:
            n = sum(r.get("cats", {}).get(c, [0, 0])[0] for r in real if r["fmt"] == fmt); k = sum(r.get("cats", {}).get(c, [0, 0])[1] for r in real if r["fmt"] == fmt)
            cells.append(f"{k}/{n}" if n else "-")
        L.append(f"| {c} | " + " | ".join(cells) + " |")
    L += ["", "## Per language (real documents)", "", "| lang | cases | gold | leaked | recall |", "|---|---|---|---|---|"]
    for lang in sorted({r["lang"] for r in real}):
        grp = [r for r in real if r["lang"] == lang]; g, lk, *_ = stats(grp)
        L.append(f"| {lang} | {len(grp)} | {g} | {lk} | {100 * (g - lk) / g:.0f}% |" if g else f"| {lang} | {len(grp)} | 0 | 0 | n/a |")
    # ---- corpus composition, per-source split, restore, timings, 10/10 summary
    def cnt(key):
        c: dict = {}
        for r in real:
            c[key(r)] = c.get(key(r), 0) + 1
        return c
    L += ["", "## Corpus composition (non-adversarial cases)", "", "| by source | cases |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(cnt(lambda r: r.get('source', 'real')).items())]
    L += ["", "| by licence | cases |", "|---|---|"] + [f"| {k or 'n/a'} | {v} |" for k, v in sorted(cnt(lambda r: r.get('licence', '')).items())]
    L += ["", "| by language | cases |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(cnt(lambda r: r['lang']).items())]
    L += ["", "## Real documents vs synthetic complex documents", "", "| source | cases | gold values | leaked | recall | restore content-equal | blocked | crashes |", "|---|---|---|---|---|---|---|---|"]
    for src_ in ("real", "synthetic"):
        grp = [r for r in real if r.get("source", "real") == src_]
        if not grp:
            continue
        g, lk, *_ = stats(grp); done = [r for r in grp if "cats" in r]
        L.append(f"| {src_} | {len(grp)} | {g} | {lk} | {100 * (g - lk) / g if g else 0:.1f}% | {sum(1 for r in done if r.get('restore_content_equal'))}/{len(done)} | "
                 f"{sum(1 for r in grp if r.get('blocked'))} | {sum(1 for r in grp if r.get('crash'))} |")
    L += ["", "## Per format x kind: leaked / injected (perfect cells are 0/n)", ""]
    kinds = sorted(cat)
    L += ["| format | " + " | ".join(kinds) + " | total |", "|---|" + "---|" * (len(kinds) + 1)]
    perfect, imperfect = [], []
    for fmt in fmts:
        cells, tn, tk = [], 0, 0
        for c in kinds:
            n = sum(r.get("cats", {}).get(c, [0, 0])[0] for r in real if r["fmt"] == fmt); k = sum(r.get("cats", {}).get(c, [0, 0])[1] for r in real if r["fmt"] == fmt)
            tn += n; tk += k
            cells.append(("**" + f"{k}/{n}" + "**" if k else f"{k}/{n}") if n else "-")
            if n:
                (imperfect if k else perfect).append(f"{fmt}/{c}")
        L.append(f"| {fmt} | " + " | ".join(cells) + f" | {tk}/{tn} |")
    L += ["", "## What is 10/10 and what is not", "",
          f"- Format x kind cells with ZERO leaks ({len(perfect)}): " + ", ".join(sorted(perfect)) if perfect else "- no perfect cells",
          f"- Cells with at least one leak ({len(imperfect)}): " + (", ".join(sorted(imperfect)) if imperfect else "none"),
          "- Formats whose every cell is perfect: " + (", ".join(f for f in fmts if not any(x.startswith(f + "/") for x in imperfect)) or "none"),
          "- Remember: recall here is end-to-end on the OUTPUT file with independent readers; OCR-read formats (png/jpg/tiff/scanned pdf) can also under-report leaks when OCR cannot read the leaked value."]
    L += ["", "## Restore (anonymise -> restore) per format", "", "| format | cases with output | restore content-equal | byte-equal | restore errors |", "|---|---|---|---|---|"]
    for fmt in fmts:
        done = [r for r in real if r["fmt"] == fmt and "cats" in r]
        if done:
            L.append(f"| {fmt} | {len(done)} | {sum(1 for r in done if r.get('restore_content_equal'))} | {sum(1 for r in done if r.get('restore_byte_equal'))} | {sum(1 for r in done if 'restore_error' in r)} |")
    L += ["", "## Natural entities replaced (precision sampling; triage in `docs/superpowers/eval-natural-hits.md`)", "",
          "| format | cases | natural replacements (unique) | per case median |", "|---|---|---|---|"]
    for fmt in fmts:
        grp = [r for r in real if r["fmt"] == fmt and "natural_total" in r]
        if grp:
            tt = sorted(r["natural_total"] for r in grp)
            L.append(f"| {fmt} | {len(grp)} | {sum(tt)} | {tt[len(tt) // 2]} |")
    L += ["", "| group | natural replacements across all real documents |", "|---|---|"]
    g_all: dict = {}
    for r in real:
        for k, v in (r.get("natural_counts") or {}).items():
            g_all[k] = g_all.get(k, 0) + v
    L += [f"| {k} | {v} |" for k, v in sorted(g_all.items(), key=lambda x: -x[1])]
    NAT = ["# Natural entities replaced in real documents (precision sampling list)", "",
           "Generated by `tools/eval_real.py report`. Each row is an entity the product replaced that is NOT one of the injected synthetic values "
           "(so it is natural content of the document). Triage each as TP (really personal/sensitive) or FP (should have stayed). Verdicts live in `tests/eval/triage.md`.", ""]
    for r in sorted(real, key=lambda r: (r["fmt"], r["id"])):
        if r.get("natural"):
            NAT += [f"## {r['id']} ({r['fmt']}, {r['lang']}) - {r.get('natural_total', 0)} natural replacements", "", "| group | kind | original | count | reason |", "|---|---|---|---|---|"]
            NAT += [f"| {a} | {b} | {c.replace('|', '/')} | {d} | {e.replace('|', '/')} |" for a, b, c, d, e in r["natural"][:30]]
            NAT.append("")
    (ROOT / "docs" / "superpowers" / "eval-natural-hits.md").write_text("\n".join(NAT) + "\n", encoding="utf-8")
    L += ["", "## Adversarial cases", "", "| case | expect | outcome | gold | leaked | opens | restore | s | peak MB |", "|---|---|---|---|---|---|---|---|---|"]
    for r in adv:
        lk = sum(v[1] for v in r.get("cats", {}).values())
        outcome = "CRASH/HANG" if r.get("crash") else ("blocked/error (no output)" if r.get("blocked") else "output written")
        L.append(f"| {r['id']} | {r.get('expect', 'anonymize')} | {outcome} | {r.get('gold', 0)} | {lk} | {r.get('opens')} | {r.get('restore_content_equal')} | {r.get('t_anon', '-')} | {r.get('peak_mb', '-')} |")
    L += ["", "## Per-case table", "", "| case | fmt | lang | traits | gold | leaked | FP unverified | opens | restore | s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in real:
        lk = sum(v[1] for v in r.get("cats", {}).values())
        L.append(f"| {r['id']} | {r['fmt']} | {r['lang']} | {r['traits'][:28]} | {r.get('gold', 0)} | {lk} | {r.get('fp', '-')} | {r.get('opens')} | {r.get('restore_content_equal')} | {r.get('t_anon', '-')} |")
    notes = ROOT / "tests" / "eval" / "matrix_notes.md"          # hand-written method, limitations and reading guide
    if notes.exists():
        L += ["", notes.read_text(encoding="utf-8")]
    (ROOT / "docs" / "superpowers" / "quality-matrix.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    F = failures(rows)
    seen = set()
    fail_dir = ROOT / "tests" / "eval" / "failures"
    for f in F:                                                        # keep a committed minimal repro (<=300 KB) for every case with a finding
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        src = CASES / f["id"]
        files = [p for p in src.glob("*") if p.name not in ("case.json", "result.json")] if src.exists() else []
        if files and files[0].stat().st_size <= 300_000:
            (fail_dir / f["id"]).mkdir(parents=True, exist_ok=True)
            shutil.copy(files[0], fail_dir / f["id"] / files[0].name)
            shutil.copy(src / "case.json", fail_dir / f["id"] / "case.json")
            f["repro"] = f"tests/eval/failures/{f['id']}/{files[0].name}"
        else:
            f["repro"] = f"regenerate: tools/eval_real.py run --only {f['id']} (input too large to commit or derived from the fetched corpus)"
    repro = {f["id"]: f["repro"] for f in F if "repro" in f}
    M = ["# Evaluation failures (owners: A PDF/OCR, B OOXML, C detect/restore/text, D security)", ""]
    triage = ROOT / "tests" / "eval" / "triage.md"          # hand-written root-cause analysis, kept next to the data
    if triage.exists():
        M += [triage.read_text(encoding="utf-8"), ""]
    M += [f"## All findings ({len(F)}, auto-generated by `tools/eval_real.py report`)", "",
          "Reproduce one case: `python tools/eval_real.py run --only <id>` (inputs are written to `tests/eval/real/_cases/<id>/`).", "",
          "| # | case | fmt | kind | expected | actual | owner | repro |", "|---|---|---|---|---|---|---|---|"]
    for i, f in enumerate(F, 1):
        M.append(f"| {i} | {f['id']} | {f['fmt']} | {f['kind']} | {f['expected']} | {str(f['actual'])[:200].replace('|', '/')} | {f['owner']} | {repro.get(f['id'], '')} |")
    (ROOT / "docs" / "superpowers" / "eval-failures.md").write_text("\n".join(M) + "\n", encoding="utf-8")
    print(f"quality-matrix.md + eval-failures.md written, {len(F)} failures")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "worker":
        print("RESULT " + json.dumps(worker(Path(sys.argv[2])), ensure_ascii=False))
    else:
        ap = argparse.ArgumentParser(description="subset examples: run --fmt docx,xlsx --jobs 4 | run --only syn_,gov_ | run --source synthetic --lang ru --limit 5")
        ap.add_argument("cmd", choices=["run", "report", "publish"]); ap.add_argument("--only", help="comma list of id substrings"); ap.add_argument("--limit", type=int)
        ap.add_argument("--fmt", help="comma list of formats (pdf,docx,png,...)"); ap.add_argument("--lang"); ap.add_argument("--source", choices=["real", "synthetic", "adversarial"])
        ap.add_argument("--jobs", type=int, default=4, help="parallel worker processes")
        a = ap.parse_args()
        if a.cmd == "run":
            run(a.only, a.limit, a.fmt, a.lang, a.jobs, a.source)
        elif a.cmd == "publish":
            shutil.copyfile(RESULTS, TRACKED_RESULTS); print("copied", RESULTS, "->", TRACKED_RESULTS)
        else:
            report()
