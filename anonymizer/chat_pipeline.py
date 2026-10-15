"""Text pipeline of the AI chat: anonymize -> outbound guard -> (dry run | send) -> streaming restore.

Rules enforced here:
  * AI is OFF unless the caller says it is on for this chat (`ai_on=True`); default off.
  * Nothing is sent when the guard blocks (fail closed). The guard runs on the exact strings that go into the request.
  * One request per `send`; no retry, no resend. `stop()` aborts the stream.
  * `dry_run` returns exactly `llm.build_request` output (labels visible, never the key, which lives in a header).
  * The outgoing log keeps labels and sizes only, never raw values or message text.
Restored text is for local display only; it is never passed back into a request (history stays in label form).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterator

from . import guard, llm
from .restore import TEXT_MARK_RE
from .service import Service, Upload
from .stream_restore import StreamRestorer
from .tokens import EMAIL_TOKEN_RE, TOKEN_RE, base_of


class AiOff(Exception):
    pass


class Blocked(Exception):
    def __init__(self, result: guard.GuardResult):
        super().__init__(result.message())
        self.result = result


@dataclass
class Prepared:
    text: str                     # anonymized user message (labels)
    system: str
    history: list                 # earlier messages in label form: [{"role","content"}]
    guard: guard.GuardResult
    labels: list = field(default_factory=list)
    allow: list = field(default_factory=list)      # POSSIBLE_* ids allowed for this one send
    originals: bool = False                        # P1: user chose original data; text is real, only secrets are stripped
    stripped: int = 0                              # number of secrets removed from the outgoing text in originals mode

    def messages(self) -> list:
        return list(self.history) + [{"role": "user", "content": self.text}]

    def guard_parts(self) -> list[str]:
        # Finding IDs include the part index. Keep the same ordering during
        # preparation and the final check so a per-span choice stays scoped.
        return [self.text, self.system] + [m["content"] for m in self.history]


class _PassThrough:
    """Originals mode has no placeholders: the reply is shown as the model wrote it."""

    def feed(self, text: str) -> str:
        return text

    def finish(self) -> str:
        return ""

    def report(self) -> dict:
        return {"found": 0, "restored": 0, "unknown": {}, "removed": {}, "damaged_but_restored": 0, "damaged": False}


class ChatPipeline:
    def __init__(self, service: Service):
        self.service = service
        self.vault = service.vault
        self.outgoing_log: list[dict] = []
        self._stop = threading.Event()

    # -- step 1+2: anonymize and guard ----------------------------------------------------------

    def anonymize_text(self, text: str, options: dict | None = None) -> str:
        job = self.service.anonymize([Upload("message.txt", text.encode("utf-8"))], options or {})
        try:
            outcome = job.files[0]
            if outcome.status == "error" or not outcome.out_path:
                raise Blocked(guard.GuardResult(True, {}, "Сообщение не удалось обезличить, поэтому ничего не отправлено."))
            raw = Path(outcome.out_path).read_bytes().decode("utf-8", errors="replace")
            return TEXT_MARK_RE.sub("", raw)
        finally:
            self.service.forget_job(job.id)

    def _mask_spans(self, anon: str, findings: list, wanted: set, allow: list) -> tuple[str, list, dict]:
        """The user chose "anonymize it" for these spans of the message: give each a vault label."""
        from .tokens import CATEGORY_ALIASES
        spans = sorted((f for f in findings if f["part"] == 0 and f["id"] in wanted), key=lambda f: -f["start"])
        # Ambiguous overlapping replacements cannot be translated safely.
        ascending = list(reversed(spans))
        if any(left["end"] > right["start"] for left, right in zip(ascending, ascending[1:])):
            raise Blocked(guard.GuardResult(True, {}, "Выбранные участки пересекаются. Ничего не отправлено."))
        changes = []
        for f in spans:
            original = anon[f["start"]:f["end"]]
            kind = CATEGORY_ALIASES.get(f["category"], f["category"])
            try:
                label = self.vault.token_for(kind, "ask:" + f["id"], original)
            except KeyError:
                label = self.vault.token_for("TERM", "ask:" + f["id"], original)
            anon = anon[:f["start"]] + label + anon[f["end"]:]
            changes.append((f["start"], f["end"], len(label) - (f["end"] - f["start"])))
        remapped = []
        source_ids = {}
        digest = guard.part_digest(anon)
        for f in findings:
            if f["part"] != 0:
                if f["possible"] and f["id"] in allow:
                    remapped.append(f["id"])
                continue
            start, end = f["start"], f["end"]
            if any(start < stop and end > begin for begin, stop, _delta in changes):
                continue
            shift = sum(delta for _begin, stop, delta in changes if stop <= start)
            translated = guard.finding_id(0, digest, f["category"], start + shift, end + shift)
            source_ids[translated] = f["id"]
            if f["possible"] and f["id"] in allow:
                remapped.append(translated)
        return anon, remapped, source_ids

    def prepare(self, text: str, system: str = "", history: list | None = None, options: dict | None = None,
                resolve: dict | None = None, attachments: list | None = None) -> Prepared:
        """`resolve`: {"anonymize": [finding ids], "allow": [finding ids]} - the per-span choices for POSSIBLE_* hits
        (allow applies to this call only; it is never stored)."""
        resolve = resolve or {}
        anon = self.anonymize_text(text, options)
        for n, (_name, body) in enumerate(attachments or [], 1):   # already anonymized by the file pipeline; the guard still sees every character
            anon += f"\n\n[Файл {n}]\n{body}\n[Конец файла {n}]"       # the file name is never sent
        system_anon = self.anonymize_text(system, options) if system.strip() else ""
        history = list(history or [])
        detector = self.service.build_detector(self.service.settings_for(options or {}))
        parts = [anon, system_anon] + [m["content"] for m in history]
        result = guard.check(parts, self.vault, detector)
        allow = [str(i) for i in resolve.get("allow") or []]
        mask = {str(i) for i in resolve.get("anonymize") or []}
        if result.blocked and mask:
            unresolved = [f for f in result.findings
                          if not (f["part"] == 0 and f["id"] in mask)
                          and not (f["possible"] and f["id"] in allow)]
            if unresolved:
                # The UI retries with the original composer text. Do not write
                # labels into the vault until every finding has a valid choice:
                # learning from a partial mask could change the next payload.
                result.findings = unresolved
                return Prepared(anon, system_anon, history, result, [], allow)
            anon, allow, source_ids = self._mask_spans(anon, result.findings, mask, allow)
            parts[0] = anon
            result = guard.check(parts, self.vault, detector, allow=allow)
            # The composer submits original text on every prepare/send. Keep
            # unresolved UI choices tied to those source spans, while `allow`
            # remains translated for the exact final payload checked by send.
            for finding in result.findings:
                finding["id"] = source_ids.get(finding["id"], finding["id"])
        elif result.blocked and allow:
            result = guard.check(parts, self.vault, detector, allow=allow)
        labels = sorted({base_of(m.group()) or m.group() for m in TOKEN_RE.finditer(anon)}
                        | {base_of(m.group()) or m.group() for m in EMAIL_TOKEN_RE.finditer(anon)})
        return Prepared(anon, system_anon, history, result, labels, allow)

    def prepare_originals(self, text: str, system: str = "", history: list | None = None,
                          attachments: list | None = None) -> Prepared:
        """P1: "send original data". No anonymization and no personal-data guard (the user chose this); passwords, keys,
        tokens and connection strings are still removed from every part. If the secret scan fails, nothing is sent."""
        detector = self.service.build_detector(self.service.settings_for({}))
        count = 0
        try:
            body, n = guard.strip_secrets(text, detector); count += n
            for k, (_name, extra) in enumerate(attachments or [], 1):
                clean, n = guard.strip_secrets(extra, detector); count += n
                body += f"\n\n[Файл {k}]\n{clean}\n[Конец файла {k}]"
            system_clean, n = guard.strip_secrets(system, detector) if system.strip() else ("", 0); count += n
            hist = []
            for m in history or []:
                clean, n = guard.strip_secrets(m["content"], detector); count += n
                hist.append({"role": m["role"], "content": clean})
        except Exception:
            return Prepared(text, system, [], guard.GuardResult(True, {}, "Проверка на пароли и ключи не завершилась. Ничего не отправлено."))
        return Prepared(body, system_clean, hist, guard.GuardResult(), [], [], True, count)

    # -- dry run ---------------------------------------------------------------------------------

    def dry_run(self, prepared: Prepared, provider: llm.Provider, max_tokens: int = 1024) -> dict:
        url, body = llm.build_request(provider, prepared.messages(), prepared.system, max_tokens, True)
        return {"url": url, "body": body, "findings": list(prepared.guard.findings), "blocked": prepared.guard.blocked, "message": prepared.guard.message(),
                "kinds": dict(prepared.guard.kinds), "labels": list(prepared.labels)}

    # -- send ------------------------------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def send(self, prepared: Prepared, provider: llm.Provider, *, ai_on: bool = False, max_tokens: int = 1024,
             timeout: float = 60.0) -> Iterator[tuple[str, object]]:
        """Yields ("delta", restored_text), then ("report", damaged-label report), ("usage", ...), ("done", ...).
        The raw model text (label form) is available as `self.last_raw` for conversation storage."""
        if not ai_on:
            raise AiOff("ИИ выключен для этого чата")
        if prepared.guard.blocked:
            raise Blocked(prepared.guard)
        # the guard runs again on exactly what goes into the request, so a stale Prepared cannot slip text through
        parts = prepared.guard_parts()
        detector = self.service.build_detector(self.service.settings_for({}))
        if prepared.originals:       # P1: personal data is allowed by the user's choice, secrets never are
            try:
                left = guard.secrets_left(parts, detector)
            except Exception:
                left = 1
            if left:
                raise Blocked(guard.GuardResult(True, {"SECRET": left}, "Отправка остановлена: в тексте остались пароли или ключи. Ничего не отправлено."))
        else:
            recheck = guard.check(parts, self.vault, detector, allow=prepared.allow)
            if recheck.blocked:
                raise Blocked(recheck)
        self._stop.clear()
        self.last_raw = ""
        restorer = _PassThrough() if prepared.originals else StreamRestorer(self.vault)
        entry = {"time": time.time(), "provider": provider.kind, "host": urllib.parse.urlsplit(provider.base).hostname,
                 "model": provider.model, "chars": sum(len(p) for p in parts), "labels": list(prepared.labels),
                 "status": "sent", "mode": "original" if prepared.originals else "anonymized"}
        self.outgoing_log.append(entry)           # logged before the request: an aborted send is still a send attempt
        raw = []
        try:
            for kind, value in llm.stream_chat(provider, prepared.messages(), prepared.system, max_tokens, timeout,
                                               cancel=self._stop.is_set):
                if kind == "delta":
                    raw.append(value)
                    shown = restorer.feed(value)
                    if shown:
                        yield "delta", shown
                else:
                    tail = restorer.finish() if kind == "usage" else ""
                    if tail:
                        yield "delta", tail
                    if kind == "usage":
                        yield "report", restorer.report()
                    yield kind, value
        except llm.LLMError as exc:
            entry["status"] = exc.code
            tail = restorer.finish()          # what arrived before the failure is kept, never resent
            if tail:
                yield "delta", tail
            raise
        finally:
            self.last_raw = "".join(raw)
