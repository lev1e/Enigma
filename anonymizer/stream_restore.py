"""Streaming restore for the AI chat: labels back to originals while the answer arrives (local display only).

A label can be cut by a chunk boundary ("Na" + "me1"), and damaged labels ("Name 1", "_Name1_", "name1") span two words. So the
last word (two if it starts with a digit) is held back until more text arrives or the stream ends. Everything before them is
restored with the same `Restorer` rules as the file restore, so the result equals restoring the whole text at once.
`report()` lists what the model damaged or invented, the same facts the file restore reports.
"""

from __future__ import annotations

import re

from .restore import Restorer

_WORD = re.compile(r"\S+")
HOLD_LIMIT = 40          # no label is longer than this; used when the tail has no whitespace at all
FLUSH_OVER = 200


class StreamRestorer:
    def __init__(self, vault):
        self.restorer = Restorer(vault)
        self._buf = ""

    def _cut(self) -> int:
        words = list(_WORD.finditer(self._buf))
        keep = words[-1:]
        if len(words) >= 2 and words[-1].group()[0].isdigit():
            keep = words[-2:]                     # "Name 1": a number after a space completes a damaged label
        cut = keep[0].start() if keep else len(self._buf)
        if cut == 0 and len(self._buf) > FLUSH_OVER:
            cut = len(self._buf) - HOLD_LIMIT
        return cut

    def feed(self, chunk: str) -> str:
        """Text that is safe to show now (may be empty while a label might still be arriving)."""
        self._buf += chunk
        cut = self._cut()
        ready, self._buf = self._buf[:cut], self._buf[cut:]
        return self.restorer.substitute(ready) if ready else ""

    def finish(self) -> str:
        ready, self._buf = self._buf, ""
        return self.restorer.substitute(ready) if ready else ""

    def report(self) -> dict:
        s = self.restorer.stats
        return {"found": s.found, "restored": s.restored, "unknown": dict(s.unknown), "removed": dict(s.removed),
                "damaged_but_restored": s.loose, "damaged": bool(s.unknown or s.loose or s.removed)}
