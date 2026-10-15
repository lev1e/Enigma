"""Outbound guard (policy 1b.8): last check before anything leaves the computer. Fails closed.

`check(parts, vault, detector)` scans every outgoing text (prompt, system prompt, file names, attachment text) for
(a) any original value stored in the vault (case/space-insensitive) and (b) any detector hit. A hit blocks the send.
The result names the KIND of data and how many, never the value. If scanning itself fails, the send is blocked.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .tokens import TOKEN_RE, EMAIL_TOKEN_RE

MIN_LEN = 3          # shorter spellings (initials) would block ordinary text; they are covered by the detector
WORD_LEN = 6         # spellings shorter than this must match as whole words


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("​", "")).strip()


@dataclass
class GuardResult:
    blocked: bool = False
    kinds: dict = field(default_factory=dict)       # kind -> count (no values)
    reason: str = ""
    findings: list = field(default_factory=list)    # detector hits: {"id","part","start","end","category","possible"}; no values

    def message(self) -> str:
        if not self.blocked:
            return ""
        if self.reason:
            return self.reason
        names = ", ".join(f"{k} x{n}" for k, n in sorted(self.kinds.items()))
        return "Sending blocked: unmasked data found in the outgoing text (" + names + "). Nothing was sent."


def _is_label(text: str) -> bool:
    return bool(TOKEN_RE.fullmatch(text.strip()) or EMAIL_TOKEN_RE.fullmatch(text.strip()))


def _only_labels(text: str) -> bool:
    """A finding that is just labels and punctuation/@ (e.g. "@Name83", "email7@example.com.") is already masked."""
    rest = EMAIL_TOKEN_RE.sub(" ", text)
    rest = TOKEN_RE.sub(" ", rest)
    return not re.search(r"[^\W_]", rest, re.UNICODE) if (rest != text) else False


def vault_originals(vault) -> list[tuple[str, str]]:
    """(normalized original, kind) for every stored spelling and edited value."""
    out = []
    for entity in vault.entities.values():
        values = list(entity.get("spellings") or []) + list((entity.get("edits") or {}).values())
        for value in values:
            if isinstance(value, str):
                norm = _norm(value)
                if len(norm) >= MIN_LEN and not _is_label(value):
                    out.append((norm, entity.get("kind", "PII")))
    return out


def part_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def finding_id(part: int, digest: str, category: str, start: int, end: int) -> str:
    """Consent identifies one span in one exact payload part, without exposing its value."""
    return f"{part}:{category}:{start}:{end}:{digest}"


def check(parts: list[str], vault, detector=None, allow=None) -> GuardResult:
    """`allow`: ids of POSSIBLE_* findings the user allowed for this one send. A definite hit (phone, e-mail, secret,
    a vault original) can never be allowed, only masked."""
    result = GuardResult()
    allow = set(allow or ())
    try:
        originals = vault_originals(vault)
        for index, part in enumerate(parts):
            if not part:
                continue
            text = _norm(part)
            for original, kind in originals:
                if original not in text:
                    continue
                if len(original) < WORD_LEN and not re.search(rf"(?<!\w){re.escape(original)}(?!\w)", text):
                    continue
                result.kinds[kind] = result.kinds.get(kind, 0) + 1
            if detector is not None:
                digest = part_digest(part)
                for finding in detector.scan(part, "outgoing", "payload"):
                    if _is_label(finding.original) or _only_labels(finding.original) or getattr(finding, "decision", None) is None:
                        continue
                    possible = finding.category.startswith("POSSIBLE_")
                    fid = finding_id(index, digest, finding.category, finding.start, finding.end)
                    if possible and fid in allow:
                        continue
                    result.kinds[finding.category] = result.kinds.get(finding.category, 0) + 1
                    result.findings.append({"id": fid, "part": index, "start": finding.start, "end": finding.end,
                                            "category": finding.category, "possible": possible})
    except Exception:
        return GuardResult(True, {}, "Sending blocked: the safety check could not complete. Nothing was sent.")
    result.blocked = bool(result.kinds)
    return result


SECRET_MASK = "[секрет удалён]"


def strip_secrets(text: str, detector) -> tuple[str, int]:
    """P1, "original data" mode: passwords, keys, tokens and connection strings never leave, even when the user chose to
    send originals. Every SECRET hit is replaced by a fixed mark. Raises on a scanner failure (the caller fails closed)."""
    if not text or detector is None:
        return text, 0
    spans = sorted({(f.start, f.end) for f in detector.scan(text, "outgoing", "payload") if f.category == "SECRET"}, reverse=True)
    for start, end in spans:
        text = text[:start] + SECRET_MASK + text[end:]
    return text, len(spans)


def secrets_left(parts: list[str], detector) -> int:
    """Re-check of the exact outgoing strings in originals mode: number of SECRET hits still present (0 = clean)."""
    # our own mask is not a secret (it can look like a value after "Пароль:"), everything else still counts
    return sum(1 for part in parts if part for f in detector.scan(part.replace(SECRET_MASK, ""), "outgoing", "payload") if f.category == "SECRET")
