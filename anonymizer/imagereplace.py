"""Картинки целиком: политика 1b.2 (картинка заменяется меткой, оригинал лежит в зашифрованном хранилище).

Это режим по умолчанию. Обнаружить лица, подписи, печати, рукописный текст, снимки экрана и QR детектором
нельзя гарантировать, поэтому любая картинка внутри документа (docx/xlsx/pptx/pdf/html/md) и отдельный файл
PNG/JPEG заменяются целиком. Оригинал хранится зашифрованным, при возврате возвращается побайтно.

Режим «закрасить текст, оставить картинку» (`Settings.image_mode == "redact_text"`) принадлежит W1 и включается
пользователем явно: хуки в `formats.py` вызывают `whole_image(settings)` и, если там False, идут прежним путём
(`formats._anonymize_image`). Этот модуль в том пути участвует только функцией `strip_all_metadata`, которую W1
вызывает для каждой оставляемой картинки.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import secrets
import struct

IMAGE_MODE_REPLACE = "replace"
IMAGE_MODE_REDACT_TEXT = "redact_text"

# Лимит на оригиналы картинок в хранилище (политика 1b.4). Переопределяется ANON_IMAGE_STORE_MB.
DEFAULT_STORE_LIMIT_MB = 1024

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RASTER_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic")
VECTOR_EXTS = (".emf", ".wmf", ".svg")
IMAGE_PART_EXTS = RASTER_EXTS + VECTOR_EXTS
MAX_SIDE = 1600
MIN_SIDE = 16
GRAY = (226, 229, 233)
INK = (70, 76, 86)

PDF_ID_KEY = "AnonImg"
INLINE_W = 8                      # поддельная встроенная картинка 8x1: восемь байт пикселей = идентификатор


class ImageStoreFull(Exception):
    """Хранилище оригиналов картинок заполнено: обезличивание останавливается, ничего не отбрасывается молча."""


def whole_image(settings) -> bool:
    """True — картинки заменяются целиком (по умолчанию). False — выбран режим W1 «закрасить текст»."""
    return str(getattr(settings, "image_mode", IMAGE_MODE_REPLACE) or IMAGE_MODE_REPLACE) != IMAGE_MODE_REDACT_TEXT


def store_limit_bytes() -> int:
    try:
        return int(float(os.environ.get("ANON_IMAGE_STORE_MB", DEFAULT_STORE_LIMIT_MB)) * 1024 * 1024)
    except ValueError:
        return DEFAULT_STORE_LIMIT_MB * 1024 * 1024


def limit_message(limit: int | None = None) -> str:
    mb = round((limit if limit is not None else store_limit_bytes()) / 1024 / 1024)
    return (f"Хранилище оригиналов картинок заполнено (лимит {mb} МБ). Файл не выдаётся: оригиналы нельзя отбросить, "
            "иначе картинки не вернутся при восстановлении. Очистите хранилище (Настройки: очистить) или обезличивайте по частям.")


def store_size(vault) -> int:
    probe = getattr(vault, "image_store_bytes", None)
    return int(probe()) if callable(probe) else 0


def stash(vault, key: str, original: bytes) -> None:
    """Кладёт оригинал в хранилище. Лимит превышен — ImageStoreFull, молча ничего не теряется."""
    limit = store_limit_bytes()
    if store_size(vault) + len(original) > limit:
        raise ImageStoreFull(limit_message(limit))
    vault.stash_image(key, original)


# -- размеры и метаданные ------------------------------------------------------------------------------------

def sniff(raw: bytes) -> str:
    if raw.startswith(PNG_MAGIC):
        return ".png"
    if raw[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if raw[:2] == b"BM":
        return ".bmp"
    if raw[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    if raw[:4] == b"\x01\x00\x00\x00" and raw[40:44] == b" EMF":
        return ".emf"
    if raw[:4] == b"\xd7\xcd\xc6\x9a" or raw[:4] in (b"\x01\x00\x09\x00", b"\x02\x00\x09\x00"):
        return ".wmf"
    head = raw[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in raw[:4096].lower()):
        return ".svg"
    return ""


def dimensions(raw: bytes) -> tuple[int, int]:
    """Ширина и высота без распаковки пикселей. Не удалось определить — (640, 400)."""
    try:
        if raw.startswith(PNG_MAGIC) and len(raw) >= 24:
            return struct.unpack(">II", raw[16:24])
        if raw[:3] == b"\xff\xd8\xff":
            pos = 2
            while pos + 9 < len(raw):
                if raw[pos] != 0xFF:
                    pos += 1
                    continue
                marker = raw[pos + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                    pos += 2 if marker != 0xFF else 1
                    continue
                size = int.from_bytes(raw[pos + 2:pos + 4], "big")
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", raw[pos + 5:pos + 9])
                    return w, h
                pos += 2 + size
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            return im.size
    except Exception:
        pass
    return 640, 400


def strip_all_metadata(raw: bytes) -> bytes:
    """Для картинок, которые остаются в файле (режим W1): убирает EXIF/GPS, XMP, IPTC, комментарии, ICC-профиль,
    миниатюры (они лежат в APP1/EXIF) и всё, что приписано после конца изображения. Пиксели не пересжимаются.
    Нераспознанный или повреждённый вход возвращается без изменений."""
    try:
        if raw.startswith(PNG_MAGIC):
            keep = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs", b"sBIT", b"bKGD",
                    b"acTL", b"fcTL", b"fdAT"}
            out, pos = [raw[:8]], 8
            while pos + 8 <= len(raw):
                size = int.from_bytes(raw[pos:pos + 4], "big")
                kind = raw[pos + 4:pos + 8]
                end = pos + 12 + size
                if end > len(raw):
                    return raw
                if kind in keep:
                    out.append(raw[pos:end])
                pos = end
                if kind == b"IEND":
                    break
            return b"".join(out)
        if raw[:3] == b"\xff\xd8\xff":
            out, pos = [raw[:2]], 2
            while pos + 4 <= len(raw):
                if raw[pos] != 0xFF:
                    return raw
                marker = raw[pos + 1]
                if marker == 0xDA:
                    eoi = raw.find(b"\xff\xd9", pos)
                    out.append(raw[pos:eoi + 2] if eoi >= 0 else raw[pos:])
                    return b"".join(out)
                if marker == 0xFF:
                    pos += 1
                    continue
                size = int.from_bytes(raw[pos + 2:pos + 4], "big")
                end = pos + 2 + size
                if end > len(raw):
                    return raw
                if not (marker == 0xFE or 0xE1 <= marker <= 0xEF):     # APP0 (JFIF) остаётся; APP1..15 и COM уходят
                    out.append(raw[pos:end])
                pos = end
            return raw
    except Exception:
        pass
    return raw


# -- создание заглушки --------------------------------------------------------------------------------------

def _fit(w: int, h: int) -> tuple[int, int]:
    scale = min(1.0, MAX_SIDE / max(w, h, 1))
    return max(MIN_SIDE, int(w * scale)), max(MIN_SIDE, int(h * scale))


def _render(w: int, h: int, label: str):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (w, h), GRAY)
    draw = ImageDraw.Draw(im)
    nonce = secrets.token_bytes(8)
    if w >= 48 and h >= 24:
        draw.rectangle([0, 0, w - 1, h - 1], outline=INK)
        size = max(10, min(h // 3, w // max(len(label), 4) * 2, 96))
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), label, font=font)
        draw.text(((w - (box[2] - box[0])) / 2 - box[0], (h - (box[3] - box[1])) / 2 - box[1]), label, fill=INK, font=font)
        cell = max(2, min(w // 40, 6))
        for i in range(64):                       # 64 ячеек по 2 бита: уникальность заглушки, чтобы хэши не совпадали
            shade = 200 + 18 * ((nonce[i // 8] >> (i % 8)) & 1) + 9 * ((nonce[((i + 3) % 64) // 8] >> (((i + 3) % 64) % 8)) & 1)
            x, y = 2 + (i % 32) * cell, 2 + (i // 32) * cell
            if x + cell < w - 2 and y + cell < h - 2:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(shade, shade, shade))
    else:
        for i, b in enumerate(nonce):             # крошечная картинка: просто шум серого
            draw.point((i % w, (i // w) % h), fill=(200 + b % 50,) * 3)
    return im


def placeholder_for(raw: bytes, label: str, ext: str = "") -> bytes:
    """Заглушка с меткой: тот же формат и те же пропорции, что у оригинала; ни метаданных, ни пикселей оригинала.
    Каждый вызов даёт уникальные байты, хэш заглушки служит ключом к оригиналу в хранилище."""
    ext = (ext or sniff(raw)).lower()
    if ext == ".emf":
        return _emf_placeholder()
    if ext == ".wmf":
        return _wmf_placeholder()
    if ext == ".svg":
        nonce = secrets.token_hex(8)
        w, h = 400, 240
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#e2e5e9" stroke="#464c56"/>'
                f'<text x="{w // 2}" y="{h // 2}" text-anchor="middle" font-size="40" fill="#464c56">{label}</text>'
                f'<desc>{nonce}</desc></svg>').encode()
    w, h = _fit(*dimensions(raw))
    im = _render(w, h, label)
    buf = io.BytesIO()
    if ext in (".jpg", ".jpeg"):
        im.save(buf, "JPEG", quality=85)
    elif ext == ".gif":
        im.convert("P").save(buf, "GIF")
    elif ext == ".bmp":
        im.save(buf, "BMP")
    elif ext in (".tif", ".tiff"):
        im.save(buf, "TIFF")
    elif ext == ".webp":
        im.save(buf, "WEBP", lossless=True)
    else:
        im.save(buf, "PNG")
    return buf.getvalue()


def _emf_placeholder() -> bytes:
    """Минимальный пустой EMF: заголовок, запись-комментарий со случайными байтами (уникальность), конец."""
    payload = b"ANON" + secrets.token_bytes(8)
    comment = struct.pack("<III", 70, 12 + len(payload), len(payload)) + payload
    eof = struct.pack("<IIIII", 14, 20, 0, 16, 20)
    total = 88 + len(comment) + len(eof)
    header = struct.pack("<II4i4iIIIIHHIII2i2i", 1, 88, 0, 0, 399, 239, 0, 0, 10600, 6360, 0x464D4520, 0x10000, total, 3, 1, 0,
                         0, 0, 0, 400, 240, 106, 64)
    assert len(header) == 88
    return header + comment + eof


def _wmf_placeholder() -> bytes:
    nonce = secrets.token_bytes(2)
    std = struct.pack("<HHHIHIH", 1, 9, 0x300, 0, 0, 3, 0)
    eof = struct.pack("<IH", 3, 0)
    # метка-комментарий не нужна: уникальность даёт ключ в заголовке (hmf) и размер
    size_words = (len(std) + len(eof)) // 2
    std = struct.pack("<HHHIHIH", 1, 9, 0x300, size_words, 0, 3, 0)
    key = 0x9AC6CDD7
    box = (0, 0, 400, 240)
    inch = 1440
    pre = struct.pack("<IHhhhhHI", key, int.from_bytes(nonce, "little"), *box, inch, 0)
    checksum = 0
    for i in range(0, 20, 2):
        checksum ^= struct.unpack("<H", pre[i:i + 2])[0]
    return pre + struct.pack("<H", checksum) + std + eof


# -- общий вход для файлов и частей OOXML -------------------------------------------------------------------

def next_label(ctx) -> str:
    n = int(ctx.__dict__.get("image_label_n", 0)) + 1
    ctx.__dict__["image_label_n"] = n
    return f"Image{n}"


def replace_image(raw: bytes, ctx, ext: str = "") -> bytes:
    """Заменяет картинку целиком. Оригинал уходит в хранилище под хэшем заглушки (ImageStoreFull при превышении лимита)."""
    ext = ext or sniff(raw)
    data = placeholder_for(raw, next_label(ctx), ext)
    stash(ctx.vault, hashlib.sha256(data).hexdigest(), raw)
    ctx.__dict__["images_replaced"] = int(ctx.__dict__.get("images_replaced", 0)) + 1
    return data


STRICT_MAGIC = (PNG_MAGIC, b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"II*\x00", b"MM\x00*")


def replaces_part(name: str, raw: bytes = b"") -> bool:
    """Часть пакета с картинкой любого вида и в любой папке (media, embeddings, charts, ...): заменяется целиком.
    Распознаётся и по расширению, и по первым байтам (переименованная картинка не проходит мимо)."""
    lowered = name.lower()
    if lowered.endswith((".xml", ".rels", ".vml")):
        return False
    if lowered.endswith(IMAGE_PART_EXTS):
        return True
    head = raw[:4096]
    return bool(head) and (head.startswith(STRICT_MAGIC) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
                           or (head[:4] == b"\x01\x00\x00\x00" and head[40:44] == b" EMF"))


_INSIDE_MAGIC = (PNG_MAGIC, b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb", b"GIF89a", b"GIF87a")


def contains_image(raw: bytes) -> bool:
    """В непрозрачном двоичном объекте (OLE .bin, чужой формат) виден заголовок картинки: заменить её нельзя, файл не выдаётся."""
    return any(m in raw for m in _INSIDE_MAGIC) or bool(re.search(rb"RIFF....WEBP", raw, re.S))


def opaque_image_warning(name: str) -> str:
    return (f"Внутри вложенного объекта {name} видна картинка, которую нельзя заменить без разбора объекта. Файл не выдаётся: "
            "удалите вложенный объект или вставьте картинку обычным способом.")


def replace_part(raw: bytes, name: str, ctx) -> bytes:
    ext = sniff(raw) or os.path.splitext(name)[1].lower()
    return replace_image(raw, ctx, ext if ext in IMAGE_PART_EXTS else ".png")


STANDALONE_EXTS = (".png", ".jpg", ".tif", ".webp", ".gif", ".bmp")     # TIFF/WebP/GIF/BMP: Pillow их читает и пишет


def sniff_file(path) -> str:
    """Расширение по первым байтам файла для форматов, кроме PNG/JPEG, которые заменяются целиком. Нужен и Pillow."""
    try:
        with open(path, "rb") as fh:
            ext = sniff(fh.read(64))
        if ext in (".tif", ".webp", ".gif", ".bmp"):
            from PIL import Image
            with Image.open(path) as im:
                im.load()
            return ext
    except Exception:
        pass
    return ""


def transform_standalone(src, dst, rel: str, ctx):
    """Отдельный файл PNG/JPEG: заменяется заглушкой, оригинал в хранилище. Возвращает FileResult."""
    from pathlib import Path
    from .models import FileResult, FileStatus
    raw = Path(src).read_bytes()
    ext = sniff(raw)
    if ext not in STANDALONE_EXTS:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=["Формат картинки не распознан: она не обработана."])
    try:
        data = replace_image(raw, ctx, ext)
    except ImageStoreFull as exc:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=[str(exc)])
    except Exception as exc:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=[f"Картинку не удалось заменить ({type(exc).__name__}). Файл не передаётся наружу."])
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(data)
    return FileResult(rel, "IMAGE", FileStatus.CLEAN, output_path=str(dst), notices=[notice_replaced(1)])


def notice_replaced(count: int) -> str:
    return (f"Картинки заменены целиком метками Image1, Image2 и так далее ({count}). Оригиналы лежат в зашифрованном "
            "хранилище и вернутся при восстановлении. Лица, подписи, печати и снимки экрана на картинках не распознаются, поэтому "
            "картинка не остаётся в файле ни частично.")


WARN_VECTOR_LOGO = ("Логотип нарисован векторно и остаётся видимым в файле; закрашено только прочитанное название. "
                    "Проверьте страницы глазами до отправки.")


def warn_kept_pixels(count: int) -> str:
    return (f"Картинки и логотипы остаются в файле видимыми ({count}): закрашен только распознанный текст, метки написаны поверх. "
            "Лица, подписи, печати и незамеченные надписи уйдут наружу как есть. Проверьте результат глазами до отправки. "
            "Оригиналы хранятся зашифрованными для возврата.")


# -- HTML / Markdown: data URI ----------------------------------------------------------------------------

TEXT_IMAGE_SUFFIXES = (".html", ".htm", ".xhtml", ".md", ".markdown", ".svg")
DATA_URI = re.compile(r"data:image/(?P<sub>[A-Za-z0-9.+-]+)(?P<params>;[A-Za-z0-9=._-]+)*?;base64,(?P<b64>[A-Za-z0-9+/=\s%]+)", re.I)
LINKED_IMAGE = re.compile(r"""(?:<img\b[^>]*?\bsrc\s*=\s*["']?|!\[[^\]]*\]\(\s*<?)(?P<url>[^"'>\s)]+)""", re.I)


def replace_data_uris(text: str, ctx) -> tuple[str, int]:
    count = 0

    def sub(m):
        nonlocal count
        try:
            raw = base64.b64decode(re.sub(r"\s|%0A|%0D", "", m.group("b64")), validate=False)
        except Exception:
            raw = b""
        if not raw:
            raw = b"\x00"
        ext = sniff(raw) or {"jpeg": ".jpg", "svg+xml": ".svg"}.get(m.group("sub").lower(), "." + m.group("sub").lower())
        data = replace_image(raw, ctx, ext if ext in IMAGE_PART_EXTS else ".png")
        count += 1
        mime = m.group(0)[:m.group(0).lower().index(";base64,")]
        return f"{mime};base64,{base64.b64encode(data).decode()}"
    return DATA_URI.sub(sub, text), count


def data_uri_spans(text: str) -> list[tuple[int, int]]:
    """Границы base64-полезной нагрузки каждого data:image: они не проходят через поиск персональных данных."""
    return [m.span("b64") for m in DATA_URI.finditer(text)]


def strip_data_uri_payloads(text: str) -> str:
    return DATA_URI.sub(lambda m: m.group(0)[:m.start("b64") - m.start()], text)


def restore_data_uris(text: str, vault) -> tuple[str, int]:
    count = 0

    def sub(m):
        nonlocal count
        try:
            data = base64.b64decode(re.sub(r"\s", "", m.group("b64")))
        except Exception:
            return m.group(0)
        original = vault.original_image(hashlib.sha256(data).hexdigest())
        if original is None:
            return m.group(0)
        count += 1
        mime = m.group(0)[:m.group(0).lower().index(";base64,")]
        return f"{mime};base64,{base64.b64encode(original).decode()}"
    return DATA_URI.sub(sub, text), count


def linked_images(text: str) -> list[str]:
    """Ссылки на файлы картинок (не data:), которые остаются ссылками: сам файл рядом программа не видит."""
    out = []
    for m in LINKED_IMAGE.finditer(text):
        url = m.group("url")
        if not url.lower().startswith("data:") and not url.startswith("#"):
            out.append(url)
    return out


def local_links(urls: list[str]) -> list[str]:
    """Ссылки на файлы рядом с документом (не http/https, не data:)."""
    return [u for u in urls if not re.match(r"(?i)^(https?:)?//|^(https?|ftp|mailto|data|cid):", u)]


def linked_warning(urls: list[str]) -> str:
    return (f"В файле есть ссылки на файлы картинок ({len(urls)}), которые остаются рядом с ним необработанными. Файл не выдаётся: "
            "обезличьте эти картинки отдельно (они заменяются целиком) и вставьте их в документ как встроенные или уберите ссылки.")


# -- PDF ----------------------------------------------------------------------------------------------------

_INLINE = re.compile(rb"(?s)(?<![\w/])BI\s.*?\sID[ \r\n](?P<data>.*?)(?<=[\s\x00-\xff])EI(?=[\s]|$)")
_PH_INLINE = b"BI /W 8 /H 1 /CS /G /BPC 8 ID "


def _is_image(doc, xref: int) -> bool:
    return doc.xref_get_key(xref, "Subtype")[1] == "/Image"


def _pack_original(obj: str, stream: bytes) -> bytes:
    body = obj.encode("utf-8")
    return len(body).to_bytes(4, "big") + body + stream


def _unpack_original(blob: bytes) -> tuple[str, bytes]:
    n = int.from_bytes(blob[:4], "big")
    return blob[4:4 + n].decode("utf-8"), blob[4 + n:]


def _device_space(doc, xref_text: str) -> str:
    """Цветовое пространство без ссылок: ICC-профиль не сохраняется (политика: ICC удаляется), берётся устройство."""
    def icc(m):
        try:
            n = int(doc.xref_get_key(int(m.group(1)), "N")[1])
        except Exception:
            n = 3
        return {1: "/DeviceGray", 4: "/DeviceCMYK"}.get(n, "/DeviceRGB")
    text = re.sub(r"\[\s*/ICCBased\s+(\d+)\s+0\s+R\s*\]", icc, xref_text)
    return text if not re.search(r"\d+\s+0\s+R", text) else "/DeviceRGB"


class ImageReplaceError(Exception):
    """Картинку PDF нельзя заменить с возвратом (неподдержанная связь объектов): файл не выдаётся."""


GLOBALS_MARK = "@@JBIG2G@@"


def _globals_blob(doc, ref: int) -> bytes:
    """JBIG2Globals как самостоятельный блок: словарь без номеров объектов (длина, фильтр) и сырой поток."""
    if doc.xref_get_key(ref, "Subtype")[0] != "null" or not doc.xref_is_stream(ref):
        raise ImageReplaceError("PDF: у картинки есть связанный объект /JBIG2Globals, который нельзя безопасно заменить")
    raw = doc.xref_stream_raw(ref) or b""
    parts = [f"/Length {len(raw)}"]
    for key in ("Filter", "DecodeParms"):
        kind, val = doc.xref_get_key(ref, key)
        if kind == "null":
            continue
        if re.search(r"\d+\s+0\s+R", val):
            raise ImageReplaceError("PDF: у картинки есть связанный объект /JBIG2Globals, который нельзя безопасно заменить")
        parts.append(f"/{key} {val}")
    return _pack_original("<< " + " ".join(parts) + " >>", raw)


def _portable(doc, obj: str, globals_cb=None) -> tuple[str, list[int]]:
    """Словарь картинки без номеров объектов: цветовое пространство подставляется, SMask/Mask заменяются маркерами
    (номера объектов меняются при сохранении, а на сами объекты в заглушке остаётся живая ссылка /AnonKeep).
    /Metadata картинки отбрасывается (метаданные в любом случае удаляются политикой); /JBIG2Globals через globals_cb
    уезжает в хранилище вместе с картинкой и возвращается новым объектом."""
    keep: list[int] = []

    def sub(m):
        key, ref = m.group(1), int(m.group(2))
        if key == "Metadata":
            return ""
        if key == "Length":                # длина потока лежит в отдельном объекте: в словарь кладётся число
            return "/Length " + doc.xref_object(ref, compressed=True).strip()
        if key == "JBIG2Globals" and globals_cb is not None:
            return f"/JBIG2Globals {GLOBALS_MARK}{globals_cb(ref)}@@"
        if key == "ColorSpace":
            return "/ColorSpace " + _device_space(doc, doc.xref_object(ref, compressed=True).strip())
        if key in ("SMask", "Mask") and doc.xref_get_key(ref, "Subtype")[1] == "/Image":
            keep.append(ref)
            return f"/{key} @@KEEP{len(keep) - 1}@@"
        raise ImageReplaceError(f"PDF: у картинки есть связанный объект /{key}, который нельзя безопасно заменить")
    obj = re.sub(r"/ColorSpace\s*\[\s*/ICCBased\s+(\d+)\s+0\s+R\s*\]",
                 lambda m: "/ColorSpace " + _device_space(doc, m.group(0)[len("/ColorSpace"):].strip()), obj)
    return re.sub(r"/(\w+)\s+(\d+)\s+0\s+R", sub, obj), keep


def replace_pdf_images(doc, ctx) -> int:
    """Все картинки PDF заменяются: объекты Image (в том числе в формах, SMask, миниатюры страниц), встроенные в
    поток страницы (BI..EI). Оригинал каждого объекта хранится по случайному идентификатору, который лежит в самой
    заглушке (ключ /AnonImg). Возвращает число замен; ImageStoreFull при превышении лимита."""
    vault = ctx.vault
    done: dict[int, str] = {}
    count = 0
    page_rects: dict[int, list] = {}
    for page in doc:
        for info in page.get_images(full=True):
            xref = info[0]
            try:
                page_rects.setdefault(xref, []).append((page, page.get_image_rects(xref)))
            except Exception:
                page_rects.setdefault(xref, []).append((page, []))
    targets = []
    for xref in range(1, doc.xref_length()):
        try:
            if _is_image(doc, xref) and doc.xref_get_key(xref, PDF_ID_KEY)[0] == "null":
                targets.append(xref)
        except Exception:
            continue
    globals_keys: dict[int, str] = {}

    def globals_key(ref: int) -> str:
        if ref not in globals_keys:
            key = secrets.token_hex(8)
            stash(vault, "pdfglb_" + key, _globals_blob(doc, ref))
            globals_keys[ref] = key
        return globals_keys[ref]

    for xref in targets:
        obj = doc.xref_object(xref, compressed=False)
        raw = doc.xref_stream_raw(xref) or b""
        portable, keep = _portable(doc, obj, globals_key)
        ident = secrets.token_hex(8)
        stash(vault, "pdfimg_" + ident, _pack_original(portable, raw))
        kept = " ".join(f"{k} 0 R" for k in keep)
        doc.update_object(xref, f"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
                                f"/BitsPerComponent 8 /{PDF_ID_KEY} ({ident}) /AnonKeep [{kept}] >>")
        doc.update_stream(xref, bytes([GRAY[0]]), new=True, compress=False)
        done[xref] = next_label(ctx)
        count += 1
    # Подписи рисуются позже (draw_pending_labels, после редактирования текста страницы): иначе рамка редактирования
    # стирает часть подписи («Image7» -> «7»), и при восстановлении её не узнать (S6D).
    pending = ctx.__dict__.setdefault("pdf_pending_labels", [])
    for xref, label in done.items():
        for page, rects in page_rects.get(xref, []):
            for rect in rects:
                if rect.width > 30 and rect.height > 14:
                    pending.append((page.number, rect, label))
    count += _replace_inline(doc, ctx)
    ctx.__dict__["images_replaced"] = int(ctx.__dict__.get("images_replaced", 0)) + count
    return count


def draw_pending_labels(doc, ctx) -> None:
    """Рисует подписи ImageN на заглушках (см. replace_pdf_images); вызывается после редактирования текста страниц."""
    for page_number, rect, label in ctx.__dict__.pop("pdf_pending_labels", []):
        if 0 <= page_number < len(doc):
            doc[page_number].insert_textbox(rect, label, fontsize=min(24, max(7, rect.height / 4)), fontname="helv",
                                            color=(.27, .3, .34), align=1)


def _content_xrefs(doc) -> list[int]:
    out: set[int] = set()
    for page in doc:
        out.update(page.get_contents())
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Subtype")[1] == "/Form":
                out.add(xref)
        except Exception:
            pass
    return sorted(out)


def _replace_inline(doc, ctx) -> int:
    n = 0
    for xref in _content_xrefs(doc):
        try:
            stream = doc.xref_stream(xref)
        except Exception:
            continue
        if not stream or b"BI" not in stream:
            continue
        changed = False

        def sub(m):
            nonlocal changed, n
            ident = secrets.token_bytes(INLINE_W)
            stash(ctx.vault, "pdfinl_" + ident.hex(), m.group(0))
            changed = True
            n += 1
            return _PH_INLINE + ident + b"\nEI"
        new = _INLINE.sub(sub, stream)
        if changed:
            doc.update_stream(xref, new)
    # Проверка: после замены в потоках не осталось встроенных картинок, кроме заглушек 8x1. Иначе файл не выдаётся.
    for xref in _content_xrefs(doc):
        try:
            stream = doc.xref_stream(xref)
        except Exception:
            continue
        for m in re.finditer(rb"(?<![\w/])BI\s*/", stream or b""):
            if not re.match(rb"BI\s*/W\s*8\s*/H\s*1[^I]{0,80}?ID\s", stream[m.start():m.start() + 120], re.S):
                raise ImageReplaceError("PDF: встроенную в страницу картинку не удалось заменить, файл не выдаётся")
    return n


def is_placeholder_info(doc, info: dict) -> bool:
    """Картинка страницы из `page.get_image_info(xrefs=True)` — наша заглушка: объект с ключом /AnonImg или встроенная 8x1.
    Любая другая картинка (в том числе оставшаяся из-за сбоя замены) читается и проверяется как раньше."""
    try:
        xref = int(info.get("xref") or 0)
        if xref:
            return doc.xref_get_key(xref, PDF_ID_KEY)[0] != "null" and int(info.get("width", 0)) <= 1 and int(info.get("height", 0)) <= 1
        return int(info.get("width", 0)) == INLINE_W and int(info.get("height", 0)) == 1
    except Exception:
        return False


def restore_pdf_images(doc, vault) -> int:
    """Возвращает оригиналы картинок в PDF, обезличенный этой программой. Нет в хранилище — остаётся заглушка."""
    count = 0
    restored_globals: dict[str, int] = {}
    for xref in range(1, doc.xref_length()):
        try:
            kind, ident = doc.xref_get_key(xref, PDF_ID_KEY)
        except Exception:
            continue
        if kind == "null" or not ident:
            continue
        blob = vault.original_image("pdfimg_" + ident.strip("()"))
        if blob is None:
            continue
        obj, raw = _unpack_original(blob)
        try:
            keeps = re.findall(r"(\d+)\s+0\s+R", doc.xref_get_key(xref, "AnonKeep")[1])
        except Exception:
            keeps = []
        for i, ref in enumerate(keeps):
            obj = obj.replace(f"@@KEEP{i}@@", f"{ref} 0 R")
        def globals_ref(m):
            key = m.group(1)
            if key not in restored_globals:
                gblob = vault.original_image("pdfglb_" + key)
                if gblob is None:
                    return None
                gobj, graw = _unpack_original(gblob)
                new = doc.get_new_xref()
                doc.update_object(new, "<< /Type /XObject >>")
                doc.update_stream(new, graw, new=True, compress=False)
                doc.update_object(new, gobj)
                restored_globals[key] = new
            return f"{restored_globals[key]} 0 R"
        missing = False
        for m in re.finditer(GLOBALS_MARK + r"([0-9a-f]+)@@", obj):
            if globals_ref(m) is None:
                missing = True
        if missing:
            continue                   # глобальных данных JBIG2 нет в хранилище: оставляем заглушку, а не битую картинку
        obj = re.sub(GLOBALS_MARK + r"([0-9a-f]+)@@", globals_ref, obj)
        doc.update_object(xref, "<< /Type /XObject >>")
        doc.update_stream(xref, raw, new=True, compress=False)   # потом словарь: иначе update_stream теряет /Filter
        doc.update_object(xref, obj)
        count += 1
    pattern = re.compile(rb"(?s)BI\s*/W\s*8\s*/H\s*1[^I]{0,80}?ID\s(.{8})\s*EI")
    for xref in _content_xrefs(doc):
        try:
            stream = doc.xref_stream(xref)
        except Exception:
            continue
        if not stream or b"/BPC" not in stream:
            continue
        changed = False

        def sub(m):
            nonlocal changed, count
            blob = vault.original_image("pdfinl_" + m.group(1).hex())
            if blob is None:
                return m.group(0)
            changed = True
            count += 1
            return blob
        new = pattern.sub(sub, stream)
        if changed:
            doc.update_stream(xref, new)
    return count
