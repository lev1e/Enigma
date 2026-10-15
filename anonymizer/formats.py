from __future__ import annotations

import copy
import contextvars
import hashlib
from array import array
import io
import os
import posixpath
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import fitz
from lxml import etree

from . import colctx
from . import lexicon
from . import imagereplace, imagetext
from . import finance as finance_module
from . import ocr
from . import refusals
from . import numbers as numeric
from .models import Decision, FileResult, FileStatus, Finding, Settings
from .normalize import fold
from .pdftext import PageChars, Segment as PixSegment, draw_text, find_all, kept_chars, redraw_lost, rgb, RectGrid
from .textstruct import CSV_SUFFIXES, HTML_SUFFIXES, XML_SUFFIXES, Structure
from .tokens import EMAIL_TOKEN_RE, INNER_TOKEN_RE, TOKEN_RE, base_of, kind_of, parse_match
from .util import atomic_write, decode_text, finding_id, safe_copy, sha256_bytes, sniff_encoding
from .vault import Vault


TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".md", ".json", ".xml", ".log", ".htm", ".html", ".ini", ".yaml", ".yml"}
OOXML_EXTENSIONS = {".xlsx", ".docx", ".pptx"}
# OpenDocument — тот же ZIP с XML внутри, и вернуть плейсхолдеры на место в нём получается.
# А вот обезличивать его пока нельзя: текст в ODF лежит прямо в <text:p> вперемешку с хвостами
# вложенных узлов, чего сборщик текста не умеет, и снимок целостности для ODF не считается.
# Поэтому такой файл никогда не объявляется очищенным.
ODF_EXTENSIONS = {".odt", ".ods", ".odp"}
MACRO_EXTENSIONS = {".xlsm", ".docm", ".pptm"}
OLD_OFFICE = {".xls", ".doc", ".ppt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic"}

# Свойства документа. В core.xml имена строчные, в app.xml — с заглавной (`Company`, `Manager`), поэтому перечислены оба вида.
# Название (`title`) и категория обычно содержат имя клиента или проекта: «Отчёт для ООО «Маяк-Строй»».
# `Template` — имя шаблона оформления в app.xml: у корпоративного шаблона в нём название клиента («Клиент_шаблон.potx»).
METADATA_TAGS = {"creator", "lastModifiedBy", "company", "manager", "comments", "description", "subject", "keywords",
                 "title", "category", "Company", "Manager", "contentStatus", "HyperlinkBase", "Template"}
TEXT_TAGS = {
    "t", "text", "delText", "delInstrText", "f", "definedName", "oddHeader", "evenHeader", "firstHeader",
    "oddFooter", "evenFooter", "firstFooter", "author", "instrText", "lpwstr", "bstr", "lpstr",
    # Выпадающий список проверки данных и формула условного форматирования держат значения
    # прямо в тексте узла: «"Иванов,Петров,Сидоров"» уезжало наружу нетронутым.
    "formula1", "formula2", "formula",
} | METADATA_TAGS
GROUP_TAGS = {"p", "si", "c", "cell", "comment", "definedName", "oddHeader", "evenHeader", "firstHeader",
              "oddFooter", "evenFooter", "firstFooter", "pt", "tx",
              "formula1", "formula2", "formula"}
SEPARATOR_TAGS = {"tab": " ", "br": "\n", "cr": "\n"}

# Средняя ширина глифа относительно кегля. Токены пишутся Helvetica (узкая латиница),
# восстановленный текст — встроенным Unicode-шрифтом, у которого глифы шире.
TOKEN_GLYPH_WIDTH = .50
RESTORED_GLYPH_WIDTH = .55
PLACEHOLDER_FONT_RANGE = (3.0, 8.0)

# Attributes that carry a person's name rather than machine data. Sheet names, shape names and
# alt text all live here and are invisible to any scan that only walks element text.
SENSITIVE_ATTRS = {"author", "initials", "userId", "lastModifiedBy", "creator", "displayName", "refreshedBy"}
# Имена, которые Excel принимает только как идентификатор: невидимый разделитель в них недопустим.
IDENTIFIER_ATTRS = {("table", "name"), ("table", "displayName"), ("tableColumn", "name"), ("definedName", "name"),
                    ("bookmarkStart", "name"), ("hyperlink", "anchor"), ("tag", "val")}
NAMED_ELEMENT_ATTRS = {
    ("sheet", "name"), ("cNvPr", "name"), ("cNvPr", "descr"), ("cNvPr", "title"),
    ("docPr", "name"), ("docPr", "descr"), ("docPr", "title"), ("cSld", "name"),
    ("table", "displayName"), ("table", "name"), ("chartSpace", "name"), ("pivotCacheDefinition", "name"),
    # Имя столбца умной таблицы обязано совпадать с текстом её заголовка в ячейке, иначе Excel предлагает «восстановить»
    # файл. Заголовок обезличивается, значит и имя столбца должно измениться так же.
    ("tableColumn", "name"), ("cacheField", "name"), ("pivotField", "name"),
    # Подсказки и тексты, которые видит человек: гиперссылка, проверка данных, условное форматирование.
    ("hyperlink", "tooltip"), ("hyperlink", "display"), ("dataValidation", "prompt"), ("dataValidation", "promptTitle"),
    ("dataValidation", "error"), ("dataValidation", "errorTitle"), ("cfRule", "text"),
    ("property", "name"), ("definedName", "name"), ("bookmarkStart", "name"), ("hyperlink", "anchor"),
    # Имена темы, палитры, шрифтовой схемы и эффектов: автор корпоративного шаблона пишет в них название клиента
    # («Клиент ppt color palette»). В документе их не видно, но в файле они лежат открытым текстом.
    # `themeFamily` (расширение Office 2013+) хранит ещё и имя файла шаблона: «Клиент_template_blue.potx».
    # Word: элементы управления и формы, свойства таблицы, переменные документа, смарт-теги; Excel: фильтр, автор общего
    # доступа, комментарий имени, стиль ячейки; PowerPoint: подсказки гиперссылок на тексте и фигуре.
    ("listItem", "displayText"), ("listItem", "value"), ("helpText", "val"), ("statusText", "val"), ("default", "val"),
    ("docVar", "val"), ("tblCaption", "val"), ("tblDescription", "val"), ("customXml", "element"), ("smartTag", "element"),
    ("customFilter", "val"), ("fileSharing", "userName"), ("definedName", "comment"), ("cellStyle", "name"),
    ("hlinkClick", "tooltip"), ("hlinkHover", "tooltip"), ("connectString", "val"), ("query", "val"),
    ("shape", "alt"), ("shape", "title"),            # VML-запасной вариант текстового поля (mc:Fallback)
    ("theme", "name"), ("clrScheme", "name"), ("fontScheme", "name"), ("fmtScheme", "name"), ("themeFamily", "name"),
    # Внешние книги, подключения к данным, значения автофильтра, пользовательские форматы чисел, надпись VML (WordArt),
    # показы PowerPoint: тексты, которые читаются в файле открытым текстом, хотя на листе их не видно.
    ("sheetName", "val"), ("connection", "name"), ("connection", "description"), ("dbPr", "connection"),
    ("dbPr", "command"), ("webPr", "url"), ("textPr", "sourceFile"), ("filter", "val"), ("numFmt", "formatCode"),
    ("textpath", "string"), ("custShow", "name"), ("docPart", "val"),
}
TEMPLATE_NAME_ATTRS = {("theme", "name"), ("clrScheme", "name"), ("fontScheme", "name"), ("fmtScheme", "name"),
                       ("themeFamily", "name")}
# Встроенные имена Office: в них нет ничего о владельце, и заменять их незачем.
BUILTIN_TEMPLATE_NAME = re.compile(
    r"(?i)^\s*(?:(?:тема\s+)?office(?:\s+\d{4}(?:\s*[-–]\s*\d{4})?)?(?:\s+(?:theme|тема))?|normal(?:\.dot[mx]?)?|blank(?:\.potx)?|"
    r"(?:custom|другая|специальная|пользовательская|настраиваемая)(?:\s+\d+)?)\s*$")
# Имена одних и тех же элементов в разных форматах значат разное: `tag` в Word — метка элемента управления, а в PowerPoint —
# служебные данные надстройки (think-cell хранит там целый XML). Поэтому такие атрибуты берутся только в своей части файла.
PART_NAMED_ATTRS = {
    "word/": {("alias", "val"), ("tag", "val"), ("fldSimple", "instr"), ("name", "val"), ("description", "val")},
    "ppt/tags/": {("tag", "val"), ("tag", "name")},
    "ppt/": {("cmAuthor", "name"), ("cmAuthor", "initials"), ("section", "name"),
             ("author", "name"), ("author", "initials"), ("author", "userId")},     # ppt/authors.xml: современные примечания
}
CUSTOM_XML_PREFIX = "customxml/"

# Адреса ссылок. Пространства имён и типы связей (`Type`, `xmlns`) тоже начинаются с http://, но это
# машинные идентификаторы формата: изменить их значит сломать файл.
LINK_ATTRS = {"Target", "href", "url", "link", "address", "location"}

# Путь на компьютере автора (`C:\\Users\\ivanov\\Desktop\\Клиент\\`, `file:///...`): в нём имя пользователя и название клиента.
LOCAL_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|file:|\\\\|/Users/|/home/)")

# Значения длиннее этого — машинные данные (base64, пути, стили), а не текст документа.
MAX_ATTRIBUTE_LENGTH = 10_000

# Сколько чисел-сумм в книге (не дат, не лет, не номеров до 12) уже стоит подсказки «включите замену чисел».
MANY_AMOUNTS = 20


EMBEDDED_SUFFIXES = (".xlsx", ".docx", ".pptx")


# Глубина вложенности контейнеров (пакет в пакете, zip в zip): глубже файл не выдаётся, а блокируется.
MAX_NEST_DEPTH = 6


class NestedBlocked(Exception):
    """Вложенный контейнер нельзя обезличить целиком: файл целиком не выдаётся."""


def is_embedded_zip(name: str) -> bool:
    return name.lower().endswith(".zip")


def is_embedded_package(name: str) -> bool:
    """Книга, документ или презентация внутри файла: данные диаграммы, вставленный объект."""
    lowered = name.lower()
    return "/embeddings/" in lowered and lowered.endswith(EMBEDDED_SUFFIXES)


# Вложения, которые программа не разбирает: их содержимое уходит наружу как есть.
EMBEDDED_LABELS = {".xlsb": "встроенный .xlsb", ".xls": "встроенный .xls", ".xlsm": "встроенный .xlsm",
                   ".doc": "встроенный .doc", ".docm": "встроенный .docm", ".ppt": "встроенный .ppt",
                   ".pptm": "встроенный .pptm", ".pdf": "встроенный PDF", ".bin": "объект OLE (.bin)"}


def unprocessed_embeddings(names, depth: int = 0) -> dict[str, int]:
    """Сколько вложений каждого вида останется необезличенным: двоичные книги, объекты OLE, PDF."""
    counts: dict[str, int] = {}
    for name in names:
        lowered = name.lower()
        if "/embeddings/" not in lowered or lowered.endswith((".xml", ".rels")) or "/_rels/" in lowered:
            continue
        if (is_embedded_package(name) or is_embedded_zip(name)) and depth < MAX_NEST_DEPTH:
            continue
        label = EMBEDDED_LABELS.get(Path(lowered).suffix, f"вложение {Path(lowered).suffix or 'без расширения'}")
        counts[label] = counts.get(label, 0) + 1
    return counts


def embedded_warning(counts: dict[str, int]) -> str:
    listing = ", ".join(f"{label} ({n})" if n > 1 else label for label, n in counts.items())
    return (f"Вложенные объекты не обезличены: {listing}. Их содержимое осталось как есть и может содержать исходные "
            "данные: удалите эти объекты из файла или проверьте их вручную")


def removal_notice(removal: "EmbeddedRemoval") -> str:
    listing = ", ".join(f"{label} ({n})" if n > 1 else label for label, n in removal.labels.items())
    what = []
    if removal.charts:
        what.append(f"диаграммы ({removal.charts}) сохранили свой вид, но изменить или обновить их данные больше нельзя")
    if removal.ole:
        what.append(f"вставленные объекты ({removal.ole}) заменены их картинками и больше не редактируются")
    tail = "; ".join(what)
    return (f"Удалены вложения, которые программа не умеет обезличить: {listing}. В них были исходные данные. "
            + (tail[:1].upper() + tail[1:] + "." if tail else ""))


THUMBNAIL_REL = "/metadata/thumbnail"


def drop_thumbnails(parsed: dict, names: list[str]) -> set[str]:
    """Эскиз первой страницы (docProps/thumbnail.jpeg) — картинка титульного слайда или листа.

    Текст на картинке заменить нельзя, а название клиента на ней читается. Эскиз удаляется вместе со ссылкой
    на него и записью о типе: Office создаст новый при следующем сохранении. Возвращает имена удалённых частей.
    """
    dropped = {n for n in names if n.lower().startswith("docprops/thumbnail")}
    rels = parsed.get("_rels/.rels")
    if rels is not None:
        for rel in list(rels):
            target = (rel.get("Target") or "").lstrip("/").lower()
            if (rel.get("Type") or "").endswith(THUMBNAIL_REL):
                dropped.update(n for n in names if n.lower() == target)
            if (rel.get("Type") or "").endswith(THUMBNAIL_REL) or target in {d.lower() for d in dropped}:
                rels.remove(rel)
    types = parsed.get("[Content_Types].xml")
    if types is not None and dropped:
        parts = {"/" + n.lower() for n in dropped}
        for node in list(types):
            if (node.get("PartName") or "").lower() in parts:
                types.remove(node)
    return dropped


PRINTER_REL = "/printersettings"
RAW_TEXT_EXTS = (".htm", ".html", ".xhtml", ".txt", ".csv", ".tsv", ".json", ".md", ".svg")
# Части, где нет читаемого текста: шрифты и служебные двоичные данные известных видов.
BENIGN_RAW_EXTS = (".odttf", ".ttf", ".otf", ".fntdata", ".eot", ".wdp", ".gif", ".bmp", ".tif", ".tiff", ".bin")


def drop_printer_settings(parsed: dict, names: list[str]) -> set[str]:
    """Настройки принтера (`printerSettings*.bin`) хранят имя пользователя, компьютера и принтера в UTF-16.

    Читаемого текста в них для программы нет, а смысла для документа тоже: Office создаст их заново при печати.
    Часть удаляется вместе со ссылками на неё и записями о типе.
    """
    dropped = {n for n in names if "/printersettings" in "/" + n.lower()}
    for part, rels in parsed.items():
        if not part.lower().endswith(".rels"):
            continue
        owner = _rels_owner(part)
        for rel in list(rels):
            if (rel.get("Type") or "").lower().endswith(PRINTER_REL):
                target = _rel_target(owner, rel).lower()
                dropped.update(n for n in names if n.lower() == target)
                rels.remove(rel)
    types = parsed.get("[Content_Types].xml")
    if types is not None and dropped:
        parts = {"/" + n.lower() for n in dropped}
        left_ext = {Path(n.lower()).suffix.lstrip(".") for n in names if n not in dropped}
        for node in list(types):
            ext = (node.get("Extension") or "").lower()
            if (node.get("PartName") or "").lower() in parts or \
                    (_xml_name(node) == "Default" and ext == "bin" and ext not in left_ext):
                types.remove(node)
    return dropped


R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
R_ID = f"{{{R_NS}}}id"


@dataclass
class EmbeddedRemoval:
    """Что убрано из вложений: удалённые части, число диаграмм без книги данных и объектов OLE, ставших картинкой."""
    parts: set[str] = field(default_factory=set)
    charts: int = 0
    ole: int = 0
    labels: dict[str, int] = field(default_factory=dict)


def _unprocessable(name: str, depth: int) -> bool:
    """Вложение, которое программа не обезличивает: двоичная книга, объект OLE, PDF, слишком глубокая вложенность."""
    lowered = name.lower()
    if "/embeddings/" not in lowered or lowered.endswith((".xml", ".rels")) or "/_rels/" in lowered:
        return False
    return not ((is_embedded_package(name) or is_embedded_zip(name)) and depth < MAX_NEST_DEPTH)


def _rels_of(part: str) -> str:
    folder, base = posixpath.split(part)
    return posixpath.join(folder, "_rels", base + ".rels")


def _rel_target(part: str, rel) -> str:
    target = rel.get("Target") or ""
    if rel.get("TargetMode") == "External":
        return ""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def _ole_picture(frame):
    """Объект OLE на слайде превращается в свою же картинку-заместитель (её PowerPoint и так показывает).

    Имя, номер и служебные метки берутся у рамки объекта, изображение и размеры — у картинки из `mc:Fallback`.
    Без готовой картинки безопасной замены нет: такой объект остаётся, а о нём предупреждают.
    """
    picture = next((node for node in frame.iter() if _xml_name(node) == "pic"), None)
    frame_props = next((node for node in frame if _xml_name(node) == "nvGraphicFramePr"), None)
    if picture is None or frame_props is None:
        return None
    picture = copy.deepcopy(picture)
    picture_props = next((node for node in picture if _xml_name(node) == "nvPicPr"), None)
    if picture_props is None:
        return None
    for node in list(picture_props):
        own = next((x for x in frame_props if _xml_name(x) == _xml_name(node)), None)
        if own is not None and _xml_name(node) in {"cNvPr", "nvPr"}:
            picture_props.replace(node, copy.deepcopy(own))
    shape = next((node for node in picture if _xml_name(node) == "spPr"), None)
    frame_xfrm = next((node for node in frame if _xml_name(node) == "xfrm"), None)
    if shape is not None and frame_xfrm is not None and not any(_xml_name(x) == "xfrm" for x in shape):
        a_ns = etree.QName(frame_xfrm[0]).namespace if len(frame_xfrm) else "http://schemas.openxmlformats.org/drawingml/2006/main"
        xfrm = etree.Element(f"{{{a_ns}}}xfrm", dict(frame_xfrm.attrib))
        xfrm.extend(copy.deepcopy(x) for x in frame_xfrm)
        shape.insert(0, xfrm)
    return picture


def drop_embedded_payloads(parsed: dict, names: list[str], depth: int = 0) -> EmbeddedRemoval:
    """Убирает вложения, которые нельзя обезличить, но без которых документ открывается и выглядит так же.

    * Книга данных диаграммы (`c:externalData` → .xlsb/.xls): в самой диаграмме остаются последние значения
      (`c:numCache`/`c:strCache`), их текст обезличивается как обычно. Диаграмма рисуется, но править данные нельзя.
    * Объект OLE на слайде (`p:oleObj` → .bin) заменяется своей картинкой-заместителем из `mc:Fallback`.
    * Объект OLE в Word (`o:OLEObject`/`w:objectEmbed` в `w:object`) теряет вложение, картинка `v:imagedata` остаётся.

    Объект без картинки, объекты OLE Excel и вложения без ссылок на них не трогаются: о них по-прежнему предупреждение.
    Книги, документы и презентации внутри файла обезличиваются отдельно и здесь не удаляются.
    """
    removal = EmbeddedRemoval()
    actual = {n.lower(): n for n in names}
    released: set[str] = set()
    for part, root in list(parsed.items()):
        if part.lower().endswith(".rels") or part == "[Content_Types].xml":
            continue
        rels = parsed.get(_rels_of(part))
        if rels is None:
            continue
        targets = {rel.get("Id"): actual.get(_rel_target(part, rel).lower(), "") for rel in rels}

        def payload(node) -> str:
            target = targets.get(node.get(R_ID) or "", "")
            return target if target and _unprocessable(target, depth) else ""

        candidates: set[str] = set()
        for node in list(root.iter()):
            name = _xml_name(node)
            if name == "externalData" and "/charts/" in part.lower() and payload(node):
                candidates.add(node.get(R_ID))
                node.getparent().remove(node)
                removal.charts += 1
            elif name == "graphicFrame":
                data = next((x for x in node.iter() if _xml_name(x) == "graphicData"), None)
                objects = [x for x in node.iter() if _xml_name(x) == "oleObj"]
                if data is None or not (data.get("uri") or "").endswith("/ole") or not objects:
                    continue
                if not all(payload(x) for x in objects):
                    continue
                picture = _ole_picture(node)
                if picture is None:
                    continue
                node.getparent().replace(node, picture)
                candidates.update(x.get(R_ID) for x in objects)
                removal.ole += 1
            elif name in {"OLEObject", "objectEmbed"} and payload(node):
                holder = node.getparent()
                if holder is None or not any(_xml_name(x) in {"imagedata", "blip"} for x in holder.iter()):
                    continue
                candidates.add(node.get(R_ID))
                holder.remove(node)
                removal.ole += 1
        if not candidates:
            continue
        # Ссылка удаляется, только если на неё в части больше ничего не указывает.
        still_used = {value for node in root.iter() for value in node.attrib.values()}
        for rel in list(rels):
            rid = rel.get("Id")
            if rid in candidates and rid not in still_used:
                released.add(targets.get(rid, ""))
                rels.remove(rel)
    released.discard("")
    # Одно вложение может быть нужно и другой части (общий объект в макете и на слайде): тогда оно остаётся.
    referenced = {_rel_target(_rels_owner(part), rel).lower()
                  for part, rels in parsed.items() if part.lower().endswith(".rels") for rel in rels}
    removal.parts = {name for name in released if name.lower() not in referenced}
    for name in removal.parts:
        label = EMBEDDED_LABELS.get(Path(name.lower()).suffix, f"вложение {Path(name.lower()).suffix or 'без расширения'}")
        removal.labels[label] = removal.labels.get(label, 0) + 1
    types = parsed.get("[Content_Types].xml")
    if types is not None and removal.parts:
        gone = {"/" + n.lower() for n in removal.parts}
        gone_ext = {Path(n.lower()).suffix.lstrip(".") for n in removal.parts}
        left_ext = {Path(n.lower()).suffix.lstrip(".") for n in names if n not in removal.parts}
        for node in list(types):
            extension = (node.get("Extension") or "").lower()
            if (node.get("PartName") or "").lower() in gone or \
                    (_xml_name(node) == "Default" and extension in gone_ext and extension not in left_ext):
                types.remove(node)
    return removal


def _rels_owner(rels_part: str) -> str:
    """`ppt/slides/_rels/slide1.xml.rels` → `ppt/slides/slide1.xml`; `_rels/.rels` → корень пакета."""
    folder, base = posixpath.split(rels_part)
    return posixpath.join(posixpath.dirname(folder), base[:-len(".rels")])


def classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return "UNSUPPORTED" if refusals.disguise(path) else "TEXT"      # .txt, внутри которого .doc/.zip/.pdf
    if ext in OOXML_EXTENSIONS:
        return "OOXML"
    if ext in ODF_EXTENSIONS:
        return "ODF"
    if ext in MACRO_EXTENSIONS:
        return "MACRO_OFFICE"
    if ext in OLD_OFFICE:
        return "OLD_OFFICE"
    if ext == ".pdf":
        return "PDF"
    if ext in IMAGE_EXTENSIONS:
        return "IMAGE" if (sniff_image(path) or imagereplace.sniff_file(path)) else "UNSUPPORTED"
    return "UNSUPPORTED"


def _xml_name(element) -> str:
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _recover_vml(raw: bytes):
    """VML часто не является well-formed XML (<br>, одиночные теги): читается с восстановлением, иначе текст останется открытым."""
    try:
        root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False,
                                                       remove_comments=True, remove_pis=True))
    except etree.XMLSyntaxError:
        return None
    return root


def parse_part(name: str, raw: bytes):
    """Корень XML-части или None. VML читается с восстановлением, остальное строго."""
    try:
        return etree.fromstring(raw, _parser())
    except etree.XMLSyntaxError:
        return _recover_vml(raw) if name.lower().endswith(".vml") else None


def _parser():
    # huge_tree=False оставляет пределы libxml2 (глубина 256, текстовый узел 10 МБ): глубоко вложенная или раздутая часть
    # не разбирается (XMLSyntaxError), то есть файл не выдаётся, а не роняет обход рекурсией.
    return etree.XMLParser(resolve_entities=False, no_network=True, recover=False,
                           remove_blank_text=False, huge_tree=False,
                           remove_comments=True, remove_pis=True)     # <!-- -->: текст, который правила не читают


# ---------------------------------------------------------------------------
# Replacement plumbing
# ---------------------------------------------------------------------------

@dataclass
class TransformContext:
    """Всё, что нужно замене: хранилище токенов, найденные люди и решения пользователя.

    Токен выдаёт хранилище, а не файл: один и тот же объект в любом файле получает один и тот же токен.
    """
    vault: Vault
    settings: Settings
    detector: object
    overrides: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)          # группа отчёта → число замен
    tokens: dict[str, set[str]] = field(default_factory=dict)     # группа отчёта → уникальные токены
    replaced: dict[str, dict] = field(default_factory=dict)       # исходное → сведения для экрана «Что заменено»
    taken_paths: dict[str, str] = field(default_factory=dict)
    numeric: dict[str, int] = field(default_factory=dict)
    auto_hidden: set[str] = field(default_factory=set)            # скрыто строгим режимом, а не человеком
    file_tokens: set[str] = field(default_factory=set)            # токены текущего файла (сбрасывается на каждый файл)

    def apply_overrides(self, findings: list[Finding]) -> list[Finding]:
        """Решения человека: `hide` заменяет сомнительное, `keep` оставляет найденное как есть."""
        for finding in findings:
            # Однофамильцы («Ilin Sergey» при двух Ильиных Сергеях, «Иванов И.» при двух Ивановых): кто из двоих, не
            # угадать, но оставлять имя открытым нельзя. Оно заменяется отдельной меткой, а возврат подставит написание
            # из хранилища дословно, поэтому ошибиться в человеке нельзя.
            if (finding.category == "PERSON" and finding.decision == Decision.REVIEW and finding.candidates
                    and "опечат" not in finding.reason):
                finding.decision = Decision.AUTO
                finding.person_id = None
                finding.key = fold(finding.original)
                finding.reason = "Совпадает с несколькими людьми: заменено отдельной меткой"
        if not self.overrides:
            return findings
        for finding in findings:
            choice = self.overrides.get(fold(finding.original))
            if choice == "keep":
                finding.decision = Decision.REVIEW
                finding.reason = "Оставлено по решению пользователя"
            elif choice == "hide":
                finding.decision = Decision.AUTO
                if finding.category == "POSSIBLE_PERSON":
                    finding.category = "PERSON"
                finding.confidence = 1.0
                finding.reason = ("Скрыто: включено «Скрывать и сомнительные слова»" if fold(finding.original) in self.auto_hidden
                                  else "Скрыто по решению пользователя")
        return findings

    def token_for(self, finding: Finding) -> str:
        kind = kind_of(finding.category)
        key = finding.key
        person_id = finding.person_id
        if kind.code == "PERSON" and person_id:
            resolver = getattr(self.detector, "resolve_person", None)
            key = (resolver(person_id) if resolver else person_id) or person_id
        if kind.code == "SECRET":
            secret = not self.settings.retain_secrets_for_restore
            token = self.vault.token_for("SECRET", key, None if secret else finding.original, secret=secret)
        else:
            token = self.vault.token_for(kind.code, key or fold(finding.original), finding.original)
        self.counts[kind.group] = self.counts.get(kind.group, 0) + 1
        self.tokens.setdefault(kind.group, set()).add(base_of(token) or token)
        self.file_tokens.add(base_of(token) or token)
        if kind.code != "SECRET":
            entry = self.replaced.setdefault(fold(finding.original), {
                "original": finding.original, "token": token, "kind": kind.code, "group": kind.group,
                "count": 0, "reason": finding.reason})
            entry["count"] += 1
        return token


def replace_findings(text: str, findings: list[Finding], ctx: TransformContext, guard: bool = True) -> str:
    accepted = sorted((x for x in findings if x.decision == Decision.AUTO), key=lambda x: x.start)
    # Номера выдаются слева направо, чтобы человек №1 был первым в документе, а замена идёт
    # справа налево, чтобы не сбить ещё не использованные позиции.
    tokens = {id(f): ctx.token_for(f) for f in accepted}
    # Склейка одним проходом. Пересборка строки на каждой находке давала квадратичный рост:
    # файл в несколько мегабайт с десятками тысяч замен обрабатывался бы минутами.
    pieces: list[str] = []
    cursor = 0
    for f in accepted:
        if f.start < cursor:
            continue
        pieces.append(text[cursor:f.start])
        pieces.append(guard_token(text, f.start, f.end, tokens[id(f)]) if guard else tokens[id(f)])
        cursor = f.end
    pieces.append(text[cursor:])
    return "".join(pieces)


ZWSP = "\u200b"


def _glues(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


def guard_token(text: str, start: int, end: int, token: str) -> str:
    """Токен не должен слипаться с соседними символами: `Name5` + `1` читалось бы как `Name51`.

    Между ними ставится невидимый разделитель; при восстановлении он удаляется вместе с токеном.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    if before in "LCR" and text[start - 2:start - 1] == "&":
        before = ""            # код колонтитула Excel (&R, &L, &C), а не буква слова
    if before and _glues(before):
        token = ZWSP + token
    if after and _glues(after):
        token = token + ZWSP
    return token


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def looks_binary(data: bytes) -> bool:
    """Случайные байты под именем .txt: управляющих символов в них в десятки раз больше, чем в любом тексте."""
    head = data[:65536]
    if not head:
        return False
    text = head.decode(sniff_encoding(head), errors="replace")
    bad = sum(1 for ch in text if (ch < " " and ch not in "\t\n\r\f\v\x1b") or ch == "\x7f" or ch == "\ufffd")
    return bad > max(4, len(text) * .02)


BINARY_AS_TEXT = "Файл не похож на текст: внутри двоичные данные. Проверьте расширение файла."


def scan_text_file(path: Path, rel: str, detector) -> FileResult:
    try:
        raw = path.read_bytes()
        if looks_binary(raw):
            return FileResult(rel, "TEXT", FileStatus.BLOCKED, warnings=[BINARY_AS_TEXT])
        text = decode_text(raw)
        detector.harvest(text, rel)
        findings = detector.scan(text, rel, "text")
        status = FileStatus.REVIEW_REQUIRED if any(f.decision != Decision.AUTO for f in findings) else FileStatus.CLEAN
        return FileResult(rel, "TEXT", status, findings,
                          integrity={"sha256": sha256_bytes(raw), "bytes": len(raw), "lines": text.count("\n") + 1})
    except Exception as exc:
        return FileResult(rel, "TEXT", FileStatus.BLOCKED, warnings=[f"Ошибка чтения: {type(exc).__name__}"])


_KEEP_ESCAPED = {"amp", "lt", "gt", "quot", "apos"}
_NUM_REF = re.compile(r"&#(?:[xX]([0-9A-Fa-f]{1,6})|([0-9]{1,7}));")
_NAMED_REF = re.compile(r"&([A-Za-z][A-Za-z0-9]{1,31});")
_JSON_U = re.compile(r"\\u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})")


_ENTITY_ANY = re.compile(r"&#(?:[xX]([0-9A-Fa-f]{1,6})|([0-9]{1,7}));|&([A-Za-z][A-Za-z0-9]{1,31});")


def _decode_escapes(text: str, suffix: str) -> tuple[str, bool]:
    decoded, changed, _ = _decode_escapes_mapped(text, suffix)
    return decoded, changed


def _decode_escapes_mapped(text: str, suffix: str) -> tuple[str, bool, "array | None"]:
    """Записи вида &#1057; и \\u0421 прячут буквы от поиска. Для поиска они читаются как сами символы.

    Структурные знаки (& < > " ' и управляющие) остаются записанными, чтобы файл не сломался. Третий результат: для каждого
    знака прочитанного текста начало его записи в исходном (и общая длина в конце). По нему находки возвращаются в исходный
    текст, а файл вне найденных мест остаётся побайтно прежним (`&#x2D;` не превращается в `-`).
    """
    import html.entities
    if suffix in (".html", ".htm", ".xml"):
        if "&" not in text:
            return text, False, None
        pieces: list[str] = []
        starts = array("I")
        cursor = 0
        for m in _ENTITY_ANY.finditer(text):
            if m.group(3) is not None:
                if m.group(3) in _KEEP_ESCAPED or m.group(3) not in html.entities.name2codepoint:
                    continue
                char = chr(html.entities.name2codepoint[m.group(3)])
            else:
                code = int(m.group(1), 16) if m.group(1) else int(m.group(2))
                if code < 128 and chr(code) in "<>&\"'" or code < 32 or code > 0x10FFFF or 0xD800 <= code < 0xE000:
                    continue
                char = chr(code)
            pieces.append(text[cursor:m.start()])
            starts.extend(range(cursor, m.start()))
            pieces.append(char)
            starts.append(m.start())
            cursor = m.end()
        if not pieces:
            return text, False, None
        pieces.append(text[cursor:])
        starts.extend(range(cursor, len(text) + 1))
        return "".join(pieces), True, starts
    if suffix == ".json":
        def esc(m):
            if m.group(3):
                code = int(m.group(3), 16)
                if code < 128 and chr(code) in '"\\' or code < 32 or 0xD800 <= code < 0xE000:
                    return m.group(0)
                return chr(code)
            hi, lo = int(m.group(1), 16), int(m.group(2), 16)
            return chr(0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00))
        pieces = []
        starts = array("I")
        cursor = 0
        for m in _JSON_U.finditer(text):
            char = esc(m)
            if char == m.group(0):
                continue
            pieces.append(text[cursor:m.start()])
            starts.extend(range(cursor, m.start()))
            pieces.append(char)
            starts.append(m.start())
            cursor = m.end()
        if not pieces:
            return text, False, None
        pieces.append(text[cursor:])
        starts.extend(range(cursor, len(text) + 1))
        return "".join(pieces), True, starts
    return text, False, None


def _to_source_offsets(findings: list[Finding], raw: str, starts) -> list[Finding]:
    """Находки, найденные в прочитанном тексте, пересчитываются в исходный: значение берётся дословно (с записями &#...;),
    поэтому возврат даёт ровно то, что было в файле."""
    for f in findings:
        a, b = int(starts[f.start]), int(starts[f.end])
        if (a, b) == (f.start, f.end) and raw[a:b] == f.original:
            continue
        if not f.key:
            f.key = fold(f.original)
        f.start, f.end, f.original = a, b, raw[a:b]
    return findings


def transform_text_file(src: Path, dst: Path, rel: str, detector, ctx: TransformContext) -> FileResult:
    raw = src.read_bytes()
    if looks_binary(raw):
        return FileResult(rel, "TEXT", FileStatus.BLOCKED, warnings=[BINARY_AS_TEXT])
    enc = sniff_encoding(raw)
    text = raw.decode(enc, errors="strict")
    source_text = text
    images_whole, image_links = 0, []
    if imagereplace.whole_image(ctx.settings) and src.suffix.lower() in imagereplace.TEXT_IMAGE_SUFFIXES:
        try:
            source_text, images_whole = imagereplace.replace_data_uris(source_text, ctx)
        except imagereplace.ImageStoreFull as exc:
            return FileResult(rel, "TEXT", FileStatus.BLOCKED, warnings=[str(exc)])
        image_links = imagereplace.local_links(imagereplace.linked_images(source_text))
        if image_links:
            return FileResult(rel, "TEXT", FileStatus.BLOCKED, warnings=[imagereplace.linked_warning(image_links)])
        text = source_text
    text, decoded, starts = _decode_escapes_mapped(text, src.suffix.lower())
    structure = Structure(text, src.suffix.lower())
    seen = structure.masked           # структурные кавычки CSV/JSON заменены пробелами: смещения те же
    if structure.suffix in CSV_SUFFIXES:
        colctx.learn_grid(structure.grid(), detector)
    elif structure.suffix in (".md", ".markdown", ".txt", ".log"):
        colctx.learn_markdown(text, detector)
        colctx.learn_tabs(text, detector)
    elif structure.suffix in (".html", ".htm", ".xhtml"):
        colctx.learn_html(text, detector)
    elif structure.suffix in XML_SUFFIXES:
        colctx.learn_xml_names(text, detector)
        colctx.learn_xml_rows(text, detector)
    detector.harvest(seen, rel)
    scanned = structure.clip(structure.column_filter(detector.scan(seen, rel, "text")))
    scanned += structure.header_findings(scanned, rel)
    scanned.sort(key=lambda x: x.start)
    if starts is not None:
        scanned = _to_source_offsets(scanned, source_text, starts)
    findings = ctx.apply_overrides(scanned)
    if images_whole:
        # Base64 заглушки не текст: случайная подстрока в ней могла бы сойти за секрет и испортить картинку.
        spans = imagereplace.data_uri_spans(source_text)
        findings = [f for f in findings if not any(f.start < e and f.end > b for b, e in spans)]
    transformed = replace_findings(source_text, findings, ctx)
    try:
        payload = transformed.encode(enc)
    except UnicodeEncodeError:
        payload, enc = transformed.encode("utf-8"), "utf-8"
    atomic_write(dst, payload)
    # Остатки ищутся в видимом тексте: слово «class» или «csv» в адресе ссылки остатком имени не считается.
    visible_source = _decode_escapes(transformed, src.suffix.lower())[0] if decoded else transformed
    if images_whole:
        visible_source = imagereplace.strip_data_uri_payloads(visible_source)
    visible = Structure(visible_source, src.suffix.lower()).masked if src.suffix.lower() in HTML_SUFFIXES + XML_SUFFIXES else visible_source
    critical = _residuals(detector, visible, findings)
    warnings = ["После обработки в файле остались данные, похожие на исходные"] if critical else []
    status = FileStatus.CLEAN if not critical else FileStatus.REVIEW_REQUIRED
    notices = ["Записи вида &#…; и \\u… прочитаны как обычные символы, чтобы найти спрятанные в них значения. Вне найденных значений файл не менялся."] if decoded else []
    if images_whole:
        notices.append(imagereplace.notice_replaced(images_whole))
    return FileResult(rel, "TEXT", status, findings, warnings, str(dst),
                      {"original_lines": source_text.count("\n") + 1, "output_lines": transformed.count("\n") + 1, "open_ok": True}, notices=notices)


GLUED_EMAIL_TOKEN = re.compile(r"email\d{1,7}(?:_\d{1,6})?@example\.com", re.I)


# Нарисованная метка почты («email1@example.com») в усиленных проходах читается с ошибкой («emailt@»): это не остаток данных.
MISREAD_EMAIL_TOKEN = re.compile(r"(?i)^[a-z]{3,6}\w{0,2}@example\.(?:com|org)$")
# Распознавание портит нарисованную метку почты («Phone1_2lemail@example.com», «email3@examplecom», «email1@exampie.com», «@example»).
GARBLED_EMAIL_TOKEN = re.compile(r"(?i)(?:^|[^a-z0-9])[a-z0-9_|!]{0,12}?(?:[e]mai[l1i]|ernai[l1i])\d{0,7}(?:_\d{1,6})?@examp[l1i]e|^@examp[l1i]e\b")


def _garbled_drawn_token(value: str, drawn) -> bool:
    """Остаток похож на нарисованную нами метку почты, прочитанную распознаванием с ошибками, а не на настоящий адрес.

    Сравнение идёт с множеством меток, которые мы действительно рисовали (`email3@example.com`): настоящий адрес на
    example.com (`john.doe@example.com`) от метки отличается именем, а не знаками, испорченными распознаванием.
    """
    from difflib import SequenceMatcher
    v = value.strip().strip(".,;:|!()[]'\"").lower()
    if not v or len(v) > 40 or "@" not in v:
        return False
    local, _, domain = v.rpartition("@")
    domain_ratio = max(SequenceMatcher(None, domain, d).ratio() for d in ("example.com", "example.org"))
    if domain_ratio < .605:
        return False
    exact = domain in ("example.com", "example.org")
    if not local:
        return not exact
    for token in drawn:
        tl, _, _ = token.lower().partition("@")
        number = re.search(r"\d+$", tl)
        ratio = SequenceMatcher(None, local, tl).ratio()
        if exact:
            # Настоящий адрес на example.com: имя не похоже на метку. Испорченная метка хранит номер и хвост «il<номер>».
            if number and (re.search(r"il" + number.group(0) + r"$", local) or (number.group(0) in local and ratio >= .45)):
                return True
        elif ratio >= .7 or (number and number.group(0) in local and ratio >= .45):
            return True
    return False


def _inside_spans(text: str, start: int, end: int, spans) -> bool:
    """Все непробельные знаки отрезка лежат внутри заданных отрезков."""
    return all(c.isspace() or any(a <= i < b for a, b in spans) for i, c in enumerate(text[start:end], start))


# Подпись поля формы («Phone:», «Представитель:», «Расчётный»): слово с большой буквы без цифр и знаков. Значения в PDF стёрты,
# а наши метки лежат в конце потока страницы, поэтому правило «password =» берёт следующую подпись за значение.
_REAL_IP = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|(?:[0-9A-Fa-f]{1,4}:){3,}")
_PLAIN_LABEL_WORD = re.compile(r"[^\d_!@#$%^&*=+~/\\]{3,40}")
_FORM_LABEL = re.compile(r"[A-ZА-ЯЁ][^\W\d_]{2,}:?")


# Названия полей реквизитов: «ИНН» или «СНИЛС» как подпись остатком не считаются (метка нашлась как сокращение организации).
_PUBLIC_LABELS = frozenset({"инн", "кпп", "огрн", "огрнип", "снилс", "бик", "окпо", "оквэд", "окато", "октмо", "фио", "ssn", "iban",
                            "bic", "swift", "dob", "tel", "fax", "inn", "kpp", "ogrn", "snils"})
_LABEL_LOOKALIKE = str.maketrans("ABCEHKMOPTXYaceopxyi", "АВСЕНКМОРТХУасеорхуі")


def _public_label(value: str) -> bool:
    return value.strip(" :.,;/|").translate(_LABEL_LOOKALIKE).lower() in _PUBLIC_LABELS


# Значок открытого замка в логотипе «OPEN ACCESS» распознавание читает как «@»: «@ACCESS» не логин, а подпись логотипа журнала.
_OCR_LOGO_WORDS = frozenset({"@access"})


def _label_word_like(value: str, vocab) -> bool:
    """Значение — подпись поля формы, прочитанная с мелкой порчей («резервныйр2», «Свидетел+», «розервный(р2»):
    слова из букв, похожего на слово документа (vocab), и хвост не длиннее трёх знаков."""
    from difflib import SequenceMatcher
    v = value.strip(" :.,;|()[]'\"+-/")
    m = re.match(r"[^\W\d_]+", v)
    if not m or len(m.group(0)) < 5 or len(v) - len(m.group(0)) > 3:
        return False
    core = m.group(0).lower()
    return any(abs(len(w) - len(core)) <= 2 and SequenceMatcher(None, core, w).ratio() >= .85 for w in vocab)


def _alien_example_email(value: str, originals) -> bool:
    """Адрес с испорченным «example.com»/«example.org» и именем, не похожим ни на одно исходное: так распознавание читает
    нашу метку почты. Точный example.com сюда не входит."""
    from difflib import SequenceMatcher
    v = value.strip().strip(".,;:|!()[]'\"").lower()
    local, _, domain = v.rpartition("@")
    if not local or domain in ("example.com", "example.org") or len(v) > 40:
        return False
    if max(SequenceMatcher(None, domain, d).ratio() for d in ("example.com", "example.org")) < .65:
        return False
    for o in originals:
        ol = o.lower().rpartition("@")[0] if "@" in o else ""
        if ol and SequenceMatcher(None, local, ol).ratio() >= .6:
            return False
    return True


def _only_own_labels(text: str) -> bool:
    """Строка целиком состоит из наших меток, склеенных без пробела («Company51email4@example.com»): остатком не является.
    Любой символ вне меток (приклеенное исходное слово) делает строку остатком, как и раньше."""
    rest = GLUED_EMAIL_TOKEN.sub("", text.strip())
    rest = INNER_TOKEN_RE.sub("", rest)
    return rest == "" and text.strip() != ""


def _residuals(detector, output_text: str, findings: list[Finding], ocr_text: bool = False, drawn=(), masked_spans=(), vocab=()) -> list[str]:
    """Что пережило замену: исходное значение всё ещё читается как отдельное слово или шаблон снова срабатывает.

    Проверяются уникальные значения, а не каждая находка: одно и то же ФИО встречается в
    документе сотни раз, и поиск по всему тексту на каждое вхождение — квадратичная работа.
    Короткое значение внутри другого слова («Ким» в «Кимберли») остатком не считается.
    """
    unique = {f.original for f in findings
              if f.decision == Decision.AUTO and f.original and f.category not in {"TERM", "FILE", "META"}}
    if ocr_text:
        # «@example», закрашенное в прошлом проходе как адрес, — искажённая метка, а не значение: его чтение остатком не считается.
        # Значение из одного-двух знаков («SS», «no») шум распознавания читает где угодно: личности оно не раскрывает.
        unique = {o for o in unique if len(o.strip()) > 2 and not _public_label(o) and not (GLUED_EMAIL_TOKEN.search(o) or MISREAD_EMAIL_TOKEN.search(o) or GARBLED_EMAIL_TOKEN.search(o)
                                            or _garbled_drawn_token(o, drawn))}
    leftovers = []
    # Быстрый отсев: значение может стоять отдельным словом, только если его первое слово есть в выходном тексте целиком.
    # Без отсева поиск каждого значения по всему тексту давал квадратичное время на больших журналах.
    words = set(re.findall(r"\w+", output_text))
    own_spans: list[tuple[int, int]] | None = None        # занятые нашими метками отрезки (считаются при первом совпадении)
    for value in unique:
        head = re.match(r"\w+", value)
        if head and (head.end() == len(value) or not (value[head.end()].isalnum() or value[head.end()] == "_")) \
                and head.group(0) not in words:
            continue
        start = output_text.find(value)
        while start != -1:
            before = output_text[start - 1] if start else " "
            after = output_text[start + len(value)] if start + len(value) < len(output_text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                if own_spans is None:
                    own_spans = [m.span() for rx in (TOKEN_RE, EMAIL_TOKEN_RE) for m in rx.finditer(output_text)]
                # Значение «com» читается в нашей метке «email1@example.com»: это часть метки, а не остаток исходного текста.
                if not any(a <= start and start + len(value) <= b for a, b in own_spans):
                    leftovers.append(value)
                    break
            start = output_text.find(value, start + 1)
    # Распознавание склеивает соседнее слово с нарисованной меткой («0170email2@example.com»): это не остаток.
    # Метка, которую поставили мы сами («password: Secret2», «login: Name1»), тоже совпадает с шаблоном, но остатком не является.
    # masked_spans — отрезки текста, занятые словами на нарисованных нами метках: искажения метки остатком не считаются,
    # а прежнее значение, оставшееся читаемым, находится по тексту выше.
    # Закрашенное «значение», само похожее на искажённую метку («@example», найденное в прошлом проходе), настоящим значением не считается.
    originals = [o.lower() for o in unique if len(o) >= 4]
    leftovers.extend(f.original for f in detector.verify(output_text)
                     if not TOKEN_RE.fullmatch(f.original.strip())
                     and not _only_own_labels(f.original)
                     and not (f.category == "SECRET" and _FORM_LABEL.fullmatch(f.original.strip(" +-|/.,;"))
                              and not any(f.original.strip(" :").lower() in o or o in f.original.lower() for o in originals))
                     and not (ocr_text and f.category == "SECRET" and vocab and _label_word_like(f.original, vocab)
                              and not any(f.original.strip(" :+-|/").lower() in o or o in f.original.lower() for o in originals))
                     and not (ocr_text and f.category == "SECRET" and _PLAIN_LABEL_WORD.fullmatch(f.original.strip(" :.,;|+-"))
                              and not any(f.original.strip(" :.,;|+-").lower() in o or o in f.original.lower() for o in originals))
                     and not (ocr_text and f.category == "USERNAME" and f.original.strip(" :.,;|").lower() in _OCR_LOGO_WORDS
                              and not any(o in f.original.lower() or f.original.strip(" :.,;|@").lower() in o for o in originals))
                     and not (ocr_text and f.category == "IP_ADDRESS" and not _REAL_IP.search(f.original))
                     and not (ocr_text and f.category == "EMAIL" and _alien_example_email(f.original, [x for x in unique if "@" in x]))
                     and not (masked_spans and not any(o in f.original.lower() for o in originals) and _inside_spans(output_text, f.start, f.end, masked_spans))
                     and not (ocr_text and not any(o in f.original.lower() for o in originals)
                              and (GLUED_EMAIL_TOKEN.search(f.original) or MISREAD_EMAIL_TOKEN.search(f.original)
                                   or GARBLED_EMAIL_TOKEN.search(f.original) or _garbled_drawn_token(f.original, drawn))))
    return leftovers


_PLATE_LOOKALIKE = str.maketrans("ABEKMHOPCTYXaeopcyx", "АВЕКМНОРСТУХаеорсух")
_PLATE_SHAPE = re.compile(r"(?<![\w])[A-Za-zА-Яа-я]\d{3}[A-Za-zА-Яа-я]{2}(?![\w])")
_DIGIT_LOOKALIKE = str.maketrans("OoIl|S", "001115")


def _lookalike_text(text: str) -> str:
    """Тот же текст (длина и позиции сохраняются), где знаки, которые распознавание путает, приведены к виду, понятному правилам:
    латинские буквы номера автомобиля становятся кириллическими, «O», «l», «/» внутри числа читаются как цифры."""
    text = _PLATE_SHAPE.sub(lambda m: m.group(0).translate(_PLATE_LOOKALIKE), text)

    def fold(m):
        token = m.group(0)
        digits = sum(c.isdigit() for c in token)
        if digits < 4:
            return token
        if token.count("/") == 1 and token.count(".") >= 2:
            token = token.replace("/", "7")
        mapped = token.translate(_DIGIT_LOOKALIKE)
        return mapped if sum(c.isdigit() for c in mapped) >= .85 * len(re.sub(r"[.\-/]", "", mapped)) else token
    return re.sub(r"\S+", fold, text)


def _verify_hits(detector, chars: PageChars, rel: str, taken: set[int], skip=None) -> list[tuple[Finding, set[int]]]:
    """То, что находит detector.verify (правила без привязки к соседним словам) в трёх видах текста страницы, с номерами символов.

    Закраска должна быть не слабее проверки: дата на отдельной строке после «born» или паспорт без метки находятся только
    проверкой, и без этого повторные проходы их не закрывали.
    """
    out: list[tuple[Finding, set[int]]] = []
    seen = set(taken)
    base = chars.view("lines")
    for mode in PDF_VIEWS:
        view = base if mode == "lines" else chars.view(mode)
        if mode != "lines" and view.text == base.text:
            continue
        for f in detector.verify(view.text):
            if f.decision != Decision.AUTO or TOKEN_RE.fullmatch(f.original.strip()) or (skip and skip(f.original)):
                continue
            ids = set(view.ids(f.start, f.end))
            if not ids or ids <= seen:
                continue
            out.append((f, ids))
            seen |= ids
        # Искажения распознавания («O148PЕ 77», «20.10.19/5»): правила читают приведённый текст, закрашиваются исходные символы.
        mapped = _lookalike_text(view.text)
        if mapped == view.text:
            continue
        for f in detector.verify(mapped):
            if f.decision != Decision.AUTO or TOKEN_RE.fullmatch(f.original.strip()):
                continue
            if mapped[f.start:f.end] == view.text[f.start:f.end]:
                continue                        # без подмен это уже находка обычного чтения
            ids = set(view.ids(f.start, f.end))
            if not ids or ids <= seen:
                continue
            out.append((replace(f, original=view.text[f.start:f.end]), ids))
            seen |= ids
    return out


# ---------------------------------------------------------------------------
# OOXML
# ---------------------------------------------------------------------------

def _zip_snapshot(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        binary: dict[str, str] = {}
        formulas = 0
        for name in names:
            lowered = name.lower()
            if lowered.endswith(".xml"):
                formulas += len(re.findall(br"<(?:[A-Za-z0-9_]+:)?f(?:\s|>)", z.read(name)))
            elif not lowered.endswith(".rels") and not is_embedded_package(name) and not is_embedded_zip(name):
                binary[name] = hashlib.sha256(z.read(name)).hexdigest()
        return {
            "entries": len(names), "names": sorted(names), "binary_hashes": binary,
            "uncompressed_bytes": sum(i.file_size for i in z.infolist()),
            "sheets": sum(n.startswith("xl/worksheets/sheet") and n.endswith(".xml") for n in names),
            "slides": sum(n.startswith("ppt/slides/slide") and n.endswith(".xml") for n in names),
            "formulas": formulas,
            "tables": sum("/tables/" in n and n.endswith(".xml") for n in names),
            "charts": sum("/charts/" in n and n.endswith(".xml") for n in names),
            "comments": sum("comment" in n.lower() and n.endswith(".xml") for n in names),
            "media": sum("/media/" in n for n in names),
            "embeddings": sum("/embeddings/" in n and not is_embedded_package(n) for n in names),
            "packages": sum(is_embedded_package(n) for n in names),
            "macros": any(n.lower().endswith("vbaproject.bin") for n in names),
            "signatures": any("_xmlsignatures/" in n.lower() for n in names),
        }


@dataclass(slots=True)
class Segment:
    """One contribution to a paragraph's text: either an editable run or a structural break."""
    element: object
    text: str
    writable: bool


def _cell_value_is_text(node) -> bool:
    """`<v>` holds a shared-string index for normal cells but literal text for formula results.

    Rewriting the index would corrupt the workbook; leaving the literal alone would leak the
    name a formula produced, which is exactly the cached value Excel displays.
    """
    parent = node.getparent()
    if parent is None:
        return False
    if _xml_name(parent) == "c":
        if parent.get("t") in ("str", "inlineStr"):
            return True
        # Телефон, карта и СНИЛС, записанные в ячейку числом, — такие же данные, как и текстом.
        return parent.get("t") in (None, "n") and _sensitive_number(node.text or "")
    return _xml_name(parent) in ("pt", "tx", "v", "cell")


def _sensitive_number(text: str) -> bool:
    from .detectors import valid_luhn, valid_snils
    digits = text.strip()
    if not digits.isdigit() or digits.startswith("0"):
        return False
    if len(digits) == 11:
        return (digits[0] in "78" and digits[1] == "9") or valid_snils(digits)
    return 13 <= len(digits) <= 19 and valid_luhn(digits)


NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


NUM_MARK = "⁠"                      # невидимая метка «ячейка была числом»: по ней возврат делает ячейку снова числом
_NUM_ATTR = "{urn:enigma:anon}num"


def _plain_integer(text: str) -> str | None:
    """«7.70708389312E11» → «770708389312»; не целое или отрицательное → None."""
    from decimal import Decimal, InvalidOperation
    try:
        value = Decimal((text or "").strip())
    except InvalidOperation:
        return None
    if not value.is_finite() or value != value.to_integral_value() or value < 0:
        return None
    return str(int(value))


def _column_number(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + ord(ch) - 64
    return number


def force_numeric_ids(parsed: dict, detector) -> int:
    """Числа в ячейках под заголовком «ИНН/Паспорт/Карта…» и серийные даты под «Дата рождения» становятся текстом для детектора.

    Ячейка помечается (`_NUM_ATTR`), значение запоминается как известное; метку снимает `_text_into_numeric_cells`.
    """
    styles = parsed.get("xl/styles.xml")
    date_styles = numeric.date_style_indexes(styles) if styles is not None else set()
    done = 0
    for name, root in parsed.items():
        if not _is_worksheet(name):
            continue
        heads: dict[str, tuple[int, str, object]] = {}
        for cells in _sheet_cells({name: root, "xl/sharedStrings.xml": parsed.get("xl/sharedStrings.xml")}
                                  if parsed.get("xl/sharedStrings.xml") is not None else {name: root}):
            for column, row, text in cells:
                if row > 15 or len(text.split()) > 6 or column in heads:
                    continue
                for pattern, category, size in ID_HEADERS:
                    if pattern.search(text):
                        heads[column] = (row, category, size)
                        break
                else:
                    found = colctx.classify_header(text)
                    if found and found[0] == "BIRTH_DATE":
                        heads[column] = (row, "BIRTH_DATE", None)
        labels: dict[tuple[int, int], tuple[str, tuple[int, int]]] = {}      # подпись слева в той же строке: «INN | 6547100017»
        for cells in _sheet_cells({name: root, "xl/sharedStrings.xml": parsed.get("xl/sharedStrings.xml")}
                                  if parsed.get("xl/sharedStrings.xml") is not None else {name: root}):
            for column, row, text in cells:
                if len(text.split()) <= 3:
                    for pattern, category, size in ID_HEADERS:
                        if pattern.search(text):
                            labels[(_column_number(column), row)] = (category, size)
                            break
        if not heads and not labels:
            continue
        for cell in list(root.iter()):
            if _xml_name(cell) != "c" or cell.get("t") not in (None, "n") or any(_xml_name(c) == "f" for c in cell):
                continue
            match = CELL_REF.match(cell.get("r", ""))
            v = next((c for c in cell if _xml_name(c) == "v"), None)
            head = heads.get(match.group(1)) if match else None
            if head is not None and int(match.group(2)) <= head[0]:
                head = None
            if head is None and match:
                label = labels.get((_column_number(match.group(1)) - 1, int(match.group(2))))
                head = (0, label[0], label[1]) if label else None
            if head is None or v is None:
                continue
            digits = _plain_integer(v.text or "")
            if digits is None:
                continue
            if head[1] == "BIRTH_DATE":
                if not (cell.get("s", "").isdigit() and int(cell.get("s")) in date_styles) or not 1 <= int(digits) <= 2958465:
                    continue
                detector.known_values.setdefault(colctx._norm(digits), ("BIRTH_DATE", digits))
            else:
                if not head[2][0] <= len(digits) <= head[2][1]:
                    continue
                detector.known_ids.setdefault(digits, head[1])
            v.text = digits
            cell.set("t", "str")
            cell.set(_NUM_ATTR, "1")
            done += 1
    return done


def _text_into_numeric_cells(root) -> None:
    """Число в ячейке заменено меткой: ячейка становится текстовой, иначе Excel сочтёт файл повреждённым."""
    for cell in list(root.iter()):           # дерево меняется по ходу: обход по копии списка
        if _xml_name(cell) != "c":
            continue
        marked = cell.attrib.pop(_NUM_ATTR, None) is not None
        if not marked and cell.get("t") not in (None, "n"):
            continue
        v = next((c for c in cell if _xml_name(c) == "v"), None)
        if v is None or v.text is None:
            continue
        if NUMERIC_TEXT.match(v.text.strip()):
            if marked:                       # детектор не тронул значение: ячейка остаётся числом
                del cell.attrib["t"]
            continue
        text = v.text
        cell.remove(v)
        cell.set("t", "inlineStr")
        ns = etree.QName(cell).namespace
        inline = etree.SubElement(cell, f"{{{ns}}}is")
        etree.SubElement(inline, f"{{{ns}}}t").text = text + NUM_MARK


_SAFE_FORMULA = re.compile(r"^[\s\d.,;:+\-*/^&%()<>=$A-Za-z_]*$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9.]*")
_SKIP_SAFE_FORMULAS: "contextvars.ContextVar[bool]" = contextvars.ContextVar("skip_safe_formulas", default=False)


def _safe_formula(text: str | None) -> bool:
    """Формула без строк, кавычек, имён листов и именованных диапазонов: имена и организации в ней не бывают."""
    if not text or not _SAFE_FORMULA.match(text):
        return False
    for m in _IDENT.finditer(text):
        word = m.group(0)
        nxt = text[m.end():m.end() + 1]
        if nxt == "(" or re.fullmatch(r"\$?[A-Za-z]{1,3}\$?\d+", word) or re.fullmatch(r"\$?[A-Za-z]{1,3}", word):
            continue
        return False
    return True


def _is_text_node(node, part: str) -> bool:
    name = _xml_name(node)
    if name == "f" and _SKIP_SAFE_FORMULAS.get() and _safe_formula(node.text):
        return False
    if part.lower().startswith(CUSTOM_XML_PREFIX):
        return True
    if name in TEXT_TAGS:
        return True
    if part.lower().endswith(".vml"):
        return True                  # надпись в текстовом поле VML: <div>, <font> и т. п.
    if name == "v":
        return "/charts/" in part or _cell_value_is_text(node)
    return False


def _groups(root, part: str) -> list[tuple[str, list[Segment]]]:
    grouped: dict[int, tuple[object, list[Segment]]] = {}
    for node in root.iter():
        name = _xml_name(node)
        separator = SEPARATOR_TAGS.get(name)
        is_text = _is_text_node(node, part) and node.text
        if not separator and not is_text:
            continue
        parent = node
        if name not in METADATA_TAGS | {"lpwstr", "bstr", "lpstr"}:
            while parent.getparent() is not None and _xml_name(parent) not in GROUP_TAGS:
                parent = parent.getparent()
        if separator and id(parent) not in grouped:
            # A leading break carries no text of its own; only breaks inside a run group matter.
            continue
        entry = grouped.setdefault(id(parent), (parent, []))
        entry[1].append(Segment(node, separator if separator else (node.text or ""), not separator))
    return [(f"{_xml_name(parent)}:{i}", segments) for i, (parent, segments) in enumerate(grouped.values())]


def _part_text(root, part: str) -> str:
    return "\n".join("".join(s.text for s in segments) for _, segments in _groups(root, part))


XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def write_text(element, value: str) -> None:
    """Записывает текст узла. Пробел в начале или конце Word и Excel отбрасывают, если нет xml:space="preserve":
    метка, разбитая на два фрагмента («Company» и «1 ждёт»), после замены оставляла «Ромашкаждёт»."""
    element.text = value
    if value and (value != value.strip(" \t\n\r") or "  " in value):
        namespace = etree.QName(element).namespace or ""
        if namespace.endswith(("/wordprocessingml/2006/main", "/spreadsheetml/2006/main")) and etree.QName(element).localname in (
                "t", "delText", "instrText"):
            element.set(XML_SPACE, "preserve")


def splice_segments(segments: list[Segment], edits: list[tuple[int, int, str]]) -> None:
    """Подставляет `edits` = (начало, конец, текст) в сегменты абзаца справа налево.

    Замена помещается в первый затронутый текстовый run, остальные затронутые участки очищаются, а
    поглощённые разрывы строк и табуляции удаляются. Незатронутые runs сохраняют своё оформление.
    """
    for start, end, token in sorted(edits, key=lambda e: e[0], reverse=True):
        spans, position = [], 0
        for segment in segments:
            spans.append((position, position + len(segment.text), segment))
            position += len(segment.text)
        affected = [(a, b, s) for a, b, s in spans if start < b and end > a]
        if not affected:
            continue
        writable = [item for item in affected if item[2].writable]
        if not writable:
            continue
        first_a, _, first = writable[0]
        last_a, last_b, last = affected[-1]
        prefix = first.text[:max(0, start - first_a)]
        suffix = last.text[max(0, end - last_a):] if last.writable else ""
        if first is last:
            first.text = prefix + token + suffix
            write_text(first.element, first.text)
            continue
        first.text = prefix + token
        write_text(first.element, first.text)
        for _, _, segment in affected[1:]:
            if segment is last and segment.writable:
                segment.text = suffix
                write_text(segment.element, suffix)
            elif segment.writable:
                segment.text = ""
                segment.element.text = ""
            else:
                parent = segment.element.getparent()
                if parent is not None:
                    parent.remove(segment.element)
                segment.text = ""


def _replace_across_segments(segments: list[Segment], findings: list[Finding], ctx: TransformContext) -> None:
    accepted = sorted((x for x in findings if x.decision == Decision.AUTO), key=lambda x: x.start)
    text = "".join(seg.text for seg in segments)
    splice_segments(segments, [(f.start, f.end, guard_token(text, f.start, f.end, ctx.token_for(f))) for f in accepted])


def scan_ooxml(path: Path, rel: str, detector, scrub_metadata: bool, inspect_embedded: bool) -> FileResult:
    warnings: list[str] = []
    try:
        snap = _zip_snapshot(path)
        if snap["signatures"]:
            return FileResult(rel, "OOXML", FileStatus.BLOCKED, warnings=["Документ содержит цифровую подпись; изменение нарушит её"], integrity=snap)
        if snap["macros"]:
            return FileResult(rel, "MACRO_OFFICE", FileStatus.REVIEW_REQUIRED, warnings=["Документ содержит VBA; автоматическая перезапись отключена"], integrity=snap)
        findings: list[Finding] = []
        with zipfile.ZipFile(path) as z:
            parts = [n for n in z.namelist() if n.lower().endswith((".xml", ".rels", ".vml"))]
            trees: list[tuple[str, object]] = []
            for name in parts:
                root = parse_part(name, z.read(name))
                if root is None:
                    warnings.append(f"Не удалось безопасно разобрать {name}")
                else:
                    trees.append((name, root))
            hints = learn_package(dict(trees), detector, rel)
            for name, root in trees:
                _, part_findings, _, _ = _scan_xml_tree(root, name, rel, detector, scrub_metadata, hints)
                findings.extend(part_findings)
        if inspect_embedded and (snap["media"] or snap["embeddings"]):
            warnings.append("Есть изображения или вложенные объекты, их визуальное содержимое не подтверждено")
        status = FileStatus.REVIEW_REQUIRED if warnings or any(f.decision != Decision.AUTO for f in findings) else FileStatus.CLEAN
        return FileResult(rel, "OOXML", status, findings, warnings, integrity=snap)
    except (zipfile.BadZipFile, OSError) as exc:
        return FileResult(rel, "OOXML", FileStatus.BLOCKED, warnings=[f"Повреждённый или недоступный Office-файл: {type(exc).__name__}"])


HEADER_FOOTER_TAGS = {"oddHeader", "evenHeader", "firstHeader", "oddFooter", "evenFooter", "firstFooter"}
# Коды колонтитулов Excel: &L &C &R (позиция), &"шрифт" &12 (размер), &P &N &D &T &F &A (поля). Они не текст:
# `&Rgusakov@firma.ru` — это код правой части и адрес, а не адрес с буквой R.
HEADER_CODES = re.compile(r'&(?:[LCR]|"[^"]*"|\d+|[A-Za-z&])')


def _mask_header_codes(text: str) -> str:
    return HEADER_CODES.sub(lambda m: " " * len(m.group(0)), text)


def _metadata_finding(rel: str, loc: str, kind: str, value: str, start: int, reason: str) -> Finding:
    return Finding(finding_id(rel, loc, kind, value), rel, loc, "META", value, start, start + len(value),
                   Decision.AUTO, 1.0, reason=reason)


def _is_metadata_value(segment: Segment, part: str, hints: "PackageHints") -> bool:
    """Значение свойства документа, которое заменяется целиком. Встроенные имена шаблонов Office не трогаем."""
    tag = _xml_name(segment.element)
    if tag == "Template" or (part == "docProps/app.xml" and segment.text.strip() in hints.templates):
        return not BUILTIN_TEMPLATE_NAME.match(segment.text)
    return tag in METADATA_TAGS or part.endswith("custom.xml")


def _scan_text_groups(root, part: str, rel: str, detector, scrub_metadata: bool, hints: "PackageHints | None" = None):
    hints = hints or PackageHints()
    findings: list[Finding] = []
    groups: list[tuple[list[Segment], list[Finding]]] = []
    scrub_here = scrub_metadata and part.startswith("docProps/")
    for group_name, segments in _groups(root, part):
        text = "".join(s.text for s in segments)
        if not text.strip():
            continue
        loc = f"{part}::{group_name}"
        scan_text = _mask_header_codes(text) if group_name.split(":")[0] in HEADER_FOOTER_TAGS else text
        found = detector.scan(scan_text, rel, loc)
        if hints.person_lists and fold(text.strip()) in hints.person_lists:
            found = _with_list_items(found, scan_text, rel, loc, detector)
        if scrub_here:
            # Свойство документа обезличивается целиком: часть значения, найденная как имя, не должна оставлять
            # рядом остаток («Mikhail Name1» из «Mikhail V. Zakharov»).
            offset, whole = 0, []
            for segment in segments:
                value = segment.text
                is_metadata = _is_metadata_value(segment, part, hints)
                if value and segment.writable and is_metadata and not has_token(value):
                    whole.append(_metadata_finding(rel, loc, "metadata", value, offset, "Метаданные документа"))
                offset += len(value)
            if whole:
                found = whole if len(whole) == len(segments) else found + [
                    w for w in whole if not any(f.start < w.end and f.end > w.start for f in found)]
        if found:
            findings.extend(found)
            groups.append((segments, found))
    return findings, groups


def _is_named_attr(element_name: str, attr_name: str, pivot_cache: bool, part: str = "") -> bool:
    if (element_name, attr_name) in NAMED_ELEMENT_ATTRS or (pivot_cache and element_name == "s" and attr_name == "v"):
        return True
    lowered = part.lower()
    if lowered.endswith(("/styles.xml", "/styleswitheffects.xml", "/fonttable.xml", "/numbering.xml", "/settings.xml")):
        return False                                  # имена стилей и шрифтов не данные: у всех документов они общие
    return any(lowered.startswith(prefix) and (element_name, attr_name) in pairs for prefix, pairs in PART_NAMED_ATTRS.items())


PERSON_HEADER = re.compile(r"(?i)\bфио\b|ф\.?\s?и\.?\s?о\b|фамили|сотрудник|владел|ответственн|участник|исполнител|"
                           r"контактное лицо|full name|surname|last name|first name|employee")
NOT_PERSON_HEADER = re.compile(r"(?i)должност|подраздел|отдел|филиал|почт|e-?mail|телефон|числен|кол-?во|количеств|описани|"
                               r"комментар|функци|статус|роль|назван|процесс")
CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


def _shared_strings(parsed: dict) -> list[str]:
    root = parsed.get("xl/sharedStrings.xml")
    if root is None:
        return []
    out = []
    for si in root:
        if _xml_name(si) != "si":
            continue
        out.append("".join(t.text or "" for t in si.iter() if _xml_name(t) == "t"
                           and not any(_xml_name(a) == "rPh" for a in t.iterancestors())))
    return out


def _sheet_cells(parsed: dict):
    """Текстовые ячейки каждого листа: [(столбец, строка, текст)]."""
    strings = _shared_strings(parsed)
    for name, root in parsed.items():
        if not _is_worksheet(name):
            continue
        cells: list[tuple[str, int, str]] = []
        for cell in root.iter():
            if _xml_name(cell) != "c":
                continue
            match = CELL_REF.match(cell.get("r", ""))
            if not match:
                continue
            kind = cell.get("t")
            text = ""
            if kind == "s":
                v = next((c for c in cell if _xml_name(c) == "v"), None)
                if v is not None and (v.text or "").strip().isdigit() and int(v.text) < len(strings):
                    text = strings[int(v.text)]
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter() if _xml_name(t) == "t")
            if text.strip():
                cells.append((match.group(1), int(match.group(2)), text.strip()))
        yield cells


def _column_values(cells, header: re.Pattern, not_header: re.Pattern):
    """(заголовок, текст) ячеек ниже подходящего заголовка того же столбца."""
    headers: dict[str, tuple[int, str]] = {}
    for column, row, text in cells:
        # «Участники: Орлов, Соколова» — значение с вводным словом, а не заголовок столбца.
        if re.search(r":\s*\S|;", text):
            continue
        if row <= 15 and len(text.split()) <= 5 and header.search(text) and not not_header.search(text):
            headers[column] = max(headers.get(column, (0, "")), (row, text))
    for column, row, text in cells:
        if column in headers and row > headers[column][0]:
            yield headers[column][1], text


# Разделители перечня в одной ячейке: «Иванов И.И.; Петров П.П.», «Участники: Орлов, Соколова».
LIST_SEPARATOR = re.compile(r"\s*(?:[;\n]|,(?=\s*[^\W\d_]))\s*")
LIST_PREFIX = re.compile(r"^[^:;,\n]{1,40}:\s*")


def list_items(text: str) -> list[tuple[int, int]]:
    """Границы элементов перечня. Вводная часть до двоеточия («Участники:») элементом не считается."""
    prefix = LIST_PREFIX.match(text)
    position = prefix.end() if prefix else 0
    spans = []
    for separator in [*LIST_SEPARATOR.finditer(text, position), None]:
        end = separator.start() if separator else len(text)
        item = text[position:end]
        if item.strip():
            left = position + len(item) - len(item.lstrip())
            spans.append((left, left + len(item.strip())))
        if separator:
            position = separator.end()
    return spans


ID_HEADERS = colctx.ID_HEADERS


def learn_identifier_columns(cells, detector, limit_rows: int = 15) -> int:
    """Значения под заголовком «ИНН», «Паспорт», «Карта» и т.п.: подпись стоит в соседней ячейке, а не рядом с числом.

    cells: (столбец, строка, текст). Запоминаются только значения из цифр нужной длины; замену выполняет детектор.
    """
    headers: dict[str, tuple[int, str, tuple[int, int]]] = {}
    rows = list(cells)
    for column, row, text in rows:
        if row <= limit_rows and len(text.split()) <= 6:
            for pattern, category, size in ID_HEADERS:
                if pattern.search(text):
                    headers[column] = (row, category, size)
                    break
    learned = 0
    for column, row, text in rows:
        head = headers.get(column)
        if not head or row <= head[0] or not re.fullmatch(r"[\d \u00a0-]+", text.strip() or "x"):
            continue
        digits = re.sub(r"\D", "", text)
        if head[2][0] <= len(digits) <= head[2][1]:
            detector.known_ids.setdefault(digits, head[1])
            learned += 1
    return learned


def _person_columns(parsed: dict) -> tuple[set[str], set[str]]:
    values: set[str] = set()
    lists: set[str] = set()
    for cells in _sheet_cells(parsed):
        for _, text in _column_values(cells, PERSON_HEADER, NOT_PERSON_HEADER):
            if len(text.split()) <= 4 and re.match(r"^[^\W\d_]", text):
                values.add(fold(text))
            if not LIST_SEPARATOR.search(text):
                continue
            # Перечень людей в одной ячейке: каждый элемент — такой же человек, как одиночное значение столбца.
            items = [text[a:b] for a, b in list_items(text)]
            if len(items) >= 2 and all(len(i.split()) <= 4 and re.match(r"^[^\W\d_]", i) for i in items):
                values.update(fold(i) for i in items)
                lists.add(fold(text))
    return values, lists


def person_column_values(parsed: dict) -> set[str]:
    """Тексты ячеек из столбцов, в заголовке которых сказано «ФИО», «Фамилия», «Сотрудник» и подобное.

    Название столбца — самая надёжная подсказка, что в ячейке человек: редкая фамилия без имени и отчества
    («Шин», «Сугимото Масатакэ») иначе неотличима от названия. Ячейка-перечень («А; Б; В») даёт каждый свой элемент.
    """
    return _person_columns(parsed)[0]


# Столбцы с географией: филиал, регион, город, площадка. Их значения выдают, где работает клиент.
# «Подразделение», «Отдел», «Должность» сюда не относятся: там обычные слова, а не названия мест.
PLACE_HEADER = re.compile(r"(?i)филиал|регион|город|площадк|территори|локаци|населённ|населенн")
CITY_HEADER = re.compile(r"(?i)город|площадк|локаци|населённ|населенн")
NOT_PLACE_HEADER = re.compile(r"(?i)подраздел|отдел|должност|адрес|телефон|почт|e-?mail|\bкод|кол-?во|количеств|числен|"
                              r"руковод|директор|начальник|менеджер|ответствен|контакт|сотрудник|фио|описани|комментар|"
                              r"статус|доля|сумм|%")
PLACE_STOP = {"не указано", "не указан", "н/д", "н.д.", "нет", "да", "все", "-", "—", "итого", "всего", "прочие", "прочее",
              "другое", "другие", "общий", "общее", "нет данных", "не определено", "без филиала"}
# Строчные слова, допустимые в названии места: «г. Москва», «Иркутская область», «Нерюнгринский р-н».
GEO_DESIGNATOR = re.compile(r"(?i)^(?:г|гор|с|п|пос|пгт|д|ст|рп|обл|р-н|область|края?|района?|округа?|республика)\.?$")
DOTTED_INITIALS = re.compile(r"\b[А-ЯЁA-Z]\.\s?[А-ЯЁA-Z]\.")


# Кириллическая форма состояния: «Выполняется», «Проводится», «Согласовано», «Оплачена».
STATUS_ENDING = re.compile(r"(?i)(?:ется|ится|ено|ана)$")


def _place_like(value: str, header: str) -> bool:
    """Значение из географического столбца похоже на название места, а не на статус, число или обычное слово."""
    words = value.split()
    if not words or len(words) > 3 or fold(value) in PLACE_STOP or fold(value) == fold(header):
        return False
    if not re.match(r"^[^\W\d_]", value) or DOTTED_INITIALS.search(value):
        return False
    if not all(w[:1].isupper() or GEO_DESIGNATOR.match(w) for w in words):
        return False
    core = [w for w in words if not GEO_DESIGNATOR.match(w)]
    for word in core:
        # Окончание формы состояния не касается известных городов: «Астана» остаётся местом.
        if lexicon.is_status_word(word) or (re.search("[а-яё]", word, re.I) and STATUS_ENDING.search(word)
                                            and not lexicon.is_toponym(word)):
            return False
    # Словарное слово годится только как прилагательное места («Дальневосточный», «Кузбасский»): «Код», «Выручка»,
    # «Основной» из соседней таблицы под тем же столбцом — обычные слова.
    return not all(lexicon.is_common_word(w) and not lexicon.is_geo_adjective(w) for w in core)


def _geo_cue(value: str, text: str) -> bool:
    """Значение где-то ещё в книге стоит рядом с географическим словом: «г. Х», «в Х», «филиал Х», «Х район»."""
    name = re.escape(value)
    return bool(re.search(rf"(?i)(?:\b(?:г|гор|пос|пгт|с|д|ст)\.\s*|\b(?:город\w*|филиал\w*|регион\w*|в|во|из)\s+){name}(?!\w)"
                          rf"|(?<!\w){name}\s+(?:област|кра[йяею]|район|округ)", text))


def place_column_values(parsed: dict) -> dict[str, str]:
    """Значение из столбца «Филиал», «Регион», «Город», «Площадка» → вид (CITY или REGION).

    Столбец засчитывается, только если в нём хотя бы два разных похожих на место значения: одиночное значение под
    случайным заголовком («Регион выполнения» над столбцом статусов) — не довод. Одиночное принимается, если оно
    ещё где-то в книге стоит рядом с географическим словом.
    """
    out: dict[str, str] = {}
    for cells in _sheet_cells(parsed):
        columns: dict[str, list[str]] = {}
        for header, text in _column_values(cells, PLACE_HEADER, NOT_PLACE_HEADER):
            value = " ".join(text.split())
            if _place_like(value, header) and value not in columns.setdefault(header, []):
                columns[header].append(value)
        everything = None
        for header, values in columns.items():
            if len(values) < 2:
                everything = everything if everything is not None else "\n".join(t for _, _, t in cells)
                values = [v for v in values if _geo_cue(v, everything)]
            for value in values:
                out.setdefault(value, "CITY" if CITY_HEADER.search(header) else "REGION")
    return out


def register_place_values(parsed: dict, detector, rel: str) -> None:
    """Значения географических столбцов становятся известными названиями для всей книги, в том числе для текста.

    Что детектор и так скрывает целиком (город из справочника, известная организация), не трогаем: у него уже есть
    свой вид. Опознанный человек в таком столбце тоже не место; а «похоже на фамилию» у прилагательного на -ский
    («Заречинский») в столбце «Филиал» — ошибка формы слова, а не человек.
    """
    entities = getattr(detector, "entities", None)
    if entities is None:
        return
    for value, kind in place_column_values(parsed).items():
        if fold(value) in detector.person_values:
            continue
        probe = detector.scan(value, rel, "column:place")
        if any(f.category == "PERSON" and f.decision == Decision.AUTO for f in probe):
            continue
        if any(f.decision == Decision.AUTO and f.start <= 0 and f.end >= len(value) for f in probe):
            continue
        entities.register(kind, value, explicit=True)


def _with_list_items(found: list[Finding], text: str, rel: str, loc: str, detector) -> list[Finding]:
    """Ячейка-перечень людей: каждый элемент проверяется ещё и как отдельное значение столбца.

    Внутри длинной строки редкая фамилия без имени («Громов») не узнаётся, а как одиночное значение столбца
    «Участники» — узнаётся. Находка по элементу заменяет находки внутри него; частично пересекающиеся не трогаем.
    """
    result = list(found)
    for start, end in list_items(text):
        if any(f.decision == Decision.AUTO and f.start <= start and f.end >= end for f in result):
            continue
        for f in detector.scan(text[start:end], rel, loc):
            a, b = f.start + start, f.end + start
            inside = [g for g in result if g.start >= a and g.end <= b]
            if any(g.start < b and g.end > a and g not in inside for g in result):
                continue
            if inside and f.decision != Decision.AUTO:
                continue
            result = [g for g in result if g not in inside]
            result.append(replace(f, start=a, end=b, finding_id=finding_id(f.file, f.location, a, b, f.original)))
    return sorted(result, key=lambda f: f.start)


@dataclass
class PackageHints:
    """Что известно о файле целиком ещё до разбора частей."""
    templates: set[str] = field(default_factory=set)      # имена тем и шаблона, придуманные автором
    person_lists: set[str] = field(default_factory=set)   # ячейки-перечни людей (свёрнутый текст)


def template_names(parsed: dict) -> set[str]:
    """Имена тем, палитр и шаблона, кроме встроенных: они же повторяются в перечне частей app.xml."""
    names: set[str] = set()
    for part, root in parsed.items():
        lowered = part.lower()
        if "/theme/" not in lowered and lowered != "docprops/app.xml":
            continue
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            element = _xml_name(node)
            if element == "Template" and node.text:
                names.add(node.text.strip())
            names.update(node.get(attr) for el, attr in TEMPLATE_NAME_ATTRS if el == element and node.get(attr))
    names = {n.strip() for n in names if n.strip() and not BUILTIN_TEMPLATE_NAME.match(n)}
    # В перечне частей имя шаблона пишется без расширения.
    return names | {re.sub(r"(?i)\.(?:pot|dot|xlt)[xm]?$", "", n) for n in names}


def learn_package(parsed: dict, detector, rel: str) -> PackageHints:
    """Обучение детектора на файле целиком до замены: люди из столбцов «ФИО», места из столбцов «Филиал», полные имена."""
    persons, lists = _person_columns(parsed)
    detector.person_values |= persons
    for cells in _sheet_cells(parsed):
        learn_identifier_columns(((c, r, t) for c, r, t in cells), detector)
        colctx.learn_grid(cells, detector)
    colctx.learn_xml_tables(parsed, detector)
    force_numeric_ids(parsed, detector)
    # Learn the document's own full names before scanning, so its abbreviations resolve.
    detector.harvest("\n".join(_harvest_source(root, name) for name, root in parsed.items()), rel)
    register_place_values(parsed, detector, rel)
    return PackageHints(template_names(parsed), lists)


def _harvest_source(root, part: str) -> str:
    """Текст части плюс значения проверяемых атрибутов.

    Полное ФИО может стоять только в имени листа или в кэше сводной таблицы. Если не показать
    его сборщику имён, человек остаётся неопознанным, и вместо замены выходит ручная проверка.
    """
    pivot_cache = "/pivotcache/" in part.lower()
    values = [_part_text(root, part)]
    for node in root.iter():
        element_name = _xml_name(node)
        for attr, value in node.attrib.items():
            if not value or len(value) > MAX_ATTRIBUTE_LENGTH:
                continue
            attr_name = etree.QName(attr).localname if attr.startswith("{") else attr
            if _is_named_attr(element_name, attr_name, pivot_cache, part) or attr_name in SENSITIVE_ATTRS:
                values.append(value)
    return "\n".join(values)


def ooxml_text(path: Path) -> str:
    """Видимое содержимое документа без разметки.

    Для сверки возврата с оригиналом сырой XML не годится: пересборка контейнера меняет
    порядок атрибутов и кавычки, и байты расходятся даже при безупречном возврате.
    """
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.lower().endswith(".xml"):
                continue
            try:
                root = etree.fromstring(archive.read(name), _parser())
            except etree.XMLSyntaxError:
                continue
            parts.append(_harvest_source(root, name))
    return "\n".join(parts)


def has_token(value: str) -> bool:
    """Значение уже обезличено: токен искать в нём ещё раз не нужно."""
    return bool(TOKEN_RE.search(value) or EMAIL_TOKEN_RE.search(value))


def _scan_attributes(root, part: str, rel: str, detector, scrub_metadata: bool):
    findings: list[Finding] = []
    groups: list[tuple[object, str, list[Finding]]] = []
    # Кэш сводной таблицы держит вторую копию исходных ячеек в атрибуте: <s v="Иванов"/>.
    # Значения листа обезличивались, а кэш уезжал наружу нетронутым.
    pivot_cache = "/pivotcache/" in part.lower()
    for node in root.iter():
        element_name = _xml_name(node)
        for attr, value in node.attrib.items():
            if not value or len(value) > MAX_ATTRIBUTE_LENGTH:
                continue
            attr_name = etree.QName(attr).localname if attr.startswith("{") else attr
            named = _is_named_attr(element_name, attr_name, pivot_cache, part) and not value.lstrip().startswith("<")
            # Имя умной таблицы и её displayName — одно и то же имя (Excel пишет их равными): меняются они одинаково, по
            # содержимому. Общее правило для displayName (метаданные автора) здесь дало бы Meta2 при нетронутом name.
            sensitive = attr_name in SENSITIVE_ATTRS and (element_name, attr_name) != ("table", "displayName")
            link = attr_name in LINK_ATTRS and value.startswith(("http://", "https://", "mailto:", "tel:"))
            local_path = attr_name in LINK_ATTRS and bool(LOCAL_PATH.match(value)) and not has_token(value)
            if not (named or sensitive or link or local_path):
                continue
            loc = f"{part}::attribute:{element_name}:{attr_name}"
            # Имена диапазонов, таблиц и столбцов пишут через подчёркивание («Клиент_Ромашка»): для разбора оно разделитель
            # слов, а не часть слова. Длина строки не меняется, поэтому позиции находок остаются верными.
            found = detector.scan(value.replace("_", " ") if (element_name, attr_name) in IDENTIFIER_ATTRS else value, rel, loc)
            if local_path and scrub_metadata:
                found = [_metadata_finding(rel, loc, "local-path", value, 0, "Путь на компьютере автора")]
            if scrub_metadata and sensitive and not found and not has_token(value):
                found = [_metadata_finding(rel, loc, "metadata-attr", value, 0, "Метаданные автора")]
            if scrub_metadata and (element_name, attr_name) in TEMPLATE_NAME_ATTRS and not has_token(value) \
                    and not BUILTIN_TEMPLATE_NAME.match(value):
                # Имя темы — ярлык шаблона, а не содержимое: заменяется целиком, смысл документа от этого не страдает.
                found = [_metadata_finding(rel, loc, "template-name", value, 0, "Имя темы или шаблона оформления")]
            if found:
                findings.extend(found)
                groups.append((node, attr, found))
    return findings, groups


def _scan_xml_tree(root, part: str, rel: str, detector, scrub_metadata: bool, hints: PackageHints | None = None):
    """Findings for one already-parsed part, so a part is never parsed more than once."""
    text_findings, text_groups = _scan_text_groups(root, part, rel, detector, scrub_metadata, hints)
    attr_findings, attr_groups = _scan_attributes(root, part, rel, detector, scrub_metadata)
    return root, text_findings + attr_findings, text_groups, attr_groups


DC_NS = "http://purl.org/dc/elements/1.1/"
MARKER_PREFIX = "anonymizer:"


def stamp_vault_marker(root, vault_id: str) -> None:
    """Пометка в свойствах документа: каким хранилищем сделан файл. Существующий идентификатор документа не затирается."""
    for node in root.iter(f"{{{DC_NS}}}identifier"):
        if (node.text or "").strip() and not (node.text or "").startswith(MARKER_PREFIX):
            return
        node.text = MARKER_PREFIX + vault_id
        return
    node = etree.SubElement(root, f"{{{DC_NS}}}identifier", nsmap={"dc": DC_NS})
    node.text = MARKER_PREFIX + vault_id


def strip_vault_marker(root) -> bool:
    removed = False
    for node in list(root.iter(f"{{{DC_NS}}}identifier")):
        if (node.text or "").startswith(MARKER_PREFIX):
            node.getparent().remove(node)
            removed = True
    return removed


def read_vault_marker(path: Path) -> str:
    """Идентификатор хранилища, которым обезличен файл, или пустая строка (пометка пропала при пересохранении)."""
    if path.suffix.lower() == ".pdf":
        try:
            with fitz.open(path) as doc:
                producer = (doc.metadata or {}).get("producer") or ""
            return producer[len(MARKER_PREFIX):].strip() if producer.startswith(MARKER_PREFIX) else ""
        except Exception:
            return ""
    try:
        with zipfile.ZipFile(path) as z:
            if "docProps/core.xml" not in z.namelist():
                return ""
            root = etree.fromstring(z.read("docProps/core.xml"), _parser())
    except Exception:
        return ""
    for node in root.iter(f"{{{DC_NS}}}identifier"):
        if (node.text or "").startswith(MARKER_PREFIX):
            return node.text[len(MARKER_PREFIX):].strip()
    return ""


IMAGE_PART_EXTS = (".png", ".jpg", ".jpeg")
MIN_IMAGE_SIDE = 40
MAX_IMAGE_PASSES = 3


class ImageBlocked(Exception):
    """Картинка с данными, которую нельзя надёжно закрасить: файл наружу не выдаётся."""


BARCODE_LABEL = "[code removed]"
_BARCODE_DIGITS = re.compile(r"\d{6,}")


def _barcode_unsafe(detector, rel: str, payload: str) -> bool:
    """QR или штрихкод, про который нельзя сказать, что в нём нет данных: не прочитался, содержит найденные данные,
    длинный номер или адрес с параметрами (в них бывают идентификаторы)."""
    text = payload.strip()
    if not text:
        return True
    if _BARCODE_DIGITS.search(text) or "?" in text or "=" in text:
        return True
    return bool(detector.scan(text, rel, "barcode"))


def _unsafe_barcodes(codes, detector, rel: str) -> list:
    return [c for c in codes if _barcode_unsafe(detector, rel, c.payload)]


def _paint_barcode_rects(page, pix, rects) -> None:
    for rect in rects:
        box = fitz.Rect(rect) + (-3, -3, 3, 3)
        fill = _fill_under(pix, box)
        page.draw_rect(box, color=None, fill=fill, width=0)
        draw_text(page, box, 0, BARCODE_LABEL, "helv", 3.0, max(6.0, min(14.0, box.height / 6)),
                  color=(1, 1, 1) if sum(fill) < 1.5 else (0, 0, 0))


def _brand_finding(detector, rel: str, phrase: str) -> Finding:
    """Логотипный текст картинки как организация: то же написание в других местах получает ту же метку Company."""
    entity = detector.entities.register("ORG", phrase, explicit=True)
    key = entity.key if entity else fold(phrase)
    return Finding(finding_id(rel, "image", 0, len(phrase), phrase), rel, "image", "ORG", phrase, 0, len(phrase),
                   Decision.AUTO, .8, key=key, reason="название на логотипе")


def _covered(rect, others) -> bool:
    area = max(rect.get_area(), 1e-6)
    return any((rect & o).get_area() >= .5 * min(area, max(o.get_area(), 1e-6)) for o in others if rect.intersects(o))


def _fuzzy_image_hits(chars: PageChars, names, hits, rel: str) -> list[tuple[Finding, set[int]]]:
    """Известные организации и скрытые слова, прочитанные на картинке с ошибками распознавания или разбитые на строки."""
    if not names:
        return []
    view = chars.view("join")
    taken = set().union(*[ids for _, ids in hits]) if hits else set()
    by_form = {form: (kind, key) for form, kind, key in names}
    out = []
    for start, end, form in imagetext.fuzzy_spans(view.text, list(by_form)):
        ids = set(view.ids(start, end))
        if not ids or ids <= taken:
            continue
        kind, key = by_form[form]
        original = view.text[start:end]
        out.append((Finding(finding_id(rel, "image", start, end, original), rel, "image", kind, original, start, end,
                            Decision.AUTO, .9, key=key, reason="известное название, прочитанное на картинке неточно"), ids))
    return out


def _person_parts(findings) -> list[tuple[str, str]]:
    """(слово ФИО от 6 букв, ключ) из найденных на этой картинке людей: имя может оказаться вшитым в обрезанный адрес."""
    out: dict[str, str] = {}
    for f in findings:
        if f.category == "PERSON":
            for word in re.findall(r"[^\W\d_]+", f.original):
                if len(word) >= 6:
                    out.setdefault(word.lower(), f.key)
    return sorted(out.items())


def _embedded_name_hits(chars: PageChars, parts, hits, rel: str) -> list[tuple[Finding, set[int]]]:
    """Слово распознавания, внутри которого стоит часть известного ФИО (имя в обрезанном по краю адресе, склейка с цифрами)."""
    if not parts:
        return []
    view = chars.view("join")
    taken = set().union(*[ids for _, ids in hits]) if hits else set()
    out = []
    for m in re.finditer(r"\S+", view.text):
        low = m.group(0).lower()
        if TOKEN_RE.search(m.group(0)):
            continue
        for part, key in parts:
            if part in low:
                ids = set(view.ids(m.start(), m.end()))
                if ids and not ids <= taken:
                    out.append((Finding(finding_id(rel, "image", m.start(), m.end(), m.group(0)), rel, "image", "PERSON", m.group(0), m.start(), m.end(),
                                        Decision.AUTO, .9, key=key, reason="часть известного ФИО внутри слова на картинке"), ids))
                break
    return out


PARTIAL_EMAIL = re.compile(r"[\w.+\-]{3,}@[\w\-]{3,}[^\s]*")


def _partial_email_hits(chars: PageChars, hits, rel: str, skip) -> list[tuple[Finding, set[int]]]:
    """Адрес, обрезанный краем картинки или оборванный распознаванием («thaverford195@corp-dem»): без окончания домена правила его не берут."""
    view = chars.view("join")
    taken = set().union(*[ids for _, ids in hits]) if hits else set()
    out = []
    for m in PARTIAL_EMAIL.finditer(view.text):
        value = m.group(0)
        if TOKEN_RE.search(value) or EMAIL_TOKEN_RE.search(value) or skip(value):
            continue
        ids = set(view.ids(m.start(), m.end()))
        if ids and not ids <= taken:
            out.append((Finding(finding_id(rel, "image", m.start(), m.end(), value), rel, "image", "EMAIL", value, m.start(), m.end(),
                                Decision.AUTO, .9, key="partial:" + value.lower(), reason="обрезанный адрес почты на картинке"), ids))
    return out


SECRET_LABEL_VALUE = re.compile(r"(?i)\b(?:token|api[ _\-]?key|secret|passw(?:or)?d|pwd|парол[ьяю]|ключ|токен)\b\s*[:=]\s*(\S+(?: \S+)?)")


NUMBER_LABEL_VALUE = re.compile(r"(?i)\b(?:инн|снилс|огрн|кпп|бик|inn|ssn|snils)\b\s*[:=№]?\s*(\d(?:[\d \-]{6,}\d))|(?<![\d.,])(\d{10}(?:\d{2})?)(?![\d])")


def _label_value_hits(chars: PageChars, hits, rel: str, skip=None) -> list[tuple[Finding, set[int]]]:
    """Значение после метки («token = sk live_705871Z0...»): распознавание портит ключ (пробел вместо «_», «0» вместо «q»),
    и правила его не узнают. На картинке всё, что стоит на строке после метки секрета, считается секретом."""
    view = chars.view("lines")
    taken = set().union(*[ids for _, ids in hits]) if hits else set()
    out = []
    for m in SECRET_LABEL_VALUE.finditer(view.text):
        value = m.group(1)
        parts = value.split(" ")
        # второе слово берётся, только если и оно похоже на кусок ключа (цифры или «_»)
        if len(parts) == 2 and not (re.search(r"\d", parts[1]) or "_" in parts[1]):
            value, start = parts[0], m.start(1)
            end = start + len(value)
        else:
            start, end = m.start(1), m.end(1)
        value = view.text[start:end]
        if len(value) < 4 or TOKEN_RE.search(value) or EMAIL_TOKEN_RE.search(value) or (skip and skip(value)):
            continue
        ids = set(view.ids(start, end))
        if ids and not ids <= taken:
            out.append((Finding(finding_id(rel, "image", start, end, value), rel, "image", "SECRET", value, start, end,
                                Decision.AUTO, .9, key="labelval:" + value.lower(), reason="значение после метки секрета на картинке"), ids))
    for m in NUMBER_LABEL_VALUE.finditer(view.text):
        start, end = (m.start(1), m.end(1)) if m.group(1) else (m.start(2), m.end(2))
        value = view.text[start:end]
        ids = set(view.ids(start, end))
        if ids and not ids <= taken and not (skip and skip(value)):
            out.append((Finding(finding_id(rel, "image", start, end, value), rel, "image", "ID_NUMBER", value, start, end,
                                Decision.AUTO, .9, key="labelnum:" + re.sub(r"\D", "", value), reason="номер после метки на картинке"), ids))
    return out


def _map_layer_ids(main: PageChars, layer: PageChars, ids) -> set[int]:
    """Символы основной карты страницы, лежащие под символами того же слова в другом слое распознавания."""
    boxes = [fitz.Rect(layer.chars[i].x0, layer.chars[i].y0, layer.chars[i].x1, layer.chars[i].y1) for i in ids if not layer.chars[i].c.isspace()]
    if not boxes:
        return set()
    out = set()
    for j, c in enumerate(main.chars):
        centre = fitz.Point((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2)
        if any(b.contains(centre) for b in boxes):
            out.add(j)
    return out


def _on_drawn_token(word, rects) -> bool:
    """Слово распознавания лежит (в основном) на нарисованной нами метке: его искажения не данные."""
    area = max((word.x1 - word.x0) * (word.y1 - word.y0), 1e-6)
    box = fitz.Rect(word.x0, word.y0, word.x1, word.y1)
    return any(box.intersects(r) and (box & r).get_area() >= .6 * area for r in rects)


def _anonymize_image(raw: bytes, name: str, rel: str, detector, ctx: TransformContext, _pass: int = 0, _origin: bytes | None = None,
                     _rects: list | None = None) -> bytes | None:
    """Закрашивает найденные данные на картинке и пишет метку поверх. None — менять нечего.

    Исходные байты уходят в хранилище под хэшем результата: по нему при возврате находится оригинал.
    ImageBlocked — данные на картинке есть, но надёжно закрасить их не вышло.
    """
    ext = Path(name).suffix.lower()
    try:
        pix = fitz.Pixmap(raw)
    except Exception:
        return None
    if pix.width < MIN_IMAGE_SIDE or pix.height < MIN_IMAGE_SIDE:
        return None
    doc = fitz.open()
    try:
        page = doc.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, stream=raw)
        scale = min(3.0, max(1.0, 1800.0 / max(pix.width, 1)))
        layers = ocr.ocr_image_layers(page, scale=scale)
        drawing: list = []
        drawn = ctx.__dict__.setdefault("image_drawn_tokens", set())      # метки почты, которые мы рисовали (для сверки с искажённым чтением)
        token_rects = list(_rects or [])                                   # где метки уже нарисованы (прошлые проходы тоже)
        own_noise = lambda v: bool(GLUED_EMAIL_TOKEN.search(v) or MISREAD_EMAIL_TOKEN.search(v) or GARBLED_EMAIL_TOKEN.search(v)
                                   or _garbled_drawn_token(v, drawn))
        names = imagetext.known_names(detector)
        for number, words in enumerate(layers):
            chars = PageChars(page)
            if not ocr.add_ocr_chars(chars, words):
                continue
            if number == 0:
                detector.harvest("\n".join([chars.view(m).text for m in ("lines", "join", "dehyphen")]), rel)
            hits = [(f, ids) for f, ids in _pdf_page_hits(detector, ctx, rel, 1, chars) if f.decision == Decision.AUTO]
            hits += _fuzzy_image_hits(chars, names, hits, rel)
            hits += _embedded_name_hits(chars, _person_parts([f for f, _ in hits] + [d[2] for d in drawing]), hits, rel)
            hits += _partial_email_hits(chars, hits, rel, own_noise)
            hits += _verify_hits(detector, chars, rel, set().union(*[ids for _, ids in hits]) if hits else set(), skip=own_noise)
            hits += _label_value_hits(chars, hits, rel, own_noise)
            for f, ids in hits:
                segs = chars.segments(sorted(ids))
                if segs and all(_covered(seg.rect, [d[0].rect for d in drawing]) for seg in segs):
                    continue                    # эту надпись уже закрыл другой проход
                token = ctx.token_for(f)
                if EMAIL_TOKEN_RE.fullmatch(token):
                    drawn.add(token)
                for k, seg in enumerate(segs):
                    drawing.append((seg, token if k == 0 else None, f))
        hits = [d[2] for d in drawing]
        codes = []
        if ocr.barcodes_available():
            codes = _unsafe_barcodes(ocr.detect_barcodes(page, scale=max(2.0, scale)), detector, rel)
        policy = getattr(ctx.settings, "image_brand_policy", "paint")
        if policy != "off":
            covered = [d[0].rect + (-2, -2, 2, 2) for d in drawing]
            groups = []
            for words in layers:
                for phrase, ws in imagetext.brand_groups(words, covered):
                    box = fitz.Rect(min(w.x0 for w in ws), min(w.y0 for w in ws), max(w.x1 for w in ws), max(w.y1 for w in ws))
                    if not _covered(box, [g[2] for g in groups]):
                        groups.append((phrase, ws, box))
            can_paint = policy == "paint" and ext in IMAGE_PART_EXTS
            for phrase, ws, box in groups:
                if can_paint and imagetext.paintable(phrase, len(groups)):
                    finding = _brand_finding(detector, rel, phrase)
                    token = ctx.token_for(finding)
                    lines: dict[int, list] = {}
                    for w in ws:
                        lines.setdefault(w.line, []).append(w)
                    for k, line in enumerate(sorted(lines.values(), key=lambda l: l[0].y0)):
                        rect = fitz.Rect(min(w.x0 for w in line), min(w.y0 for w in line), max(w.x1 for w in line),
                                         max(w.y1 for w in line)) + (-ocr.PAD, -ocr.PAD * .6, ocr.PAD, ocr.PAD * .6)
                        drawing.append((PixSegment(rect, 0, rect.height * .8, 0), token if k == 0 else None, finding))
                    hits.append(finding)
                    ctx.__dict__["logos_painted"] = ctx.__dict__.get("logos_painted", 0) + 1
                    ctx.__dict__.setdefault("image_review", []).append(
                        f"{name}: название или логотип «{phrase}» закрашено меткой {token}: проверьте, что это действительно название.")
                else:
                    ctx.__dict__.setdefault("image_review", []).append(
                        f"{name}: на картинке есть название или логотип, которое программа не опознала как данные и не закрасила: "
                        f"«{phrase}». Если это название организации или проекта, закройте его вручную или добавьте в список скрываемых слов.")
        if not hits and not codes:
            return None
        if ext not in IMAGE_PART_EXTS:
            raise ImageBlocked(f"{name}: на картинке есть данные или QR-код, но формат {ext or '?'} не поддерживается для закраски")
        for seg, _, _ in drawing:
            page.draw_rect(seg.rect, color=None, fill=_fill_under(pix, seg.rect), width=0)
        for seg, token, _ in drawing:
            if token:
                fill = _fill_under(pix, seg.rect)
                dark_bg = sum(fill) < 1.5
                draw_text(page, seg.rect, seg.rot, token, "helv", 3.0, max(6.0, min(seg.rect.height, seg.rect.width) if seg.rot in (90, 270) else seg.rect.height),
                          color=(1, 1, 1) if dark_bg else (0, 0, 0))
        _paint_barcode_rects(page, pix, [c.rect for c in codes])
        out = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        data = out.tobytes("png") if ext == ".png" else out.tobytes("jpeg", jpg_quality=92)
        # Проверка тем же распознаванием: прочитанное значение на готовой картинке — отказ.
        check = fitz.open()
        cp = check.new_page(width=out.width, height=out.height)
        cp.insert_image(cp.rect, stream=data)
        token_rects += [seg.rect for seg, token, _ in drawing if token]
        words_back = [w for layer in ocr.ocr_image_layers(cp, scale=scale) for w in layer]
        text, spans = "", []
        for w in words_back:
            if text:
                text += " "
            if _on_drawn_token(w, token_rects):
                spans.append((len(text), len(text) + len(w.text)))
            text += w.text
        if _residuals(detector, text, hits, ocr_text=True, drawn=drawn, masked_spans=spans):
            # Распознавание не детерминировано, одно и то же слово читается не с первого раза (как и в PDF): закрашиваем результат ещё раз.
            again = _anonymize_image(data, name, rel, detector, ctx, _pass + 1, _origin or raw, token_rects) if _pass + 1 < MAX_IMAGE_PASSES else None
            if again is None:
                raise ImageBlocked(f"{name}: данные на картинке остались читаемыми после закраски")
            return again
        if codes and _unsafe_barcodes(ocr.detect_barcodes(cp, scale=max(2.0, scale)), detector, rel):
            raise ImageBlocked(f"{name}: QR-код или штрихкод на картинке остался читаемым после закраски")
        check.close()
        if codes:
            ctx.__dict__["barcodes_removed"] = ctx.__dict__.get("barcodes_removed", 0) + len(codes)
        ctx.vault.stash_image(sha256_bytes(data), _origin or raw)
        return data
    finally:
        doc.close()


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_META_CHUNKS = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}
# Из необязательных блоков PNG остаются только те, что нужны для показа; любой другой (в том числе частный) удаляется.
PNG_KEEP_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"pHYs", b"sBIT",
                   b"bKGD", b"acTL", b"fcTL", b"fdAT"}


def sniff_image(path: Path) -> str:
    """'.png' / '.jpg' по первым байтам файла, иначе ''. Расширению не верим: подделка не должна обходить закраску."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return ""
    if head.startswith(PNG_MAGIC):
        return ".png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return ""


def strip_image_metadata(raw: bytes, ext: str) -> bytes:
    """Убирает из PNG/JPEG служебные блоки (EXIF с GPS и автором, XMP, IPTC, комментарии) без пересжатия пикселей."""
    try:
        if ext == ".png":
            out, pos = [raw[:8]], 8
            while pos + 8 <= len(raw):
                size = int.from_bytes(raw[pos:pos + 4], "big")
                kind = raw[pos + 4:pos + 8]
                end = pos + 12 + size
                if end > len(raw):
                    return raw
                if kind in PNG_KEEP_CHUNKS and kind not in PNG_META_CHUNKS:
                    out.append(raw[pos:end])
                pos = end
                if kind == b"IEND":
                    break               # всё после IEND — приписанные данные, а не часть картинки
            return b"".join(out)
        out, pos = [raw[:2]], 2
        while pos + 4 <= len(raw):
            if raw[pos] != 0xFF:
                return raw
            marker = raw[pos + 1]
            if marker == 0xDA:                     # начало данных: дальше только пиксели и конец файла (EOI)
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
            if not (marker == 0xFE or (0xE1 <= marker <= 0xEF and marker != 0xE2)):
                out.append(raw[pos:end])        # APP0 (JFIF), ICC (APP2), таблицы и кадр остаются
            pos = end
        return raw
    except Exception:
        return raw


def transform_image(src: Path, dst: Path, rel: str, detector, ctx: TransformContext) -> FileResult:
    """Отдельный файл PNG/JPEG: текст на картинке распознаётся, найденное закрашивается, оригинал уходит в хранилище."""
    if imagereplace.whole_image(ctx.settings):
        return imagereplace.transform_standalone(src, dst, rel, ctx)
    raw = src.read_bytes()
    ext = sniff_image(src)
    if not ext:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=["В режиме «Закрасить текст» поддержаны только PNG и JPEG. Для других форматов (TIFF, WebP, GIF, BMP) выберите «Заменять картинку целиком»."])
    if not ctx.settings.ocr_images:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=[
            "Распознавание текста на картинках выключено в настройках, поэтому картинка не проверена и не передаётся наружу."])
    if not ocr.available():
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=[
            "На этом компьютере нет программы распознавания текста, поэтому проверить картинку на данные нельзя. "
            "Файл не передаётся наружу."])
    try:
        pix = fitz.Pixmap(raw)
        small = pix.width < MIN_IMAGE_SIDE or pix.height < MIN_IMAGE_SIDE
    except Exception:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=["Картинка повреждена и не читается."])
    codes_before = ctx.__dict__.get("barcodes_removed", 0)
    review_from = len(ctx.__dict__.get("image_review", []))
    logos_before = ctx.__dict__.get("logos_painted", 0)
    try:
        changed = _anonymize_image(raw, src.name, rel, detector, ctx)
    except ImageBlocked as exc:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=[str(exc)])
    except ocr.OcrUnavailable as exc:
        return FileResult(rel, "IMAGE", FileStatus.BLOCKED, warnings=[f"Распознавание текста не удалось ({exc}). Файл не передаётся наружу."])
    notices = ["Лица, подписи, печати и рисунки программа не распознаёт: просмотрите картинку сами."]
    if ctx.__dict__.get("barcodes_removed", 0) > codes_before:
        notices.append("На картинке закрашен QR-код или штрихкод: в нём могли быть данные, вернуть его при восстановлении нельзя.")
    if not ocr.barcodes_available():
        notices.append("QR-коды и штрихкоды на этом компьютере не проверяются: если они есть на картинке, проверьте их сами.")
    if ctx.__dict__.get("logos_painted", 0) > logos_before:
        notices.append(f"Закрашено названий на логотипах: {ctx.__dict__['logos_painted'] - logos_before}. Оригинал картинки хранится для возврата.")
    if small:
        notices.append("Картинка очень маленькая: текст на ней не искался.")
    if changed is None:
        data = strip_image_metadata(raw, ext) if ctx.settings.scrub_metadata else raw
        if data != raw:
            ctx.vault.stash_image(sha256_bytes(data), raw)
            notices.append("Из картинки удалены служебные данные (EXIF, автор, место съёмки).")
    else:
        data = changed
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    review = ctx.__dict__.get("image_review", [])[review_from:]
    return FileResult(rel, "IMAGE", FileStatus.REVIEW_REQUIRED if review else FileStatus.CLEAN, warnings=list(review),
                      notices=notices, output_path=str(dst))


def scan_image(path: Path, rel: str, detector) -> FileResult:
    return FileResult(rel, "IMAGE", FileStatus.CLEAN)


def _fill_under(pix, rect) -> tuple[float, float, float]:
    """Цвет фона рядом с закрашиваемым местом: медиана точек по периметру чуть снаружи рамки (буквы по краям не мешают)."""
    pts = []
    steps = 8
    for i in range(steps + 1):
        x = rect.x0 + (rect.x1 - rect.x0) * i / steps
        y = rect.y0 + (rect.y1 - rect.y0) * i / steps
        pts += [(x, rect.y0 - 2), (x, rect.y1 + 2), (rect.x0 - 2, y), (rect.x1 + 2, y)]
    chans: list[list[float]] = [[], [], []]
    for x, y in pts:
        xi, yi = int(x), int(y)
        if 0 <= xi < pix.width and 0 <= yi < pix.height:
            px = pix.pixel(xi, yi)
            for i in range(3):
                chans[i].append(px[i] if len(px) > i else px[0])
    if not chans[0]:
        return (1.0, 1.0, 1.0)
    return tuple(sorted(c)[len(c) // 2] / 255.0 for c in chans)


def transform_ooxml(src: Path, dst: Path, rel: str, detector, ctx: TransformContext, depth: int = 0) -> FileResult:
    before = _zip_snapshot(src)
    if before["macros"] or before["signatures"]:
        # Файл не копируем: нетронутая копия с макросом или подписью наружу не выходит (запрос W9, пункт 1).
        reason = "VBA" if before["macros"] else "цифровая подпись"
        message = ("В файле есть макросы (VBA): автоматическая обработка отключена, файл не выдан. Сохраните копию без макросов (.xlsx, .docx, .pptx)."
                   if before["macros"] else "В файле есть цифровая подпись: автоматическая обработка отключена, файл не выдан.")
        return FileResult(rel, "OOXML", FileStatus.BLOCKED,
                          warnings=[f"Автоматическая обработка отключена: {reason}", message], output_path="", integrity=before)
    findings: list[Finding] = []
    warnings: list[str] = []
    output_text: list[str] = []
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".anon-office-", suffix=src.suffix, dir=dst.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(src, "r") as zin:
            parsed: dict[str, object] = {}
            for info in zin.infolist():
                if info.filename.lower().endswith((".xml", ".rels", ".vml")):
                    try:
                        parsed[info.filename] = etree.fromstring(zin.read(info.filename), _parser())
                    except etree.XMLSyntaxError:
                        recovered = _recover_vml(zin.read(info.filename)) if info.filename.lower().endswith(".vml") else None
                        if recovered is None:
                            warnings.append(f"Не обработан внутренний XML: {info.filename}")
                        else:
                            parsed[info.filename] = recovered
            hints = learn_package(parsed, detector, rel)
            thumbnails = drop_thumbnails(parsed, zin.namelist()) if (ctx.settings.scrub_metadata or imagereplace.whole_image(ctx.settings)) else set()
            removal = drop_embedded_payloads(parsed, zin.namelist(), depth) if ctx.settings.scrub_metadata \
                else EmbeddedRemoval()
            printers = drop_printer_settings(parsed, [n for n in zin.namelist() if n not in removal.parts]) if ctx.settings.scrub_metadata else set()
            dropped = thumbnails | removal.parts | printers
            image_ocr = bool(ctx.settings.ocr_images) and ocr.available()
            review_from = len(ctx.__dict__.get("image_review", []))
            logos_from = ctx.__dict__.get("logos_painted", 0)
            stripped_images = whole_images = kept_images = 0
            blocked_images: list[str] = []
            changed_images: dict[str, str] = {}
            finance_info = None
            finance_hint = False
            skip_token = None
            if src.suffix.lower() == ".xlsx" and depth == 0:
                if ctx.settings.finance_numbers:
                    finance_info = _finance_prepass(parsed, ctx, rel, warnings)
                    if finance_info.get("blocked"):
                        return FileResult(rel, "OOXML", FileStatus.BLOCKED, findings,
                                          ["Суммы нельзя замаскировать без поломки формул, файл не выдаётся: "
                                           + "; ".join(finance_info["conflicts"][:5])])
                    skip_token = _SKIP_SAFE_FORMULAS.set(True)
                else:
                    finance_hint = finance_module.looks_financial(parsed)
            numbers_on = ctx.settings.numbers and src.suffix.lower() == ".xlsx" and finance_info is None
            date_styles: set[int] = set()
            avoid: set[str] = set()
            amounts = 0
            if src.suffix.lower() == ".xlsx":
                styles = parsed.get("xl/styles.xml")
                date_styles = numeric.date_style_indexes(styles) if styles is not None else set()
            if numbers_on:
                for name, root in parsed.items():
                    if _is_worksheet(name):
                        avoid.update(canon for _, _, canon in numeric.numeric_cells(root, date_styles))
            elif src.suffix.lower() == ".xlsx" and depth == 0:
                amounts = sum(numeric.should_replace(canon) for name, root in parsed.items() if _is_worksheet(name)
                              for _, _, canon in numeric.numeric_cells(root, date_styles))
            with zipfile.ZipFile(tmp_name, "w") as zout:
                for info in zin.infolist():
                    if info.filename in dropped:
                        continue
                    raw = zin.read(info.filename)
                    root = parsed.get(info.filename)
                    whole = root is None and imagereplace.whole_image(ctx.settings) and imagereplace.replaces_part(info.filename, raw)
                    if root is None and not whole and imagereplace.whole_image(ctx.settings) and _unprocessable(info.filename, depth) \
                            and imagereplace.contains_image(raw):
                        return FileResult(rel, "OOXML", FileStatus.BLOCKED, findings, [imagereplace.opaque_image_warning(info.filename)])
                    if whole:
                        try:
                            raw = imagereplace.replace_part(raw, info.filename, ctx)
                        except imagereplace.ImageStoreFull as exc:
                            return FileResult(rel, "OOXML", FileStatus.BLOCKED, findings, [str(exc)])
                        changed_images[info.filename] = hashlib.sha256(raw).hexdigest()
                        whole_images += 1
                    if root is None and not whole and "/media/" in info.filename.lower() \
                            and info.filename.lower().endswith(IMAGE_PART_EXTS + tuple(IMAGE_EXTENSIONS)):
                        kept_images += 1
                        new_raw = None
                        if image_ocr:
                            try:
                                new_raw = _anonymize_image(raw, info.filename, rel, detector, ctx)
                            except ImageBlocked as exc:
                                blocked_images.append(str(exc))
                            except Exception as exc:
                                blocked_images.append(f"{info.filename}: не удалось прочитать текст на картинке ({type(exc).__name__})")
                        if new_raw is None and ctx.settings.scrub_metadata and info.filename.lower().endswith(IMAGE_PART_EXTS):
                            kind_ext = ".png" if raw.startswith(PNG_MAGIC) else ".jpg" if raw[:3] == b"\xff\xd8\xff" else ""
                            clean = strip_image_metadata(raw, kind_ext) if kind_ext else raw
                            if clean != raw:
                                ctx.vault.stash_image(sha256_bytes(clean), raw)
                                new_raw = clean
                                stripped_images += 1
                        if new_raw is not None:
                            changed_images[info.filename] = hashlib.sha256(new_raw).hexdigest()
                            raw = new_raw
                    if root is None and info.filename.lower().endswith(RAW_TEXT_EXTS) \
                            and "/media/" not in info.filename.lower():
                        new_raw, inner = _transform_raw_text(raw, info.filename, rel, detector, ctx)
                        if inner is None:
                            warnings.append(f"Часть файла не прочитана и осталась как есть: {info.filename}")
                        else:
                            findings.extend(inner.findings)
                            output_text.append(new_raw.decode(sniff_encoding(new_raw), errors="replace"))
                            if new_raw != raw:
                                changed_images[info.filename] = hashlib.sha256(new_raw).hexdigest()
                                raw = new_raw
                    elif root is None and _unknown_raw_part(info.filename):
                        warnings.append(f"Часть файла не обработана, её содержимое осталось как есть: {info.filename}")
                    if root is None and is_embedded_package(info.filename):
                        raw, inner = _transform_embedded(raw, info.filename, rel, detector, ctx, depth)
                        findings.extend(inner.findings)
                        warnings.extend(f"{info.filename}: {w}" for w in inner.warnings)
                    elif root is None and (is_embedded_zip(info.filename) or raw[:4] == b"PK\x03\x04"):
                        if not is_embedded_zip(info.filename):
                            raise NestedBlocked(f"{info.filename}: вложенный архив неизвестного вида")
                        raw, inner_findings, inner_warnings = _transform_zip(raw, info.filename, rel, detector, ctx, depth + 1)
                        findings.extend(inner_findings)
                        warnings.extend(f"{info.filename}: {w}" for w in inner_warnings)
                    if root is not None:
                        _, part_findings, groups, attrs = _scan_xml_tree(root, info.filename, rel, detector,
                                                                         ctx.settings.scrub_metadata, hints)
                        part_findings = ctx.apply_overrides(part_findings)
                        by_id = {f.finding_id: f for f in part_findings}
                        findings.extend(part_findings)
                        for segments, original_group in groups:
                            _replace_across_segments(segments, [by_id[f.finding_id] for f in original_group], ctx)
                        if _is_worksheet(info.filename):
                            _text_into_numeric_cells(root)
                        for node, attr, original_attr in attrs:
                            value = replace_findings(node.get(attr, ""), [by_id[f.finding_id] for f in original_attr], ctx,
                                                     guard=(_xml_name(node), etree.QName(attr).localname) not in IDENTIFIER_ATTRS)
                            node.set(attr, value)
                        if numbers_on:
                            lowered = info.filename.lower()
                            if _is_worksheet(info.filename):
                                done, cleared = numeric.anonymize_worksheet(root, date_styles, ctx.vault, avoid)
                                ctx.numeric["replaced"] = ctx.numeric.get("replaced", 0) + done
                                ctx.numeric["formulas_cleared"] = ctx.numeric.get("formulas_cleared", 0) + cleared
                            elif "/charts/" in lowered and lowered.endswith(".xml"):
                                ctx.numeric["replaced"] = ctx.numeric.get("replaced", 0) + \
                                    numeric.anonymize_chart_cache(root, ctx.vault, avoid)
                            elif lowered == "xl/workbook.xml":
                                numeric.request_recalculation(root)
                        output_text.append(_part_text(root, info.filename))
                        if depth == 0 and info.filename == "docProps/core.xml" and getattr(ctx.vault, "vault_id", ""):
                            stamp_vault_marker(root, ctx.vault.vault_id)
                        raw = etree.tostring(root, xml_declaration=raw.lstrip().startswith(b"<?xml"),
                                             encoding="UTF-8", standalone=None)
                    zout.writestr(info, raw)
        warnings.extend(ctx.__dict__.get("image_review", [])[review_from:])
        if blocked_images:
            return FileResult(rel, "OOXML", FileStatus.BLOCKED, findings,
                              ["Данные на картинках внутри файла нельзя надёжно закрасить, файл не выдаётся: " + "; ".join(blocked_images[:3])])
        if finance_info is not None:
            verify_notes: list[str] = []
            leaks = finance_module.verify_output(tmp_name, ctx.vault.finance[finance_info["id"]], ctx.settings.finance_text_amounts,
                                                 verify_notes)
            finance_info["notes"] = list(finance_info.get("notes", [])) + verify_notes
            if leaks:
                ctx.vault.finance.pop(finance_info["id"], None)
                return FileResult(rel, "OOXML", FileStatus.BLOCKED, findings,
                                  ["В результате остались настоящие суммы (части файла: " + ", ".join(leaks[:4])
                                   + "). Файл не выдаётся."])
        os.replace(tmp_name, dst)
    except NestedBlocked as exc:
        return FileResult(rel, "OOXML", FileStatus.BLOCKED, findings,
                          [f"Вложенный объект нельзя надёжно обезличить, файл не выдаётся: {exc}"])
    finally:
        if skip_token is not None:
            _SKIP_SAFE_FORMULAS.reset(skip_token)
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    after = _zip_snapshot(dst)
    structural_keys = ("sheets", "slides", "formulas", "tables", "charts", "comments", "media", "embeddings", "macros", "signatures")
    # Удалённые эскиз и вложения — намеренное отличие, а не порча структуры.
    expected_names = [n for n in before["names"] if n not in dropped]
    expected_hashes = {n: changed_images.get(n, h) for n, h in before["binary_hashes"].items() if n not in dropped}
    expected = {**before, "embeddings": before["embeddings"] - len(removal.parts)}
    integrity_ok = (expected_names == after["names"] and expected_hashes == after["binary_hashes"]
                    and all(expected[k] == after[k] for k in structural_keys))
    residual = _residuals(detector, "\n".join(output_text), findings)
    if not integrity_ok:
        warnings.append("Нарушена структурная целостность OOXML")
    if residual:
        warnings.append("После обработки остались критические совпадения")
    embedded = unprocessed_embeddings(after["names"], depth) if ctx.settings.inspect_embedded else {}
    if embedded:
        warnings.append(embedded_warning(embedded))
    notices: list[str] = []
    if thumbnails:
        notices.append("Эскиз первой страницы удалён: на этой картинке читалось исходное содержимое. "
                       "Office создаст новый эскиз при следующем сохранении")
    if removal.parts:
        notices.append(removal_notice(removal))
    if whole_images:
        notices.append(imagereplace.notice_replaced(whole_images))
    if kept_images:
        if image_ocr:
            warnings.append(imagereplace.warn_kept_pixels(kept_images))
        else:
            warnings.append(f"Картинки и логотипы остаются в файле видимыми ({kept_images}): "
                            "распознавание текста недоступно или выключено, надписи не закрашены. "
                            "Лица, подписи, печати и надписи уйдут наружу как есть. "
                            "Замените картинки целиком или проверьте результат глазами до отправки.")
    if ctx.__dict__.get("logos_painted", 0) > logos_from:
        notices.append(f"Закрашено названий на логотипах: {ctx.__dict__['logos_painted'] - logos_from}.")
    if stripped_images:
        notices.append(f"Из картинок удалены служебные данные: EXIF, автор, место съёмки ({stripped_images})")
    if ctx.settings.inspect_embedded and after["media"] and not image_ocr and not whole_images:
        notices.append(f"В файле есть изображения ({after['media']}). "
                       "Текст на картинках программа не читает: проверьте их вручную")
    if amounts >= MANY_AMOUNTS and finance_info is None:
        notices.append(f"Числа в таблицах не обезличены (значений: {amounts}). Если суммы и показатели — коммерческая "
                       "тайна, включите «Заменять числа в Excel» и обезличьте файл заново")
    if finance_info is not None:
        notices.append(f"Числа: {finance_info['scaled']} ячеек замаскировано, {finance_info['formulas']} формул не тронуто, "
                       f"{len(finance_info['conflicts']) + len(finance_info.get('notes', []))} предупреждений, вне ячеек заменено {finance_info.get('surfaces', 0)}. Результаты формул очищены: Excel пересчитает их при открытии. "
                       "Масштабирование скрывает величины, но не соотношения.")
        warnings.extend(finance_info["conflicts"])
        warnings.extend(finance_info.get("notes", []))
    elif finance_hint:
        notices.append("Файл похож на финансовую модель: суммы видны. Включите «Скрывать суммы в Excel», "
                       "чтобы заменить их с сохранением формул и возвратом настоящих чисел.")
    status = FileStatus.CLEAN if integrity_ok and not residual and not warnings else FileStatus.REVIEW_REQUIRED
    result = FileResult(rel, "OOXML", status, findings, warnings, str(dst),
                        {"open_ok": True, "structure_equal": integrity_ok, "before": before, "after": after,
                         "dropped": sorted(dropped)})
    result.notices = notices
    return result


def _finance_prepass(parsed: dict, ctx: TransformContext, rel: str, warnings: list[str]) -> dict:
    """Маскирование сумм на разобранных частях книги: до обычного прохода по текстам (числа в нём не участвуют)."""
    model = finance_module.Model(parsed)
    plan = finance_module.build_plan(model, ctx.settings.finance_on_formula_conflict, ctx.settings.finance_scale_per_sheet)
    conflicts = [c.text for c in plan.conflicts]
    if plan.blocked:
        return {"blocked": True, "conflicts": conflicts}
    info = finance_module.apply_plan(model, plan, ctx.settings.finance_text_amounts, ctx.vault, rel)
    info["conflicts"] = conflicts
    if plan.excluded:
        info["conflicts"] = conflicts or ["Часть сумм осталась видимой: формулы с ними нельзя масштабировать"]
    if getattr(plan, "cross_sheet", False) and ctx.settings.finance_scale_per_sheet:
        info["conflicts"].append("Свой коэффициент для каждого листа не применён: формулы ссылаются на суммы других листов")
    ctx.numeric["finance_masked"] = ctx.numeric.get("finance_masked", 0) + info["scaled"]
    ctx.numeric["finance_formulas"] = ctx.numeric.get("finance_formulas", 0) + info["formulas"]
    ctx.numeric["finance_warnings"] = ctx.numeric.get("finance_warnings", 0) + len(info["conflicts"])
    return info


def _unknown_raw_part(name: str) -> bool:
    """Часть, которую программа не разбирает и про которую нельзя сказать, что в ней нет текста."""
    lowered = name.lower()
    if lowered.endswith((".xml", ".rels", ".vml")) or "/media/" in lowered or "/embeddings/" in lowered:
        return False        # xml разбирается отдельно, картинки и вложения — своими предупреждениями
    if lowered.endswith(BENIGN_RAW_EXTS + IMAGE_PART_EXTS) or lowered.endswith(RAW_TEXT_EXTS):
        return False
    return not lowered.endswith("/")


def _transform_raw_text(raw: bytes, name: str, rel: str, detector, ctx: TransformContext):
    """Текстовая часть контейнера (html для altChunk, txt, csv, json, svg) обезличивается как отдельный файл."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ("in" + Path(name).suffix)
        target = Path(tmp) / ("out" + Path(name).suffix)
        source.write_bytes(raw)
        try:
            result = transform_text_file(source, target, rel, detector, ctx)
        except Exception:
            return raw, None
        return target.read_bytes(), result


def _transform_embedded(raw: bytes, name: str, rel: str, detector, ctx: TransformContext, depth: int):
    """Вложенная книга (данные диаграммы) обезличивается тем же способом, что и сам файл."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ("in" + Path(name).suffix)
        target = Path(tmp) / ("out" + Path(name).suffix)
        source.write_bytes(raw)
        if depth + 1 > MAX_NEST_DEPTH:
            raise NestedBlocked(f"{name}: слишком глубокая вложенность")
        try:
            result = transform_ooxml(source, target, rel, detector, ctx, depth + 1)
        except NestedBlocked:
            raise
        except Exception:
            raise NestedBlocked(f"{name}: вложенный файл не удалось обезличить")
        if result.status == FileStatus.BLOCKED or not target.exists():
            raise NestedBlocked(f"{name}: " + ("; ".join(result.warnings) or "вложенный файл заблокирован"))
        return target.read_bytes(), result


MAX_NESTED_BYTES = 512 * 1024 * 1024


def _transform_zip(raw: bytes, name: str, rel: str, detector, ctx: TransformContext, depth: int):
    """Произвольный zip внутри файла: каждая часть обезличивается тем же способом, глубже предела — блокировка."""
    if depth > MAX_NEST_DEPTH:
        raise NestedBlocked(f"{name}: слишком глубокая вложенность")
    try:
        zin = zipfile.ZipFile(io.BytesIO(raw))
        infos = zin.infolist()
        if sum(i.file_size for i in infos) > MAX_NESTED_BYTES:
            raise NestedBlocked(f"{name}: архив слишком велик после распаковки")
    except zipfile.BadZipFile:
        raise NestedBlocked(f"{name}: архив не читается")
    findings: list[Finding] = []
    warnings: list[str] = []
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            if info.is_dir():
                zout.writestr(info, b"")
                continue
            try:
                data = zin.read(info.filename)
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                raise NestedBlocked(f"{name}/{info.filename}: часть не читается ({type(exc).__name__})")
            lowered = info.filename.lower()
            label = f"{name}/{info.filename}"
            if lowered.endswith(EMBEDDED_SUFFIXES):
                data, inner = _transform_embedded(data, label, rel, detector, ctx, depth)
                findings.extend(inner.findings)
                warnings.extend(f"{info.filename}: {w}" for w in inner.warnings)
            elif lowered.endswith(".zip") or data[:4] == b"PK\x03\x04":
                data, f2, w2 = _transform_zip(data, label, rel, detector, ctx, depth + 1)
                findings.extend(f2)
                warnings.extend(f"{info.filename}: {w}" for w in w2)
            elif lowered.endswith(RAW_TEXT_EXTS):
                new_raw, inner = _transform_raw_text(data, info.filename, rel, detector, ctx)
                if inner is None:
                    raise NestedBlocked(f"{label}: текст не удалось обезличить")
                if inner.status == FileStatus.BLOCKED:
                    raise NestedBlocked(f"{label}: " + "; ".join(inner.warnings))
                findings.extend(inner.findings)
                data = new_raw
            elif imagereplace.whole_image(ctx.settings) and imagereplace.replaces_part(lowered, data):
                try:
                    data = imagereplace.replace_part(data, lowered, ctx)
                except imagereplace.ImageStoreFull as exc:
                    raise NestedBlocked(f"{label}: {exc}")
            elif lowered.endswith(IMAGE_PART_EXTS + tuple(IMAGE_EXTENSIONS)) or lowered.endswith(BENIGN_RAW_EXTS):
                warnings.append(f"Картинка или двоичные данные внутри архива не проверялись: {info.filename}")
            else:
                warnings.append(f"Часть архива не обработана, её содержимое осталось как есть: {info.filename}")
            zout.writestr(info, data)
    return out.getvalue(), findings, warnings


def _is_worksheet(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("xl/worksheets/") and lowered.endswith(".xml") and "/_rels/" not in lowered


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _pdf_warnings(images: int, chars: int, pages: int, annotations: int, links: int, embedded: int, ocr_on: bool = False,
                  barcodes_on: bool = True) -> list[str]:
    """Проблемы, из-за которых нельзя утверждать, что файл безопасен."""
    warnings = []
    if images and chars < max(30, pages * 20) and not ocr_on:
        warnings.append("Похоже, это скан: текста в нём почти нет, а изображения программа не читает. "
                        "Имена на изображении останутся видимыми")
    if images and not barcodes_on:
        warnings.append("QR-коды и штрихкоды на изображениях PDF на этом компьютере не проверяются: в них могут быть данные")
    if annotations:
        warnings.append("В PDF есть примечания или комментарии: их содержимое не проверялось")
    if embedded:
        warnings.append("В PDF есть вложенные файлы: они не обезличиваются")
    return warnings


def _pdf_notices(images: int, chars: int, pages: int, links: int, ocr_words: int = 0, ocr_on: bool = False,
                 barcodes_on: bool = False) -> list[str]:
    notices = []
    if images and ocr_on:
        notices.append(f"Текст на изображениях распознан ({ocr_words} слов) и проверен"
                       + ("; QR-коды и штрихкоды проверены" if barcodes_on else ""))
    elif images and chars >= max(30, pages * 20):
        notices.append(f"В PDF есть изображения ({images}). Текст на них программа не читает: проверьте вручную")
    if links:
        notices.append("В PDF есть гиперссылки: адреса в них не изменялись")
    return notices


# Свойства документа PDF. Имя автора живёт здесь, а не на странице, и до сих пор уезжало
# наружу нетронутым: файл без единого имени в тексте объявлялся чистым вместе с «/Author».
PDF_METADATA_FIELDS = ("title", "author", "subject", "keywords", "creator", "producer")


def _pdf_metadata(doc) -> dict[str, str]:
    meta = doc.metadata or {}
    return {field: meta[field] for field in PDF_METADATA_FIELDS if meta.get(field)}


@dataclass(slots=True)
class PdfHit:
    """Найденное значение с символами на странице (или нескольких, если оно перенесено через разрыв)."""
    finding: Finding
    ids: dict[int, list[int]]


PDF_VIEWS = ("lines", "join", "dehyphen")


def _pdf_page_hits(detector, ctx, rel: str, page_no: int, chars: PageChars) -> list[tuple[Finding, set[int]]]:
    """Находки по трём видам текста страницы: как есть, строки склеены, перенос слов убран.

    Значение, перенесённое на другую строку («Иванов Иван» / «Петрович», «7707-» / «083893»), в обычном виде
    не находится, в склеенном находится; вид выбирается по тому, какой охватил больше символов.
    """
    base = chars.view("lines")
    found: list[tuple[int, Finding, set[int]]] = []
    for order, mode in enumerate(PDF_VIEWS):
        view = base if mode == "lines" else chars.view(mode)
        if mode != "lines" and view.text == base.text:
            continue
        items = detector.scan(view.text, rel, f"page:{page_no}")
        if ctx is not None:
            items = ctx.apply_overrides(items)
        protected = set()
        if ctx is not None:
            for regex, email in ((TOKEN_RE, False), (EMAIL_TOKEN_RE, True)):
                for match in regex.finditer(view.text):
                    if ctx.vault.lookup(*parse_match(match, email=email)).status == "ok":
                        protected.update(view.ids(*match.span()))
        for f in items:
            ids = set(view.ids(f.start, f.end))
            if ids & protected:
                # A retry may rediscover e.g. "Domain" inside our Domain1 as
                # a person's name. Never turn an existing label into another
                # label; retain and mask any actual data outside it.
                ids -= protected
                original = "".join(chars.chars[i].c for i in sorted(ids))
                if not original.strip():
                    continue
                f = replace(f, original=original, person_id=None,
                            key=finding_id("pdf-label-remainder", f.category, original))
            if not ids:
                continue
            if mode != "lines" and len({chars.chars[i].line for i in ids}) < 2:
                continue            # внутри одной строки то же самое уже найдено обычным видом
            found.append((order, f, ids))
    found.sort(key=lambda x: (-len(x[2]), x[1].decision != Decision.AUTO, x[0]))
    kept: list[tuple[Finding, set[int]]] = []
    line_sets = [ids for order, _, ids in found if order == 0]
    for order, f, ids in found:
        if any(ids <= other for _, other in kept):
            continue
        # A value glued across a line break ("Delacroix, Thomas" / "Northwind Holdings" -> a company "Thomas Northwind Holdings") that cuts
        # into a value found on the line itself is the glue's fault: both would be drawn over the same letters and restored twice.
        if order and any(ids & lo and not lo <= ids for lo in line_sets):
            continue
        kept.append((f, ids))
    kept.sort(key=lambda x: min(x[1]))
    return kept


def _pdf_seam_hits(detector, ctx, rel: str, index: int, first: PageChars, second: PageChars) -> list[PdfHit]:
    merged = PageChars.seam(first, second)
    hits = []
    for f, ids in _pdf_page_hits(detector, ctx, rel, index + 1, merged):
        per_page: dict[int, list[int]] = {}
        for i in sorted(ids):
            tag, cid = merged.origin[i]
            per_page.setdefault(index + tag, []).append(cid)
        if len(per_page) == 2:
            hits.append(PdfHit(f, per_page))
    return hits


def _pdf_hits(detector, ctx, rel: str, maps: list[PageChars], strict: bool = False) -> list[PdfHit]:
    hits: list[PdfHit] = []
    for i, chars in enumerate(maps):
        page = _pdf_page_hits(detector, ctx, rel, i + 1, chars)
        hits.extend(PdfHit(f, {i: sorted(ids)}) for f, ids in page)
        if strict and not getattr(chars, "has_ocr", False) and ctx is not None:
            # Повторный проход после остатка: то, что находят правила проверки в готовом файле, закрашивается тоже (проверка не сильнее закраски).
            taken = set().union(*[ids for _, ids in page]) if page else set()
            hits.extend(PdfHit(f, {i: sorted(ids)}) for f, ids in _verify_hits(detector, chars, rel, taken))
        if getattr(chars, "has_ocr", False) and ctx is not None:
            # Закраска не слабее проверки: то, что находят правила проверки в прочитанном распознаванием тексте, закрашивается тоже.
            taken = set().union(*[ids for _, ids in page]) if page else set()
            noise = lambda v: bool(GLUED_EMAIL_TOKEN.search(v) or MISREAD_EMAIL_TOKEN.search(v) or GARBLED_EMAIL_TOKEN.search(v))
            more = _verify_hits(detector, chars, rel, taken, skip=noise)
            hits.extend(PdfHit(f, {i: sorted(ids)}) for f, ids in more)
            taken |= set().union(*[ids for _, ids in more]) if more else set()
            labelled = _label_value_hits(chars, [(h.finding, set(h.ids[i])) for h in hits if i in h.ids], rel, noise)
            hits.extend(PdfHit(f, {i: sorted(ids)}) for f, ids in labelled)
            taken |= set().union(*[ids for _, ids in labelled]) if labelled else set()
            # Каждый слой распознавания читается и проверяется отдельно (как на картинке): слово, которое один проход прочитал
            # с ошибкой («sk live_…», «Marcus R Haverford» без точки), другой читает верно; находка переносится на основную карту.
            for layer in getattr(chars, "shadows", ()):
                found = [(f, ids) for f, ids in _pdf_page_hits(detector, ctx, rel, i + 1, layer) if f.decision == Decision.AUTO]
                found += _verify_hits(detector, layer, rel, set(), skip=noise)
                for f, ids in found:
                    mapped = _map_layer_ids(chars, layer, ids)
                    if mapped and not mapped <= taken:
                        hits.append(PdfHit(f, {i: sorted(mapped)}))
                        taken |= mapped
    for i in range(len(maps) - 1):
        for seam in _pdf_seam_hits(detector, ctx, rel, i, maps[i], maps[i + 1]):
            hits = _pdf_merge_seam_hit(hits, seam, maps)
    return hits


def _pdf_merge_seam_hit(hits: list[PdfHit], seam: PdfHit, maps: list[PageChars] | None = None) -> list[PdfHit]:
    """One replacement per source glyph, including entities crossing pages."""
    if seam.finding.decision != Decision.AUTO:
        return [*hits, seam]
    seam_ids = {(page, cid) for page, ids in seam.ids.items() for cid in ids}
    if maps is not None:
        covered = {(page, cid) for hit in hits if hit.finding.decision == Decision.AUTO
                   for page, ids in hit.ids.items() for cid in ids}
        if seam_ids & covered:
            # Keep page-local identities and positions. Only the still-unmasked
            # portion of the seam needs another label; copying the complete
            # seam original would restore already-covered glyphs twice.
            remaining = seam_ids - covered
            fragments = []
            for page in sorted(seam.ids):
                chars = maps[page]
                for line in chars.lines:
                    group = []
                    for cid in [*line, None]:
                        if cid is not None and (page, cid) in remaining:
                            group.append(cid)
                            continue
                        if group:
                            original = "".join(chars.chars[i].c for i in group)
                            if original.strip():
                                fragment = replace(seam.finding, original=original, person_id=None,
                                                   key=finding_id("pdf-seam", seam.finding.category, original),
                                                   finding_id=finding_id(seam.finding.finding_id, page, *group))
                                fragments.append(PdfHit(fragment, {page: group}))
                            group = []
            mapped = {(page, cid) for fragment in fragments for page, ids in fragment.ids.items() for cid in ids}
            if any(not maps[page].chars[cid].c.isspace() for page, cid in remaining - mapped):
                raise ValueError("Не удалось сопоставить часть значения на разрыве страниц PDF")
            return [*hits, *fragments]
    overlaps = []
    for index, hit in enumerate(hits):
        if hit.finding.decision != Decision.AUTO:
            continue
        hit_ids = {(page, cid) for page, ids in hit.ids.items() for cid in ids}
        if not seam_ids & hit_ids:
            continue
        if seam_ids <= hit_ids:
            return hits                # already covered in full by one coherent replacement
        if not hit_ids <= seam_ids:
            # Dropping either finding would leave part of its sensitive text
            # unmasked; drawing both duplicates originals during restoration.
            raise ValueError("Пересекающиеся значения на разрыве страниц PDF нельзя безопасно заменить")
        overlaps.append(index)
    removed = set(overlaps)
    return [hit for index, hit in enumerate(hits) if index not in removed] + [seam]


def _pdf_joined_texts(maps: list[PageChars]) -> list[str]:
    """Текст со склеенными строками и разрывами страниц: полное ФИО, перенесённое на другую строку, тоже учит имена."""
    texts = [m.view(mode).text for m in maps for mode in ("join", "dehyphen")]
    for first, second in zip(maps, maps[1:]):
        seam = PageChars.seam(first, second)
        texts.extend(seam.view(mode).text for mode in ("join", "dehyphen"))
    return texts


def _pdf_whole_word(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start else " "
    after = text[end] if end < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _pdf_extra_hits(hits: list[PdfHit], maps: list[PageChars]) -> list[PdfHit]:
    """Те же значения в местах, где детектор их не отметил (у него своя логика контекста): замена должна быть везде."""
    covered: dict[int, set[int]] = {}
    for hit in hits:
        for page, ids in hit.ids.items():
            covered.setdefault(page, set()).update(ids)
    first_of: dict[str, Finding] = {}
    for hit in hits:
        if hit.finding.decision == Decision.AUTO and hit.finding.original and hit.finding.category not in {"TERM", "FILE", "META"}:
            first_of.setdefault(hit.finding.original, hit.finding)
    extra: list[PdfHit] = []
    for page, chars in enumerate(maps):
        views = [chars.view(m) for m in PDF_VIEWS]
        for value, finding in first_of.items():
            for view in views:
                for start, end in find_all(view, value):
                    if not _pdf_whole_word(view.text, start, end):
                        continue
                    ids = view.ids(start, end)
                    if not ids or covered.setdefault(page, set()) & set(ids):
                        continue
                    covered[page].update(ids)
                    extra.append(PdfHit(finding, {page: ids}))
    return extra


def _pdf_image_pages(doc) -> tuple[int, list[int]]:
    """Сколько изображений в файле и на каких страницах они занимают больше половины листа (скан)."""
    images, scans = 0, []
    for index, page in enumerate(doc):
        placed = page.get_images(full=True)
        images += len(placed)
        if not placed:
            continue
        area = max(1.0, page.rect.width * page.rect.height)
        covered = 0.0
        try:
            for info in page.get_image_info():
                covered += abs(fitz.Rect(info["bbox"]) & page.rect)
        except Exception:
            covered = area
        if covered / area >= .5:
            scans.append(index)
    return images, scans


VECTOR_TEXT_MIN_PATHS = 30      # столько мелких контуров на странице — признак текста в кривых
VECTOR_TEXT_MIN_PATHS_NO_TEXT = 6   # на странице без текстового слоя хватает и нескольких букв в кривых


def _pdf_font_unreadable(doc, page) -> bool:
    """Шрифт без таблицы ToUnicode (составной с Identity-кодировкой или Type3): извлечённый текст — набор кодов глифов."""
    try:
        fonts = page.get_fonts(full=True)
    except Exception:
        return False
    for font in fonts:
        xref, kind, encoding = font[0], str(font[2]), str(font[5])
        if kind not in ("Type0", "Type3") or (kind == "Type0" and not encoding.startswith("Identity")):
            continue
        try:
            if doc.xref_get_key(xref, "ToUnicode")[0] in ("null", "undefined"):
                return True
        except Exception:
            continue
    return False


def _pdf_garbage_text(chars: PageChars) -> bool:
    """Большая доля символов вне букв, цифр и знаков: так выглядит текст с испорченной таблицей кодов."""
    letters = [c.c for c in chars.chars if not c.c.isspace()]
    if len(letters) < 5:
        return False
    bad = sum(1 for c in letters if c == "\ufffd" or unicodedata.category(c) in ("Co", "Cc", "Cn", "Cs"))
    return bad / len(letters) >= .2


def _pdf_unreadable_pages(doc, maps: list[PageChars]) -> list[int]:
    """Страницы, чей текстовый слой нельзя прочитать как текст: их содержимое видно глазами, а правила его не видят."""
    out = []
    for index, (page, chars) in enumerate(zip(doc, maps)):
        if not any(not c.c.isspace() for c in chars.chars):
            continue
        if _pdf_font_unreadable(doc, page) or _pdf_garbage_text(chars):
            out.append(index)
    return out


def _pdf_unreadable_warning(pages: list[int]) -> str:
    listed = ", ".join(str(i + 1) for i in pages[:8]) + ("…" if len(pages) > 8 else "")
    return (f"На страницах PDF ({listed}) текст нельзя прочитать из файла: у шрифта нет таблицы символов. Он виден на экране, "
            "но программа его не находит, поэтому без распознавания текста данные остались бы видимыми. Файл не выдаётся")


def _pdf_image_rect(page, min_paths: int = VECTOR_TEXT_MIN_PATHS) -> fitz.Rect | None:
    """Прямоугольник страницы, занятый изображениями (объединение), или None, если их нет или они крошечные."""
    rect = None
    area = ocr.unrotated_rect(page)
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        infos = []
    for info in infos:
        if imagereplace.is_placeholder_info(page.parent, info):
            continue        # заглушка W10 (1x1 или 8x1 пиксель): читать на ней нечего, оригинала в файле нет
        r = fitz.Rect(info["bbox"]) & area
        if r.is_empty or r.width < 20 or r.height < 12:
            continue
        rect = r if rect is None else rect | r
    # Текст, переведённый в кривые (экспорт из дизайн-редактора): слоя текста нет, а буквы читаются глазами и OCR.
    # Признак — много мелких контуров; область распознавания — их объединение.
    try:
        small = [fitz.Rect(d["rect"]) for d in page.get_drawings() if d.get("rect") is not None
                 and 0 < d["rect"].width <= 60 and 0 < d["rect"].height <= 60]
    except Exception:
        small = []
    if len(small) >= min_paths:
        union = small[0]
        for r in small[1:]:
            union = union | r
        union = (union + (-2, -2, 2, 2)) & area
        if not union.is_empty and union.width >= 20 and union.height >= 12:
            rect = union if rect is None else rect | union
    return rect


def _mask_drawn_chars(maps: list[PageChars], rects: dict[int, list], start: list[int] | None = None) -> int:
    """Знаки распознавания, лежащие на метках, которые нарисовали мы, становятся пробелами: искажённое чтение
    нашей метки («omal@examgls.com» вместо «email1@example.com») не данные. Возвращает число закрытых знаков.

    rects — по страницам пары (рамка, метка). start — с какого знака страницы считать (обычный текст до него остаётся).
    Исходное значение под меткой стёрто или закрашено, а знаки, выступающие за метку, остаются в тексте и проверяются как прежде.
    Слово, у которого все знаки делят одну рамку (слой без раскладки по буквам), закрывается только в той части,
    что похожа на метку («Свидетел+Name5» → «Свидетел»).
    """
    from difflib import SequenceMatcher
    masked = 0
    for index, m in enumerate(maps):
        marks = [(fitz.Rect(r), token) for r, token in rects.get(index, ())]
        boxes = [r + (-1.5, -1.5, 1.5, 1.5) for r, _ in marks]
        if not boxes:
            continue
        grid = RectGrid(boxes)         # сетка: перебор всех меток для каждого знака квадратичен (сотни тысяч знаков, сотни меток)
        for layer in (m, *getattr(m, "shadows", ())):
            chars = layer.chars
            first = start[index] if start and layer is m else 0
            word_level = [False] * len(chars)
            for i in range(first, len(chars)):
                ch = chars[i]
                if ch.c == " ":
                    continue
                if ch.x1 - ch.x0 > 2.5 * max(ch.y1 - ch.y0, 1.0):
                    word_level[i] = True
                    continue
                at = fitz.Point((ch.x0 + ch.x1) / 2, (ch.y0 + ch.y1) / 2)
                if grid.contains(at):
                    ch.c = " "
                    masked += 1
            i = first
            while i < len(chars):
                if not word_level[i]:
                    i += 1
                    continue
                j = i
                while j < len(chars) and word_level[j] and chars[j].line == chars[i].line:
                    j += 1
                word = "".join(c.c for c in chars[i:j])
                box = fitz.Rect(min(c.x0 for c in chars[i:j]), min(c.y0 for c in chars[i:j]),
                                max(c.x1 for c in chars[i:j]), max(c.y1 for c in chars[i:j]))
                for rect, token in marks:
                    area = (box & rect).get_area() if box.intersects(rect) else 0
                    if area < .1 * min(box.get_area(), rect.get_area()):
                        continue
                    n = len(token)
                    best = (0.0, 0, 0)
                    for size in range(max(1, n - 2), n + 3):
                        for k in range(0, len(word) - size + 1):
                            ratio = SequenceMatcher(None, word[k:k + size].lower(), token.lower()).ratio()
                            if ratio > best[0]:
                                best = (ratio, k, k + size)
                    if best[0] >= .72:
                        for c in chars[i + best[1]:i + best[2]]:
                            if c.c != " ":
                                c.c = " "
                                masked += 1
                i = j
    return masked


def _pdf_ocr_maps(doc, maps: list[PageChars], force: set[int] | frozenset = frozenset(),
                  brands: list | None = None, register=None) -> tuple[int, str]:
    """Распознаёт текст на изображениях страниц и добавляет его в карты символов. Возвращает (слов, ошибка).

    force — страницы с нечитаемым текстовым слоем: он отбрасывается, страница читается целиком по картинке.
    """
    total = 0
    if not ocr.available():
        return 0, ""
    try:
        for index, (page, chars) in enumerate(zip(doc, maps)):
            if index in force:
                chars.chars.clear(), chars.lines.clear(), chars.blocks.clear(), chars.force.clear()
                rect = ocr.unrotated_rect(page)
            else:
                no_text = sum(1 for c in chars.chars if c.c.isalnum()) < 5
                rect = _pdf_image_rect(page, VECTOR_TEXT_MIN_PATHS_NO_TEXT if no_text else VECTOR_TEXT_MIN_PATHS)
            if rect is None:
                continue
            if brands is None or index in force or rect.get_area() > .9 * ocr.unrotated_rect(page).get_area():
                # Скан на всю страницу читается теми же проходами, что и отдельная картинка: контраст, инверсия, увеличение, каналы.
                # Слова других проходов добавляются там, где первый ничего не прочитал (Vision пропускает строки целиком).
                chars.shadows = []
                for words in ocr.ocr_image_layers(page, rect=rect):
                    total += ocr.add_ocr_chars(chars, words)
                    layer = PageChars(page)
                    if index in force:
                        layer.chars.clear(), layer.lines.clear(), layer.blocks.clear(), layer.force.clear()
                    if ocr.add_ocr_chars(layer, words):
                        chars.shadows.append(layer)
                continue
            # Картинка внутри страницы: несколько проходов, слова других проходов добавляются там, где первый ничего не прочитал.
            layers = ocr.ocr_image_layers(page, rect=rect)
            for words in layers:
                total += ocr.add_ocr_chars(chars, words)
            found = imagetext.distinct([p for words in layers for p in imagetext.brand_phrases(words, [])])
            for phrase in found:
                if register is not None and imagetext.paintable(phrase, len(found)):
                    register(phrase)
                parts = phrase.lower().split()
                rects = [fitz.Rect(w.x0, w.y0, w.x1, w.y1) for words in layers for w in words if w.text.lower() in parts]
                brands.append((index, phrase, rects))
    except Exception as exc:
        return total, f"{type(exc).__name__}"
    return total, ""


def _pdf_barcodes(doc, rel: str, detector) -> tuple[dict[int, list[fitz.Rect]], int, str]:
    """QR и штрихкоды на изображениях страниц: (опасные рамки по страницам, число безопасных, ошибка)."""
    unsafe: dict[int, list[fitz.Rect]] = {}
    safe = 0
    if not ocr.barcodes_available():
        return unsafe, 0, ""
    try:
        for index, page in enumerate(doc):
            rect = _pdf_image_rect(page)
            if rect is None:
                continue
            codes = ocr.detect_barcodes(page, rect + (-4, -4, 4, 4))
            bad = _unsafe_barcodes(codes, detector, rel)
            safe += len(codes) - len(bad)
            if bad:
                unsafe[index] = [c.rect for c in bad]
    except Exception as exc:
        return unsafe, safe, type(exc).__name__
    return unsafe, safe, ""


def _pdf_scan_warning(scans: list[int]) -> str:
    pages = ", ".join(str(i + 1) for i in scans[:8]) + ("…" if len(scans) > 8 else "")
    return (f"Страницы PDF заняты изображением (скан): {pages}. Текст на изображении программа не читает, "
            "поэтому имена и номера на нём остались бы видимыми. Файл не выдаётся")


def _pdf_page_images(doc, page) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for img in page.get_images(full=True):
        try:
            out[img[0]] = doc.extract_image(img[0])["image"]
        except Exception:
            continue
    return out


def _pdf_stash_page_images(doc, page, before: dict[int, bytes], labels: list[str], ctx) -> int:
    """Оригиналы закрашенных картинок страницы сохраняются в хранилище: при возврате страница получает прежние пиксели.
    После закраски PyMuPDF заводит новые объекты картинок, поэтому пары берутся по порядку на странице."""
    import json
    after = _pdf_page_images(doc, page)
    old = list(before.values())
    done = 0
    for index, new in enumerate(after.values()):
        if index >= len(old) or new == old[index]:
            continue
        sha = sha256_bytes(new)
        ctx.vault.stash_image(sha, old[index])
        ctx.vault.stash_image(sha + "_labels", json.dumps(labels).encode("utf-8"))
        done += 1
    return done


VECTOR_CROP_DPI = 200


def vector_key(page_index: int, token: str) -> str:
    return sha256_bytes(f"vecpage|{page_index}|{token}".encode("utf-8"))


def _pdf_stash_vector_crops(ctx, page_index: int, crops: list[tuple[str, "fitz.Rect", bytes]]) -> None:
    """Текст, нарисованный контурами (логотип, заголовок-рисунок), при закраске теряет графику: прежние пиксели области
    сохраняются в хранилище и при возврате ложатся на место метки, как картинка скана."""
    import json
    by_token: dict[str, list] = {}
    for token, rect, png in crops:
        sha = sha256_bytes(png)
        ctx.vault.stash_image(sha, png)
        by_token.setdefault(token, []).append([rect.x0, rect.y0, rect.x1, rect.y1, sha])
    for token, entries in by_token.items():
        ctx.vault.stash_image(vector_key(page_index, token), json.dumps(entries).encode("utf-8"))


def pdf_is_signed(doc) -> bool:
    """Настоящая подпись документа: словарь подписи со /ByteRange. Права использования Reader (/Perms /UR3, /UR)
    и пустые поля подписи подписью не считаются: они не нарушаются изменением файла."""
    if getattr(doc, "get_sigflags", lambda: -1)() <= 0:
        return False
    usage: set[int] = set()
    try:
        cat = doc.pdf_catalog()
        kind, value = doc.xref_get_key(cat, "Perms")
        if kind == "xref":
            kind, value = "dict", doc.xref_object(int(value.split()[0]), compressed=True)
        if kind == "dict":
            for key in ("UR3", "UR"):
                m = re.search(rf"/{key}\s+(\d+)\s+0\s+R", value)
                if m:
                    usage.add(int(m.group(1)))
    except Exception:
        return True
    for xref in range(1, doc.xref_length()):
        try:
            body = doc.xref_object(xref, compressed=True)
        except Exception:
            continue
        if "/ByteRange" not in body or xref in usage:
            continue
        if re.search(r"/TransformMethod\s*/UR3?\b", body) and "/DocMDP" not in body:
            continue
        return True
    return False


def scan_pdf(path: Path, rel: str, detector) -> FileResult:
    findings: list[Finding] = []
    try:
        doc = fitz.open(path)
        if pdf_is_signed(doc):
            doc.close()
            return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=["PDF содержит цифровую подпись; изменение нарушит её"])
        _pdf_open_layers(doc)
        pages, chars, annotations, links = len(doc), 0, 0, 0
        embedded = getattr(doc, "embfile_count", lambda: 0)()
        maps = [PageChars(page) for page in doc]
        images, scans = _pdf_image_pages(doc)
        unreadable = _pdf_unreadable_pages(doc, maps)
        ocr_words, ocr_error = _pdf_ocr_maps(doc, maps, set(unreadable))
        code_rects, _, code_error = _pdf_barcodes(doc, rel, detector)
        if ocr_words or (ocr.available() and not ocr_error):
            scans = []
        for page in doc:
            annotations += sum(1 for _ in (page.annots() or []))
            links += len(page.get_links())
        chars = sum(len(m.view("lines").text.strip()) for m in maps)
        metadata = _pdf_metadata(doc)
        doc.close()
        detector.harvest("\n".join([*(m.view("lines").text for m in maps), *_pdf_joined_texts(maps)]), rel)
        findings.extend(h.finding for h in _pdf_hits(detector, None, rel, maps))
        for field, value in metadata.items():
            findings.extend(detector.scan(value, rel, f"metadata:{field}"))
        warnings = _pdf_warnings(images, chars, pages, annotations, links, embedded, ocr.available() and not ocr_error,
                                 ocr.barcodes_available())
        if unreadable and (ocr_error or not ocr.available()):
            warnings.insert(0, _pdf_unreadable_warning(unreadable))
        if code_error:
            warnings.insert(0, "Не удалось проверить QR-коды и штрихкоды на изображениях PDF")
        if code_rects:
            count = sum(len(v) for v in code_rects.values())
            warnings.insert(0, f"На изображениях PDF есть QR-коды или штрихкоды с данными ({count}): при обезличивании они закрашиваются")
        if ocr_error:
            warnings.insert(0, "Не удалось распознать текст на изображениях PDF")
        if scans:
            warnings.insert(0, _pdf_scan_warning(scans))
        status = FileStatus.REVIEW_REQUIRED if warnings else FileStatus.CLEAN
        return FileResult(rel, "PDF", status, findings, warnings,
                          integrity={"pages": pages, "images": images, "text_chars": chars,
                                     "annotations": annotations, "links": links, "embedded": embedded})
    except Exception as exc:
        return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=[f"PDF не открывается: {type(exc).__name__}"])


PDF_PERSONAL_FIELDS = ("title", "author", "subject", "keywords")


def _pdf_extra_texts(doc) -> list[str]:
    """Текст вне страниц: закладки, примечания, свойства документа."""
    texts = list(_pdf_metadata(doc).values())
    try:
        texts.extend(str(entry[1]) for entry in doc.get_toc(simple=False))
    except Exception:
        pass
    for page in doc:
        for annot in (page.annots() or []):
            try:
                texts.extend(str(v) for k, v in (annot.info or {}).items() if k in ("content", "title", "subject") and v)
            except Exception:
                continue
        try:
            texts.extend(str(w.field_value) for w in (page.widgets() or []) if isinstance(w.field_value, str) and w.field_value)
        except Exception:
            continue
    return texts


def _scrub_pdf_extras(doc, rel: str, detector, ctx: TransformContext, findings: list[Finding]) -> int:
    """Закладки, XMP и текст примечаний: такое же содержимое файла, как страницы, но в других местах.

    Возвращает, сколько примечаний обработано (их текст обезличен).
    """
    try:
        doc.del_xml_metadata()        # XMP дублирует автора и название и не покрыт обычными свойствами
    except Exception:
        pass
    try:
        toc = doc.get_toc(simple=False)
        changed = False
        for entry in toc:
            found = ctx.apply_overrides(detector.scan(entry[1], rel, "toc"))
            if found:
                findings.extend(found)
                entry[1] = replace_findings(entry[1], found, ctx)
                changed = True
        if changed:
            doc.set_toc(toc)
    except Exception:
        pass
    done = 0
    for page in doc:
        try:
            for widget in (page.widgets() or []):
                value = widget.field_value
                if not isinstance(value, str) or not value.strip() or has_token(value):
                    continue
                found = ctx.apply_overrides(detector.scan(value, rel, "form-field"))
                if found:
                    findings.extend(found)
                    widget.field_value = replace_findings(value, found, ctx)
                    widget.update()
        except Exception:
            pass
        for annot in (page.annots() or []):
            try:
                info = dict(annot.info or {})
                new_info, touched = {}, False
                for key in ("content", "title", "subject"):
                    value = info.get(key) or ""
                    if not value.strip() or has_token(value):
                        continue
                    found = ctx.apply_overrides(detector.scan(value, rel, f"annotation:{key}"))
                    if found:
                        findings.extend(found)
                        new_info[key] = replace_findings(value, found, ctx)
                        touched = True
                if touched:
                    annot.set_info(**new_info)
                    annot.update()
                if not (info.get("content") or "").strip() or touched:
                    done += 1
            except Exception:
                continue
    return done



def _pdf_open_layers(doc) -> None:
    """Скрытые слои (OCG) не видны get_text: текст в них не находился и не заменялся. Делаем все слои видимыми."""
    try:
        doc.xref_set_key(doc.pdf_catalog(), "OCProperties", "null")
    except Exception:
        pass


def _pdf_drop_attachments(doc, findings_note: list[str]) -> int:
    """Вложенные файлы и аннотации-вложения несут исходные данные целиком: удаляются, о чём сообщается."""
    dropped = 0
    try:
        for name in list(doc.embfile_names()):
            doc.embfile_del(name)
            dropped += 1
    except Exception:
        pass
    for page in doc:
        try:
            for annot in list(page.annots() or []):
                if annot.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT:
                    page.delete_annot(annot)
                    dropped += 1
        except Exception:
            continue
    return dropped


def _pdf_clean_info(doc) -> None:
    """В /Info остаются только стандартные поля: нестандартные («Company», «CustomOwner») несут имена и организации."""
    try:
        info = doc.xref_get_key(-1, "Info")
        if info[0] != "xref":
            return
        xref = int(info[1].split()[0])
        keep = {"Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate", "Trapped"}
        for key in doc.xref_get_keys(xref):
            if key not in keep:
                doc.xref_set_key(xref, key, "null")
    except Exception:
        pass


def _pdf_scrub_widget_extras(doc) -> None:
    """Подсказка (/TU), имя для экспорта (/TM) и значение по умолчанию (/DV) поля формы остаются в файле после замены значения."""
    for page in doc:
        try:
            for widget in (page.widgets() or []):
                for key in ("TU", "TM", "DV", "Opt"):       # /Opt: варианты выбора списка могут быть именами и адресами
                    doc.xref_set_key(widget.xref, key, "null")
        except Exception:
            continue
    # Миниатюра страницы (/Thumb) хранит пиксели исходной страницы, пользовательские словари страницы и дерево
    # структуры (/Alt, /E, /ActualText) — тексты вне страницы, которые правила не проверяют.
    for page in doc:
        for key in ("Thumb", "PieceInfo"):
            try:
                doc.xref_set_key(page.xref, key, "null")
            except Exception:
                continue
    try:
        doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", "null")
        doc.xref_set_key(doc.pdf_catalog(), "MarkInfo", "null")
    except Exception:
        pass


def _pdf_scrub_links(doc, rel: str, detector, ctx, findings: list[Finding]) -> int:
    """Ссылки с адресом, имеющим персональные данные (mailto:, адрес сайта), удаляются: адрес в аннотации-ссылке не страница."""
    removed = 0
    for page in doc:
        for link in list(page.get_links()):
            uri = link.get("uri") or ""
            if not uri:
                continue
            found = ctx.apply_overrides(detector.scan(uri, rel, "link"))
            if found:
                findings.extend(found)
                page.delete_link(link)
                removed += 1
    return removed


def _search_rects(page, value: str):
    rects = page.search_for(value)
    if not rects and value != " ".join(value.split()):
        rects = page.search_for(" ".join(value.split()))
    return rects


MAX_PDF_PASSES = 3


def transform_pdf(src: Path, dst: Path, rel: str, detector, ctx: TransformContext, _pass: int = 0,
                  _rects: dict[int, list] | None = None, _strict: bool = False) -> FileResult:
    doc = fitz.open(src)
    if pdf_is_signed(doc):
        doc.close()
        safe_copy(src, dst)
        return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=["PDF содержит цифровую подпись; файл не изменялся"], output_path=str(dst))
    whole_pdf_images = 0
    if imagereplace.whole_image(ctx.settings):
        try:
            whole_pdf_images = imagereplace.replace_pdf_images(doc, ctx)
        except (imagereplace.ImageStoreFull, imagereplace.ImageReplaceError) as exc:
            doc.close()
            return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=[str(exc)])
    findings: list[Finding] = []
    warnings: list[str] = []
    if getattr(doc, "is_repaired", False):
        warnings.append("Файл PDF был повреждён (оборван или с неверной структурой) и исправлен при чтении: проверьте результат, "
                        "часть содержимого могла быть потеряна")
    annotations = links = 0
    _pdf_open_layers(doc)
    embedded = getattr(doc, "embfile_count", lambda: 0)()
    for page in doc:
        embedded += sum(1 for a in (page.annots() or []) if a.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT)
    maps = [PageChars(page) for page in doc]
    images, scans = _pdf_image_pages(doc)
    if whole_pdf_images:
        images, scans = 0, []             # картинки уже заменены заглушками: читать и искать на них нечего
    unreadable = _pdf_unreadable_pages(doc, maps)
    native_chars = [0 if i in unreadable else len(m.chars) for i, m in enumerate(maps)]
    brands: list = []
    policy = getattr(ctx.settings, "image_brand_policy", "paint")
    register = (lambda phrase: detector.entities.register("ORG", phrase, explicit=True)) if policy == "paint" else None
    ocr_words, ocr_error = _pdf_ocr_maps(doc, maps, set(unreadable), brands if policy != "off" else None, register)
    if scans and (ocr_error or not ocr.available()):
        doc.close()
        return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=[_pdf_scan_warning(scans)])
    if unreadable and (ocr_error or not ocr.available()):
        doc.close()
        return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=[_pdf_unreadable_warning(unreadable)])
    # Метки прошлого прохода: их искажённое чтение на картинке страницы не должно закрашиваться как новые данные.
    drawn_rects: dict[int, list] = {i: list(v) for i, v in (_rects or {}).items()}
    if drawn_rects:
        _mask_drawn_chars(maps, drawn_rects, native_chars)
    code_rects, codes_safe, code_error = _pdf_barcodes(doc, rel, detector)
    if code_error:
        doc.close()
        return FileResult(rel, "PDF", FileStatus.BLOCKED, warnings=[
            "Не удалось проверить QR-коды и штрихкоды на изображениях PDF: в них могут быть данные, файл не выдаётся"])
    page_text = [m.view("lines").text for m in maps]
    chars = sum(len(t.strip()) for t in page_text)
    # Слова документа (подписи полей): остаток, похожий на подпись с порчей распознавания, значением не считается.
    vocab = {w.lower() for t in page_text for w in re.findall(r"[^\W\d_]{5,}", t)}
    # Имена из закладок, примечаний и свойств учатся так же, как имена со страниц: полное ФИО там тоже бывает единственным.
    detector.harvest("\n".join([*page_text, *_pdf_joined_texts(maps), *_pdf_extra_texts(doc)]), rel)
    colctx.learn_pdf_tables(doc, detector)
    for page in doc:
        annotations += sum(1 for _ in (page.annots() or []))
        links += len(page.get_links())
    hits = _pdf_hits(detector, ctx, rel, maps, _strict)
    findings.extend(h.finding for h in hits)
    auto = [h for h in hits if h.finding.decision == Decision.AUTO]
    auto += _pdf_extra_hits(auto, maps)
    # Ссылки читаются до замены: после apply_redactions список ссылок страницы в PyMuPDF бывает испорчен (IndexError).
    links_removed = _pdf_scrub_links(doc, rel, detector, ctx, findings)
    if links_removed:
        links = max(0, links - links_removed)
    placed_tokens: list[str] = []
    drawing: dict[int, list[tuple]] = {}
    ocr_rects: dict[int, list[tuple[str, fitz.Rect]]] = {}
    ocr_labels: dict[int, set[str]] = {}       # метки, поставленные на месте текста с картинки: при возврате вернётся сама картинка
    for hit in sorted(auto, key=lambda h: (min(h.ids), min(h.ids[min(h.ids)]))):
        token = ctx.token_for(hit.finding)
        placed_tokens.append(token)
        first = True
        for page_index in sorted(hit.ids):
            if hit.ids[page_index] and min(hit.ids[page_index]) >= native_chars[page_index]:
                ocr_labels.setdefault(page_index, set()).add(token)
            for seg in maps[page_index].segments(hit.ids[page_index]):
                if hit.ids[page_index] and min(hit.ids[page_index]) >= native_chars[page_index]:
                    ocr_rects.setdefault(page_index, []).append((token, fitz.Rect(seg.rect)))
                drawing.setdefault(page_index, []).append((seg, token if first else None))
                first = False
    for page_index in sorted(set(drawing) | set(code_rects)):
        items = drawing.get(page_index, [])
        page = doc[page_index]
        crops = []
        for token, box in ocr_rects.get(page_index, []):
            try:
                crops.append((token, box, page.get_pixmap(clip=box, dpi=VECTOR_CROP_DPI).tobytes("png")))
            except Exception:
                pass
        cuts: list[fitz.Rect] = []
        for seg, _ in items:
            # Рамка на каждый символ значения: общая рамка строки стирает и соседние буквы.
            for cut in maps[page_index].slivers(seg.ids, native_chars[page_index]):
                page.add_redact_annot(cut, fill=(1, 1, 1))
                cuts.append(cut)
        for rect in code_rects.get(page_index, []):
            page.add_redact_annot(fitz.Rect(rect) + (-3, -3, 3, 3), fill=(1, 1, 1))
        before_images = _pdf_page_images(doc, page) if ocr_labels.get(page_index) else {}
        # Редактирование PyMuPDF стирает и чужие символы, лежащие под рамкой или переписанные вместе с ней (кириллица вне
        # WinAnsi: і ї є, наложенный текст). Они не относятся к значению и дорисовываются, чтобы страница не теряла текст.
        hit_boxes: dict[str, list[fitz.Rect]] = {}
        for seg, _ in items:
            for i in seg.ids:
                ch = maps[page_index].chars[i]
                hit_boxes.setdefault(ch.c, []).append(fitz.Point((ch.x0 + ch.x1) / 2, (ch.y0 + ch.y1) / 2))
        # Своим считается только символ в той же точке: чужая буква под значением (наложенный текст) тоже должна дорисоваться.
        neighbours = kept_chars(page, cuts, skip=lambda c, at: any(abs(p.x - at.x) < .7 and abs(p.y - at.y) < .7 for p in hit_boxes.get(c, ()))) if items else []
        # Заглушки картинок (W10) не трогаются: пиксельное редактирование пересоздаёт объект и теряет ключ /AnonImg, оригинал не вернуть.
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE if whole_pdf_images else fitz.PDF_REDACT_IMAGE_PIXELS,
                              graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        redraw_lost(page, neighbours)
        stashed = _pdf_stash_page_images(doc, page, before_images, sorted(ocr_labels[page_index]), ctx) if before_images else 0
        if crops and not stashed:
            _pdf_stash_vector_crops(ctx, page_index, crops)
        placed_here: list[tuple[fitz.Rect, str]] = []
        for seg, token in items:
            if token:
                box = fitz.Rect(seg.rect)
                # Одно слово, найденное двумя находками (разные виды текста), получило бы одну и ту же метку дважды на одном месте;
                # при возврате вторая метка не гасится и буквы значения теряются.
                if any(t == token and not (box & r).is_empty and (box & r).get_area() >= .5 * min(box.get_area(), r.get_area()) for r, t in placed_here):
                    continue
                draw_text(page, seg.rect, seg.rot, token, "helv", PLACEHOLDER_FONT_RANGE[0], PLACEHOLDER_FONT_RANGE[1],
                          color=rgb(seg.color))
                drawn_rects.setdefault(page_index, []).append((box, token))
                placed_here.append((box, token))
        for rect in code_rects.get(page_index, []):
            box = fitz.Rect(rect) + (-3, -3, 3, 3)
            draw_text(page, box, 0, BARCODE_LABEL, "helv", 3.0, max(6.0, min(14.0, box.height / 6)))
    if whole_pdf_images:
        imagereplace.draw_pending_labels(doc, ctx)
    metadata = dict(doc.metadata or {})
    scrubbed = False
    for field, value in _pdf_metadata(doc).items():
        if has_token(value):
            continue
        if field in PDF_PERSONAL_FIELDS and ctx.settings.scrub_metadata:
            # Название, автор, тема и ключевые слова обезличиваются целиком, как свойства документа Office.
            found = [_metadata_finding(rel, f"metadata:{field}", "metadata", value, 0, "Метаданные документа")]
        else:
            found = ctx.apply_overrides(detector.scan(value, rel, f"metadata:{field}"))
        if not found:
            continue
        findings.extend(found)
        metadata[field] = replace_findings(value, found, ctx)
        scrubbed = True
    if getattr(ctx.vault, "vault_id", ""):
        metadata["producer"] = MARKER_PREFIX + ctx.vault.vault_id
        scrubbed = True
    if scrubbed:
        doc.set_metadata(metadata)
    annotations_done = _scrub_pdf_extras(doc, rel, detector, ctx, findings)
    _pdf_scrub_widget_extras(doc)
    _pdf_clean_info(doc)
    removed_files = _pdf_drop_attachments(doc, warnings)
    if removed_files:
        embedded = 0
        warnings.append(f"Вложенные файлы PDF удалены из результата: {removed_files}. Их содержимое не обезличивалось")
    dst.parent.mkdir(parents=True, exist_ok=True)
    pages_before = len(doc)
    doc.save(dst, garbage=4, deflate=True, clean=True)
    doc.close()
    verify_doc = fitz.open(dst)
    verify_maps = [PageChars(page) for page in verify_doc]
    if ocr_words or unreadable:
        again, verify_error = _pdf_ocr_maps(verify_doc, verify_maps, set(unreadable))
        if verify_error:
            verify_doc.close()
            try:
                Path(dst).unlink()
            except OSError:
                pass
            return FileResult(rel, "PDF", FileStatus.BLOCKED, findings,
                              ["Не удалось проверить результат: текст на изображениях не распознан повторно, файл не выдаётся"])
    if code_rects:
        try:
            still = any(_unsafe_barcodes(ocr.detect_barcodes(verify_doc[i]), detector, rel) for i in code_rects)
        except Exception:
            still = True
        if still:
            verify_doc.close()
            try:
                Path(dst).unlink()
            except OSError:
                pass
            return FileResult(rel, "PDF", FileStatus.BLOCKED, findings, [
                "QR-код или штрихкод в PDF остался читаемым после закраски, файл не выдаётся"])
    pages_after = len(verify_doc)
    verify_doc.close()
    # Проверка читает и дополнительные слои распознавания страниц-сканов: значение, видимое хотя бы в одном слое, остаток.
    verify_all = verify_maps + [layer for m in verify_maps for layer in getattr(m, "shadows", ())]
    views = {mode: "\n".join(m.view(mode).text for m in verify_all) for mode in PDF_VIEWS}
    if ocr_words or unreadable:
        # Остатки ищутся в тексте без знаков, лежащих на наших метках; наличие самих меток (lost) проверяется по полному тексту.
        _mask_drawn_chars(verify_maps, drawn_rects)
    checked = {mode: "\n".join(m.view(mode).text for m in verify_all) for mode in PDF_VIEWS}
    values = {w.lower() for f in findings for w in re.findall(r"[^\W\d_]{5,}", f.original or "")}
    residual = sorted({r for text in checked.values()
                       for r in _residuals(detector, text, findings, ocr_text=bool(ocr_words), vocab=vocab - values)})
    if ocr_words:
        # Значения после метки и длинные номера, которые правила не узнали, но закраска берёт (_label_value_hits): остаток и в проверке.
        # Слово из одних букв после метки («token =» и дальше подпись следующего поля: значение стёрто) подписью и является:
        # настоящие секреты содержат цифры или знаки, а такие значения закраска берёт и здесь учитывает.
        residual = sorted(set(residual) | {f.original for m in verify_all if getattr(m, "has_ocr", False)
                                           for f, _ in _label_value_hits(m, [], rel)
                                           if not _PLAIN_LABEL_WORD.fullmatch(f.original.strip(" :.,;|"))})
    if residual and (ocr_words or unreadable) and _pass + 1 < MAX_PDF_PASSES:
        # Распознавание картинок не детерминировано: слово, которое не прочиталось в первый раз, прочиталось при проверке.
        # Результат обезличивается ещё раз (метки те же), проверка при этом не ослабляется.
        again = Path(dst).with_name(Path(dst).stem + f".pass{_pass + 1}.pdf")
        try:
            os.replace(dst, again)
            second = transform_pdf(again, dst, rel, detector, ctx, _pass + 1, drawn_rects)
        finally:
            try:
                again.unlink()
            except OSError:
                pass
        second.findings = findings + second.findings
        second.warnings = list(dict.fromkeys(warnings + second.warnings))
        return second
    if residual and not (ocr_words or unreadable) and not _strict and _pass + 1 < MAX_PDF_PASSES:
        # Слой текста, который основной проход не разобрал («7th Street» в плохом слое распознавания), проверка читает: один раз
        # результат обезличивается заново вместе с находками проверки. Если остаток снова есть, файл по-прежнему не выдаётся.
        again = Path(dst).with_name(Path(dst).stem + f".pass{_pass + 1}.pdf")
        try:
            os.replace(dst, again)
            second = transform_pdf(again, dst, rel, detector, ctx, _pass + 1, drawn_rects, True)
        finally:
            try:
                again.unlink()
            except OSError:
                pass
        second.findings = findings + second.findings
        second.warnings = list(dict.fromkeys(warnings + second.warnings))
        return second
    if residual:
        # Исходное значение читается в результате (перенос, поворот, текст за краем): такой файл наружу не выдаётся.
        try:
            Path(dst).unlink()
        except OSError:
            pass
        return FileResult(rel, "PDF", FileStatus.BLOCKED, findings,
                          ["Не удалось надёжно убрать из PDF исходные данные, файл не выдаётся. "
                           f"Остались значения: {len(residual)}. Обезличьте документ в исходном редакторе и повторите"])
    verify_text = views["join"]
    lost = sorted({t for t in placed_tokens if t not in verify_text and t not in views["lines"] and t not in views["dehyphen"]})
    if lost:
        # Слишком мелкий текст: значение стёрто, а метка не читается, и вернуть его нельзя.
        warnings.append(f"В PDF не удалось вставить метки ({len(lost)}): мелкий или повёрнутый текст. Эти значения нельзя вернуть")
    if pages_before != pages_after:
        warnings.append("Изменилось количество страниц")
    if code_rects:
        count = sum(len(v) for v in code_rects.values())
        warnings.append(f"В PDF закрашены QR-коды или штрихкоды ({count}): в них могли быть данные, вернуть их при восстановлении нельзя")
    for warning in _pdf_warnings(images, chars, pages_before, max(0, annotations - annotations_done), links, embedded, ocr.available(),
                                 ocr.barcodes_available()):
        if warning not in warnings:
            warnings.append(warning)
    logos = 0
    for page_index, phrase, rects in brands:
        painted = [fitz.Rect(maps[page_index].chars[i].x0, maps[page_index].chars[i].y0, maps[page_index].chars[i].x1,
                             maps[page_index].chars[i].y1) for h in hits for i in h.ids.get(page_index, [])]
        if any(r.intersects(q) for r in rects for q in painted):
            logos += 1
            warnings.append(f"{rel}, страница {page_index + 1}: название или логотип «{phrase}» на картинке закрашено: "
                            "проверьте, что это действительно название.")
        else:
            warnings.append(f"{rel}, страница {page_index + 1}: на картинке есть название или логотип, которое программа не опознала "
                            f"как данные и не закрасила: «{phrase}». Если это название организации или проекта, закройте его "
                            "вручную или добавьте в список скрываемых слов.")
    status = FileStatus.CLEAN if not warnings else FileStatus.REVIEW_REQUIRED
    result = FileResult(rel, "PDF", status, findings, warnings, str(dst),
                        {"pages_before": pages_before, "pages_after": pages_after, "original_text_removed": not residual})
    result.notices = _pdf_notices(images, chars, pages_before, links, ocr_words, ocr.available(),
                                  ocr.barcodes_available())
    if whole_pdf_images:
        result.notices.append(imagereplace.notice_replaced(whole_pdf_images))
    if logos:
        result.notices.append(f"Закрашено названий на логотипах: {logos}.")
        if whole_pdf_images or not images:
            result.warnings.append(imagereplace.WARN_VECTOR_LOGO)
            result.status = FileStatus.REVIEW_REQUIRED
    return result


def extract_text(path: Path) -> str:
    """Читаемый текст файла: для проверки «уже обезличен ли файл» и для сверки результата."""
    kind = classify(path)
    if kind == "TEXT":
        return decode_text(path.read_bytes())
    if kind == "OOXML":
        return ooxml_text(path)
    if kind == "PDF":
        doc = fitz.open(path)
        try:
            return "\n".join(page.get_text("text", sort=True) for page in doc)
        finally:
            doc.close()
    return ""
