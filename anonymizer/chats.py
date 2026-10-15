"""Чаты: история работы с файлами.

Чат — кейс: набор файлов, которые идут вместе (исходный → обезличенный → возвращённый), и лента шагов. Соответствия
в чате не хранятся: чат помнит только, какие метки встретились в его файлах, а значения берёт из общего хранилища
(`vault.py`). Поэтому правка соответствия действует во всех чатах сразу.

На диске всё зашифровано ключом устройства, как хранилище: метаданные чата, обезличенные и возвращённые версии.
Исходные файлы хранятся только в чате с включённой галочкой «Хранить оригиналы»: возвращённая версия и исходник
содержат настоящие данные, поэтому по умолчанию исходника нет, а у возвращённых версий короткий срок.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import crypto, settings_schema
from .tokens import KINDS, base_of
from .util import atomic_write, opaque_id

ROLES = ("anon", "restored", "orig", "prev", "ret")   # prev — обезличенная версия до последней пересборки; ret — файл, который вернул ИИ
ID_RE = re.compile(r"[a-z0-9]{6,20}")
META_NAME = "chat.bin"
HISTORY_MARKER = "history-imported.bin"
MAX_STEPS = 500
CHAT_BOOL_SETTINGS = settings_schema.CHAT_BOOLS   # переопределяются в чате поверх общих настроек
CHAT_LIST_SETTINGS = settings_schema.CHAT_LISTS                          # слова чата добавляются к общим спискам
KIND_ORDER = {kind.code: index for index, kind in enumerate(KINDS)}


def _valid(identifier: str) -> bool:
    return bool(ID_RE.fullmatch(identifier or ""))


class ChatStore:
    def __init__(self, directory: Path, key: bytes | None = None) -> None:
        self.dir = directory
        self._key = key
        self._lock = threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- хранение -------------------------------------------------------------

    def _chat_dir(self, chat_id: str) -> Path:
        if not _valid(chat_id):
            raise ValueError("Неверный номер чата")
        return self.dir / chat_id

    def _read(self, chat_id: str) -> dict | None:
        try:
            raw = (self._chat_dir(chat_id) / META_NAME).read_bytes()
            return json.loads(crypto.decrypt_blob(raw, self._key))
        except (OSError, ValueError, crypto.KeyErrorSafe):
            return None

    def _write(self, chat: dict) -> None:
        chat["updated"] = time.time()
        raw = json.dumps(chat, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        atomic_write(self._chat_dir(chat["id"]) / META_NAME, crypto.encrypt_blob(raw, self._key))

    def _blob_path(self, chat_id: str, file_id: str, role: str) -> Path:
        if not _valid(file_id) or role not in ROLES:
            raise ValueError("Неверный файл или версия")
        return self._chat_dir(chat_id) / f"{file_id}.{role}.bin"

    @staticmethod
    def _shred(path: Path) -> None:
        """Затирает файл перед удалением. Он и так зашифрован; это страховка, а не гарантия (журналируемые диски)."""
        try:
            size = path.stat().st_size
            with path.open("r+b") as handle:
                handle.write(b"\0" * size)
                handle.flush()
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass

    # -- чаты -----------------------------------------------------------------

    def create(self, title: str = "", *, keep_originals: bool = False, bound_doc: str | None = None,
               created: float | None = None, **extra) -> dict:
        with self._lock:
            now = created or time.time()
            chat = {"id": opaque_id(6).lower(), "title": (title or "").strip(), "created": now, "updated": now,
                    "keep_originals": bool(keep_originals), "bound_doc": bound_doc, "files": [], "steps": [], **extra}
            self._write(chat)
            return chat

    def get(self, chat_id: str) -> dict | None:
        with self._lock:
            return self._read(chat_id) if _valid(chat_id) else None

    def listing(self) -> list[dict]:
        """Для боковой панели: самые свежие сверху."""
        with self._lock:
            items = []
            for path in self.dir.iterdir():
                chat = self._read(path.name) if path.is_dir() and _valid(path.name) else None
                if chat:
                    items.append({"id": chat["id"], "title": chat["title"], "created": chat["created"],
                                  "updated": chat["updated"], "files": len(chat["files"]),
                                  "keep_originals": chat["keep_originals"], "bound_doc": chat.get("bound_doc"),
                                  "archived": bool(chat.get("archived")),
                                  "project": (chat.get("project") or {}).get("root"),
                                  "first_file": (chat["files"][0].get("name") if chat["files"] else "")})
            return sorted(items, key=lambda c: c["updated"], reverse=True)

    def rename(self, chat_id: str, title: str) -> dict:
        with self._lock:
            chat = self._need(chat_id)
            title = (title or "").strip()
            if not title:
                raise ValueError("Название не может быть пустым")
            chat["title"] = title[:200]
            self._write(chat)
            return chat

    def mark_project(self, chat_id: str, root: str) -> dict:
        """Чат — проект: файлы хранятся с относительными путями, `root` — имя исходной папки."""
        with self._lock:
            chat = self._need(chat_id)
            chat["project"] = {"root": root}
            self._write(chat)
            return chat

    def set_settings(self, chat_id: str, patch: dict) -> dict:
        """Переопределения параметров обезличивания только для этого чата. `None` снимает переопределение: параметр снова
        берётся из общих настроек. Неизвестные ключи игнорируются."""
        with self._lock:
            chat = self._need(chat_id)
            mine = dict(settings_schema.expand_legacy(chat.get("settings") or {}))
            for name, value in settings_schema.expand_legacy(patch).items():
                if name in CHAT_BOOL_SETTINGS:
                    if value is None:
                        mine.pop(name, None)
                    else:
                        mine[name] = bool(value)
                elif name in CHAT_LIST_SETTINGS:
                    terms = [str(t).strip() for t in (value or []) if str(t).strip()] if value is not None else []
                    if terms:
                        mine[name] = list(dict.fromkeys(terms))
                    else:
                        mine.pop(name, None)
            chat["settings"] = mine
            self._write(chat)
            return chat

    # -- слова чата: решения о спорных словах живут здесь, а не в общих настройках ---------------

    def terms(self, chat_id: str) -> dict[str, list[str]]:
        mine = (self.get(chat_id) or {}).get("settings") or {}
        return {"hide_terms": list(mine.get("hide_terms") or []), "keep_terms": list(mine.get("keep_terms") or [])}

    def keep_set(self, chat_id: str, prefs: dict) -> set[str]:
        """Слова, которые в этом чате не скрываются: общий список с поправкой на решения чата (в нижнем регистре)."""
        mine = self.terms(chat_id)
        kept = {t.lower() for t in prefs.get("keep_terms", [])} - {t.lower() for t in mine["hide_terms"]}
        return kept | {t.lower() for t in mine["keep_terms"]}

    def add_term(self, chat_id: str, list_name: str, term: str) -> dict:
        """Решение о слове только для этого чата. Слово не может быть в обоих списках чата сразу."""
        if list_name not in CHAT_LIST_SETTINGS:
            raise ValueError("Неизвестный список")
        term = (term or "").strip()
        if not term:
            raise ValueError("Слово не может быть пустым")
        other = "keep_terms" if list_name == "hide_terms" else "hide_terms"
        with self._lock:
            chat = self._need(chat_id)
            mine = dict(chat.get("settings") or {})
            lst = list(mine.get(list_name) or [])
            was_mine = term.lower() in (t.lower() for t in lst)
            if not was_mine:
                lst.append(term)
            old_rest = list(mine.get(other) or [])
            rest = [t for t in old_rest if t.lower() != term.lower()]
            for name, values in ((list_name, lst), (other, rest)):
                if values:
                    mine[name] = values
                else:
                    mine.pop(name, None)
            chat["settings"] = mine
            self._write(chat)
            return {"was_listed": was_mine, "was_other": len(rest) != len(old_rest)}

    def remove_term(self, chat_id: str, list_name: str, term: str, back_to_other: bool = False) -> None:
        """Отмена `add_term`."""
        if list_name not in CHAT_LIST_SETTINGS:
            raise ValueError("Неизвестный список")
        other = "keep_terms" if list_name == "hide_terms" else "hide_terms"
        key = (term or "").strip().lower()
        with self._lock:
            chat = self._need(chat_id)
            mine = dict(chat.get("settings") or {})
            lst = [t for t in mine.get(list_name) or [] if t.lower() != key]
            rest = list(mine.get(other) or [])
            if back_to_other and key not in (t.lower() for t in rest):
                rest.append(term.strip())
            for name, values in ((list_name, lst), (other, rest)):
                if values:
                    mine[name] = values
                else:
                    mine.pop(name, None)
            chat["settings"] = mine
            self._write(chat)

    def set_keep_originals(self, chat_id: str, keep: bool) -> dict:
        """Выключение стирает уже сохранённые исходники: галочка снята — на диске их нет."""
        with self._lock:
            chat = self._need(chat_id)
            chat["keep_originals"] = bool(keep)
            if not keep:
                for record in chat["files"]:
                    self._drop_blob(chat_id, record, "orig")
            self._write(chat)
            return chat

    def bind(self, chat_id: str, bound_doc: str | None) -> dict:
        with self._lock:
            chat = self._need(chat_id)
            chat["bound_doc"] = bound_doc
            self._write(chat)
            return chat

    def set_backup(self, chat_id: str, backup_id: str | None) -> dict:
        """Копия документа Office до обезличивания (`addin.Originals`), по которой панель откатывает документ чата."""
        with self._lock:
            chat = self._need(chat_id)
            chat["addin_backup"] = backup_id
            self._write(chat)
            return chat

    def delete(self, chat_id: str) -> bool:
        """Стирает чат и его документы. Метки в общем хранилище остаются: на них опираются другие чаты и уже выданные файлы."""
        with self._lock:
            directory = self._chat_dir(chat_id)
            if not directory.is_dir():
                return False
            for path in directory.iterdir():
                self._shred(path)
            try:
                directory.rmdir()
            except OSError:
                return False
            return True

    def wipe(self) -> None:
        """Очистка хранилища делает метки чатов недействительными: чаты уходят вместе с ним."""
        with self._lock:
            for path in list(self.dir.iterdir()):
                if path.is_dir() and _valid(path.name):
                    self.delete(path.name)
            (self.dir / HISTORY_MARKER).unlink(missing_ok=True)

    def _need(self, chat_id: str) -> dict:
        chat = self.get(chat_id)
        if chat is None:
            raise KeyError("Чата нет")
        return chat

    # -- файлы и шаги ---------------------------------------------------------

    def add_file(self, chat_id: str, name: str, kind: str, *, status: str = "ok", tokens: list[str] | None = None,
                 counts: dict | None = None, names: dict | None = None, anon: bytes | None = None,
                 restored: bytes | None = None, orig: bytes | None = None) -> dict:
        """Запись о файле. Исходник сохраняется только если у чата включена галочка, иначе молча отбрасывается."""
        with self._lock:
            chat = self._need(chat_id)
            record = {"id": opaque_id(6).lower(), "name": name, "kind": kind, "status": status,
                      "tokens": sorted(set(tokens or [])), "counts": counts or {}, "roles": {},
                      "names": dict(names or {}), "added": time.time()}
            chat["files"].append(record)
            self._write(chat)
            for role, data in (("anon", anon), ("restored", restored), ("orig", orig)):
                if data is not None:
                    self.save_blob(chat_id, record["id"], role, data)
            return self._need(chat_id)["files"][-1]

    def update_file(self, chat_id: str, file_id: str, **fields) -> dict:
        with self._lock:
            chat = self._need(chat_id)
            record = self._record(chat, file_id)
            for name in ("status", "counts", "name", "stale", "rsig", "rtokens"):
                if name in fields:
                    record[name] = fields[name]
            if "names" in fields:
                record["names"] = {**record.get("names", {}), **fields["names"]}
            if "tokens" in fields:
                record["tokens"] = sorted(set(fields["tokens"] or []))
            self._write(chat)
            return record

    @staticmethod
    def _record(chat: dict, file_id: str) -> dict:
        for record in chat["files"]:
            if record["id"] == file_id:
                return record
        raise KeyError("Файла нет в чате")

    def save_blob(self, chat_id: str, file_id: str, role: str, data: bytes) -> bool:
        with self._lock:
            chat = self._need(chat_id)
            record = self._record(chat, file_id)
            if role == "orig" and not chat["keep_originals"]:
                return False
            atomic_write(self._blob_path(chat_id, file_id, role), crypto.encrypt_blob(data, self._key))
            record["roles"][role] = {"size": len(data), "time": time.time()}
            self._write(chat)
            return True

    def read_blob(self, chat_id: str, file_id: str, role: str) -> bytes | None:
        with self._lock:
            try:
                return crypto.decrypt_blob(self._blob_path(chat_id, file_id, role).read_bytes(), self._key)
            except (OSError, ValueError):
                return None

    def _drop_blob(self, chat_id: str, record: dict, role: str) -> None:
        if role in record["roles"]:
            self._shred(self._blob_path(chat_id, record["id"], role))
            del record["roles"][role]

    def remove_file(self, chat_id: str, file_id: str) -> None:
        with self._lock:
            chat = self._need(chat_id)
            record = self._record(chat, file_id)
            for role in ROLES:
                self._shred(self._blob_path(chat_id, file_id, role))
            chat["files"].remove(record)
            self._write(chat)

    def add_step(self, chat_id: str, kind: str, **data) -> dict:
        """Шаг ленты: `anonymize`, `restore`, `edit`. Содержимое файлов в шаг не попадает, только счётчики и итог."""
        with self._lock:
            chat = self._need(chat_id)
            step = {"id": opaque_id(4).lower(), "time": time.time(), "kind": kind, **data}
            chat["steps"].append(step)
            del chat["steps"][:-MAX_STEPS]
            self._write(chat)
            return step

    # -- таблица замен --------------------------------------------------------

    def table(self, chat_id: str, vault) -> list[dict]:
        """Соответствия чата: выборка из хранилища по меткам его файлов. Слитые метки показываются под той, куда их слили."""
        with self._lock:
            chat = self._need(chat_id)
            files_by_base: dict[str, set[str]] = {}
            for record in chat["files"]:
                for token in record["tokens"]:
                    base = base_of(token)
                    row = vault.describe(base) if base else None
                    if row:
                        files_by_base.setdefault(row["base"], set()).add(record["id"])
            kept = self.keep_set(chat_id, vault.prefs)
            rows = []
            for base, file_ids in files_by_base.items():
                row = vault.describe(base, kept)
                row["files"] = len(file_ids)
                rows.append(row)
            rows.sort(key=lambda r: (KIND_ORDER.get(r["kind"], 99), int(re.search(r"\d+", r["base"]).group())))
            return rows

    def match_chats(self, bases: set[str], vault) -> list[tuple[int, float, str]]:
        """Чаты с метками из `bases` (после слияний): (число общих меток, обновлён, номер), лучший первым."""
        wanted = {vault._final(b) for b in bases}
        found = []
        for item in self.listing():
            chat = self.get(item["id"])
            used = {vault._final(base_of(t)) for rec in chat["files"] for t in rec["tokens"] if base_of(t)}
            overlap = len(used & wanted)
            if overlap:
                found.append((overlap, item["updated"], item["id"]))
        return sorted(found, reverse=True)

    def chats_using(self, bases: set[str], vault) -> list[str]:
        """Чаты, в файлах которых есть хоть одна из меток (после слияний): для привязки документа Office без идентификатора."""
        return [cid for _, _, cid in self.match_chats(bases, vault)]

    def match_one(self, bases: set[str], vault) -> str | None:
        """Единственный подходящий чат: с наибольшим числом общих меток, и только если он один такой."""
        found = self.match_chats(bases, vault)
        if not found or (len(found) > 1 and found[1][0] == found[0][0]):
            return None
        return found[0][2]

    # -- срок хранения и миграция ---------------------------------------------

    def purge(self, anon_days: int = 180, restored_days: int = 30) -> int:
        """Нулевой срок — хранить бессрочно. Возвращённые версии содержат настоящие данные, поэтому уходят раньше."""
        removed = 0
        now = time.time()
        with self._lock:
            for item in self.listing():
                chat = self._need(item["id"])
                if anon_days > 0 and chat["updated"] < now - anon_days * 86400:
                    removed += self.delete(chat["id"])
                    continue
                if restored_days > 0:
                    changed = False
                    for record in chat["files"]:
                        info = record["roles"].get("restored")
                        if info and info["time"] < now - restored_days * 86400:
                            self._drop_blob(chat["id"], record, "restored")
                            changed = True
                    if changed:
                        self._write(chat)
        return removed

    def import_history(self, vault) -> int:
        """Журнал хранилища → архивные чаты без файлов, по одному на задание. Разовая миграция: после неё чаты ведутся сами,
        и каждое новое задание, у которого уже есть настоящий чат, призрачным дублем не становится; удалённый чат не воскресает."""
        with self._lock:
            marker = self.dir / HISTORY_MARKER
            if marker.exists():
                return 0
            has_real = any(not item.get("archived") or self.get(item["id"]).get("files") and
                           any(r.get("roles") for r in self.get(item["id"])["files"]) for item in self.listing())
            known = set()
            for item in self.listing():
                chat = self.get(item["id"])
                if chat and chat.get("history_id"):
                    known.add(chat["history_id"])
            added = 0
            for entry in vault.history:
                if entry["id"] in known or has_real:
                    continue
                names = entry.get("files") or []
                chat = self.create(names[0] if names else "Задание", created=entry["time"], archived=True,
                                   history_id=entry["id"])
                chat = self._need(chat["id"])
                chat["updated"] = entry["time"]
                chat["files"] = [{"id": opaque_id(6).lower(), "name": name, "kind": "", "status": "ok",
                                  "tokens": entry.get("tokens", []), "counts": entry.get("counts", {}), "roles": {},
                                  "added": entry["time"]} for name in names]
                chat["steps"] = [{"id": opaque_id(4).lower(), "time": entry["time"], "kind": entry.get("kind", "anonymize"),
                                  "counts": entry.get("counts", {})}]
                raw = json.dumps(chat, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                atomic_write(self._chat_dir(chat["id"]) / META_NAME, crypto.encrypt_blob(raw, self._key))
                added += 1
            atomic_write(marker, crypto.encrypt_blob(b"1", self._key))
            return added
