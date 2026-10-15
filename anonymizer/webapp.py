"""Локальный сервер страницы программы: 127.0.0.1, ключ сеанса, одна страница.

Программа не выходит в сеть. Сервер слушает только петлевой адрес, каждый запрос проверяется по
случайному токену сеанса и заголовку Host, поэтому ни браузер, ни другой компьютер в сети до него
не дотянутся. Страницу показывает окно программы (`desktop.py`).
"""

from __future__ import annotations

import http.server
import json
import os
import re
import queue
import mimetypes
import secrets
import shutil
import socket
import socketserver
import sys
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path

from . import __version__, ai_chat, chat_api, keystore, crypto, folders, settings_schema, table_io, updater
from . import ner
from .chats import ChatStore
from .service import (MAX_UPLOAD_BYTES, SUFFIX_ANON, SUFFIX_RESTORED, JobCancelled, PathUpload, Service, Upload, safe_name,
                      split_ext)
from .tokens import GROUP_LABELS, base_of
from .util import authored, client_message
from .vault import Vault

WEB_DIR = Path(__file__).parent / "web"
_VENDOR_MIME = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def open_with_system(path: Path) -> None:
    """Открывает файл программой по умолчанию. Путь выбирает программа, не страница."""
    import subprocess
    if sys.platform == "win32":
        os.startfile(str(path))                       # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_rerun_args(job, options, overrides) -> None:
    """Тело запроса приходит снаружи: неверные типы — это 400, а не падение сервера."""
    if job is not None and not isinstance(job, str):
        raise ValueError("Некорректный номер задания.")
    if not isinstance(options, dict) or not (overrides is None or isinstance(overrides, dict)):
        raise ValueError("Некорректные параметры повторного запуска.")
    if overrides and not all(isinstance(k, str) and isinstance(v, str) for k, v in overrides.items()):
        raise ValueError("Некорректные решения о словах.")


class App:
    """Состояние сервера: хранилище, сервис, загруженные файлы и запущенные задания."""

    def __init__(self, vault: Vault, workdir: Path, token: str):
        self.vault = vault
        self.service = Service(vault, workdir)
        self.token = token
        self.uploads: dict[str, tuple[Upload, dict, float]] = {}
        self.folders: dict[str, tuple[folders.FolderScan, float]] = {}
        self.runners: dict[str, threading.Thread] = {}
        self.stop = threading.Event()
        self.on_focus = None        # окно подставляет сюда функцию «вывести вперёд»
        self.addin_error = ""       # почему не запустился сервер add-in (порт занят и т.п.)
        self.keep_alive = False     # фоновая программа не завершается, когда закрыто последнее окно
        self.pinned_alive = False   # запущена как фоновая (автозапуск): остаётся всегда
        self.quit_event = threading.Event()
        self.updates = updater.UpdateState()
        self.windows: dict[str, float] = {}                 # окна-клиенты: когда каждое в последний раз отзывалось
        self.window_events: dict[str, "queue.Queue[dict]"] = {}
        self.spawn_window = None    # фоновая программа подставляет сюда запуск окна
        chats_root = vault.path.parent if vault.path else workdir.parent
        self.chats = ChatStore(chats_root / "chats", key=vault._key)
        self.chats.purge(int(vault.prefs.get("retention_days") or 0), int(vault.prefs.get("restored_retention_days") or 0))
        self.chats.import_history(vault)
        self.keystore = keystore.Keystore(chats_root / "ai", vault._key)       # AI provider settings; keys never in the vault or backups
        self.ai_chats = ai_chat.AiChats(self)
        self.open_dir = workdir / ".open"               # расшифрованные копии для «Открыть»: живут до выхода
        self.cleanup_open()
        self.opener = open_with_system
        self.job_chat: dict[str, tuple[str, list[str]]] = {}   # задание → (чат, номера записей): повтор заменяет их
        self.open_chat = ""                                    # чат, который просила открыть панель Office (окно забирает один раз)
        self.chat_hooks: list = []                             # вызываются при удалении чата: (чат, копия документа Office)
        self.recording: set[str] = set()                       # задания, чьи результаты ещё пишутся в чат

    # -- окна ------------------------------------------------------------------

    WINDOW_ALIVE_SECONDS = 60

    def register_window(self, window_id: str) -> None:
        self.windows[window_id] = time.time()
        self.window_events.setdefault(window_id, queue.Queue())

    def close_window(self, window_id: str) -> None:
        self.windows.pop(window_id, None)
        self.window_events.pop(window_id, None)

    def live_windows(self) -> list[str]:
        limit = time.time() - self.WINDOW_ALIVE_SECONDS
        return [w for w, seen in self.windows.items() if seen >= limit]

    def wait_window_event(self, window_id: str, timeout: float = 25.0) -> dict:
        """Окно висит на этом запросе и просыпается, только когда ему есть что сказать: пока тихо, процессор не тратится."""
        if window_id not in self.windows:
            self.register_window(window_id)
        self.windows[window_id] = time.time()
        try:
            event = self.window_events[window_id].get(timeout=timeout)
        except queue.Empty:
            event = {}
        if window_id in self.windows:
            self.windows[window_id] = time.time()
        return event

    def request_window(self, tab: str | None = None) -> None:
        """Показать окно программы: уже открытому окну уходит событие, иначе запускается новое."""
        live = self.live_windows()
        if live:
            for window_id in live:
                self.window_events[window_id].put({"focus": True, "tab": tab})
        elif self.spawn_window:
            self.spawn_window(tab)

    # -- загрузка -------------------------------------------------------------

    def add_upload(self, name: str, data: bytes) -> dict:
        from .util import opaque_id
        upload_id = opaque_id(6).lower()
        upload = Upload(safe_name(name), data)
        info = self.service.peek(upload)
        self.uploads[upload_id] = (upload, info, time.time())
        self._trim_uploads()
        return {"id": upload_id, **info}

    def add_upload_path(self, path: str) -> dict:
        """Файл, выбранный в системном диалоге: читается напрямую с диска, без передачи через страницу."""
        source = Path(path)
        if source.stat().st_size > MAX_UPLOAD_BYTES:
            raise ValueError("Файл слишком большой (больше 300 МБ). Выберите файл поменьше.")
        return self.add_upload(source.name, source.read_bytes())

    def add_folder(self, path: str, kind: str) -> dict:
        """Папка, выбранная в системном диалоге: обходится сразу, читаются только размеры."""
        from .util import opaque_id
        root = Path(path)
        if not root.is_dir():
            raise ValueError("Папка недоступна. Выберите её заново.")
        scan = folders.scan_folder(root, kind)
        folder_id = opaque_id(6).lower()
        self.folders[folder_id] = (scan, time.time())
        return {"id": folder_id, **scan.public()}

    def _trim_uploads(self) -> None:
        limit = time.time() - 3 * 3600
        for key in [k for k, (_, _, created) in self.uploads.items() if created < limit]:
            self.uploads.pop(key, None)

    def take_uploads(self, ids: list[str]) -> list[Upload]:
        missing = [i for i in ids if i not in self.uploads]
        if missing:
            raise KeyError("Файл больше не доступен на сервере. Выберите его заново.")
        return [self.uploads[i][0] for i in ids]

    # -- задания --------------------------------------------------------------

    def start_job(self, kind: str, ids: list[str], options: dict, overrides: dict | None = None,
                  rerun_of: str | None = None, chat_id: str | None = None, replace: list[str] | None = None,
                  match_chat: bool = False, skipped: list[str] | None = None, uploads_in: list | None = None,
                  project: dict | None = None) -> str:
        """`uploads_in` — готовые файлы (проект из папки: имя = относительный путь); `project` — описание папки-проекта.
        `skipped` — записи чата, которые пересборка не смогла обновить (нет исходника): они остаются устаревшими.
        `chat_id` — чат, в который записать результат; без него результат попадает в новый чат.
        `replace` — записи чата, которые заменяются новыми версиями (по порядку файлов): так «Применить правки» не плодит дубли.
        `match_chat` — возврат без `chat_id` ищет чат по меткам файла (панель Office): единственный подходящий, иначе новый."""
        check_rerun_args(rerun_of, options, overrides)
        if chat_id and self.chats.get(chat_id) is None:
            raise KeyError("Чата нет")
        previous = self.job_chat.get(rerun_of) if rerun_of else None
        if previous and not chat_id:
            chat_id, replace = previous[0], previous[1]
        if chat_id and kind == "anonymize":
            # Повтор берёт настройки чата заново (их могли изменить после первого прохода); явные значения запуска сильнее.
            options = self.with_chat_settings(chat_id, options)
        if kind == "restore" and not chat_id:
            match_chat = True          # из чистого черновика возврат попадает в чат, где файл обезличивали (если он один такой)
        if rerun_of:
            job = self.service.new_job("anonymize", options)
            uploads: list[Upload] = []
        else:
            uploads = uploads_in if uploads_in is not None else self.take_uploads(ids)
            job = self.service.new_job(kind, options)
        job.project = project

        old = self.service.jobs.get(rerun_of) if rerun_of else None
        old_folder = getattr(old, "folder", None)
        self.recording.add(job.id)

        def work() -> None:
            try:
                if rerun_of:
                    self.service.rerun(rerun_of, options, overrides or {}, job=job)
                    if chat_id and job.state == "done":
                        self.remember_in_chat(chat_id, job.options.get("remembered"))
                    if old_folder is not None:
                        folders.remove_previous(old_folder)
                        job.folder = old_folder
                        folders.finish_folder(self.service, job, old_folder)
                elif kind == "anonymize":
                    self.service.anonymize(uploads, options, overrides, job=job)
                else:
                    self.service.restore(uploads, job=job)
                if old_folder is None:
                    self._record_job(job, uploads or old.inputs, chat_id, replace, match_chat, skipped)
            except JobCancelled:
                job.state = "failed"
                job.error = "Остановлено. В чат ничего не добавлено."
            except Exception as exc:  # задание не должно уронить сервер
                job.state = "failed"
                job.error = client_message(exc) if authored(exc) else \
                    f"Не удалось выполнить операцию ({type(exc).__name__}). Файл не изменён."
            finally:
                self.recording.discard(job.id)
        return self._run(job, work)

    # -- чаты -----------------------------------------------------------------

    def _record_job(self, job, inputs: list[Upload], chat_id: str | None, replace: list[str] | None,
                    match_chat: bool = False, skipped: list[str] | None = None) -> None:
        """Результат задания → файлы и шаг чата. Ошибка записи не должна портить сам результат."""
        if job.state != "done":
            return
        try:
            if match_chat and not chat_id and job.kind == "restore":
                chat_id = self.match_chat_by_tokens({t for o in job.files for t in o.tokens})
            chat_id = self._write_chat(job, inputs, chat_id, replace or [], skipped)
            job.chat = chat_id
        except Exception:
            job.chat = ""
            job.warning = ("Результат не удалось записать в чат (проверьте свободное место на диске). Файлы готовы: "
                           "скачайте их сейчас, потом они будут недоступны.")

    def _write_chat(self, job, inputs: list[Upload], chat_id: str | None, replace: list[str],
                    skipped: list[str] | None = None) -> str:
        store = self.chats
        outcomes = job.files
        project = getattr(job, "project", None)
        if not chat_id or store.get(chat_id) is None:
            chat_id = store.create(self._chat_title(job, inputs), keep_originals=self.keep_originals_default())["id"]
            if job.kind == "anonymize":      # параметры, отличающиеся от общих, остаются за этим чатом
                prefs = self.vault.prefs
                store.set_settings(chat_id, {k: job.options[k] for k in settings_schema.CHAT_BOOLS
                                             if job.options.get(k) is not None and bool(job.options[k]) != bool(prefs.get(k))})
                self.remember_in_chat(chat_id, job.options.get("remembered"))
        if project and job.kind == "anonymize" and not (store.get(chat_id) or {}).get("project"):
            store.mark_project(chat_id, project["root"])
        chat = store.get(chat_id)
        if not chat.get("title"):
            store.rename(chat_id, self._chat_title(job, inputs))
        keep = chat["keep_originals"]
        ids: list[str] = []
        failed: list[str] = []
        for index, outcome in enumerate(outcomes):
            upload = inputs[index] if index < len(inputs) else None
            out = Path(outcome.out_path).read_bytes() if outcome.out_path and outcome.status != "error" else None
            if job.kind == "anonymize":
                names = {"anon": outcome.out_name} if out is not None else {}
                blobs = {"anon": out, "orig": upload.data if (keep and upload is not None and out is not None) else None}
                name = upload.name if upload else outcome.name
            else:
                names = {"restored": outcome.out_name} if out is not None else {}
                blobs = {"restored": out}
                name = upload.name if project and upload is not None else outcome.name
                if out is not None and upload is not None:
                    # Что вернул ИИ и какие значения подставлены: по ним видно, что возврат устарел, и его можно повторить.
                    blobs["ret"] = upload.data
                    names["ret"] = safe_name(upload.name)
            fields = {"status": outcome.status, "tokens": outcome.tokens, "counts": outcome.counts,
                      "names": names}
            if job.kind == "restore" and out is not None:
                fields["rsig"] = table_io.signature(self.vault, outcome.tokens)
                fields["rtokens"] = list(outcome.tokens)
            target = None
            if job.kind == "anonymize" and index < len(replace):
                target = next((r for r in chat["files"] if r["id"] == replace[index]), None)
            if job.kind == "restore" and index < len(replace):
                target = next((r for r in chat["files"] if r["id"] == replace[index]), None)
            elif job.kind == "restore" and upload is not None and (project or chat.get("project")):
                target = folders.match_project_record(self.vault, chat, upload.name, outcome.tokens)
            elif job.kind == "restore" and upload is not None:
                target = next((r for r in chat["files"] if r.get("names", {}).get("anon") == safe_name(upload.name)
                               and "restored" not in r["roles"]), None)
                if target is None and outcome.tokens:
                    # Файл вернулся под другим именем: подходит запись, где есть все его метки, но только если она одна.
                    wanted = set(outcome.tokens)
                    found = [r for r in chat["files"] if "restored" not in r["roles"] and r["roles"].get("anon")
                             and wanted <= set(r["tokens"])]
                    target = found[0] if len(found) == 1 else None
            if job.kind == "anonymize" and target is not None:
                if out is None:
                    failed.append(target["id"])          # новой версии нет: файл остаётся с прежней, устаревшей
                else:
                    fields["stale"] = False
                    if target["roles"].get("anon"):
                        # Прежняя версия не пропадает: к ней можно вернуться (одна последняя).
                        previous = store.read_blob(chat_id, target["id"], "anon")
                        if previous is not None:
                            store.save_blob(chat_id, target["id"], "prev", previous)
                            fields["names"] = {**names, "prev": target.get("names", {}).get("anon") or target["name"]}
            if target is not None:
                if job.kind == "restore":
                    fields["tokens"] = sorted(set(target["tokens"]) | set(outcome.tokens))
                    fields.pop("counts")
                record = store.update_file(chat_id, target["id"], **fields)
            else:
                record = store.add_file(chat_id, name, outcome.format, status=outcome.status, tokens=outcome.tokens,
                                        counts=outcome.counts, names=names)
                if job.kind == "restore" and upload is not None:
                    record = store.update_file(chat_id, record["id"], names={"anon": safe_name(upload.name)})
            for role, data in blobs.items():
                if data is not None:
                    store.save_blob(chat_id, record["id"], role, data)
            ids.append(record["id"])
        totals: dict[str, int] = {}
        for outcome in outcomes:
            for group, count in outcome.counts.items():
                totals[group] = totals.get(group, 0) + count
        worst = "error" if any(o.status == "error" for o in outcomes) else \
            "attention" if any(o.status == "attention" for o in outcomes) else "ok"
        extra: dict = {}
        if job.kind == "anonymize":
            options = {k: job.options[k] for k in settings_schema.CHAT_BOOLS
                       if job.options.get(k) is not None}
            if options:
                extra["options"] = options
            if project:
                extra["project"] = {k: project[k] for k in ("root", "unsupported", "unsupported_total", "note")}
            stale_ids = [*(skipped or []), *failed]
            if skipped is not None:
                for record_id in stale_ids:
                    store.update_file(chat_id, record_id, stale=True)
                names_by_id = {r["id"]: r["name"] for r in store.get(chat_id)["files"]}
                job.result["not_updated"] = [names_by_id.get(i, "") for i in stale_ids]
                if stale_ids:
                    extra["skipped"] = stale_ids
        store.add_step(chat_id, job.kind, files=ids, counts=totals, status=worst,
                       errors=sum(1 for o in outcomes if o.status == "error"), **extra)
        if job.kind == "anonymize":
            self.job_chat[job.id] = (chat_id, ids)
        return chat_id

    def chat_deleted(self, chat_id: str, backup: str | None = None) -> None:
        """Чат стёрт: вместе с ним уходят рабочие копии его заданий (результаты с настоящими данными) и копия документа Office."""
        self.job_chat = {job: value for job, value in self.job_chat.items() if value[0] != chat_id}
        for job_id, job in list(self.service.jobs.items()):
            if (chat_id == "*" or job.chat == chat_id) and job.state != "running":
                self.service.forget_job(job_id)
        for hook in list(self.chat_hooks):
            try:
                hook(chat_id, backup)
            except Exception:
                pass

    def match_chat_by_tokens(self, tokens) -> str | None:
        """Чат, в файлах которого больше всего меток из `tokens`; None, если такого нет или их несколько."""
        bases = {b for b in (base_of(t) for t in tokens) if b}
        return self.chats.match_one(bases, self.vault) if bases else None

    def chat_summary(self, chat_id: str) -> dict | None:
        """Состояние чата для панели Office: название, число замен, последний шаг, правки, не применённые к файлам."""
        chat = self.chats.get(chat_id)
        if chat is None:
            return None
        kinds = [s for s in chat["steps"] if s["kind"] in ("anonymize", "restore")]
        last = kinds[-1]["kind"] if kinds else None
        total, pending = 0, 0
        for step in chat["steps"]:
            if step["kind"] == "anonymize":
                total = sum((step.get("counts") or {}).values())
                pending = pending if step.get("skipped") else 0      # часть файлов не пересобрана: правки к ним в силе
            elif step["kind"] == "edit" and (step.get("action") in ("keep", "hide", "merge", "split")
                                             or step.get("action") == "import" and step.get("ai_changed")):
                pending += 1
        return {"id": chat["id"], "title": chat["title"], "files": len(chat["files"]), "replaced_total": total,
                "last_step_kind": last, "state": {"anonymize": "anonymized", "restore": "restored"}.get(last, "none"),
                "pending_edits": pending, "stale_files": sum(1 for r in chat["files"] if r.get("stale")), "bound_doc": chat.get("bound_doc"), "has_backup": False}

    def take_open_chat(self) -> str:
        """Чат, который просила открыть панель Office; отдаётся окну один раз."""
        chat, self.open_chat = self.open_chat, ""
        return chat

    def with_chat_settings(self, chat_id: str, options: dict) -> dict:
        """Порядок: явное значение запуска > настройка чата > общая настройка (её подставит `settings_for`).
        Свои слова чата добавляются к общим спискам, а не заменяют их."""
        chat = self.chats.get(chat_id)
        mine = dict((chat or {}).get("settings") or {})
        merged = dict(options)
        for name in settings_schema.CHAT_BOOLS:
            if merged.get(name) is None and name in mine:
                merged[name] = mine[name]
        for name in ("hide_terms", "keep_terms"):
            merged[name] = list(dict.fromkeys([*(mine.get(name) or []), *merged.get(name, [])]))
        # Слова чата сильнее общих списков, но только в этом чате (общие настройки не трогаются).
        merged["term_decisions"] = {name: list(mine.get(name) or []) for name in ("hide_terms", "keep_terms")}
        return merged

    def remember_in_chat(self, chat_id: str, remembered: dict | None) -> None:
        """Решения о словах с экрана результата запоминаются за чатом, а не в общих настройках."""
        for bucket, name in (("hide", "hide_terms"), ("keep", "keep_terms")):
            for word in (remembered or {}).get(bucket, []):
                try:
                    self.chats.add_term(chat_id, name, word)
                except (ValueError, KeyError):
                    pass

    PAGE_PREFS = ("sidebar_collapsed", "sidebar_width", "pane_width", "preview_width", "preview_open", "addin_hint_dismissed")

    def save_prefs(self, body: dict) -> dict:
        """Общие настройки: проверка по схеме, затем запись. Возвращает пояснения к автоматическим поправкам."""
        patch = settings_schema.validate_patch({k: v for k, v in body.items() if k not in self.PAGE_PREFS})
        notes: list[str] = []
        if "hide_terms" in patch or "keep_terms" in patch:
            hide = patch.get("hide_terms", self.vault.prefs.get("hide_terms", []))
            keep = patch.get("keep_terms", self.vault.prefs.get("keep_terms", []))
            hide, keep, dropped = settings_schema.reconcile_lists(hide, keep)
            patch["hide_terms"], patch["keep_terms"] = hide, keep
            if dropped:
                notes.append("Из списка «Никогда не скрывать» убраны слова, которые есть в «Всегда скрывать»: " + ", ".join(dropped))
        for name, (lo, hi) in {"sidebar_width": (200, 420), "pane_width": (320, 640), "preview_width": (340, 640)}.items():
            if name in body:   # ширина колонки: целое в допустимых пределах или None (по умолчанию)
                value = body[name]
                patch[name] = value if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi else None
        if "sidebar_collapsed" in body:
            patch["sidebar_collapsed"] = body["sidebar_collapsed"]
        if "preview_open" in body:
            patch["preview_open"] = body["preview_open"] is True
        if "addin_hint_dismissed" in body:
            patch["addin_hint_dismissed"] = body["addin_hint_dismissed"] is True
        changed = self.vault.set_prefs(**patch)
        return {"notes": notes, "changed": changed}

    def apply_preset(self, name: str) -> None:
        preset = settings_schema.PRESETS.get(name) or (self.vault.prefs.get("presets") or {}).get(name)
        if preset is None:
            raise ValueError("Такого набора настроек нет.")
        self.vault.set_prefs(**settings_schema.validate_patch(preset.get("values", preset)))

    def save_preset(self, name: str) -> None:
        name = (name or "").strip()
        if not name or name in settings_schema.PRESETS:
            raise ValueError("Название набора пустое или занято встроенным набором.")
        prefs = self.vault.prefs
        values = {o.key: prefs.get(o.key, o.default) for o in settings_schema.OPTIONS if o.scope == "chat" or o.key in ("keep_originals", "retention_days", "restored_retention_days")}
        self.vault.set_prefs(presets={**(prefs.get("presets") or {}), name: values})

    def delete_preset(self, name: str) -> None:
        self.vault.set_prefs(presets={k: v for k, v in (self.vault.prefs.get("presets") or {}).items() if k != name})

    def keep_originals_default(self) -> bool:
        return bool(self.vault.prefs.get("keep_originals", True))

    def _chat_title(self, job, inputs: list[Upload]) -> str:
        """Название по умолчанию: исходное имя первого файла. Чаты лежат только здесь и зашифрованы, а «Файл3»
        в списке чатов ничего не говорит. При возврате исходное имя — у возвращённого файла."""
        if getattr(job, "project", None) and job.kind == "anonymize":
            return job.project["root"][:200]
        names = [u.name for u in inputs] if job.kind == "anonymize" else [o.out_name for o in job.files if o.status != "error"]
        for name in names:
            stem = split_ext(name or "")[0].replace(SUFFIX_ANON, "").replace(SUFFIX_RESTORED, "").strip()
            if stem:
                return stem
        return "Чат"

    def apply_chat(self, chat_id: str, options: dict) -> str:
        """Пересобирает обезличенные версии по сохранённым исходникам. Без исходников честно отказывает."""
        chat = self.chats.get(chat_id)
        if chat is None:
            raise KeyError("Чата нет")
        if not chat["keep_originals"]:
            raise ValueError("Исходники в этом чате не хранятся. Включите «Хранить оригиналы» и добавьте файлы в чат заново.")
        ids, replace, skipped = [], [], []
        for record in chat["files"]:
            data = self.chats.read_blob(chat_id, record["id"], "orig")
            if data is not None:
                ids.append(self.add_upload(record["name"], data)["id"])
                replace.append(record["id"])
            elif record.get("roles", {}).get("anon"):
                skipped.append(record["id"])
        if not ids:
            raise ValueError("В чате нет сохранённых исходников. Добавьте файлы в чат заново.")
        # Параметры, с которыми чат обезличивали, а не нынешние настройки главного экрана.
        last = next((s for s in reversed(chat["steps"]) if s["kind"] == "anonymize" and s.get("options")), None)
        if last:
            options = {**options, **last["options"]}
        return self.start_job("anonymize", ids, options, chat_id=chat_id, replace=replace, skipped=skipped)

    def rerestore(self, chat_id: str) -> str:
        """Возвращает заново файлы, чьи значения изменились после возврата: по сохранённым файлам, которые вернул ИИ."""
        if self.chats.get(chat_id) is None:
            raise KeyError("Чата нет")
        stale = table_io.stale_restored(self, chat_id)
        if not stale:
            raise ValueError("Возвращать заново нечего: значения не менялись.")
        ids, replace = [], []
        for record in stale:
            data = self.chats.read_blob(chat_id, record["id"], "ret")
            if data is not None:
                ids.append(self.add_upload(record.get("names", {}).get("ret") or record["name"], data)["id"])
                replace.append(record["id"])
        if not ids:
            raise ValueError(table_io.NO_RETURNED)
        return self.start_job("restore", ids, {}, chat_id=chat_id, replace=replace)

    def table_file(self, chat_id: str, fmt: str) -> Path:
        """Таблица замен чата во временной папке (стирается при выходе): чтобы сохранить её или открыть."""
        data, name = table_io.export_file(self, chat_id, fmt)
        from .util import opaque_id
        target = self.open_dir / f"table-{opaque_id(5).lower()}" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def import_table(self, chat_id: str, name: str, data: bytes, apply: bool = False, token: str | None = None) -> dict:
        return table_io.import_table(self, chat_id, name, data, apply, token)

    def clear_vault(self) -> None:
        """Очистка хранилища делает метки чатов недействительными: чаты уходят вместе с ним."""
        self.vault.clear()
        self.ai_chats.clear_all()
        self.keystore.clear()
        self.chats.wipe()
        self.job_chat.clear()
        self.chat_deleted("*", None)             # копии документов Office и рабочие папки заданий уходят вместе с хранилищем

    def materialize(self, chat_id: str, file_id: str, role: str) -> Path:
        """Расшифрованная копия версии файла во временной папке: чтобы открыть её системной программой."""
        chat = self.chats.get(chat_id)
        if chat is None:
            raise KeyError("Чата нет")
        record = next((r for r in chat["files"] if r["id"] == file_id), None)
        if record is None:
            raise KeyError("Файла нет в чате")
        data = self.chats.read_blob(chat_id, file_id, role)
        if data is None:
            raise KeyError("Этой версии файла нет")
        name = safe_name(record.get("names", {}).get(role) or record["name"])
        target = self.open_dir / file_id / role / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def cleanup_open(self) -> None:
        """Расшифрованные копии не должны пережить программу: затираются и удаляются при выходе и при запуске."""
        if self.open_dir.exists():
            for path in self.open_dir.rglob("*"):
                if path.is_file():
                    self.chats._shred(path)
            shutil.rmtree(self.open_dir, ignore_errors=True)

    MAINTENANCE_SECONDS = 120

    def maintenance(self) -> None:
        """Один проход уборки: открытые копии результатов недолго живут в рабочей папке (`Service.cleanup`)."""
        try:
            self.service.cleanup()
        except Exception:
            pass

    def start_maintenance(self) -> threading.Thread:
        """Уборка по таймеру: фоновая программа работает днями, одной уборки при запуске мало."""
        def loop() -> None:
            while not self.stop.wait(self.MAINTENANCE_SECONDS):
                self.maintenance()
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread

    def _run(self, job, work) -> str:
        thread = threading.Thread(target=work, daemon=True)
        self.runners[job.id] = thread
        thread.start()
        return job.id

    def start_project_job(self, kind: str, folder_id: str, options: dict, chat_id: str | None = None) -> str:
        """Папка целиком как проект чата: те же файлы идут одним заданием общего обучения, в чат — с относительными путями.
        `restore` — папка, которую вернул ИИ: файлы подбираются к записям проекта по пути."""
        entry = self.folders.get(folder_id)
        if entry is None:
            raise KeyError("Папка больше не доступна на сервере. Выберите её заново.")
        scan = entry[0]
        problem = folders.project_problem(scan)
        if problem:
            raise ValueError(problem)
        if kind == "restore" and not chat_id:
            raise ValueError("Откройте чат проекта и добавьте папку с ответом ИИ в него.")
        uploads = [PathUpload(unicodedata.normalize("NFC", rel.as_posix()), path) for rel, path in scan.files]
        project = {"root": unicodedata.normalize("NFC", scan.root.name), "unsupported": scan.skipped[:100],
                   "unsupported_total": len(scan.skipped), "note": scan.limit_hit}
        return self.start_job(kind, [], options if kind == "anonymize" else {}, chat_id=chat_id or None,
                              uploads_in=uploads, project=project)

    def cancel_job(self, job_id: str) -> None:
        job = self.service.jobs.get(job_id)
        if job is not None and job.state == "running":
            job.cancel = True

    def project_dir(self, chat_id: str, role: str) -> Path:
        """Файлы проекта в его структуре во временной папке (стирается при выходе): сохраняет их уже окно."""
        from .util import opaque_id
        target = self.open_dir / f"project-{opaque_id(5).lower()}"
        target.mkdir(parents=True, exist_ok=True)
        return Path(folders.write_project(self, chat_id, role if role == "restored" else "anon", target)["out"])

    def start_folder_job(self, kind: str, folder_id: str, options: dict) -> str:
        entry = self.folders.get(folder_id)
        if entry is None:
            raise KeyError("Папка больше не доступна на сервере. Выберите её заново.")
        context = folders.FolderContext(entry[0], kind)
        job = self.service.new_job(kind, options)

        def work() -> None:
            try:
                folders.run_folder(self.service, context, options, job)
            except Exception as exc:
                job.state = "failed"
                job.error = client_message(exc) if authored(exc) else \
                    f"Не удалось обработать папку ({type(exc).__name__}). Исходные файлы не изменены."
        return self._run(job, work)

    def service_busy(self) -> bool:
        return any(thread.is_alive() for thread in self.runners.values())

    def job_public(self, job_id: str) -> dict | None:
        job = self.service.jobs.get(job_id)
        if job is None:
            return None
        # Пока результат пишется в чат, задание для страницы ещё идёт: иначе она увидит «готово» раньше, чем чат заполнен.
        state = "running" if job.state == "done" and job.id in self.recording else job.state
        return {"id": job.id, "kind": job.kind, "state": state, "percent": job.percent, "stage": job.stage,
                "files": [f.public() for f in job.files], "result": job.result if job.state == "done" else {},
                "error": job.error, "chat": job.chat, "warning": job.warning, "processed": job.processed, "total": job.total}

    # -- состояние ------------------------------------------------------------

    def addin_hint(self) -> bool:
        """Тихая подсказка про надстройку: только Windows/macOS, пока она не подключена и подсказку не закрыли."""
        if sys.platform not in ("win32", "darwin") or self.vault.prefs.get("addin_hint_dismissed"):
            return False
        from . import addin_install
        try:
            return not addin_install.is_installed()
        except Exception:
            return False

    def state(self) -> dict:
        prefs = self.vault.prefs
        history = [{"time": h["time"], "kind": h["kind"], "files": h.get("files", [])[:3], "counts": h.get("counts", {})}
                   for h in reversed(self.vault.history[-8:])]
        return {"version": __version__, "notice": self.vault.notice, "prefs": prefs, "addin_hint": self.addin_hint(),
                "image_mode_unsafe": prefs.get("image_mode") == "redact_text", "schema": settings_schema.public_schema(), "stats": self.vault.stats(), "history": history,
                "groups": GROUP_LABELS, "platform": sys.platform, "ner_available": ner.installed()}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Anonymizer"
    protocol_version = "HTTP/1.1"

    app: App
    port: int
    _cached_body: bytes | None = None

    # -- служебное ------------------------------------------------------------

    def log_message(self, *args) -> None:  # никаких журналов с именами файлов
        return

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _origin_ok(self) -> bool:
        """Запрос с чужого сайта несёт чужой Origin. Окно и фоновая программа Origin не шлют или шлют свой."""
        origin = self.headers.get("Origin")
        return not origin or origin in {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def _cookie_token(self) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "anon_t":
                return value
        return ""

    def _authorized(self) -> bool:
        return self._host_ok() and secrets.compare_digest(self._cookie_token(), self.app.token)

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8",
              headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict | list, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> bytes:
        # Тело читается один раз и целиком. Не прочитанное тело остаётся в соединении и портит следующий запрос
        # (страница держит соединение открытым): «Очистить хранилище» ломало всё, что нажималось после него.
        if self._cached_body is not None:
            return self._cached_body
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            raise ValueError("Некорректная длина запроса.")
        if length > MAX_UPLOAD_BYTES + 1024 * 1024:
            self.close_connection = True
            raise ValueError("Файл слишком большой (больше 300 МБ).")
        self._cached_body = self.rfile.read(length) if length else b""
        return self._cached_body

    def _json_body(self) -> dict:
        raw = self._body()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            raise ValueError("Некорректное тело запроса.") from None
        if not isinstance(data, dict):
            raise ValueError("Некорректное тело запроса.")
        return data

    # -- маршруты -------------------------------------------------------------

    def _chat_app(self) -> App:
        return self.app

    def _chat_call(self, method: str, path: str) -> None:
        """Маршруты чатов: общие для окна и add-in (`chat_api`). Авторизация проверена до вызова."""
        try:
            result = chat_api.handle(self._chat_app(), method, path, self._json_body)
        except KeyError as exc:
            return self._error(404, client_message(exc, "Не найдено") if authored(exc) else "Не найдено")
        except (ValueError, crypto.KeyErrorSafe) as exc:
            return self._error(400, client_message(exc, "Некорректный запрос."))
        except Exception as exc:
            return self._error(500, f"Внутренняя ошибка ({type(exc).__name__}).")
        if result[0] == "file":
            _, data, name = result
            return self._send(200, data, mimetypes.guess_type(name)[0] or "application/octet-stream", {
                "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}"})
        self._json(result[1])

    def _ai_call(self, method: str, path: str) -> None:
        """AI settings and AI chat routes (W12). Same token/Host/Origin checks as the chat routes; never on the Office add-in."""
        try:
            result = chat_api.ai_handle(self.app, method, path, self._json_body)
        except KeyError as exc:
            return self._error(404, client_message(exc, "Не найдено") if authored(exc) else "Не найдено")
        except (ValueError, crypto.KeyErrorSafe) as exc:
            return self._error(400, client_message(exc, "Некорректный запрос."))
        except Exception as exc:
            return self._error(500, f"Внутренняя ошибка ({type(exc).__name__}).")
        if result[0] == "file":
            _, data, name = result
            return self._send(200, data, "text/plain; charset=utf-8", {
                "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}"})
        if result[0] == "stream":
            return self._sse(result[1])
        self._json(result[1])

    def _sse(self, events) -> None:
        """Server-sent events for an AI reply. Closes when the reply is done, the client leaves or a write stalls."""
        self.close_connection = True
        self.send_response(200)
        for key, value in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"),
                           ("X-Content-Type-Options", "nosniff"), ("Connection", "close"),
                           ("Content-Security-Policy", "default-src 'self'; connect-src 'self'; frame-ancestors 'none'")):
            self.send_header(key, value)
        self.end_headers()
        try:
            self.connection.settimeout(30)
            for name, data in events:
                if name == "ping":
                    self.wfile.write(b": ping\n\n")
                else:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except OSError:
            pass                      # client left or stalled; the run itself continues and can be stopped or polled

    def _delete_authorized(self) -> bool:
        return self._authorized() and self.headers.get("X-Requested-With") == "anonymizer"

    def do_DELETE(self) -> None:
        self._cached_body = None
        if not self._host_ok() or not self._delete_authorized():
            self.close_connection = True
            return self._error(403, "Нет доступа")
        path = urllib.parse.urlparse(self.path).path
        try:
            self._body()
        except ValueError as exc:
            return self._error(400, client_message(exc, "Некорректный запрос."))
        if chat_api.is_ai_path(path):
            return self._ai_call("DELETE", path)
        if chat_api.is_chat_path(path):
            return self._chat_call("DELETE", path)
        return self._error(404, "Не найдено")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self._host_ok():
            return self._error(403, "Недопустимый адрес")
        if path == "/":
            query = urllib.parse.parse_qs(parsed.query)
            supplied = (query.get("t") or [""])[0]
            if supplied and secrets.compare_digest(supplied, self.app.token):
                return self._send(302, b"", "text/plain", {
                    "Location": "/", "Set-Cookie": f"anon_t={self.app.token}; Path=/; HttpOnly; SameSite=Strict"})
            if not self._authorized():
                return self._send(403, "Откройте программу заново: адрес с ключом сеанса устарел.".encode("utf-8"),
                                  "text/plain; charset=utf-8")
            return self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if not self._authorized():
            return self._error(403, "Нет доступа")
        if path == "/ai":
            return self._send(200, (WEB_DIR / "ai.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/ai-chat.js":
            return self._send(200, (WEB_DIR / "ai-chat.js").read_bytes(), "text/javascript; charset=utf-8")
        if path.startswith("/vendor/"):
            name = path[len("/vendor/"):]
            mime = _VENDOR_MIME.get(Path(name).suffix.lower())
            target = WEB_DIR / "vendor" / name
            if not mime or not re.fullmatch(r"[A-Za-z0-9._-]+", name) or not target.is_file():
                return self._error(404, "Нет такого файла")
            return self._send(200, target.read_bytes(), mime)
        if path == "/api/ping":
            return self._json({"ok": True, "pid": os.getpid(), "version": __version__, "keep_alive": self.app.keep_alive,
                                    "windows": len(self.app.live_windows())})
        if path == "/api/window/wait":
            window_id = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
            return self._json(self.app.wait_window_event(window_id) if window_id else {})
        if path == "/api/state":
            return self._json({**self.app.state(), "open_chat": self.app.take_open_chat()})
        if path == "/api/update/status":
            return self._json(self.app.updates.public())
        if path == "/api/addin/status":
            from . import addin_install
            return self._json({**addin_install.status(), "server_error": self.app.addin_error})
        if chat_api.is_ai_path(path):
            return self._ai_call("GET", path)
        if chat_api.is_chat_path(path):
            return self._chat_call("GET", path)
        if path.startswith("/api/jobs/"):
            job = self.app.job_public(path.rsplit("/", 1)[-1])
            return self._json(job) if job else self._error(404, "Задание не найдено")
        if path.startswith("/api/download/"):
            return self._download(path)
        return self._error(404, "Не найдено")

    def _download(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 4:
            return self._error(404, "Не найдено")
        _, _, job_id, which = parts
        service = self.app.service
        if which == "all":
            archive = service.zip_outputs(job_id)
            if archive is None:
                return self._error(404, "Файлы не найдены")
            name = archive.name
            try:
                data = archive.read_bytes()
            except OSError:
                return self._error(404, "Файлы не найдены")
            service.note_delivered(job_id)
            mime = "application/zip"
        else:
            found = service.output_path(job_id, int(which)) if which.isdigit() else None
            if found is None:
                return self._error(404, "Файл не найден")
            file_path, name = found
            try:
                data = file_path.read_bytes()
            except OSError:
                return self._error(404, "Файл не найден")
            service.note_delivered(job_id, int(which))
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        quoted = urllib.parse.quote(name)
        self._send(200, data, mime, {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"})

    def do_POST(self) -> None:
        self._cached_body = None
        if not self._host_ok() or not self._authorized():
            self.close_connection = True          # тело не читаем: чужому запросу соединение не оставляем
            return self._error(403, "Нет доступа")
        path = urllib.parse.urlparse(self.path).path
        try:
            self._body()
        except ValueError as exc:
            return self._error(400, client_message(exc, "Некорректный запрос."))
        if self.headers.get("X-Requested-With") != "anonymizer" or not self._origin_ok():
            return self._error(403, "Нет доступа")
        if chat_api.is_ai_path(path):
            return self._ai_call("POST", path)
        if chat_api.is_chat_path(path):
            return self._chat_call("POST", path)
        try:
            if path == "/api/upload":
                name = urllib.parse.unquote(self.headers.get("X-Filename") or "file")
                data = self._body()
                if not data:
                    return self._error(400, "Файл пустой.")
                return self._json(self.app.add_upload(name, data))
            if path == "/api/anonymize":
                body = self._json_body()
                job_id = self.app.start_job("anonymize", body.get("files", []), body.get("options", {}),
                                            chat_id=body.get("chat_id") or None)
                return self._json({"job": job_id})
            if path == "/api/restore":
                body = self._json_body()
                job_id = self.app.start_job("restore", body.get("files", []), {}, chat_id=body.get("chat_id") or None)
                return self._json({"job": job_id})
            if path == "/api/folder/project":
                body = self._json_body()
                kind = "restore" if body.get("kind") == "restore" else "anonymize"
                return self._json({"job": self.app.start_project_job(kind, body.get("folder", ""), body.get("options", {}),
                                                                      body.get("chat_id") or None)})
            if path == "/api/cancel":
                self.app.cancel_job(str(self._json_body().get("job", "")))
                return self._json({"ok": True})
            if path == "/api/folder/anonymize":
                body = self._json_body()
                return self._json({"job": self.app.start_folder_job("anonymize", body.get("folder", ""), body.get("options", {}))})
            if path == "/api/folder/restore":
                body = self._json_body()
                return self._json({"job": self.app.start_folder_job("restore", body.get("folder", ""), {})})
            if path == "/api/rerun":
                body = self._json_body()
                job_id = self.app.start_job("anonymize", [], body.get("options", {}), body.get("overrides", {}),
                                            rerun_of=body.get("job"))
                return self._json({"job": job_id})
            if path == "/api/prefs":
                body = self._json_body()
                try:
                    result = self.app.save_prefs(body)
                except ValueError as exc:
                    return self._error(400, client_message(exc, "Некорректный запрос."))
                return self._json({**self.app.state(), **result})
            if path == "/api/prefs/preset":
                body = self._json_body()
                try:
                    if body.get("apply"):
                        self.app.apply_preset(str(body["apply"]))
                    elif body.get("save"):
                        self.app.save_preset(str(body["save"]))
                    elif body.get("delete"):
                        self.app.delete_preset(str(body["delete"]))
                except ValueError as exc:
                    return self._error(400, client_message(exc, "Некорректный запрос."))
                return self._json(self.app.state())
            if path == "/api/vault/clear":
                self.app.clear_vault()
                return self._json(self.app.state())
            if path == "/api/backup/export":
                password = self._json_body().get("password", "")
                if len(password) < 6:
                    return self._error(400, "Пароль должен быть не короче 6 знаков.")
                blob = self.app.vault.export_backup(password)
                return self._send(200, blob, "application/octet-stream", {
                    "Content-Disposition": "attachment; filename*=UTF-8''anonymizer-backup.anonkeys"})
            if path == "/api/backup/import":
                password = urllib.parse.unquote(self.headers.get("X-Password") or "")
                info = self.app.vault.import_backup(self._body(), password)
                return self._json({**info, **self.app.state()})
            if path == "/api/forget":
                body = self._json_body()
                self.app.service.forget_job(body.get("job", ""))
                return self._json({"ok": True})
            if path in ("/api/addin/install", "/api/addin/uninstall"):
                from . import addin_install
                steps = addin_install.install() if path.endswith("install") and not path.endswith("uninstall") else addin_install.uninstall()
                self.app.keep_alive = self.app.pinned_alive or addin_install.is_installed()
                return self._json({"steps": steps})
            if path == "/api/native/upload-path":
                # Путь выбрал человек в системном окне; читает файл фоновая программа, а не страница.
                try:
                    return self._json(self.app.add_upload_path(str(self._json_body().get("path", ""))))
                except OSError:
                    return self._error(400, "Файл не удалось прочитать. Проверьте, что он не открыт в другой программе.")
            if path == "/api/native/folder":
                body = self._json_body()
                try:
                    return self._json({"folder": self.app.add_folder(str(body.get("path", "")), body.get("kind", "anonymize"))})
                except OSError:
                    return self._error(400, "Папку не удалось прочитать.")
            if path == "/api/window/open":
                self.app.register_window(str(self._json_body().get("id", "")))
                return self._json({"ok": True})
            if path == "/api/window/closed":
                self.app.close_window(str(self._json_body().get("id", "")))
                return self._json({"ok": True})
            if path == "/api/update/check":
                self.app.updates.start_check(force=True)
                return self._json(self.app.updates.public())
            if path == "/api/update/install":
                def apply_update(new_app):
                    updater.spawn_swap(new_app, background=self.app.pinned_alive)
                    self.app.quit_event.set()
                self.app.updates.install(self.app.pinned_alive, apply_update)
                return self._json(self.app.updates.public())
            if path == "/api/quit":
                self.app.quit_event.set()
                return self._json({"ok": True})
            if path == "/api/focus":
                if self.app.on_focus:
                    self.app.on_focus()
                else:
                    self.app.request_window()
                return self._json({"ok": True})
        except KeyError as exc:
            return self._error(404, client_message(exc, "Не найдено") if authored(exc) else "Не найдено")
        except (ValueError, crypto.KeyErrorSafe) as exc:
            return self._error(400, client_message(exc, "Некорректный запрос."))
        except Exception as exc:
            return self._error(500, f"Внутренняя ошибка ({type(exc).__name__}).")
        return self._error(404, "Не найдено")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address) -> None:
        # Страница обрывает соединение при перезагрузке; это не ошибка сервера.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def server_bind(self) -> None:
        # HTTPServer.server_bind вызывает getfqdn(): на корпоративных компьютерах с медленным DNS запуск
        # зависал на минуты. Программе имя узла не нужно.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def create_server(vault: Vault | None = None, workdir: Path | None = None, port: int = 0) -> tuple[Server, App]:
    token = secrets.token_urlsafe(24)
    vault = vault or Vault.default()
    app = App(vault, workdir or (crypto.app_data_dir() / "work"), token)
    port = port or _free_port()
    handler = type("BoundHandler", (Handler,), {"app": app, "port": port})
    server = Server(("127.0.0.1", port), handler)
    return server, app
