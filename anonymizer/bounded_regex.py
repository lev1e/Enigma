"""Delimiter searches that do not rescan every unmatched opening marker.

The opening/closing patterns must be unambiguous, linear token patterns; the
full expression must match whenever a complete opening and closing pair exists.
Returned matches retain offsets into the original document.
"""
from __future__ import annotations

import re


class DelimitedPattern:
    def __init__(self, pattern: str, opening: str, closing: str, flags: int = 0, *, opening_end: str | None = None):
        self._full = re.compile(pattern, flags)
        self._opening_end = opening_end
        self._opening = re.compile(opening, flags)
        self._closing = re.compile(closing, flags)
        self.pattern, self.flags = self._full.pattern, self._full.flags

    def finditer(self, text: str):
        pos = 0
        while opening := self._opening.search(text, pos):
            body_start = opening.end()
            if self._opening_end is not None:
                end = text.find(self._opening_end, body_start)
                if end < 0:
                    return
                body_start = end + len(self._opening_end)
            closing = self._closing.search(text, body_start)
            if closing is None:
                return
            match = self._full.match(text, opening.start(), closing.end())
            if match is None:
                raise ValueError("Invalid delimiter pattern")
            yield match
            pos = match.end()

    def search(self, text: str):
        return next(self.finditer(text), None)


def markup_tokens(text: str, pattern: re.Pattern, *, xml: bool = False):
    """Scan markup once, bounding each regex match to a complete token.

    Quotes and XML declaration subsets can contain '>'. Unterminated quoted
    markup is left as text, without retrying all '<' characters inside it.
    """
    pos, size = 0, len(text)
    closing_patterns = {name: re.compile(r"</" + name + r"\s*+>", re.I) for name in ("script", "style")} if not xml else {}
    closers = {}
    while (start := text.find('<', pos)) >= 0:
        special = next(((prefix, end) for prefix, end in (
            ('<!--', '-->'), ('<![CDATA[', ']]>'), ('<?', '?>')
        ) if text.startswith(prefix, start) and (xml or prefix == '<!--')), None)
        if special:
            end = text.find(special[1], start + len(special[0]))
            if end < 0:
                return
            end += len(special[1])
        else:
            quote, subset, end = '', False, start + 1
            interrupted = False
            while end < size:
                char = text[end]
                if quote:
                    if char == quote:
                        quote = ''
                elif char in '\"\'':
                    quote = char
                elif xml and text.startswith('<!', start) and char == '[':
                    subset = True
                elif subset and char == ']':
                    subset = False
                elif char == '>' and not subset:
                    end += 1
                    break
                elif char == '<' and not subset:
                    # A new tag cannot occur inside an unquoted attribute.
                    interrupted = True
                    break
                end += 1
            if end == size and (not size or text[size - 1] != '>'):
                return
            if interrupted:
                pos = end
                continue
            if not xml:
                intro = re.match(r'<(script|style)\b', text[start:end], re.I)
                if intro:
                    name = "script" if re.fullmatch("script", intro[1], re.I) else "style"
                    # None caches the fact that no later closer exists, so
                    # repeated unclosed script tags never rescan the suffix.
                    if name not in closers or (closers[name] is not None and closers[name].start() < end):
                        closers[name] = closing_patterns[name].search(text, end)
                    if closers[name] is not None:
                        end = closers[name].end()
        match = pattern.match(text, start, end)
        if match:
            yield match
            pos = match.end()
        else:
            pos = end


class ConnectionPattern:
    """Bound each connection-string search to its next password assignment."""
    pattern = r"(?i)\b(?:Server|Host|Data Source)\s*=.+?(?:Password|Pwd)\s*=\s*[^;\s]+(?:;[^\n]*)?"
    flags = re.I | re.U
    _full = re.compile(pattern)
    _opening = re.compile(r"(?i)\b(?:Server|Host|Data Source)\s*+=.")
    _closing = re.compile(r"(?i)(?:Password|Pwd)\s*+=\s*+(?=[^;\s])")

    def search(self, text: str):
        return next(self.finditer(text), None)

    def finditer(self, text: str):
        pos, line_end, closing = 0, -1, None
        while opening := self._opening.search(text, pos):
            # Both caches move forward with the opening candidates. Retaining
            # one match and one offset avoids memory proportional to the number
            # of password headers or lines in an untrusted document.
            if closing is None or closing.start() < opening.end():
                closing = self._closing.search(text, opening.end())
                if closing is None:
                    return
            if line_end < opening.end():
                line_end = text.find('\n', opening.end())
                if line_end < 0:
                    line_end = len(text)
            if closing.start() > line_end:
                # A later opening may start before this LF and continue its
                # whitespace to '=' on the next line. Preserve that candidate;
                # the opening's last character may itself begin its name.
                pos = opening.end() - 1
                continue
            match = self._full.match(text, opening.start())
            if match is None:
                raise ValueError('Invalid connection delimiter pattern')
            yield match
            pos = match.end()
