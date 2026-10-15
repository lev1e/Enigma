"""Текст PDF-страницы с координатой каждого символа.

`page.search_for(value)` ищет по строке за строкой в границах страницы: значение, перенесённое на другую строку или
страницу, повёрнутый текст и текст за краем страницы так не находятся, и исходные данные остаются в файле. Здесь
страница читается посимвольно (rawdict), текст для детектора собирается с картой «позиция в тексте -> символы»,
а найденные значения превращаются в прямоугольники по строкам с учётом направления текста.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import os

import fitz

BIG = fitz.Rect(-10000, -10000, 10000, 10000)
FLAGS = (fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_MEDIABOX_CLIP & ~fitz.TEXT_PRESERVE_LIGATURES)
# Символы, которые не видны, но разрывают слово при извлечении текста: «ivan.pe­trov@mail.ru».
INVISIBLE = {"­", "​", "‌", "‍", "⁠", "﻿"}
SEAM_LINES = 4          # сколько строк с каждой стороны разрыва страницы читается как один фрагмент
HYPHENS = {"-", "‐", "‑"}
GRID = 24.0


@dataclass(slots=True)
class Ch:
    c: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    color: int
    rot: int            # направление текста: 0, 90, 180, 270 (против часовой стрелки, как у insert_text)
    line: int


@dataclass(slots=True)
class Segment:
    rect: fitz.Rect
    rot: int
    size: float
    color: int
    ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class View:
    """Текст для детектора и карта символов: refs[i] — номера символов, из которых получен text[i]."""
    text: str
    refs: list[tuple[int, ...]]

    def ids(self, start: int, end: int) -> list[int]:
        out: list[int] = []
        for r in self.refs[max(0, start):max(0, end)]:
            out.extend(r)
        return out


class PageChars:
    def __init__(self, page):
        self.chars: list[Ch] = []
        self.lines: list[list[int]] = []          # номера символов по строкам
        self.blocks: list[list[int]] = []         # номера строк по блокам
        self.force: set[int] = set()
        data = page.get_text("rawdict", flags=FLAGS, clip=BIG)
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            line_ids: list[int] = []
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1, 0))
                rot = int(round(math.degrees(math.atan2(-dy, dx)) / 90.0)) * 90 % 360
                ids: list[int] = []
                li = len(self.lines)
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        x0, y0, x1, y1 = ch["bbox"]
                        ids.append(len(self.chars))
                        self.chars.append(Ch(ch["c"], x0, y0, x1, y1, float(span.get("size", 0)), int(span.get("color", 0)), rot, li))
                if ids:
                    self.lines.append(ids)
                    line_ids.append(li)
            if line_ids:
                self.blocks.append(line_ids)

    @staticmethod
    def seam(first: "PageChars", second: "PageChars") -> "PageChars":
        """Конец одной страницы и начало следующей как один блок: значение может быть перенесено через разрыв страницы.

        У результата есть `origin[i] = (0|1, номер символа на своей странице)`.
        """
        merged = PageChars.__new__(PageChars)
        merged.chars, merged.lines, merged.blocks, merged.origin, merged.force = [], [], [], [], set()
        if not first.lines or not second.lines:
            return merged
        block = []
        for tag, page, line_ids in ((0, first, range(max(0, len(first.lines) - SEAM_LINES), len(first.lines))),
                                    (1, second, range(min(SEAM_LINES, len(second.lines))))):
            for li in line_ids:
                new_ids = []
                for cid in page.lines[li]:
                    c = page.chars[cid]
                    new_ids.append(len(merged.chars))
                    merged.chars.append(Ch(c.c, c.x0, c.y0, c.x1, c.y1, c.size, c.color, c.rot, len(merged.lines)))
                    merged.origin.append((tag, cid))
                block.append(len(merged.lines))
                merged.lines.append(new_ids)
            if tag == 0:
                merged.force.add(len(merged.lines) - 1)         # разрыв страницы: продолжение, как бы ни стояли строки
        merged.blocks = [block]
        return merged

    # --- тексты -------------------------------------------------------------------------------------------------------

    def view(self, mode: str = "lines") -> View:
        """mode: lines — как get_text('text'); join — строки блока склеены пробелом, дефис переноса оставлен;
        dehyphen — то же, но дефис переноса убран («7707-\\n083893» читается как 7707083893)."""
        out: list[str] = []
        refs: list[tuple[int, ...]] = []

        def add(c: str, ids: tuple[int, ...]) -> None:
            if c in INVISIBLE:
                if refs and ids:
                    refs[-1] = refs[-1] + ids
                return
            out.append(c)
            refs.append(ids)

        total = len(self.lines)
        for li, ids in enumerate(self.lines):
            nxt = li + 1 if li + 1 < total and self._follows(li, li + 1) else None
            n = len(ids)
            for k, cid in enumerate(ids):
                c = self.chars[cid].c
                if mode == "dehyphen" and nxt is not None and k == n - 1 and c in HYPHENS and self._wraps(ids, k, nxt):
                    # дефис переноса принадлежит предыдущему символу: он закрашивается вместе со значением
                    if refs:
                        refs[-1] = refs[-1] + (cid,)
                    continue
                add(c, (cid,))
            if nxt is None or mode == "lines":
                add("\n", ())
                continue
            tail = self.chars[ids[-1]].c
            if tail in HYPHENS | INVISIBLE and self._wraps(ids, n - 1, nxt):
                continue                        # слово продолжается на следующей строке: пробела нет
            add(" ", ())
        return View("".join(out), refs)

    def _follows(self, a: int, b: int) -> bool:
        """Вторая строка продолжает первую: то же направление и интервал не больше трёх кеглей."""
        if a in self.force:
            return True
        ca, cb = self.chars[self.lines[a][0]], self.chars[self.lines[b][0]]
        if ca.rot != cb.rot:
            return False
        limit = 3.0 * max(ca.size, cb.size, 1.0)
        if ca.rot == 0:
            gap = cb.y0 - ca.y0
        elif ca.rot == 180:
            gap = ca.y0 - cb.y0
        elif ca.rot == 90:
            gap = cb.x0 - ca.x0
        else:
            gap = ca.x0 - cb.x0
        return 0 < gap <= limit

    def _wraps(self, ids: list[int], k: int, next_line: int) -> bool:
        """Перенос слова: перед дефисом буква или цифра, а следующая строка продолжается буквой или цифрой."""
        if k == 0:
            return False
        before = self.chars[ids[k - 1]].c
        nxt = self.lines[next_line]
        after = self.chars[nxt[0]].c if nxt else ""
        return before.isalnum() and after.isalnum()

    # --- прямоугольники ------------------------------------------------------------------------------------------------

    def segments(self, ids: list[int]) -> list[Segment]:
        """Символы значения, сгруппированные по строкам: одна строка — один прямоугольник."""
        by_line: dict[int, list[int]] = {}
        for cid in sorted(set(ids)):
            by_line.setdefault(self.chars[cid].line, []).append(cid)
        out = []
        for li in sorted(by_line):
            group = [self.chars[i] for i in by_line[li] if self.chars[i].c.strip() or len(by_line[li]) == 1]
            if not group:
                continue
            rect = fitz.Rect(min(c.x0 for c in group), min(c.y0 for c in group), max(c.x1 for c in group), max(c.y1 for c in group))
            first = group[0]
            out.append(Segment(rect, first.rot, max(c.size for c in group), first.color, by_line[li]))
        return out

    def _grid(self) -> dict:
        """Сетка 24x24 pt: в каких ячейках лежит рамка каждого символа (для быстрого поиска соседей)."""
        grid = getattr(self, "_cells", None)
        if grid is None:
            grid = {}
            for i, c in enumerate(self.chars):
                for gx in range(int(c.x0 // GRID), int(c.x1 // GRID) + 1):
                    for gy in range(int(c.y0 // GRID), int(c.y1 // GRID) + 1):
                        grid.setdefault((gx, gy), []).append(i)
            self._cells = grid
        return grid

    def _others_in(self, rect: fitz.Rect, mine: set[int]) -> list[int]:
        grid = self._grid()
        seen: set[int] = set()
        for gx in range(int(rect.x0 // GRID), int(rect.x1 // GRID) + 1):
            for gy in range(int(rect.y0 // GRID), int(rect.y1 // GRID) + 1):
                for i in grid.get((gx, gy), ()):
                    if i in mine or i in seen:
                        continue
                    c = self.chars[i]
                    if c.x0 <= rect.x1 and c.x1 >= rect.x0 and c.y0 <= rect.y1 and c.y1 >= rect.y0:
                        seen.add(i)
        return list(seen)

    @staticmethod
    def _touch(a: fitz.Rect, c: "Ch") -> bool:
        return c.x0 <= a.x1 and c.x1 >= a.x0 and c.y0 <= a.y1 and c.y1 >= a.y0

    def slivers(self, ids: list[int], native_limit: int | None = None) -> list[fitz.Rect]:
        """Рамки редактирования по символам: центральная часть рамки каждого символа значения.

        Редактирование PyMuPDF удаляет каждый символ, рамка которого пересекается с рамкой редактирования. Общая рамка строки
        задевает соседей (кернинг, наклон, перекрытие рамок), а центральная часть символа — только сам символ.
        Символы с номером от `native_limit` (текст с картинок) закрашиваются целиком: там стираются пиксели.

        Соседние рамки одной строки сливаются в одну, если промежуток между ними не задевает ни одного чужого символа:
        PyMuPDF тратит на каждую рамку время, растущее с числом рамок страницы (квадратично), а результат тот же.
        """
        mine = set(ids)
        items: list[tuple[int, fitz.Rect]] = []
        for cid in sorted(mine):
            c = self.chars[cid]
            box = fitz.Rect(c.x0, c.y0, c.x1, c.y1)
            if box.is_empty:
                continue
            if native_limit is not None and cid >= native_limit:
                items.append((cid, box))
                continue
            if not c.c.strip():
                continue
            dx, dy = box.width * .3, box.height * .3
            items.append((cid, fitz.Rect(box.x0 + dx, box.y0 + dy, box.x1 - dx, box.y1 - dy)))
        out: list[fitz.Rect] = []
        run: list[fitz.Rect] = []
        run_ch = None
        union = None
        for cid, rect in items:
            c = self.chars[cid]
            if run and c.line == run_ch.line and c.rot == run_ch.rot and (cid >= (native_limit or 1 << 60)) == (run_id >= (native_limit or 1 << 60)):
                grown = fitz.Rect(union) | rect
                gap = max(rect.x0 - union.x1, union.x0 - rect.x1, rect.y0 - union.y1, union.y0 - rect.y1)
                if gap <= max(c.size, 1.0) * 1.5 and not any(
                        not any(self._touch(m, o) for m in [*run, rect])
                        for o in map(self.chars.__getitem__, self._others_in(grown, mine))
                        if self._touch(grown, o)):
                    run.append(rect)
                    union = grown
                    continue
            if run:
                out.append(union)
            run, run_ch, run_id, union = [rect], c, cid, fitz.Rect(rect)
        if run:
            out.append(union)
        return out


def find_all(view: View, value: str) -> list[tuple[int, int]]:
    """Все вхождения значения без учёта регистра; пробелы внутри значения совпадают с любым числом пробельных символов."""
    parts = [re.escape(p) for p in value.split()]
    if not parts:
        return []
    pattern = re.compile(r"[\s ]+".join(parts), re.IGNORECASE)
    return [m.span() for m in pattern.finditer(view.text)]


# --- вставка текста ---------------------------------------------------------------------------------------------------

def fit_size(text: str, length: float, fontname: str, lo: float, hi: float) -> float:
    size = hi
    while size > lo:
        if fitz.get_text_length(text, fontname=fontname, fontsize=size) <= length:
            return size
        size -= .25
    return lo


def draw_text(page, seg_rect: fitz.Rect, rot: int, text: str, fontname: str, lo: float, hi: float,
              color=(0, 0, 0), room: float | None = None) -> float:
    """Вписывает текст в прямоугольник строки с учётом направления. Возвращает кегль.

    room — сколько места можно занять вдоль строки сверх прямоугольника (например, до края страницы).
    """
    length = (seg_rect.height if rot in (90, 270) else seg_rect.width)
    avail = max(length, room or 0.0)
    size = fit_size(text, avail, fontname, lo, hi)
    d = size * .2
    if rot == 0:
        pt = fitz.Point(seg_rect.x0, seg_rect.y1 - d)
    elif rot == 90:
        pt = fitz.Point(seg_rect.x1 - d, seg_rect.y1)
    elif rot == 180:
        pt = fitz.Point(seg_rect.x1, seg_rect.y0 + d)
    else:
        pt = fitz.Point(seg_rect.x0 + d, seg_rect.y0)
    page.insert_text(pt, text, fontname=fontname, fontsize=size, color=color, rotate=rot)
    return size


def rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0, (color & 255) / 255.0


# --- дорисовка символов, потерянных при удалении рамок ----------------------------------------------------------------

LOST_FONT = "china-s"          # покрывает кириллицу, включая і ї є; helv этих букв не имеет


class RectGrid:
    """Быстрый поиск среди многих прямоугольников: сетка 48x48 пт."""
    CELL = 48.0

    def __init__(self, rects):
        self.rects = list(rects)
        self.cells: dict[tuple[int, int], list[int]] = {}
        for n, r in enumerate(self.rects):
            for key in self._keys(r):
                self.cells.setdefault(key, []).append(n)

    def _keys(self, r):
        c = self.CELL
        return [(i, j) for i in range(int(r.x0 // c), int(r.x1 // c) + 1) for j in range(int(r.y0 // c), int(r.y1 // c) + 1)]

    def near(self, r):
        seen: set[int] = set()
        for key in self._keys(r):
            for n in self.cells.get(key, ()):
                if n not in seen:
                    seen.add(n)
                    yield self.rects[n]

    def intersects(self, r) -> bool:
        return any(r.intersects(q) for q in self.near(r))

    def contains(self, point) -> bool:
        probe = fitz.Rect(point.x, point.y, point.x, point.y)
        return any(q.contains(point) for q in self.near(probe))


def kept_chars(page, rects: list[fitz.Rect], own: "callable | None" = None, skip: "callable | None" = None) -> list[tuple]:
    """Символы горизонтального текста, задетые рамками `rects`, но не принадлежащие самим замещаемым значениям.

    -> [(символ, начало, кегль, цвет)]. `own(span_text, rect, centre)` -> True для символов замещаемого значения.
    """
    if not rects:
        return []
    grid = RectGrid(rects)
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return []
    chars: list[tuple] = []
    for block in raw.get("blocks", []):
        # Перезапись текстового объекта затрагивает не только пересёкшиеся символы, но и всё, что с ними в одном блоке.
        if not any(grid.intersects(fitz.Rect(span["bbox"])) for line in block.get("lines", []) for span in line.get("spans", [])):
            continue
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            if abs(dy) > .05 or dx < 0:
                continue
            for span in line.get("spans", []):
                text = "".join(c["c"] for c in span.get("chars", []))
                color = span.get("color", 0)
                tint = (((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0, (color & 255) / 255.0)
                size = max(3.0, float(span.get("size", 8.0)))
                for ch in span.get("chars", []):
                    box = fitz.Rect(ch["bbox"])
                    if ch["c"].isspace():
                        continue                # вторая половина лигатуры («fi», «Th») имеет пустую рамку, но тоже буква
                    centre = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
                    if own is None:
                        if skip is not None:
                            if skip(ch["c"], centre):
                                continue
                        elif grid.contains(centre):
                            continue
                    elif any(own(text, r, centre) for r in grid.near(box) if (box & r).get_area() > 0):
                        continue
                    chars.append((ch["c"], tuple(ch["origin"]), size, tint, box.is_empty))
    return chars


def redraw_lost(page, chars: list[tuple]) -> int:
    """Дорисовывает те из `chars`, которых на странице после удаления рамок не осталось. -> сколько символов дорисовано."""
    if not chars:
        return 0
    alive: dict[str, list[tuple[float, float]]] = {}
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return 0
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    alive.setdefault(ch["c"], []).append((ch["origin"][0], ch["origin"][1]))
    lost: list[tuple] = []
    base_alive = True
    for ch in chars:
        if len(ch) > 4 and ch[4]:
            # Вторая буква лигатуры живёт и умирает вместе с первой: её собственная точка после перезаписи смещается.
            if not base_alive:
                lost.append(ch)
            continue
        spots = alive.get(ch[0], [])
        hit = next((s for s in spots if abs(s[0] - ch[1][0]) <= 1.5 and abs(s[1] - ch[1][1]) <= 1.5), None)
        base_alive = hit is not None
        if hit is None:
            lost.append(ch)
        else:
            spots.remove(hit)
    drawn = 0
    for ch in lost:
        # Каждый символ ставится в свою точку: промежутки между словами сохраняются без пробелов в строке.
        try:
            put_text(page, fitz.Point(*ch[1]), ch[0], ch[2], ch[3])
            drawn += 1
        except Exception:
            pass
    return drawn


# --- шрифт для возвращаемого текста ------------------------------------------------------------------------------------

_FONT_FILES = (
    "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/tahoma.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
)
_font_cache: dict[str, "fitz.Font | None"] = {}


def _loaded_fonts() -> list[tuple[str, "fitz.Font"]]:
    out = []
    for path in _FONT_FILES:
        if path not in _font_cache:
            try:
                _font_cache[path] = fitz.Font(fontfile=path) if os.path.isfile(path) else None
            except Exception:
                _font_cache[path] = None
        if _font_cache[path] is not None:
            out.append((path, _font_cache[path]))
    return out


def font_for(text: str) -> tuple[str, str | None]:
    """-> (имя шрифта, файл или None). Системный шрифт, в котором есть все символы строки; иначе встроенный china-s.

    Встроенные шрифты PyMuPDF молча теряют часть символов (china-s: і ї є ґ « » ß; helv: всю кириллицу).
    """
    need = {c for c in text if not c.isspace()}
    for path, font in _loaded_fonts():
        if all(font.has_glyph(ord(c)) for c in need):
            return "fb" + str(abs(hash(path)) % 100000), path
    return LOST_FONT, None


def text_width(text: str, fontname: str, fontfile: str | None, size: float) -> float:
    if fontfile:
        return _font_cache[fontfile].text_length(text, fontsize=size)
    return fitz.get_text_length(text, fontname=fontname, fontsize=size)


def put_text(page, point, text: str, size: float, color=(0, 0, 0)) -> None:
    fontname, fontfile = font_for(text)
    if not fontfile:
        page.insert_text(point, text, fontname=fontname, fontsize=size, color=color)
        return
    # Пробел во вставленном системном шрифте читается как неразрывный (U+00A0): слова кладутся по одному, пробел остаётся промежутком.
    x, y = float(point[0]), float(point[1])
    gap = text_width(" ", fontname, fontfile, size) or size * .3
    for word in text.split(" "):
        if word:
            page.insert_text((x, y), word, fontname=fontname, fontfile=fontfile, fontsize=size, color=color)
            x += text_width(word, fontname, fontfile, size)
        x += gap
