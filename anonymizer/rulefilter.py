"""Cheap pre-filter for regex rules: literals every match of a pattern must contain.

A rule whose required literals do not occur in a text cannot match it, so the (much slower) regex scan is skipped.
The literals come from the parsed pattern itself, never from a hand-kept list: only literal runs that sit on every
path through the pattern count (top level, inside groups, inside repeats with min >= 1, and as a whole branch set).
Everything else (classes, lookarounds, optional parts, conditionals) contributes nothing. Comparison is done on
casefolded text and casefolded literals, which accepts at least everything the regex's own IGNORECASE accepts.
"""
from __future__ import annotations

import re
from re import _parser as _sre   # noqa: PLC2701  (stdlib parser; same one re.compile uses)

_MAX_ALTERNATIVES = 24
_cache: dict[re.Pattern, tuple[str, ...] | None] = {}


def _runs(items) -> list[tuple[str, ...] | None]:
    """Requirement of each element of a sequence (None: nothing required). Adjacent literals merge into one run."""
    out: list[tuple[str, ...] | None] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(("".join(buf),))
            buf.clear()

    for op, av in items:
        if op is _sre.LITERAL:
            buf.append(chr(av))
            continue
        flush()
        out.append(_element(op, av))
    flush()
    return out


def _element(op, av) -> tuple[str, ...] | None:
    if op is _sre.SUBPATTERN:
        return _best(_runs(av[3]))
    if op is _sre.BRANCH:
        merged: list[str] = []
        for branch in av[1]:
            req = _best(_runs(branch))
            if not req:
                return None
            merged.extend(req)
        return tuple(dict.fromkeys(merged)) if len(set(merged)) <= _MAX_ALTERNATIVES else None
    if op in (_sre.MAX_REPEAT, _sre.MIN_REPEAT, _sre.POSSESSIVE_REPEAT):
        return _best(_runs(av[2])) if av[0] >= 1 else None
    if op is _sre.ATOMIC_GROUP:
        return _best(_runs(av))
    return None


def _best(options) -> tuple[str, ...] | None:
    """The most selective requirement among elements that must all hold: longest shortest-literal, fewest alternatives."""
    best, key = None, (0, 0)
    for req in options:
        if not req:
            continue
        k = (min(len(x) for x in req), -len(req))
        if k > key:
            best, key = req, k
    return best


def required_literals(pattern: re.Pattern) -> tuple[str, ...] | None:
    """Casefolded literals, at least one of which occurs in every text the pattern matches; None when unknown."""
    if pattern in _cache:
        return _cache[pattern]
    try:
        tree = _sre.parse(pattern.pattern, pattern.flags)
        req = _best(_runs(tree))
        result = tuple(dict.fromkeys(fold_text(x) for x in req)) if req else None
        if result and any(not x for x in result):
            result = None
    except Exception:       # noqa: BLE001  - an unparsable pattern simply gets no filter
        result = None
    _cache[pattern] = result
    return result


def fold_text(text: str) -> str:
    """casefold plus dotless i -> i: the regex engine's IGNORECASE also equates U+0131 with "i", casefold alone does not."""
    return text.casefold().replace("\u0131", "i")


def may_match(pattern: re.Pattern, folded_text: str) -> bool:
    req = required_literals(pattern)
    if req is None:
        return True
    return any(x in folded_text for x in req)
