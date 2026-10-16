"""AI chat routes and storage (W12). Only the local server talks to the provider; the page talks to the local server.

Per chat: an AI flag (default OFF) and the conversation in LABEL form, encrypted with the device key next to the chat
(`ai.bin`; deleting the chat shreds it). Restored text is computed on the fly for display and is never stored and never
put back into a request. A reply streams into an in-memory run that the page polls; nothing is logged but sizes and labels.
"""

from __future__ import annotations

import base64
import dataclasses
import binascii
import json
import re
import secrets
import threading
import time
from pathlib import Path

from . import ai_docedit, chat_pipeline, crypto, docedit, guard, llm, policy
from .docedit import PatchRejected
from .formats import extract_text
from .service import Upload
from .stream_restore import StreamRestorer
from .restore import Restorer, TEXT_MARK_RE
from .tokens import EMAIL_TOKEN_RE, TOKEN_RE
from .util import atomic_write

FILE = "ai.bin"
HISTORY_LIMIT = 20            # earlier messages sent along with a new one
MAX_TEXT = 60_000
MAX_RUNS = 20
MAX_ATTACH_BYTES = 5 * 1024 * 1024    # file size before anonymization
MAX_ATTACH_CHARS = 120_000            # anonymized text of one file that may go to the provider
MODEL_OK = re.compile(r"[\w.:/+@-]{1,120}")
MAX_ATTACHMENTS = 3                   # per message
SSE_KEEPALIVE = 15.0
SSE_MAX_SECONDS = 900.0


# S10A: composer at the bottom of the file chat. The message may carry the anonymized text of the chat's files and may ask the
# model to edit the latest file. Only label-form text leaves the machine; the edited text comes back as a NEW file in the chat.
EDIT_RE = re.compile(r"(?<!\w)(поправ|исправ|измени|изменит|замени|заменит|отредактир|редактир|перепиш|добавь|добавит|удали|убери|"
                     r"дополни|переформулир|сократи|правк|edit|fix|rewrite|change|replace)", re.I)
TEXT_EXTS = (".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".html", ".htm", ".xml", ".log", ".yaml", ".yml")
def _edit_block(raw: str) -> str | None:
    start = raw.find("<<<ФАЙЛ>>>")
    if start < 0:
        return None
    start += len("<<<ФАЙЛ>>>")
    end = raw.find("<<<КОНЕЦ>>>", start)
    if end < 0:
        return None
    body = raw[start:end].lstrip(" \t")
    if body.startswith("\r"):
        body = body[1:]
    if body.startswith("\n"):
        body = body[1:]
    body = body.rstrip(" \t")
    if body.endswith("\n"):
        body = body[:-1]
    if body.endswith("\r"):
        body = body[:-1]
    return body

EDIT_SYSTEM = ("Ты редактируешь файл. Первый из приложенных файлов (Файл 1) нужно изменить по просьбе пользователя. "
               "Верни ПОЛНЫЙ исправленный текст этого файла между строками <<<ФАЙЛ>>> и <<<КОНЕЦ>>>, без пояснений внутри блока. "
               "Все метки в тексте (например Name1, Phone1) оставляй без изменений. Пояснение к правке, если нужно, напиши после блока.")


_TEMPLATE_PARTS = ("/slidelayouts/", "/slidemasters/", "/notesmasters/", "/handoutmasters/")     # template placeholder text, not file content


def _body_text(path) -> str:
    """Readable text of an anonymized file without Office properties and theme parts (template names, metadata)."""
    import tempfile
    import zipfile
    if path.suffix.lower() not in (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"):
        return extract_text(path)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / path.name
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(copy, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                low = info.filename.lower()
                if not low.startswith("docprops/") and "/theme/" not in low and not any(m in low for m in _TEMPLATE_PARTS):
                    dst.writestr(info, src.read(info.filename))
        return extract_text(copy)


class AiChats:
    def __init__(self, app):
        self.app = app
        self.runs: dict[str, dict] = {}
        self.attachments: dict[str, dict] = {}      # in memory only, label form; gone on restart or vault clear
        self._lock = threading.RLock()

    # -- encrypted conversation (label form only) ----------------------------------------------

    def _path(self, chat_id: str):
        if self.app.chats.get(chat_id) is None:
            raise KeyError("Чат не найден")
        return self.app.chats._chat_dir(chat_id) / FILE

    def load(self, chat_id: str) -> dict:
        path = self._path(chat_id)
        try:
            data = json.loads(crypto.decrypt_blob(path.read_bytes(), self.app.chats._key))
        except (OSError, ValueError, crypto.KeyErrorSafe):
            data = {}
        choice = data.get("choice") if isinstance(data.get("choice"), dict) else {}
        props = data.get("proposals") if isinstance(data.get("proposals"), dict) else {}
        return {"ai": bool(data.get("ai")), "messages": list(data.get("messages") or []), "proposals": props,
                "choice": {"provider": str(choice.get("provider", "")), "model": str(choice.get("model", ""))}}

    def save(self, chat_id: str, data: dict) -> None:
        path = self._path(chat_id)
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        atomic_write(path, crypto.encrypt_blob(raw, self.app.chats._key))

    # -- views -----------------------------------------------------------------------------------

    def view(self, chat_id: str) -> dict:
        data = self.load(chat_id)
        restorer = Restorer(self.app.vault)         # display only: restored text is not stored anywhere
        messages = [{"role": m["role"], "label_text": m["content"], "mode": m.get("mode", "anonymized"),
                     "text": m["content"] if m.get("mode") == "orig" else restorer.substitute(m["content"])}
                    for m in data["messages"]]
        run = self.active_run(chat_id)
        return {"ai": data["ai"], "enabled": self.app.keystore.enabled(), "messages": messages,
                "run": run["id"] if run else None, "choice": data["choice"], "proposals": self.pending(chat_id)}

    def set_choice(self, chat_id: str, body: dict) -> dict:
        """P1: the provider and model picked for this chat are remembered (switching mid-conversation is allowed)."""
        pid, model = str(body.get("provider", "")), str(body.get("model", ""))
        info = self._info(pid)
        if model and not MODEL_OK.fullmatch(model):
            raise ValueError("Некорректное название модели")
        data = self.load(chat_id)
        data["choice"] = {"provider": info["id"], "model": model}
        self.save(chat_id, data)
        return {"choice": data["choice"]}

    def active_run(self, chat_id: str) -> dict | None:
        for run in self.runs.values():
            if run["chat"] == chat_id and not run["done"]:
                return run
        return None

    def _info(self, pid: str) -> dict:
        """Public metadata (id, name, tier, badge, models) of the chosen provider; empty id = first ready one."""
        store = self.app.keystore
        if not pid:
            ready = [p for p in store.listing() if p.get("saved") or p.get("local")]
            if not ready:
                raise ValueError("Не настроен ни один провайдер")
            return ready[0]
        try:
            return store.public(pid)
        except KeyError:
            raise ValueError("Такого провайдера нет") from None

    def _provider(self, pid: str, model: str = "") -> llm.Provider:
        info = self._info(pid)
        provider = self.app.keystore.provider(info["id"])
        if model:
            if not MODEL_OK.fullmatch(model):
                raise ValueError("Некорректное название модели")
            provider = dataclasses.replace(provider, model=model)
        return provider

    # -- prepare / dry run -------------------------------------------------------------------

    def _prepare(self, chat_id: str, body: dict, pipeline, originals: bool = False):
        text = str(body.get("text", ""))
        if not text.strip():
            raise ValueError("Сначала напишите сообщение")
        if len(text) > MAX_TEXT:
            raise ValueError("Сообщение слишком длинное")
        history = self.load(chat_id)["messages"][-HISTORY_LIMIT:]
        if not originals:      # messages written in original-data mode never go back out in an anonymized request
            history = [m for m in history if m.get("mode") != "orig"]
        history = [{"role": m["role"], "content": m["content"]} for m in history]
        resolve = body.get("resolve") if isinstance(body.get("resolve"), dict) else {}
        ids = body.get("attachments") or []
        if not isinstance(ids, list) or len(ids) > MAX_ATTACHMENTS:
            raise ValueError(f"Не больше {MAX_ATTACHMENTS} файлов в одном сообщении")
        files = []
        for att_id in ids:
            att = self.attachments.get(str(att_id))
            if att is None or att["chat"] != chat_id:
                raise ValueError("Прикреплённый файл больше недоступен. Прикрепите его снова.")
            files.append((att["name"], att["text"]))
        if originals:
            extra = [("attachment", t) for t in body.get("_orig_texts") or []]
            return pipeline.prepare_originals(text, str(body.get("system", "")), history, files + extra)
        return pipeline.prepare(text, str(body.get("system", "")), history, None, resolve, files)

    @staticmethod
    def _blocked_view(prepared, dry: dict | None) -> dict:
        return {"blocked": prepared.guard.blocked, "message": prepared.guard.message(), "kinds": dict(prepared.guard.kinds),
                "findings": [{k: f[k] for k in ("id", "start", "end", "category", "possible")} for f in prepared.guard.findings
                             if f["part"] == 0],
                "other_findings": sum(1 for f in prepared.guard.findings if f["part"] != 0),
                "anonymized": prepared.text, "labels": list(prepared.labels), "dry_run": dry}

    def _build(self, chat_id: str, body: dict):
        """Shared by the dry run and the send: provider, policy checks, files, anonymized or original request.
        Returns (body, provider, info, prepared, edit, note, originals)."""
        body = dict(body)
        body.pop("_orig_texts", None)                  # internal key, never taken from the page
        info = self._info(str(body.get("provider", "")))
        provider = self._provider(info["id"], str(body.get("model", "")))
        if not policy.host_allowed(policy.load(), provider.base):
            raise ValueError("Адрес сервера не входит в список разрешённых политикой безопасности")
        edit, note = None, ""
        if body.get("with_files"):
            body, edit, note = self._with_chat_files(chat_id, body)
        originals = bool(body.get("_orig_texts"))
        if originals:
            why = policy.check_originals(policy.load(), info["tier"])
            if why:
                raise ValueError(why)
        pipeline = chat_pipeline.ChatPipeline(self.app.service)
        prepared = self._prepare(chat_id, body, pipeline, originals)
        return body, provider, info, prepared, edit, note, originals, pipeline

    def prepare(self, chat_id: str, body: dict) -> dict:
        body, provider, info, prepared, _edit, _note, originals, pipeline = self._build(chat_id, body)
        dry = pipeline.dry_run(prepared, provider, int(body.get("max_tokens") or 1024))
        dry = {"url": dry["url"], "body": dry["body"]}       # exactly what would be sent (the key is a header, not shown)
        view = self._blocked_view(prepared, dry)
        view["mode"] = "original" if originals else "anonymized"
        view["secrets_removed"] = prepared.stripped
        return view

    # -- attachments -------------------------------------------------------------------------------

    def attach(self, chat_id: str, body: dict) -> dict:
        """Anonymize an attached file with the normal pipeline; keep only guard-approved label-form text.
        Refusals return {"ok": False, "reason": ...} and nothing is stored or sent."""
        self._path(chat_id)
        name = str(body.get("name") or "file")[:200]
        encoded = str(body.get("data") or "")
        if len(encoded) > MAX_ATTACH_BYTES * 4 // 3 + 16:
            return {"ok": False, "reason": "Файл слишком большой (предел 5 МБ)."}
        try:
            data = base64.b64decode(encoded, validate=False)
        except (binascii.Error, ValueError):
            return {"ok": False, "reason": "Файл не удалось прочитать."}
        if not data:
            return {"ok": False, "reason": "Файл пустой."}
        if len(data) > MAX_ATTACH_BYTES:
            return {"ok": False, "reason": "Файл слишком большой (предел 5 МБ)."}
        service = self.app.service
        try:
            job = service.anonymize([Upload(name, data)], {})
        except Exception as exc:
            return {"ok": False, "reason": f"Файл не удалось обезличить ({type(exc).__name__}). Ничего не отправлено."}
        try:
            outcome = job.files[0] if job.files else None
            if outcome is None or outcome.status == "error" or not outcome.out_path:
                why = " ".join(m["text"] for m in (outcome.messages if outcome else []) if m["level"] == "error")
                return {"ok": False, "reason": "Файл отклонён и не отправлен. " + (why or "")}
            warns = [m["text"] for m in outcome.messages if m["level"] == "warn"]
            if [w for w in warns if not w.startswith("Данных для замены не найдено")]:     # that one is benign; the guard still checks the text
                why = " ".join(warns)
                return {"ok": False, "reason": "Сначала файл нужно проверить в главном окне; он не отправлен. " + why}
            from pathlib import Path
            text = _body_text(Path(outcome.out_path)).strip()
            out_name = "attachment"        # the file name itself is never sent
        except Exception as exc:
            return {"ok": False, "reason": f"Обезличенный текст не удалось прочитать ({type(exc).__name__}). Ничего не отправлено."}
        finally:
            service.forget_job(job.id)
        if not text:
            return {"ok": False, "reason": "В файле не найден текст (сканы и картинки не отправляются)."}
        if len(text) > MAX_ATTACH_CHARS:
            return {"ok": False, "reason": "В файле слишком много текста для одного сообщения."}
        result = guard.check([out_name, text], self.app.vault, service.build_detector(service.settings_for({})))
        if result.blocked:
            return {"ok": False, "reason": "В файле всё ещё похоже на персональные данные, поэтому он не отправлен. "
                    + result.message()}
        att_id = secrets.token_urlsafe(9)
        with self._lock:
            while len(self.attachments) >= 20:
                self.attachments.pop(next(iter(self.attachments)))
            self.attachments[att_id] = {"id": att_id, "chat": chat_id, "name": out_name, "text": text}
        return {"ok": True, "id": att_id, "name": out_name, "chars": len(text)}

    # -- local restore of an answer, offered as a download ------------------------------------------

    def export(self, chat_id: str, body: dict):
        messages = self.load(chat_id)["messages"]
        try:
            index = int(body.get("index"))
            message = messages[index]
        except (TypeError, ValueError, IndexError):
            raise ValueError("Сообщение не найдено") from None
        if message["role"] != "assistant":
            raise ValueError("Сохранить можно только ответ ИИ")
        if message.get("mode") == "orig":
            return "file", message["content"].encode("utf-8"), f"ai-answer-{index + 1}.txt"
        restorer = StreamRestorer(self.app.vault)
        text = restorer.feed(message["content"]) + restorer.finish()
        report = restorer.report()
        if report["damaged"] and not body.get("accept_damaged"):
            return "json", {"ok": False, "needs_confirm": True, "report": report}
        return "file", text.encode("utf-8"), f"ai-answer-{index + 1}.txt"

    # -- files of the chat as label-form context (S10A) -----------------------------------------

    def _chat_file_text(self, chat_id: str, record: dict, original: bool = False) -> str:
        import tempfile
        if original:       # the stored original, else the version with the values put back (same content)
            blob = self.app.chats.read_blob(chat_id, record["id"], "orig") or self.app.chats.read_blob(chat_id, record["id"], "restored")
            name = record["name"]
        else:
            blob = self.app.chats.read_blob(chat_id, record["id"], "anon")
            name = (record.get("names") or {}).get("anon") or record["name"]
        if not blob:
            return ""
        if name.lower().endswith(TEXT_EXTS):
            return TEXT_MARK_RE.sub("", blob.decode("utf-8", errors="replace")).strip()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ("f" + Path(name).suffix.lower())
            path.write_bytes(blob)
            try:
                return TEXT_MARK_RE.sub("", _body_text(path)).strip()
            except Exception:
                return ""

    def _chat_targets(self, chat_id: str) -> list[dict]:
        chat = self.app.chats.get(chat_id) or {"files": []}
        return [r for r in reversed(chat["files"]) if r.get("status") != "error" and "anon" in r.get("roles", {})]

    def _register(self, chat_id: str, text: str) -> str:
        att_id = secrets.token_urlsafe(9)
        with self._lock:
            while len(self.attachments) >= 20:
                self.attachments.pop(next(iter(self.attachments)))
            self.attachments[att_id] = {"id": att_id, "chat": chat_id, "name": "attachment", "text": text}
        return att_id

    def _with_chat_files(self, chat_id: str, body: dict) -> tuple[dict, dict | None, str]:
        """Adds the anonymized text of the chat's files to the message. Returns (body, edit target or None, note)."""
        text = str(body.get("text", ""))
        want_edit = bool(body.get("edit")) or bool(EDIT_RE.search(text))
        targets = self._chat_targets(chat_id)
        if "file_ids" in body:                    # per-message file choice: only chat files the user ticked; an empty list means none
            chosen = body.get("file_ids")
            if not isinstance(chosen, list) or not all(isinstance(x, str) for x in chosen):
                raise ValueError("Некорректный список файлов")
            wanted = set(chosen)
            targets = [r for r in targets if r["id"] in wanted]    # unknown or foreign ids are simply ignored, never fetched
        sources = body.get("sources") if isinstance(body.get("sources"), dict) else {}
        ids = list(body.get("attachments") or [])
        note, edit = "", None
        picked, orig_texts = [], []
        # P2B: docx / pptx / xlsx are edited by a JSON patch; the model gets the structure of the chosen version instead of plain text
        selected = ai_docedit.clean_selection(body.get("selected"))
        office = None
        if not want_edit and targets and "?" not in text and ai_docedit.DESIGN_RE.search(text):
            lead = next((r for r in targets if r["id"] == body.get("selected_file")), None) if selected else None
            if ai_docedit.is_office((lead or targets[0])["name"]):
                want_edit = True                   # a design request ("шрифт крупнее") on an Office file is an edit request too
        if want_edit and targets:
            pref = body.get("selected_file")
            top = next((r for r in targets if r["id"] == pref), None) if selected and isinstance(pref, str) else None
            top = top or targets[0]
            if ai_docedit.is_office(top["name"]):
                office = (top, sources.get(top["id"]) == "original")
                targets = [top] + [r for r in targets if r["id"] != top["id"]]
        for rec in targets:
            use_orig = sources.get(rec["id"]) == "original"
            if office and rec["id"] == office[0]["id"]:
                body_text = self._office_context(chat_id, rec, use_orig, text, selected)
            else:
                body_text = self._chat_file_text(chat_id, rec, use_orig)
            if body_text and len(body_text) <= MAX_ATTACH_CHARS:
                picked.append((rec, body_text, use_orig))
            elif use_orig and not body_text:
                raise ValueError("У этого файла нет исходной версии: выберите «Обезличенный».")
            if len(picked) >= max(0, MAX_ATTACHMENTS - len(ids)):
                break
        if any(u for _r, _t, u in picked):       # at least one file goes as the original: the whole message is an original-data message
            orig_texts = [t for _r, t, u in picked if u]
            if not (office and office[1]):
                want_edit = False
                note = "Правка файла работает только с обезличенной версией. Ниже текстовый ответ ИИ." if (bool(body.get("edit")) or bool(EDIT_RE.search(text))) else ""
                office = None
        if want_edit and office:
            if picked and picked[0][0]["id"] == office[0]["id"]:
                edit = dict(office[0], _office={"orig": office[1], "selected": selected})
            else:
                note = "Файл слишком большой для правки через ИИ или пустой. Ниже текстовый ответ ИИ."
        elif want_edit and targets:
            top = targets[0]
            name = (top.get("names") or {}).get("anon") or top["name"]
            if not name.lower().endswith(TEXT_EXTS):
                ext = Path(name).suffix.lower() or "этого типа"
                note = (f"Править файл {ext} прямо в чате пока нельзя: безопасно перенести правку ИИ в такой формат "
                        "программа не умеет. Ниже текстовый ответ ИИ, внесите правку вручную.")
            elif picked and picked[0][0]["id"] == top["id"] and not picked[0][2]:
                edit = top
            else:
                note = "Файл слишком большой для правки через ИИ или пустой. Ниже текстовый ответ ИИ."
        elif want_edit and not targets:
            note = "В чате нет файла для правки. Добавьте файл, и ИИ сможет предложить новую версию."
        new_ids = [self._register(chat_id, t) for _r, t, u in picked if not u]
        out = dict(body)
        out["attachments"] = new_ids + ids
        if orig_texts:
            out["_orig_texts"] = orig_texts
        if edit:
            out["system"] = ai_docedit.system_prompt(ai_docedit.fmt_of(edit["name"])) if edit.get("_office") else EDIT_SYSTEM
        return out, edit, note

    # -- P2B: Office files are edited by a validated JSON patch --------------------------------------

    def _office_blob(self, chat_id: str, rec: dict, orig: bool):
        """(bytes, name) of the chosen version: the anonymized file, or the original (else the restored one: same content)."""
        if orig:
            blob = self.app.chats.read_blob(chat_id, rec["id"], "orig") or self.app.chats.read_blob(chat_id, rec["id"], "restored")
            return blob, rec["name"]
        return self.app.chats.read_blob(chat_id, rec["id"], "anon"), (rec.get("names") or {}).get("anon") or rec["name"]

    def _office_context(self, chat_id: str, rec: dict, orig: bool, text: str, selected: list) -> str:
        blob, name = self._office_blob(chat_id, rec, orig)
        if not blob:
            raise ValueError("У этого файла нет исходной версии: выберите «Обезличенный»." if orig else "У файла нет обезличенной версии.")
        try:
            ctx, _info = ai_docedit.build_context(blob, name, text, selected)
        except PatchRejected as exc:
            if exc.code == "too_big":
                raise ValueError("Файл большой: выделите слайд, лист или абзац, который нужно изменить.") from None
            raise ValueError("Этот файл ИИ править не умеет: " + exc.text) from None
        if len(ctx) > MAX_ATTACH_CHARS:
            raise ValueError("Файл большой: выделите слайд, лист или абзац, который нужно изменить.")
        return ctx

    def _propose(self, run: dict, raw: str) -> dict:
        """Reply -> one validated patch -> cards. Nothing is written; a rejected patch offers nothing (no partial apply)."""
        edit = run["edit"]
        info = edit["_office"]
        try:
            patch = ai_docedit.extract_patch(raw)
        except ValueError as exc:
            if "```" not in raw and '"ops"' not in raw:
                return {"applied": False, "note": "ИИ не предложил правок, это текстовый ответ. Файл не менялся."}
            return {"applied": False, "note": str(exc)}
        base, name = self._office_blob(run["chat"], edit, info["orig"])
        if not base:
            return {"applied": False, "note": "Версия файла недоступна. Правки не предложены."}
        try:
            patch = ai_docedit.unalias_for(base, name, patch)
            view = ai_docedit.validate(base, name, patch, guard.SECRET_MASK if info["orig"] else None)
        except PatchRejected as exc:
            return {"applied": False, "note": ai_docedit.reason(exc), "code": exc.code}
        pid = secrets.token_urlsafe(9)
        prop = {"id": pid, "chat": run["chat"], "file": edit["id"], "orig": info["orig"], "patch": patch,
                "items": view["items"], "hint": view["hint"], "note": view["note"], "done": []}
        with self._lock:                  # kept in the encrypted chat data, so a restart or a second window still sees it
            data = self.load(run["chat"])
            props = data["proposals"]
            while len(props) >= 10:
                props.pop(next(iter(props)))
            props[pid] = prop
            self.save(run["chat"], data)
        writable = sum(1 for it in view["items"] if not it["comment"])
        return {"applied": False, "proposal": self._public_proposal(prop),
                "note": f"Предложено правок: {writable}. Ничего не изменено, пока вы не нажмёте «Применить»." if writable
                else "ИИ оставил только комментарии. Файл не менялся."}

    @staticmethod
    def _public_proposal(p: dict) -> dict:
        return {"id": p["id"], "file": p["file"], "source": "original" if p["orig"] else "anonymized", "items": p["items"],
                "hint": p["hint"], "note": p["note"], "done": sorted(p["done"])}

    def pending(self, chat_id: str) -> list:
        with self._lock:
            return [self._public_proposal(p) for p in self.load(chat_id)["proposals"].values()]

    def decide(self, chat_id: str, body: dict) -> dict:
        """Apply (all or chosen cards) or reject a proposal. Applying re-validates exactly the chosen subset against the current
        version and creates a NEW version; on any rejection nothing changes."""
        pid, action = str(body.get("id", "")), body.get("action")
        with self._lock:
            data = self.load(chat_id)
            props = data["proposals"]
            prop = props.get(pid)
            if prop is None:
                raise KeyError("Предложение правок не найдено или уже закрыто")
            if action == "reject":
                ops = body.get("ops")
                if isinstance(ops, list) and ops:         # reject some cards: they are marked done and never applied
                    prop["done"] = sorted(set(prop["done"]) | {int(i) for i in ops if isinstance(i, int)})
                    if all(i in prop["done"] or it["comment"] for i, it in enumerate(prop["items"])):
                        props.pop(pid, None)
                    self.save(chat_id, data)
                    return {"ok": True, "left": self._left(prop)}
                props.pop(pid, None)
                self.save(chat_id, data)
                return {"ok": True, "left": []}
            if action != "apply":
                raise ValueError("Неизвестное действие")
            ops = body.get("ops", "all")
            if ops == "all":
                ops = [i for i, it in enumerate(prop["items"]) if not it["comment"] and i not in prop["done"]]
            if not isinstance(ops, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ops):
                raise ValueError("Некорректный список правок")
            ops = [i for i in ops if i not in prop["done"]]
            sub = ai_docedit.subset(prop["patch"], ops)
            rec = self.app.chats.get(chat_id)
            rec = next((r for r in (rec or {"files": []})["files"] if r["id"] == prop["file"]), None)
            if rec is None:
                raise KeyError("Файл правки больше недоступен")
            base, name = self._office_blob(chat_id, rec, prop["orig"])
            if not base:
                return {"ok": False, "reason": "Версия файла недоступна. Файл остался прежним."}
            try:
                if prop["orig"]:
                    ai_docedit.check_secret_mask(sub, guard.SECRET_MASK)
                new, _report = docedit.apply_patch(base, name, sub)
            except PatchRejected as exc:
                return {"ok": False, "reason": ai_docedit.reason(exc), "code": exc.code, "left": self._left(prop)}
            total = len([1 for it in prop["items"] if not it["comment"]])
            made = self._store_office_version(chat_id, rec, new, prop["orig"],
                                              f"принято {len(ops)} из {total}")
            if made.get("reason"):
                return {"ok": False, "reason": made["reason"], "left": self._left(prop)}
            prop["done"] = sorted(set(prop["done"]) | set(ops))
            prop["file"] = made["file"]
            left = self._left(prop)
            if not left:
                props.pop(pid, None)
            self.save(chat_id, data)
            return {"ok": True, "file": made["file"], "name": made["name"], "source": "original" if prop["orig"] else "anonymized",
                    "left": left, "hint": prop["hint"],
                    "note": f"Создана версия «{made['name']}». Исходный файл и прежние версии сохранены." + (" " + made["warn"] if made.get("warn") else "")}

    @staticmethod
    def _left(prop: dict) -> list:
        return [i for i, it in enumerate(prop["items"]) if not it["comment"] and i not in prop["done"]]

    def _store_office_version(self, chat_id: str, rec: dict, new: bytes, orig: bool, summary: str) -> dict:
        """Stores `new` as a NEW file record. Anonymized base: the restored copy is made locally by the normal restorer (any unknown
        or loose label = no version). Original base: the anonymized copy is made with the normal pipeline, best effort."""
        import tempfile
        src_name = rec["name"] if orig else (rec.get("names") or {}).get("anon") or rec["name"]
        stem, ext = src_name.rsplit(".", 1) if "." in src_name else (src_name, "")
        stem = re.sub(r" \(правка ИИ \d+\)$", "", stem)
        n = 1 + sum(1 for r in (self.app.chats.get(chat_id) or {"files": []})["files"] if r["name"].startswith(stem + " (правка ИИ "))
        new_name = f"{stem} (правка ИИ {n})" + ("." + ext if ext else "")
        kind = rec.get("kind", ext)
        warn = ""
        names = {"anon": new_name, "restored": new_name, "aiedit_of": rec["id"]}
        texts = " ".join(e.get("text") or "" for c in docedit.outline(new, new_name)["containers"] for e in c["elements"])
        if not orig:
            from .restore import restore_ooxml
            with tempfile.TemporaryDirectory() as tmp:
                a, b = Path(tmp) / ("a." + ext), Path(tmp) / ("b." + ext)
                a.write_bytes(new)
                restorer = Restorer(self.app.vault)
                try:
                    ok = restore_ooxml(a, b, restorer)
                    restored = b.read_bytes() if ok and b.exists() else None
                except Exception:
                    restored = None
            if restored is None or restorer.stats.unknown or restorer.stats.loose:
                return {"reason": "Правка не применена: значения нельзя вернуть без догадок. Файл остался прежним."}
            tokens = sorted({m.group() for m in TOKEN_RE.finditer(texts)} | {m.group() for m in EMAIL_TOKEN_RE.finditer(texts)})
            record = self.app.chats.add_file(chat_id, new_name, kind, tokens=tokens, names=names, anon=new, restored=restored)
        else:
            anon, tokens = None, []
            service = self.app.service
            try:
                job = service.anonymize([Upload(new_name, new)], {})
                try:
                    out = job.files[0] if job.files else None
                    if out is not None and out.status != "error" and out.out_path:
                        anon, tokens = Path(out.out_path).read_bytes(), list(out.tokens or [])
                finally:
                    service.forget_job(job.id)
            except Exception:
                anon = None
            record = self.app.chats.add_file(chat_id, new_name, kind, tokens=tokens, names=names, anon=anon, restored=new, orig=new)
            if anon is None:
                warn = ("Обезличенной копии нет: файл не удалось обезличить автоматически. Новая версия есть только в исходном виде; "
                        "обезличьте её в главном окне, прежде чем отправлять куда-либо.")
        self.app.chats.add_step(chat_id, "ai_edit", files=[record["id"]], source=rec["id"], status="ok", summary=summary)
        return {"file": record["id"], "name": new_name, "warn": warn}

    def _apply_edit(self, run: dict, raw: str) -> dict:
        """Turns the model's answer into a new version of the file, or says plainly why not. Fails closed."""
        edit = run["edit"]
        label_text = _edit_block(raw)
        if label_text is None or not label_text.strip():
            return {"applied": False, "note": "ИИ не вернул файл целиком, поэтому новая версия не создана. Текстовый ответ ниже."}
        restorer = Restorer(self.app.vault)
        restored = restorer.substitute(label_text)
        st = restorer.stats
        if st.unknown or st.removed or st.loose:
            return {"applied": False, "note": "ИИ исказил метки в тексте, поэтому значения нельзя вернуть без догадок. "
                    "Новая версия не создана. Текстовый ответ ниже."}
        chat_id = run["chat"]
        src_name = (edit.get("names") or {}).get("anon") or edit["name"]
        stem, ext = (src_name.rsplit(".", 1) + [""])[:2] if "." in src_name else (src_name, "")
        stem = re.sub(r" \(правка ИИ \d+\)$", "", stem)
        n = 1 + sum(1 for r in (self.app.chats.get(chat_id) or {"files": []})["files"] if r["name"].startswith(stem + " (правка ИИ "))
        new_name = f"{stem} (правка ИИ {n})" + ("." + ext if ext else "")
        tokens = sorted({m.group() for m in TOKEN_RE.finditer(label_text)} | {m.group() for m in EMAIL_TOKEN_RE.finditer(label_text)})
        record = self.app.chats.add_file(chat_id, new_name, edit.get("kind", "text"), tokens=tokens,
                                         names={"anon": new_name, "restored": new_name, "aiedit_of": edit["id"]},
                                         anon=label_text.encode("utf-8"), restored=restored.encode("utf-8"))
        self.app.chats.add_step(chat_id, "ai_edit", files=[record["id"]], source=edit["id"], status="ok")
        return {"applied": True, "file": record["id"], "name": new_name,
                "note": "Создана новая версия файла. Исходный файл и прежние версии сохранены."}

    # -- send --------------------------------------------------------------------------------------

    def send(self, chat_id: str, body: dict) -> dict:
        if not self.app.keystore.enabled():
            raise ValueError("ИИ выключен в настройках")
        data = self.load(chat_id)
        if not data["ai"]:
            raise ValueError("ИИ выключен для этого чата")
        if self.active_run(chat_id):
            raise ValueError("Ответ уже идёт. Дождитесь его или остановите")
        body, provider, info, prepared, edit, note, originals, pipeline = self._build(chat_id, body)
        if prepared.guard.blocked:
            return self._blocked_view(prepared, None)          # fail closed: nothing leaves, nothing is stored
        if originals and not body.get("confirm_originals"):    # quiet one-line notice, confirmed by one more Enter in the page
            return {"blocked": False, "needs_confirm_originals": True,
                    "notice": {"provider": info["name"], "badge": info["badge"], "model": provider.model,
                               "secrets_removed": prepared.stripped}}
        data["choice"] = {"provider": info["id"], "model": provider.model}
        self.save(chat_id, data)
        run = {"id": secrets.token_urlsafe(9), "chat": chat_id, "text": "", "done": False, "error": "", "report": None,
               "usage": None, "pipeline": pipeline, "time": time.time(), "cond": threading.Condition(),
               "edit": edit, "edit_result": {"applied": False, "note": note} if note else None,
               "mode": "orig" if originals else "anonymized"}
        with self._lock:
            for old in [r for r in self.runs.values() if r["done"]][:-MAX_RUNS]:
                self.runs.pop(old["id"], None)
            self.runs[run["id"]] = run
        max_tokens = int(body.get("max_tokens") or 1024)
        threading.Thread(target=self._run, args=(run, prepared, provider, max_tokens), daemon=True).start()
        return {"blocked": False, "run": run["id"], "labels": list(prepared.labels), "editing": bool(edit), "note": note,
                "mode": "original" if originals else "anonymized", "secrets_removed": prepared.stripped}

    def _run(self, run: dict, prepared, provider: llm.Provider, max_tokens: int) -> None:
        pipeline = run["pipeline"]
        try:
            for kind, value in pipeline.send(prepared, provider, ai_on=True, max_tokens=max_tokens):
                with run["cond"]:
                    if kind == "delta":
                        run["text"] += value
                    elif kind == "report":
                        run["report"] = value
                    elif kind == "usage":
                        run["usage"] = value
                    run["cond"].notify_all()
        except llm.LLMError as exc:
            run["error"] = llm.scrub(exc.message, provider)
        except chat_pipeline.Blocked as exc:
            run["error"] = str(exc)
        except Exception as exc:               # never let a provider surprise leak into the page as a stack trace
            run["error"] = f"Непредвиденная ошибка ({type(exc).__name__})"
        finally:
            raw = getattr(pipeline, "last_raw", "")
            if run.get("edit") and raw and not run["error"]:
                try:
                    run["edit_result"] = self._propose(run, raw) if run["edit"].get("_office") else self._apply_edit(run, raw)
                except Exception as exc:       # never leave a half-made version: the text answer stays available
                    run["edit_result"] = {"applied": False, "note": f"Новую версию создать не удалось ({type(exc).__name__}). Текстовый ответ ниже."}
            try:
                if raw or not run["error"]:
                    data = self.load(run["chat"])
                    flag = {"mode": "orig"} if run.get("mode") == "orig" else {}
                    data["messages"] += [{"role": "user", "content": prepared.text, **flag}]
                    if raw:
                        data["messages"] += [{"role": "assistant", "content": raw, **flag}]   # label form (anonymized) or as written (original)
                    self.save(run["chat"], data)
            except (KeyError, OSError):
                pass
            with run["cond"]:
                run["done"] = True
                run["cond"].notify_all()

    def events(self, run_id: str):
        """Server-sent events for one reply: `delta` (already restored text, never a half label), then one `done`."""
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError("Ответ не найден")

        def generate():
            sent, started = 0, time.monotonic()
            while True:
                with run["cond"]:
                    run["cond"].wait_for(lambda: len(run["text"]) > sent or run["done"], timeout=SSE_KEEPALIVE)
                    text, done = run["text"], run["done"]
                if len(text) > sent:
                    yield "delta", {"text": text[sent:]}
                    sent = len(text)
                if done and len(text) == sent:
                    yield "done", {"length": sent, "error": run["error"], "report": run["report"], "usage": run["usage"],
                                  "edit": run.get("edit_result")}
                    return
                if time.monotonic() - started > SSE_MAX_SECONDS:
                    yield "done", {"length": sent, "error": "Ответ не пришёл вовремя.", "report": None, "usage": None}
                    return
                if not done and len(text) == sent:
                    yield "ping", {}
        return generate()

    def poll(self, run_id: str) -> dict:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError("Ответ не найден")
        return {"text": run["text"], "length": len(run["text"]), "done": run["done"], "error": run["error"],
                "report": run["report"], "usage": run["usage"], "edit": run.get("edit_result")}

    def stop(self, run_id: str) -> dict:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError("Ответ не найден")
        run["pipeline"].stop()
        return {"ok": True}

    def clear_all(self) -> None:
        for run in self.runs.values():
            run["pipeline"].stop()
        self.runs.clear()
        self.attachments.clear()


def handle(app, method: str, path: str, body) -> tuple:
    """Routes under /api/ai/chats and /api/ai/runs. Same error convention as `chat_api.handle`."""
    import re
    ai = app.ai_chats
    match = re.fullmatch(r"/api/ai/chats/([^/]+)(?:/(toggle|prepare|send|history|attach|export|choice|patch))?", path)
    if match:
        chat_id, action = match.groups()
        if action is None and method == "GET":
            return "json", ai.view(chat_id)
        if action == "toggle" and method == "POST":
            data = ai.load(chat_id)
            data["ai"] = bool(body().get("on"))
            ai.save(chat_id, data)
            return "json", {"ai": data["ai"]}
        if action == "choice" and method == "POST":
            return "json", ai.set_choice(chat_id, body())
        if action == "patch" and method == "POST":
            return "json", ai.decide(chat_id, body())
        if action == "prepare" and method == "POST":
            return "json", ai.prepare(chat_id, body())
        if action == "send" and method == "POST":
            return "json", ai.send(chat_id, body())
        if action == "attach" and method == "POST":
            return "json", ai.attach(chat_id, body())
        if action == "export" and method == "POST":
            return ai.export(chat_id, body())
        if action == "history" and method == "DELETE":
            data = ai.load(chat_id)
            data["messages"] = []
            ai.save(chat_id, data)
            return "json", {"ok": True}
    match = re.fullmatch(r"/api/ai/runs/([A-Za-z0-9_-]{1,40})(?:/(stop|events))?", path)
    if match:
        run_id, action = match.groups()
        if action is None and method == "GET":
            return "json", ai.poll(run_id)
        if action == "stop" and method == "POST":
            return "json", ai.stop(run_id)
        if action == "events" and method == "GET":
            return "stream", ai.events(run_id)
    raise KeyError("Не найдено")
