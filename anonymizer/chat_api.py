"""Маршруты чатов. Одни и те же для окна программы (`webapp.Handler`) и панели Office (`addin.AddinHandler`):
страница чата открывается в диалоге Office и говорит с тем же фоновым процессом.

Ошибки: `KeyError` — не найдено (404), `ValueError` — неверный запрос (400); обработчик HTTP переводит их сам.
"""

from __future__ import annotations

import mimetypes
import re
import urllib.parse

from . import folders, table_io
from .chats import ROLES

CHAT_PREFIX = "/api/chats"
CHAT = re.compile(r"/api/chats/([^/]+)")
FILE = re.compile(r"/api/chats/([^/]+)/files/([^/]+)/([^/]+?)(/open)?")
PREVIEW = re.compile(r"/api/chats/([^/]+)/files/([^/]+)/([^/]+)/preview(?:/(\d{1,5}))?")
ENTITY = re.compile(r"/api/chats/([^/]+)/entities/([^/]+)")
APPLY = re.compile(r"/api/chats/([^/]+)/apply")
TABLE_FILE = re.compile(r"/api/chats/([^/]+)/table\.(xlsx|csv)")
TABLE_IMPORT = re.compile(r"/api/chats/([^/]+)/table/(import|undo)")
PROJECT_ZIP = re.compile(r"/api/chats/([^/]+)/project/(anon|restored)\.zip")
RERESTORE = re.compile(r"/api/chats/([^/]+)/rerestore")
ACTIONS = ("edit", "merge", "split", "keep", "hide", "hide_new", "forget", "undo")
UNDOABLE = ("edit", "merge", "split", "keep", "hide", "batch")


def is_chat_path(path: str) -> bool:
    return path == CHAT_PREFIX or path.startswith(CHAT_PREFIX + "/")


AI_PREFIX = "/api/ai"
AI_PROVIDER = re.compile(r"/api/ai/providers/([a-z0-9_-]{1,40})(?:/(key|test|models))?")


def is_ai_path(path: str) -> bool:
    return path == AI_PREFIX or path.startswith(AI_PREFIX + "/")


def ai_handle(app, method: str, path: str, body) -> tuple:
    """AI provider settings (W12). The page gets masked metadata only; a key is accepted once (POST .../key) and never
    returned. Needs `app.keystore` (a `keystore.Keystore`). Same error convention as `handle`."""
    from . import ai_chat, llm, policy
    if path.startswith(AI_PREFIX + "/chats/") or path.startswith(AI_PREFIX + "/runs/"):
        return ai_chat.handle(app, method, path, body)
    store = app.keystore
    if path == AI_PREFIX + "/providers" and method == "GET":
        return "json", {"items": store.listing(), "enabled": store.enabled(), "kinds": list(llm.KINDS),
                        "curated": llm.CURATED_MODELS, "policy": policy.status()}
    if path == AI_PREFIX + "/enabled" and method == "POST":
        store.set_enabled(bool(body().get("enabled")))
        return "json", {"enabled": store.enabled()}
    match = AI_PROVIDER.fullmatch(path)
    if not match:
        raise KeyError("Not found")
    pid, action = match.groups()
    if action is None and method == "POST":
        data = body()
        return "json", store.configure(pid, str(data.get("kind", "")), str(data.get("base_url", "")),
                                       str(data.get("model", "")), data.get("max_tokens"),
                                       models=data.get("models"), internal=data.get("internal"), name=data.get("name"))
    if action is None and method == "DELETE":
        store.delete(pid)
        return "json", {"ok": True}
    if action == "key" and method == "POST":
        return "json", store.set_secret(pid, str(body().get("key", "")))
    if action == "key" and method == "DELETE":
        return "json", store.remove_secret(pid)
    if action in ("test", "models") and method == "POST":
        result = llm.test_connection(store.provider(pid))
        return "json", {k: result[k] for k in ("ok", "code", "message", "models")}
    raise KeyError("Not found")


def public(chat: dict) -> dict:
    """Чат для страницы: без служебных полей (метки файлов остаются внутри)."""
    files = [{k: record.get(k) for k in ("id", "name", "kind", "status", "counts", "roles", "names", "added", "stale")}
             for record in chat["files"]]
    return {"id": chat["id"], "title": chat["title"], "created": chat["created"], "updated": chat["updated"],
            "keep_originals": chat["keep_originals"], "bound_doc": chat.get("bound_doc"),
            "archived": bool(chat.get("archived")), "project": chat.get("project"),
            "settings": dict(chat.get("settings") or {}), "files": files, "steps": chat["steps"]}


def _full(app, chat_id: str) -> dict:
    chat = app.chats.get(chat_id)
    if chat is None:
        raise KeyError("Чата нет")
    return {**public(chat), "table": app.chats.table(chat_id, app.vault), "restore": table_io.restore_state(app, chat_id)}


def handle(app, method: str, path: str, body) -> tuple:
    """Возвращает ("json", данные) или ("file", байты, имя). `body` — функция, читающая тело запроса как словарь."""
    if path == CHAT_PREFIX:
        if method == "GET":
            return "json", {"items": app.chats.listing()}
        if method == "POST":
            data = body()
            keep = data["keep_originals"] if "keep_originals" in data else app.keep_originals_default()
            chat = app.chats.create(str(data.get("title", "")), keep_originals=bool(keep))
            return "json", public(chat)
    match = PREVIEW.fullmatch(path)
    if match and method == "GET":
        from . import preview
        chat_id, file_id, role, page = match.groups()
        if role not in ROLES:
            raise KeyError("Такой версии нет")
        chat = app.chats.get(chat_id)
        record = next((r for r in (chat or {"files": []})["files"] if r["id"] == file_id), None)
        data = app.chats.read_blob(chat_id, file_id, role) if record else None
        if data is None:
            raise KeyError("Этой версии файла нет")
        name = record.get("names", {}).get(role) or record["name"]
        # Метки подсвечиваются только там, где лежит обезличенный текст; «Исходный» и «Возвращённый» остаются локальными.
        result = preview.render(name, data, int(page or 1), marks=role in ("anon", "prev", "ret"))
        return "json", {**result, "role": role, "file": file_id, "local_only": role in ("orig", "restored")}
    match = FILE.fullmatch(path)
    if match:
        chat_id, file_id, role, opening = match.groups()
        if role not in ROLES:
            raise KeyError("Такой версии нет")
        if opening and method == "POST":
            app.opener(app.materialize(chat_id, file_id, role))
            return "json", {"ok": True}
        if not opening and method == "GET":
            chat = app.chats.get(chat_id)
            record = next((r for r in (chat or {"files": []})["files"] if r["id"] == file_id), None)
            data = app.chats.read_blob(chat_id, file_id, role) if record else None
            if data is None:
                raise KeyError("Этой версии файла нет")
            return "file", data, record.get("names", {}).get(role) or record["name"]
    match = ENTITY.fullmatch(path)
    if match and method == "POST":
        return "json", _edit_entity(app, match.group(1), urllib.parse.unquote(match.group(2)), body())
    match = APPLY.fullmatch(path)
    if match and method == "POST":
        return "json", {"job": app.apply_chat(match.group(1), body().get("options") or {})}
    match = TABLE_FILE.fullmatch(path)
    if match and method == "GET":
        data, name = table_io.export_file(app, match.group(1), match.group(2))
        return "file", data, name
    match = TABLE_IMPORT.fullmatch(path)
    if match and method == "POST":
        chat_id, what = match.groups()
        data = body()
        if what == "undo":
            if app.chats.get(chat_id) is None:
                raise KeyError("Чата нет")
            return "json", _undo(app, chat_id, "", {**(data.get("undo") or data), "action": "undo"}, set())
        raw = table_io.decode_upload(data) if not data.get("apply") else b""
        return "json", table_io.import_table(app, chat_id, str(data.get("name", "")), raw, bool(data.get("apply")),
                                             data.get("token"))
    match = PROJECT_ZIP.fullmatch(path)
    if match and method == "GET":
        data, name = folders.project_zip(app, match.group(1), match.group(2))
        return "file", data, name
    match = RERESTORE.fullmatch(path)
    if match and method == "POST":
        return "json", {"job": app.rerestore(match.group(1))}
    match = CHAT.fullmatch(path)
    if match:
        chat_id = match.group(1)
        if method == "GET":
            return "json", _full(app, chat_id)
        if method == "POST":
            data = body()
            if app.chats.get(chat_id) is None:
                raise KeyError("Чата нет")
            if "title" in data:
                app.chats.rename(chat_id, str(data["title"]))
            if "keep_originals" in data:
                app.chats.set_keep_originals(chat_id, bool(data["keep_originals"]))
            if isinstance(data.get("settings"), dict):
                app.chats.set_settings(chat_id, data["settings"])
            return "json", public(app.chats.get(chat_id))
        if method == "DELETE":
            backup = (app.chats.get(chat_id) or {}).get("addin_backup")
            if not app.chats.delete(chat_id):
                raise KeyError("Чата нет")
            app.chat_deleted(chat_id, backup)
            return "json", {"ok": True}
    raise KeyError("Не найдено")


def _edit_entity(app, chat_id: str, base: str, data: dict) -> dict:
    """Правка соответствия из чата. Правится общее хранилище; в чате остаётся запись о шаге без значений."""
    vault = app.vault
    if app.chats.get(chat_id) is None:
        raise KeyError("Чата нет")
    action = data.get("action")
    if action not in ACTIONS:
        raise ValueError("Неизвестное действие")
    if action == "hide_new":
        return _hide_new(app, chat_id, data)
    if action == "undo" and data.get("of") == "batch":
        return _undo(app, chat_id, base, data, set())
    bases = {row["base"] for row in app.chats.table(chat_id, vault)}
    if vault._final(base) not in bases:
        raise KeyError("Метки нет в этом чате")
    variant = int(data.get("variant") or 0)
    result: dict = {}
    if action == "undo":
        return _undo(app, chat_id, base, data, bases)
    if action == "edit":
        previous = vault.edit_value(base, variant, str(data.get("value", "")))
        result["undo"] = {"of": "edit", "base": vault._final(base), "variant": variant, "previous": previous}
    elif action == "merge":
        target = str(data.get("into", ""))
        if vault._final(target) not in bases:
            raise ValueError("Метки для слияния нет в этом чате")
        source = vault._final(base)
        vault.merge(base, target)
        result["into"] = vault._final(target)
        result["undo"] = {"of": "merge", "base": source}
    elif action == "split":
        result["new_base"] = vault.split(base, variant)
        result["undo"] = {"of": "split", "base": vault._final(base), "new_base": result["new_base"]}
    elif action in ("keep", "hide"):
        term = str(data.get("term") or "").strip()
        if not term:
            row = vault.describe(base)
            if row["secret"] or not 1 <= variant <= len(row["variants"]):
                raise ValueError("Выберите написание")
            term = row["variants"][variant - 1]["original"]
        info = app.chats.add_term(chat_id, "keep_terms" if action == "keep" else "hide_terms", term)
        result["undo"] = {"of": action, "base": vault._final(base), "term": term, "was_other": info["was_other"],
                          "was_listed": info["was_listed"]}
        result["was_listed"] = info["was_listed"]
    else:
        vault.forget(base)
    app.chats.add_step(chat_id, "edit", action=action, base=base, **({"into": result["into"]} if "into" in result else {}))
    return {**result, "table": app.chats.table(chat_id, vault)}


def _hide_new(app, chat_id: str, data: dict) -> dict:
    """Слово, которое программа пропустила: скрыть его в этом чате. Тот же `add_term`, что и у «Скрывать снова»:
    слово попадает в список слов чата (общие настройки не меняются), в чате остаётся шаг правки, а файлы пересобирает обычное «Применить»."""
    vault = app.vault
    term = str(data.get("term") or "").strip()
    if not term:
        raise ValueError("Введите слово, которое нужно скрыть")
    found = vault.entity_for_term(term, with_base=True)
    info = app.chats.add_term(chat_id, "hide_terms", term)
    app.chats.add_step(chat_id, "edit", action="hide", base=found[2] if found else "")
    return {"already_hidden": info["was_listed"], "was_other": info["was_other"],
            "covered_by": found[2] if found else None, "table": app.chats.table(chat_id, vault)}


def _undo(app, chat_id: str, base: str, data: dict, bases: set) -> dict:
    """Отмена правки по описанию, которое вернула сама правка. Выданная метка при отмене не меняет значения:
    слияние отменяется снятием слияния, разделение слиянием новой метки обратно, значение возвращается к прежнему.
    `{"of": "batch", "items": [...]}` — отмена загрузки таблицы: части отменяются в обратном порядке."""
    vault = app.vault
    of = data.get("of")
    if of not in UNDOABLE:
        raise ValueError("Это действие нельзя отменить")
    if of == "batch":
        for item in reversed(list(data.get("items") or [])):
            try:
                _undo_one(app, chat_id, str(item.get("base", "")), item)
            except (ValueError, KeyError):
                continue                 # часть уже отменена или изменилась: остальное всё равно возвращается
    else:
        _undo_one(app, chat_id, base, data)
    app.chats.add_step(chat_id, "edit", action="undo", of=of, base=base)
    return {"table": app.chats.table(chat_id, vault)}


def _undo_one(app, chat_id: str, base: str, data: dict) -> None:
    vault = app.vault
    of = data.get("of")
    if of not in ("edit", "merge", "split", "keep", "hide"):
        raise ValueError("Это действие нельзя отменить")
    if of == "edit":
        vault.restore_edit(base, int(data.get("variant") or 0), data.get("previous"))
    elif of == "merge":
        vault.unmerge(base)
    elif of == "split":
        new_base = str(data.get("new_base", ""))
        if new_base not in vault.entities or vault._final(new_base) == vault._final(base):
            raise ValueError("Разделение уже отменено")
        vault.merge(new_base, base)
    else:
        term = str(data.get("term") or "").strip()
        if not term:
            raise ValueError("Не указано слово")
        if not data.get("was_listed"):  # слово уже стояло в списке до правки: список остаётся, отменять нечего
            app.chats.remove_term(chat_id, "keep_terms" if of == "keep" else "hide_terms", term, back_to_other=bool(data.get("was_other")))
