"""Хранилище соответствий «токен ↔ исходное значение».

Один зашифрованный файл на компьютере пользователя. Токены выдаются на всё хранилище, а не на файл:
`Name7` в одном документе и `Name7` в другом — всегда один и тот же человек. Поэтому обезличенные
файлы можно свободно объединять в одном чате с моделью, а при восстановлении не нужно выбирать
ни ключ, ни «сессию»: токен сам однозначно указывает на значение.

Хранилище не содержит текста документов, только значения, которые были заменены.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import crypto
from . import settings_schema
from .tokens import KIND_BY_CODE, Kind, format_token, token_base
from .util import atomic_write, opaque_id

DEFAULT_PREFS = {
    "retention_days": 180,     # 0 — хранить, пока пользователь сам не очистит
    "restored_retention_days": 30,   # возвращённые версии в чатах содержат настоящие данные: срок короче (0 — бессрочно)
    "hide_terms": [],          # всегда скрывать
    "keep_terms": [],          # никогда не скрывать
    "numbers": False,          # заменять числа суррогатами (только Excel)
    "strict": False,           # скрывать и сомнительные слова: всё из списка «Возможно, нужно скрыть ещё»
    "countries": True,         # скрывать страны: по умолчанию включено, иначе их забывают отметить
    "neutral_names": True,     # называть результат «Файл1 (обезличено)» вместо исходного имени
    "keep_originals": True,    # новые чаты хранят исходники (зашифрованно): без них правки не пересобрать файл
    "sidebar_width": None,     # ширина списка чатов, px; None — по умолчанию
    "pane_width": None,        # ширина таблицы замен, px; None — по умолчанию
    "sidebar_collapsed": None, # список чатов скрыт; None — выбор не делали (на узком окне список скрывается сам)
    "preview_width": None,     # ширина панели просмотра файла, px; None — по умолчанию (S12C)
    "addin_hint_dismissed": False,  # подсказка про надстройку Office закрыта (W9B)
    "preview_open": False,     # панель просмотра файла в чате открыта (S11A)
    "presets": {},             # свои наборы настроек: {имя: {ключ: значение}}
    **{k: v for k, v in settings_schema.defaults().items() if k not in ("hide_terms", "keep_terms", "numbers", "strict", "countries", "neutral_names", "keep_originals", "retention_days", "restored_retention_days")},
}

MAX_HISTORY = 200


@dataclass(slots=True)
class Lookup:
    status: str                 # ok | unknown | variant_missing | removed
    original: str | None = None
    base: str = ""


def canon_number(text: str) -> str | None:
    """Каноническая запись числа: `1200`, `1200.0` и `1.2E3` — одно и то же число."""
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


class Vault:
    def __init__(self, path: Path | None = None, key: bytes | None = None) -> None:
        self.path = path
        self._key = key
        self._lock = threading.RLock()
        self.counters: dict[str, int] = {}
        self.entities: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.numbers: dict[str, str] = {}        # исходное → суррогат (канонические записи)
        self.numbers_back: dict[str, str] = {}   # суррогат → исходное
        self.finance: dict[str, dict] = {}       # id записи маскирования сумм → множитель и исходные значения ячеек
        self.file_names: dict[str, str] = {}     # номер нейтрального имени («Файл3» → "3») → исходное имя файла
        self.file_times: dict[str, float] = {}   # когда имя использовали в последний раз: по сроку хранения исходные имена уходят
        self.pins: dict[str, str] = {}           # «вид\0написание» → сущность: написание, выделенное в отдельную сущность
        self.prefs: dict = json.loads(json.dumps(DEFAULT_PREFS))
        self.history: list[dict] = []
        # Идентификатор хранилища попадает в обезличенные файлы. По нему при возврате видно, что файл сделан другим
        # хранилищем: одинаковые метки (Name1) там означают других людей.
        self.vault_id = opaque_id(6).lower()
        self.known_ids: set[str] = {self.vault_id}
        self.notice = ""
        self.dirty = False
        self._erased = False                      # срок хранения что-то стёр: следующее сохранение не оставляет .bak
        self._images: dict[str, bytes] = {}      # когда хранилище без файла: оригиналы картинок в памяти
        if path is not None and path.exists():
            self._load()
        self._purge()

    # -- хранение -------------------------------------------------------------

    @classmethod
    def default(cls) -> "Vault":
        """Хранилище пользователя. Нечитаемое (другой компьютер, потерян ключ устройства) не удаляется, а
        откладывается в сторону: его можно вернуть вместе с ключом, а программа при этом запускается."""
        path = crypto.app_data_dir() / "vault.bin"
        try:
            return cls(path)
        except crypto.KeyErrorSafe as exc:
            aside = path.with_name(f"vault.unreadable.{int(time.time())}.bin")
            path.replace(aside)
            vault = cls(path)
            vault.notice = (f"Прежнее хранилище не удалось открыть ({exc}). Оно сохранено как {aside.name} в папке "
                            "программы. Файлы, обезличенные раньше, восстановить не получится, пока не будет возвращён "
                            "ключ устройства.")
            return vault

    def _payload(self) -> dict:
        return {"version": 1, "counters": self.counters, "entities": self.entities, "numbers": self.numbers, "finance": self.finance,
                "file_names": self.file_names, "file_times": self.file_times, "pins": self.pins, "prefs": self.prefs, "history": self.history, "vault_id": self.vault_id, "known_ids": sorted(self.known_ids)}

    def _load(self) -> None:
        blob = self.path.read_bytes()
        try:
            data = json.loads(crypto.decrypt_blob(blob, self._key))
        except crypto.KeyErrorSafe:
            # Не затираем нечитаемое хранилище: пользователь может вернуть ключ устройства.
            raise
        self._apply(data)

    def _apply(self, data: dict) -> None:
        self.counters = {k: int(v) for k, v in data.get("counters", {}).items()}
        self.entities = data.get("entities", {})
        self.numbers = data.get("numbers", {})
        self.finance = data.get("finance", {})
        self.numbers_back = {v: k for k, v in self.numbers.items()}
        self.file_names = {str(k): v for k, v in data.get("file_names", {}).items()}
        self.file_times = {str(k): float(v) for k, v in data.get("file_times", {}).items() if str(k) in self.file_names}
        self.pins = dict(data.get("pins", {}))
        self.prefs = {**json.loads(json.dumps(DEFAULT_PREFS)), **settings_schema.expand_legacy(data.get("prefs", {}))}
        self.history = data.get("history", [])
        self.vault_id = data.get("vault_id") or self.vault_id
        self.known_ids = set(data.get("known_ids", [])) | {self.vault_id}
        self._reindex()

    def _reindex(self) -> None:
        """Индекс «ключ → токен»: ключ слитой сущности ведёт к той, в которую её слили."""
        self.by_key = {self._key_of(e["kind"], e["key"]): self._final(base) for base, e in self.entities.items()}

    def _drop_backup(self) -> None:
        """Прежняя копия хранилища содержит то, что человек только что стёр: затираем её."""
        backup = self.path.with_suffix(".bak")
        try:
            with backup.open("r+b") as handle:
                handle.write(b"\0" * backup.stat().st_size)
                handle.flush()
        except OSError:
            pass
        try:
            backup.unlink()
        except OSError:
            pass

    def save(self, destructive: bool = False) -> None:
        """`destructive` — сохранение после стирания данных: копия `.bak` с прежним содержимым не остаётся."""
        if self.path is None:
            self.dirty = False
            return
        with self._lock:
            destructive = destructive or self._erased
            self._erased = False
            raw = json.dumps(self._payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            blob = crypto.encrypt_blob(raw, self._key)
            if destructive:
                atomic_write(self.path, blob)
                self._drop_backup()
                self.dirty = False
                return
            if self.path.exists():
                try:
                    (self.path.with_suffix(".bak")).write_bytes(self.path.read_bytes())
                except OSError:
                    pass
            atomic_write(self.path, blob)
            self.dirty = False

    def commit(self) -> None:
        with self._lock:
            if self.dirty:
                self.save()

    @staticmethod
    def _key_of(kind: str, key: str) -> str:
        return f"{kind}\x00{key}"

    def _purge(self) -> None:
        days = int(self.prefs.get("retention_days") or 0)
        if days <= 0:
            return
        limit = time.time() - days * 86400
        targets = {e["merged_into"] for e in self.entities.values() if e.get("merged_into")}  # на них ссылаются слитые метки
        stale = [base for base, e in self.entities.items() if e.get("used", 0) < limit and base not in targets]
        for base in stale:
            entity = self.entities.pop(base)
            self.by_key.pop(self._key_of(entity["kind"], entity["key"]), None)
        if stale:
            self.dirty = True
            self._erased = True
        now = time.time()
        for number in list(self.file_names):
            if self.file_times.setdefault(number, now) < limit:
                del self.file_names[number], self.file_times[number]
                self.dirty = True
                self._erased = True
        for entry in self.history:
            if entry.get("time", now) < limit and entry.get("files"):
                entry["files"] = []              # исходные имена файлов старого задания
                self.dirty = True
                self._erased = True

    def snapshot(self):
        """Состояние до задания: повторный проход с правками пользователя не должен оставлять пропусков в нумерации."""
        with self._lock:
            return copy.deepcopy((self.counters, self.entities, self.numbers, self.history, self.file_names, self.pins))

    def rollback(self, snap) -> None:
        with self._lock:
            self.counters, self.entities, self.numbers, self.history, self.file_names, self.pins = copy.deepcopy(snap)
            self.numbers_back = {v: k for k, v in self.numbers.items()}
            self._reindex()
            self.dirty = True
            self.save(destructive=True)

    # -- оригиналы изображений ---------------------------------------------------
    # Картинка с закрашенными данными не содержит исходных пикселей. Оригинал лежит рядом с хранилищем, зашифрованный
    # тем же ключом, под хэшем обезличенной картинки: по нему при возврате находится нужный файл.

    def _image_dir(self) -> Path | None:
        return None if self.path is None else self.path.parent / "images"

    def stash_image(self, anonymized_sha: str, original: bytes) -> None:
        folder = self._image_dir()
        if folder is None:
            self._images[anonymized_sha] = original
            return
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write(folder / f"{anonymized_sha}.bin", crypto.encrypt_blob(original, self._key))

    def image_store_bytes(self) -> int:
        """Сколько байт занимают сохранённые оригиналы картинок (для лимита, см. imagereplace.stash)."""
        folder = self._image_dir()
        if folder is None:
            return sum(len(v) for v in self._images.values())
        try:
            return sum(p.stat().st_size for p in folder.glob("*.bin"))
        except OSError:
            return 0

    def original_image(self, anonymized_sha: str) -> bytes | None:
        folder = self._image_dir()
        if folder is None:
            return self._images.get(anonymized_sha)
        target = folder / f"{anonymized_sha}.bin"
        if not target.exists():
            return None
        try:
            return crypto.decrypt_blob(target.read_bytes(), self._key)
        except Exception:
            return None

    def clear(self) -> None:
        with self._lock:
            self._images = {}
            folder = self._image_dir()
            if folder is not None and folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            self.counters, self.entities, self.by_key = {}, {}, {}
            self.numbers, self.numbers_back, self.history = {}, {}, []
            self.finance = {}
            self.file_names, self.file_times, self.pins = {}, {}, {}
            # Нумерация начинается заново, поэтому файлы, обезличенные раньше, больше не относятся к этому хранилищу.
            self.vault_id = opaque_id(6).lower()
            self.known_ids = {self.vault_id}
            self.dirty = True
            self.save(destructive=True)

    # -- выдача токенов -------------------------------------------------------

    def token_for(self, kind_code: str, key: str, spelling: str | None, *, extension: str = "",
                  secret: bool = False) -> str:
        """Токен для написания `spelling` сущности (kind, key). Повторный вызов даёт тот же токен."""
        kind: Kind = KIND_BY_CODE[kind_code]
        with self._lock:
            composite = self._key_of(kind.code, key)
            base = self.by_key.get(composite)
            pinned = None if secret or spelling is None else self.pins.get(self._pin_key(kind.code, spelling))
            if pinned in self.entities:
                base = self._final(pinned)
            now = time.time()
            if base is None:
                number = self.counters.get(kind.stem, 0) + 1
                self.counters[kind.stem] = number
                base = token_base(kind, number)
                self.entities[base] = {"kind": kind.code, "key": key, "spellings": [], "created": now,
                                       "used": now, "secret": secret}
                self.by_key[composite] = base
                self.dirty = True
            entity = self.entities[base]
            entity["used"] = now
            if secret or spelling is None:
                return format_token(kind, _number_of(base), 1, extension)
            spellings: list[str] = entity["spellings"]
            if spelling in spellings:
                variant = spellings.index(spelling) + 1
            else:
                spellings.append(spelling)
                variant = len(spellings)
                self.dirty = True
            return format_token(kind, _number_of(base), variant, extension)

    def lookup(self, kind: Kind, number: int, variant: int = 1) -> Lookup:
        with self._lock:
            base = token_base(kind, number)
            entity = self.entities.get(base)
            if entity is None:
                return Lookup("unknown", None, base)
            # Слитая сущность: метка из старого файла указывает на написание в той, в которую её слили.
            while entity.get("merged_into"):
                mapped = entity.get("vmap", {}).get(str(variant))
                base = entity["merged_into"]
                entity = self.entities.get(base)
                if entity is None:
                    return Lookup("unknown", None, base)
                if mapped is None:
                    spellings = entity["spellings"]
                    return Lookup("variant_missing", spellings[0] if spellings else None, base)
                variant = int(mapped)
            if entity.get("secret"):
                return Lookup("removed", None, base)
            spellings = entity["spellings"]
            if not spellings:
                return Lookup("removed", None, base)
            if variant > len(spellings):
                return Lookup("variant_missing", spellings[0], base)
            entity["used"] = time.time()
            self.dirty = True
            edited = entity.get("edits", {}).get(str(variant))
            return Lookup("ok", edited if edited is not None else spellings[variant - 1], base)

    def entity_label(self, base: str) -> str:
        entity = self.entities.get(base)
        return entity["spellings"][0] if entity and entity.get("spellings") else ""

    # -- правки соответствий --------------------------------------------------
    #
    # Инвариант: выданная ранее метка никогда не начинает означать другое значение. Слияние и разделение добавляют
    # правила, а файлы, обезличенные до правки, возвращаются дословно.

    @staticmethod
    def _pin_key(kind_code: str, spelling: str) -> str:
        return f"{kind_code}\x00{spelling}"

    def _final(self, base: str) -> str:
        seen = set()
        while base in self.entities and self.entities[base].get("merged_into") and base not in seen:
            seen.add(base)
            base = self.entities[base]["merged_into"]
        return base

    def _entity(self, base: str) -> dict:
        entity = self.entities.get(base)
        if entity is None:
            raise ValueError(f"Метки {base} нет в хранилище")
        return entity

    def describe(self, base: str, kept: set[str] | None = None) -> dict | None:
        """Строка таблицы замен для метки (слитая метка показывается как та, в которую её слили)."""
        with self._lock:
            base = self._final(base)
            entity = self.entities.get(base)
            if entity is None:
                return None
            kind = KIND_BY_CODE[entity["kind"]]
            number = _number_of(base)
            secret = bool(entity.get("secret"))
            spellings = [] if secret else list(entity["spellings"])
            edits = entity.get("edits", {})
            if kept is None:
                kept = {t.lower() for t in self.prefs.get("keep_terms", [])}
            variants = [{"token": format_token(kind, number, i + 1), "value": edits.get(str(i + 1), text),
                         "original": text, "edited": str(i + 1) in edits, "kept": text.lower() in kept}
                        for i, text in enumerate(spellings)]
            merged = sorted(b for b, e in self.entities.items() if self._final(b) == base and b != base)
            return {"base": base, "kind": kind.code, "label": kind.label, "secret": secret,
                    "variants": variants, "merged": merged}

    def edit_value(self, base: str, variant: int, text: str) -> str | None:
        """Что подставлять при возврате вместо метки. Распознавание по-прежнему опирается на написание из файла.
        Возвращает прежнюю правку (None, если её не было): по ней правку можно отменить."""
        text = (text or "").strip()
        if not text:
            raise ValueError("Значение не может быть пустым")
        with self._lock:
            entity = self._entity(self._final(base))
            if entity.get("secret"):
                raise ValueError("Пароли и ключи не хранятся и не редактируются")
            if not 1 <= variant <= len(entity["spellings"]):
                raise ValueError("Такого написания нет")
            previous = entity.get("edits", {}).get(str(variant))
            entity.setdefault("edits", {})[str(variant)] = text
            self.dirty = True
            self.save(destructive=True)            # .bak хранил бы прежнее значение правки
            return previous

    def restore_edit(self, base: str, variant: int, previous: str | None) -> None:
        """Отмена правки значения: возвращает прежнюю правку или убирает её, значение снова берётся из файла."""
        with self._lock:
            entity = self._entity(self._final(base))
            if entity.get("secret") or not 1 <= variant <= len(entity["spellings"]):
                raise ValueError("Такого написания нет")
            if previous is None:
                entity.get("edits", {}).pop(str(variant), None)
                if "edits" in entity and not entity["edits"]:
                    del entity["edits"]
            else:
                entity.setdefault("edits", {})[str(variant)] = previous
            self.dirty = True
            self.save(destructive=True)

    def merge(self, source: str, target: str) -> None:
        """`source` — тот же объект, что `target`. Новые обезличивания выдают метку `target`, старые файлы с `source` возвращаются как раньше."""
        with self._lock:
            source, target = self._final(source), self._final(target)
            if source == target:
                raise ValueError("Нельзя слить метку с самой собой")
            src, dst = self._entity(source), self._entity(target)
            if src["kind"] != dst["kind"]:
                raise ValueError("Слить можно только метки одного вида")
            if src.get("secret") or dst.get("secret"):
                raise ValueError("Пароли и ключи не сливаются")
            vmap: dict[str, int] = {}
            for index, text in enumerate(src["spellings"], start=1):
                if text in dst["spellings"]:
                    vmap[str(index)] = dst["spellings"].index(text) + 1
                else:
                    dst["spellings"].append(text)
                    vmap[str(index)] = len(dst["spellings"])
                    if str(index) in src.get("edits", {}):
                        dst.setdefault("edits", {})[str(len(dst["spellings"]))] = src["edits"][str(index)]
            undo: dict = {"pins": [], "reparent": {}}
            for name, other in self.entities.items():  # те, кого раньше слили в source, теперь ведут в target
                if other.get("merged_into") == source:
                    undo["reparent"][name] = other.get("vmap", {})
                    other["vmap"] = {k: vmap.get(str(v)) for k, v in other.get("vmap", {}).items() if str(v) in vmap}
                    other["merged_into"] = target
            src["merged_into"], src["vmap"] = target, vmap
            for pin, base in list(self.pins.items()):
                if base == source:
                    undo["pins"].append(pin)
                    self.pins[pin] = target
            src["merge_undo"] = undo
            dst["used"] = time.time()
            self._reindex()
            self.dirty = True
            self.save()

    def unmerge(self, source: str) -> str:
        """Отмена слияния: `source` снова отдельная метка. Файлы с любой из меток продолжают возвращаться верно,
        потому что написания слитой метки остались и в `source`, и в `target`. Возвращает `target`."""
        with self._lock:
            src = self._entity(source)
            target = src.get("merged_into")
            undo = src.get("merge_undo")
            if not target or undo is None:
                raise ValueError("Эту метку нельзя разъединить: слияния нет или оно сделано старой версией программы")
            for name, vmap in undo.get("reparent", {}).items():
                other = self.entities.get(name)
                if other is not None and other.get("merged_into") == target:
                    other["merged_into"], other["vmap"] = source, vmap
            for pin in undo.get("pins", []):
                if self.pins.get(pin) == target:
                    self.pins[pin] = source
            for key in ("merged_into", "vmap", "merge_undo"):
                src.pop(key, None)
            self._reindex()
            self.dirty = True
            self.save()
            return target

    def split(self, base: str, variant: int) -> str:
        """Написание `variant` — другой объект. Новые обезличивания выдают ему новую метку; старые файлы возвращаются как раньше."""
        with self._lock:
            base = self._final(base)
            entity = self._entity(base)
            if entity.get("secret"):
                raise ValueError("Пароли и ключи не разделяются")
            spellings = entity["spellings"]
            if len(spellings) < 2:
                raise ValueError("У этой метки одно написание: разделять нечего")
            if not 1 <= variant <= len(spellings):
                raise ValueError("Такого написания нет")
            kind = KIND_BY_CODE[entity["kind"]]
            number = self.counters.get(kind.stem, 0) + 1
            self.counters[kind.stem] = number
            new_base = token_base(kind, number)
            text = spellings[variant - 1]
            now = time.time()
            self.entities[new_base] = {"kind": kind.code, "key": f"split:{opaque_id(5).lower()}", "spellings": [text],
                                       "created": now, "used": now, "secret": False}
            self.pins[self._pin_key(kind.code, text)] = new_base
            self._reindex()
            self.dirty = True
            self.save()
            return new_base

    def forget(self, base: str) -> None:
        """Стереть значения метки. Номер остаётся занятым, файлы с этой меткой при возврате сообщат, что значения нет."""
        with self._lock:
            entity = self._entity(self._final(base))
            entity["spellings"] = []
            entity.pop("edits", None)
            for pin, owner in list(self.pins.items()):
                if self._final(owner) == self._final(base):
                    del self.pins[pin]
            self.dirty = True
            self.save(destructive=True)

    def entity_for_term(self, term: str, kinds: set[str] | None = None, *, with_base: bool = False):
        """Сущность, чьё написание совпадает со словом (без учёта регистра): (вид, ключ) или (вид, ключ, метка)."""
        wanted = " ".join((term or "").casefold().split())
        if not wanted:
            return None
        with self._lock:
            for base, entity in self.entities.items():
                if entity.get("secret") or entity.get("merged_into") or (kinds and entity["kind"] not in kinds):
                    continue
                if any(" ".join(s.casefold().split()) == wanted for s in entity.get("spellings", [])):
                    return (entity["kind"], entity["key"], self._final(base)) if with_base else (entity["kind"], entity["key"])
            return None

    def add_term(self, list_name: str, term: str) -> dict:
        """«Всегда скрывать» и «никогда не скрывать»; слово не может быть в обоих списках сразу."""
        if list_name not in ("hide_terms", "keep_terms"):
            raise ValueError("Неизвестный список")
        term = (term or "").strip()
        if not term:
            raise ValueError("Слово не может быть пустым")
        other = "keep_terms" if list_name == "hide_terms" else "hide_terms"
        with self._lock:
            mine = list(self.prefs.get(list_name, []))
            was_mine = term.lower() in (t.lower() for t in mine)
            if not was_mine:
                mine.append(term)
            old_rest = list(self.prefs.get(other, []))
            rest = [t for t in old_rest if t.lower() != term.lower()]
            self.set_prefs(**{list_name: mine, other: rest})
            return {"was_listed": was_mine, "was_other": len(rest) != len(old_rest)}

    def remove_term(self, list_name: str, term: str, back_to_other: bool = False) -> None:
        """Отмена `add_term`: слово уходит из списка и, если оно перед этим было в другом списке, возвращается туда."""
        if list_name not in ("hide_terms", "keep_terms"):
            raise ValueError("Неизвестный список")
        other = "keep_terms" if list_name == "hide_terms" else "hide_terms"
        with self._lock:
            values = {list_name: [t for t in self.prefs.get(list_name, []) if t.lower() != term.strip().lower()]}
            if back_to_other and term.strip().lower() not in (t.lower() for t in self.prefs.get(other, [])):
                values[other] = [*self.prefs.get(other, []), term.strip()]
            self.set_prefs(**values)

    # -- числовые суррогаты ---------------------------------------------------

    def surrogate_for(self, original: str, make) -> str:
        """Суррогат числа: одно и то же число всегда даёт один и тот же суррогат."""
        with self._lock:
            found = self.numbers.get(original)
            if found is not None:
                return found
            for _ in range(200):
                candidate = make()
                if candidate not in self.numbers_back and candidate != original:
                    break
            else:  # практически недостижимо: пространство суррогатов огромно
                raise RuntimeError("Не удалось подобрать суррогат числа")
            self.numbers[original] = candidate
            self.numbers_back[candidate] = original
            self.dirty = True
            return candidate

    def original_of_surrogate(self, surrogate: str) -> str | None:
        return self.numbers_back.get(surrogate)

    # -- нейтральные имена файлов ---------------------------------------------

    def file_number(self, original: str) -> int:
        """Номер нейтрального имени для исходного имени файла: одно и то же имя всегда получает один номер."""
        with self._lock:
            for number, name in self.file_names.items():
                if name == original:
                    self.file_times[number] = time.time()
                    return int(number)
            number = max((int(n) for n in self.file_names), default=0) + 1
            self.file_names[str(number)] = original
            self.file_times[str(number)] = time.time()
            self.dirty = True
            return number

    def original_file_name(self, number: int) -> str | None:
        return self.file_names.get(str(number))

    # -- настройки и журнал ---------------------------------------------------

    def set_prefs(self, **values) -> bool:
        """Сохраняет настройки; True, если что-то изменилось. Без изменений файл хранилища не пишется."""
        with self._lock:
            changed = False
            for name, value in values.items():
                if name in DEFAULT_PREFS and (name not in self.prefs or self.prefs[name] != value):
                    self.prefs[name] = value
                    changed = True
            if changed:
                self._purge()                      # новый срок хранения действует сразу, а не при следующем запуске
                self.dirty = True
                self.save()
            return changed

    def log(self, kind: str, files: list[str], counts: dict[str, int], extra: dict | None = None) -> None:
        with self._lock:
            self.history.append({"id": opaque_id(5), "time": time.time(), "kind": kind, "files": files,
                                 "counts": counts, **(extra or {})})
            del self.history[:-MAX_HISTORY]
            self.dirty = True

    def stats(self) -> dict:
        with self._lock:
            by_kind: dict[str, int] = {}
            for entity in self.entities.values():
                by_kind[entity["kind"]] = by_kind.get(entity["kind"], 0) + 1
            return {"entities": len(self.entities), "numbers": len(self.numbers), "by_kind": by_kind}

    # -- резервная копия ------------------------------------------------------

    def export_backup(self, password: str) -> bytes:
        with self._lock:
            raw = json.dumps(self._payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return crypto.password_encrypt(raw, password)

    def import_backup(self, blob: bytes, password: str) -> dict:
        """Слияние возможно, только если токены обоих хранилищ не спорят: иначе `Name5` из копии
        означал бы другого человека, чем `Name5` здесь, и файлы обоих компьютеров перепутались бы."""
        data = json.loads(crypto.password_decrypt(blob, password))
        with self._lock:
            conflicts = 0
            for base, entity in data.get("entities", {}).items():
                local = self.entities.get(base)
                if local and (local["kind"], local["key"]) != (entity["kind"], entity["key"]):
                    conflicts += 1
            if conflicts and self.entities:
                raise ValueError(
                    f"Импорт невозможен: в {conflicts} случаях один и тот же токен в копии и на этом компьютере "
                    "означает разные значения. Импортируйте копию в пустое хранилище (очистите историю).")
            if not self.entities:
                self._apply(data)
            else:
                for base, entity in data.get("entities", {}).items():
                    local = self.entities.get(base)
                    if local is None:
                        self.entities[base] = entity
                    else:
                        for spelling in entity.get("spellings", []):
                            if spelling not in local["spellings"]:
                                local["spellings"].append(spelling)
                for stem, value in data.get("counters", {}).items():
                    self.counters[stem] = max(self.counters.get(stem, 0), int(value))
                self.known_ids |= set(data.get("known_ids", [])) | ({data["vault_id"]} if data.get("vault_id") else set())
                for original, surrogate in data.get("numbers", {}).items():
                    self.numbers.setdefault(original, surrogate)
                self.numbers_back = {v: k for k, v in self.numbers.items()}
                for number, name in data.get("file_names", {}).items():
                    self.file_names.setdefault(str(number), name)
                for pin, base in data.get("pins", {}).items():
                    self.pins.setdefault(pin, base)
                self._reindex()
            self.dirty = True
            self.save()
            return {"entities": len(self.entities)}


def _number_of(base: str) -> int:
    match = re.search(r"(\d+)", base)
    return int(match.group(1))
