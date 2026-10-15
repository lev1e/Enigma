from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path


# Working copies Office and editors leave behind. They duplicate content that is already
# covered by the real file, so they are skipped — and reported, never silently dropped.
SKIPPED_PREFIXES = ("~$", ".~lock.")
SKIPPED_SUFFIXES = (".tmp", ".bak", ".swp", ".part", ".crdownload")


def opaque_id(nbytes: int = 10) -> str:
    import base64
    return base64.b32encode(secrets.token_bytes(nbytes)).decode("ascii").rstrip("=")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".anon-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".anon-copy-", dir=dst.parent)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


_COMMON_RU = "оеаинтслвркдмуп"


def _ru_score(text: str) -> float:
    """Доля частых русских строчных букв среди всех букв: верная кодировка даёт связный текст, неверная — мусор."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c in _COMMON_RU) / len(letters) + sum(1 for c in letters if "\u0400" <= c <= "\u04ff") / len(letters)


def sniff_encoding(raw: bytes) -> str:
    """Единственная точка определения кодировки: и чтение, и обратная запись берут её отсюда."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return "utf-32"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    head = raw[:4096 // 4 * 4]
    if b"\x00" in head:
        # Текст в UTF-16/32 без метки: нули стоят на одних и тех же местах. Подходит только кодировка, в которой всё читается.
        zero = [head[i::4].count(0) for i in range(4)]
        n = len(head) // 4 * .6
        if len(head) >= 8 and zero[2] > n and zero[3] > n:
            guess = ["utf-32-le"]
        elif len(head) >= 8 and zero[0] > n and zero[1] > n:
            guess = ["utf-32-be"]
        else:
            guess = ["utf-16-be" if head[0::2].count(0) > head[1::2].count(0) else "utf-16-le"]
        for encoding in guess:
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if text and sum(1 for c in text[:2000] if c.isprintable() or c in "\r\n\t") >= .95 * len(text[:2000]):
                return encoding
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    best, best_score = "cp1251", -1.0
    for encoding in ("cp1251", "koi8-r", "cp866"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        score = _ru_score(text)
        if score > best_score + 1e-9:
            best, best_score = encoding, score
    return best


def decode_text(raw: bytes) -> str:
    return raw.decode(sniff_encoding(raw), errors="replace")


def finding_id(*parts: object) -> str:
    """Стабильный идентификатор находки: одни и те же координаты дают тот же id на любом проходе."""
    payload = "\0".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24].upper()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


_LOG = logging.getLogger("anonymizer")


def authored(exc: BaseException) -> bool:
    """Сообщение написано нами для человека (а не пришло из сторонней библиотеки с фрагментом файла)."""
    kind = type(exc)
    if kind is ValueError:
        return True
    if kind is KeyError:
        return bool(exc.args) and isinstance(exc.args[0], str) and " " in exc.args[0]
    return kind.__module__.startswith("anonymizer.")


def client_message(exc: BaseException, fallback: str = "Не удалось выполнить операцию. Файл не изменён.") -> str:
    """Текст ошибки для клиента. Чужие сообщения (openpyxl, json, zipfile) могут нести кусок документа: наружу идёт общий
    текст, в локальный журнал только тип и место (без текста сообщения)."""
    if authored(exc):
        return str(exc.args[0]) if type(exc) is KeyError else str(exc)
    tb = exc.__traceback__
    where = ""
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is not None:
        where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}"
    _LOG.warning("operation failed: %s at %s", type(exc).__name__, where)
    return fallback


def peak_memory_mb() -> float:
    """Peak resident/working-set memory in MiB, using the platform's real counter."""
    import sys
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize / 1048576
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1048576 if sys.platform == "darwin" else 1024)
