"""Provider settings and API keys for the AI chat (W12, slice 2). No new dependencies.

Where a key lives (best available first):
  keychain  macOS Keychain, through the system `security` tool (the key goes over stdin, never argv)
  dpapi     Windows: encrypted with DPAPI for this Windows account, stored as a blob in the profile folder.
            (Windows Credential Manager through ctypes is not implemented; DPAPI gives the same account binding.)
            UNVERIFIED on a real Windows machine.
  file      fallback: encrypted with the vault key inside the profile folder. WEAKER: anyone who can read both the
            profile folder and the device key can read the key. The UI marks it as weaker.

The page only ever gets masked metadata (`public()`): kind, endpoint, model, "saved", last 4 characters, backend.
The key is returned only by `secret()` to backend code that sends the request. Keys are never logged, never put in
URLs and never included in exported backups (this module is not part of the vault backup).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from . import crypto, llm
from .util import atomic_write

FILE_NAME = "ai_providers.bin"
SERVICE = "Anonymizer-AI"
ID_RE = re.compile(r"[a-z0-9_-]{1,40}")
MODEL_RE = re.compile(r"[\w.:/+@-]{1,120}")
SAFE_KEY = re.compile(r"[\x21-\x7e]{8,512}")          # printable ASCII, no spaces
WEAK_BACKENDS = ("file",)


class Backend:
    name = "file"

    def put(self, pid: str, secret: str) -> bool:
        raise NotImplementedError

    def get(self, pid: str) -> str | None:
        raise NotImplementedError

    def delete(self, pid: str) -> None:
        raise NotImplementedError


class MacKeychain(Backend):
    name = "keychain"

    def __init__(self, run=None):
        self._run = run or self._exec

    @staticmethod
    def _exec(args: list[str], stdin: str | None = None) -> tuple[int, str]:
        proc = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=15)
        return proc.returncode, proc.stdout

    @staticmethod
    def available() -> bool:
        return sys.platform == "darwin" and os.path.exists("/usr/bin/security")

    def put(self, pid: str, secret: str) -> bool:
        if not SAFE_KEY.fullmatch(secret) or any(c in secret for c in "'\"\\"):
            return False                                   # cannot quote safely: fall back
        code, _ = self._run(["/usr/bin/security", "-i"],
                            f"add-generic-password -U -s {SERVICE} -a {pid} -w '{secret}'\n")
        return code == 0

    def get(self, pid: str) -> str | None:
        code, out = self._run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", pid, "-w"])
        return out.rstrip("\n") if code == 0 and out.strip() else None

    def delete(self, pid: str) -> None:
        self._run(["/usr/bin/security", "delete-generic-password", "-s", SERVICE, "-a", pid])


class WindowsDpapi(Backend):
    name = "dpapi"

    def __init__(self, directory: Path):
        self.dir = directory

    @staticmethod
    def available() -> bool:
        return os.name == "nt"

    def _path(self, pid: str) -> Path:
        return self.dir / f"ai_{pid}.dpapi"

    def put(self, pid: str, secret: str) -> bool:
        try:
            atomic_write(self._path(pid), crypto._dpapi(secret.encode("utf-8"), protect=True))
            return True
        except Exception:
            return False

    def get(self, pid: str) -> str | None:
        try:
            return crypto._dpapi(self._path(pid).read_bytes(), protect=False).decode("utf-8")
        except Exception:
            return None

    def delete(self, pid: str) -> None:
        self._path(pid).unlink(missing_ok=True)


def default_backend(directory: Path) -> Backend | None:
    if MacKeychain.available():
        return MacKeychain()
    if WindowsDpapi.available():
        return WindowsDpapi(directory)
    return None


class Keystore:
    def __init__(self, directory: Path, key: bytes | None = None, backend: Backend | None | str = "auto"):
        self.dir = directory
        self._key = key
        self._lock = threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.backend = default_backend(directory) if backend == "auto" else backend

    # -- storage ---------------------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            data = json.loads(crypto.decrypt_blob((self.dir / FILE_NAME).read_bytes(), self._key))
        except (OSError, ValueError, crypto.KeyErrorSafe):
            data = {}
        data.setdefault("providers", {})
        data.setdefault("secrets", {})                  # only for the weaker file fallback
        data.setdefault("settings", {"enabled": False})
        return data

    def _save(self, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        atomic_write(self.dir / FILE_NAME, crypto.encrypt_blob(raw, self._key))

    @staticmethod
    def _check_id(pid: str) -> str:
        if not ID_RE.fullmatch(pid or ""):
            raise ValueError("Invalid provider id")
        return pid

    # -- provider configuration (no secrets) -------------------------------------------------------

    @staticmethod
    def _clean_models(models) -> list[str]:
        out = []
        for m in models if isinstance(models, list) else []:
            m = str(m).strip()
            if MODEL_RE.fullmatch(m) and m not in out:
                out.append(m)
        return out[:60]

    def configure(self, pid: str, kind: str, base_url: str = "", model: str = "", max_tokens: int | None = None,
                  models=None, internal=None, name=None) -> dict:
        self._check_id(pid)
        if kind not in llm.KINDS:
            raise ValueError("Unknown provider type")
        probe = llm.Provider(kind, base_url.strip(), "x", model)
        parts = probe.base
        if not parts:
            raise ValueError("An endpoint address is required for a custom provider")
        try:
            llm.validate(llm.Provider(kind, base_url.strip(), "placeholder-key", model))
        except llm.LLMError as exc:
            raise ValueError(exc.message) from None
        with self._lock:
            data = self._load()
            entry = data["providers"].setdefault(pid, {})
            entry.update({"kind": kind, "base_url": base_url.strip(), "model": model.strip()})
            if max_tokens:
                entry["max_tokens"] = max(1, min(int(max_tokens), 200000))
            if models is not None:                    # P1: model list shown in the composer picker
                entry["models"] = self._clean_models(models)
            if internal is not None:                  # P1: a label ("внутренняя"/"внешняя"), not a security setting
                entry["internal"] = bool(internal)
            if name is not None:
                entry["name"] = str(name).strip()[:60]
            self._save(data)
        return self.public(pid)

    # -- keys -------------------------------------------------------------------------------------

    def set_secret(self, pid: str, secret: str) -> dict:
        self._check_id(pid)
        secret = (secret or "").strip()
        if not SAFE_KEY.fullmatch(secret):
            raise ValueError("The key looks wrong (8-512 printable characters, no spaces)")
        with self._lock:
            data = self._load()
            if pid not in data["providers"]:
                raise KeyError("Configure the provider first")
            where = "file"
            data["secrets"].pop(pid, None)
            if self.backend and self.backend.put(pid, secret):
                where = self.backend.name
            else:
                data["secrets"][pid] = secret
            data["providers"][pid].update({"backend": where, "last4": secret[-4:]})
            self._save(data)
        return self.public(pid)

    def secret(self, pid: str) -> str | None:
        """For backend code only. Never pass the result to the page, logs or exceptions."""
        with self._lock:
            data = self._load()
            entry = data["providers"].get(pid)
            if not entry:
                return None
            if entry.get("backend") == "file":
                return data["secrets"].get(pid)
            return self.backend.get(pid) if self.backend and entry.get("backend") == self.backend.name else None

    def remove_secret(self, pid: str) -> dict:
        with self._lock:
            data = self._load()
            entry = data["providers"].get(pid)
            if entry:
                if self.backend and entry.get("backend") == self.backend.name:
                    self.backend.delete(pid)
                data["secrets"].pop(pid, None)
                entry.pop("backend", None)
                entry.pop("last4", None)
                self._save(data)
        return self.public(pid)

    def delete(self, pid: str) -> None:
        with self._lock:
            self.remove_secret(pid)
            data = self._load()
            data["providers"].pop(pid, None)
            self._save(data)

    def clear(self) -> None:
        """Vault clear: keys go too (the encrypted file would be unreadable with a new device key anyway)."""
        with self._lock:
            for pid in list(self._load()["providers"]):
                self.remove_secret(pid)
            (self.dir / FILE_NAME).unlink(missing_ok=True)

    # -- views ------------------------------------------------------------------------------------

    def public(self, pid: str) -> dict:
        """Masked metadata for the page. Contains no secret."""
        entry = self._load()["providers"].get(pid)
        if entry is None:
            raise KeyError("No such provider")
        saved = bool(entry.get("backend"))
        from . import policy
        internal = bool(entry.get("internal"))
        tier = policy.tier_of(policy.load(), pid, entry.get("base_url", ""), internal)
        models = list(entry.get("models") or [])
        if entry.get("model") and entry["model"] not in models:
            models.insert(0, entry["model"])
        return {"id": pid, "name": entry.get("name") or pid, "models": models, "internal": internal, "tier": tier,
                "badge": "внутренняя" if tier == "internal" else "внешняя", "kind": entry["kind"], "base_url": entry.get("base_url", ""), "model": entry.get("model", ""),
                "max_tokens": entry.get("max_tokens"), "saved": saved,
                "masked": ("•" * 8 + entry.get("last4", "")) if saved else "",
                "backend": entry.get("backend", ""), "weak": entry.get("backend") in WEAK_BACKENDS,
                "local": llm.Provider(entry["kind"], entry.get("base_url", "")).is_local}

    def listing(self) -> list[dict]:
        return [self.public(pid) for pid in self._load()["providers"]]

    def provider(self, pid: str) -> llm.Provider:
        entry = self._load()["providers"].get(pid)
        if entry is None:
            raise KeyError("No such provider")
        return llm.Provider(entry["kind"], entry.get("base_url", ""), self.secret(pid) or "", entry.get("model", ""))

    def enabled(self) -> bool:
        return bool(self._load()["settings"].get("enabled"))

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            data = self._load()
            data["settings"]["enabled"] = bool(value)
            self._save(data)
