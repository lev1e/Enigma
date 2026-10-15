"""Текст на картинках: нечёткое сопоставление с известными названиями и поиск «логотипного» текста, который не опознан."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import fitz

from .normalize import fold

WORD = re.compile(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*")
MIN_FUZZY_LETTERS = 6
WORD_RATIO = .72
PHRASE_RATIO = .84
BIG_RATIO = 1.3         # слово выше обычного на столько считается крупным (название, заголовок, логотип)


def _norm(text: str) -> str:
    return fold(text).replace("ё", "е")


def close_enough(a: str, b: str, ratio: float = PHRASE_RATIO) -> bool:
    a, b = _norm(a), _norm(b)
    return len(b) >= 4 and abs(len(a) - len(b)) <= 2 and SequenceMatcher(None, a, b).ratio() >= ratio


def fuzzy_spans(text: str, names: list[str]) -> list[tuple[int, int, str]]:
    """Места в тексте, где известное название прочитано с ошибками распознавания («Энергня» вместо «Энергия»)."""
    tokens = [(m.start(), m.end(), _norm(m.group(0))) for m in WORD.finditer(text)]
    found: list[tuple[int, int, str]] = []
    taken: list[tuple[int, int]] = []
    for name in sorted(set(names), key=lambda n: -len(n)):
        parts = [_norm(p) for p in WORD.findall(name)]
        if not parts or sum(len(p) for p in parts) < MIN_FUZZY_LETTERS or len(parts) > 5:
            continue
        n = len(parts)
        for i in range(len(tokens) - n + 1):
            window = tokens[i:i + n]
            if any(abs(len(t[2]) - len(p)) > 2 or SequenceMatcher(None, t[2], p).ratio() < WORD_RATIO
                   for t, p in zip(window, parts)):
                continue
            if not close_enough(" ".join(t[2] for t in window), " ".join(parts)):
                continue
            span = (window[0][0], window[-1][1])
            if any(span[0] < b and a < span[1] for a, b in taken):
                continue
            taken.append(span)
            found.append((span[0], span[1], name))
    return sorted(found)


def known_names(detector) -> list[tuple[str, str, str]]:
    """(написание, вид, ключ) явно известных организаций, проектов и скрытых слов: из документов и хранилища."""
    entities = getattr(getattr(detector, "entities", None), "entities", None) or {}
    out = []
    for entity in entities.values():
        if entity.kind in {"ORG", "PROJECT", "TERM"} and entity.explicit:
            for form in entity.forms:
                if sum(ch.isalpha() for ch in form) >= MIN_FUZZY_LETTERS:
                    out.append((form, entity.kind, entity.key))
    return out


def _centre_in(word, rects) -> bool:
    cx, cy = (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2
    return any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in rects)


def _candidate(text: str) -> bool:
    letters = text.replace("-", "").replace("’", "").replace("'", "")
    return len(letters) >= 3 and letters.isalpha() and (text[0].isupper() or letters.isupper())


def brand_groups(words, covered) -> list[tuple[str, list]]:
    """Названия, похожие на логотип или бренд (два-три слова с заглавной, крупное слово) и не закрытые находками."""
    words = [w for w in words if not w.rot and w.text.strip()]
    if not words:
        return []
    heights = sorted(w.y1 - w.y0 for w in words)
    typical = heights[len(heights) // 2] or 1.0
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    runs = []       # (слова, высота, верх, низ, левый край)
    for ws in lines.values():
        ws.sort(key=lambda w: w.x0)
        whole_line = all(_candidate(w.text) and not _centre_in(w, covered) for w in ws)
        run: list = []
        for w in ws + [None]:
            if w is not None and _candidate(w.text) and not _centre_in(w, covered):
                run.append(w)
                continue
            if run:
                height = sorted(x.y1 - x.y0 for x in run)[len(run) // 2]
                big = height >= BIG_RATIO * typical
                if whole_line or (big and len(run) >= 2):
                    runs.append((run, height, min(x.y0 for x in run), max(x.y1 for x in run), run[0].x0, whole_line))
                run = []
    runs.sort(key=lambda r: (r[2], r[4]))
    merged: list[list] = []
    for run in runs:
        for group in merged:
            last = group[-1]
            if 0 <= run[2] - last[3] <= 1.2 * max(run[1], last[1]) and .7 <= run[1] / max(last[1], 1e-6) <= 1.4 \
                    and abs(run[4] - last[4]) <= 6 * max(run[1], last[1]):
                group.append(run)
                break
        else:
            merged.append([run])
    phrases = []
    for group in merged:
        count = sum(len(r[0]) for r in group)
        big = max(r[1] for r in group) >= BIG_RATIO * typical
        if count >= 2 or (big and group[0][5] and len(group[0][0][0].text) >= 5):
            ws = [w for r in group for w in r[0]]
            phrases.append((" ".join(w.text for w in ws), ws))
    return phrases


def brand_phrases(words, covered) -> list[str]:
    return [p for p, _ in brand_groups(words, covered)]


TABLE_LIKE = 5          # столько названий на одной картинке — это таблица или список, а не логотип: только предупреждение


def paintable(phrase: str, count: int) -> bool:
    """Закрашивать ли найденное название: одиночные слова, цифры и таблицы не закрашиваются, о них только предупреждение."""
    words = WORD.findall(phrase)
    return count < TABLE_LIKE and len(words) >= 2 and sum(len(w) for w in words) >= 8


def distinct(phrases: list[str]) -> list[str]:
    """Одно и то же название, прочитанное разными проходами с мелкими различиями, считается один раз."""
    out: list[str] = []
    for p in phrases:
        if not any(close_enough(p, q, .78) for q in out):
            out.append(p)
    return out
