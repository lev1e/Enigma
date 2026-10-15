"""Обновление собранной программы для macOS.

Лента `latest.json` лежит по постоянному адресу и описывает последнюю версию:
    {"version": "2.3.0", "url": "https://.../Anonymizer-2.3.0-arm64.zip", "sha256": "...", "signature": "<base64>", "notes": "..."}
Подпись Ed25519 ставится на строку «версия\\nsha256» закрытым ключом сборщика (tools/release_mac.py); открытый ключ зашит ниже.
Поэтому подменённая лента или архив не устанавливаются, даже если адрес хранения скомпрометирован.

Установка: архив скачивается в папку данных программы (без карантина Gatekeeper, поэтому обновлённая программа запускается без
предупреждений), проверяется хеш, подпись, идентификатор и подпись кода пакета; затем отдельный скрипт после выхода программы
подменяет `Anonymizer.app` на месте и запускает новую версию. Старая версия остаётся рядом как `.previous` до следующего запуска.
Хранилище и ключи лежат в `~/Library/Application Support` и обновлением не затрагиваются.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, crypto

# Постоянный адрес ленты. Переопределяется переменной ANONYMIZER_UPDATE_URL (для проверки и для закрытых раздач).
DEFAULT_FEED_URL = "https://github.com/lev1e/Anonymizer/releases/latest/download/latest.json"
PUBLIC_KEY_B64 = "c4LAWde/wStziM2eEY61llwptIZHdeGuyhUKhMqLvsg="
BUNDLE_ID = "dev.enigma.anonymizer"
CHECK_INTERVAL = 12 * 3600
MAX_FEED_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


class UpdateError(ValueError):
    pass


def feed_url() -> str:
    return os.environ.get("ANONYMIZER_UPDATE_URL") or DEFAULT_FEED_URL


def parse_version(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(text).split("+")[0].split("-")[0])
    if not parts:
        raise UpdateError("Не удалось прочитать номер версии.")
    return tuple(int(p) for p in parts)


def app_bundle() -> Path | None:
    """Путь к Anonymizer.app, из которого запущена программа; None — запуск из исходников."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable).resolve()
    for parent in path.parents:
        if parent.suffix == ".app":
            return parent
    return None


def install_blocker(bundle: Path | None = None) -> str:
    """Почему самообновление невозможно в этом запуске (пустая строка — можно)."""
    bundle = bundle or app_bundle()
    if bundle is None:
        return "Обновление работает в собранной программе для macOS."
    text = str(bundle)
    if "AppTranslocation" in text or text.startswith("/Volumes/"):
        return "Перетащите Anonymizer в папку «Программы» и запустите оттуда: из образа диска или Загрузок обновиться нельзя."
    if not os.access(bundle.parent, os.W_OK):
        return f"Нет права записи в «{bundle.parent}». Переместите программу в «Программы» или в папку «Программы» в домашней папке."
    return ""


# -- лента и подпись ------------------------------------------------------------------------

def signed_text(version: str, sha256: str) -> bytes:
    return f"{version}\n{sha256.lower()}".encode("ascii")


def verify_signature(version: str, sha256: str, signature_b64: str, public_key_b64: str | None = None) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64 or PUBLIC_KEY_B64))
        key.verify(base64.b64decode(signature_b64), signed_text(version, sha256))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise UpdateError("Подпись обновления не подтверждена: оно не будет установлено.") from exc


def _allowed_url(url: str) -> bool:
    parts = urlparse(url)
    if parts.scheme == "https":
        return bool(parts.netloc)
    return parts.scheme in ("http", "file") and (parts.scheme == "file" or parts.hostname in ("127.0.0.1", "localhost"))


def _open(url: str, timeout: float):
    if not _allowed_url(url):
        raise UpdateError("Адрес обновления должен начинаться с https://.")
    request = urllib.request.Request(url, headers={"User-Agent": f"Anonymizer/{__version__}", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_feed(url: str | None = None) -> dict:
    url = url or feed_url()
    if not url:
        raise UpdateError("Адрес обновлений не настроен.")
    try:
        with _open(url, 15) as response:
            raw = response.read(MAX_FEED_BYTES + 1)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError("Не удалось связаться с сервером обновлений. Проверьте подключение к интернету.") from exc
    if len(raw) > MAX_FEED_BYTES:
        raise UpdateError("Лента обновлений повреждена.")
    try:
        feed = json.loads(raw.decode("utf-8"))
        for field in ("version", "url", "sha256", "signature"):
            if not isinstance(feed.get(field), str) or not feed[field]:
                raise ValueError(field)
        parse_version(feed["version"])
    except (ValueError, UnicodeDecodeError, AttributeError, UpdateError) as exc:
        raise UpdateError("Лента обновлений повреждена.") from exc
    verify_signature(feed["version"], feed["sha256"], feed["signature"])      # подпись проверяется до любых действий с лентой
    return feed


def check(url: str | None = None, current: str = __version__) -> dict:
    """Читает ленту. Возвращает {"available": bool, "version", "notes", "current"}; ошибки сети и подписи — UpdateError."""
    feed = fetch_feed(url)
    newer = parse_version(feed["version"]) > parse_version(current)
    return {"available": newer, "version": feed["version"], "notes": str(feed.get("notes", ""))[:2000], "current": current,
            "feed": feed if newer else None}


def public_info(info: dict | None) -> dict:
    if not info:
        return {}
    return {k: v for k, v in info.items() if k != "feed"}


# -- скачивание и подготовка ----------------------------------------------------------------

def updates_dir() -> Path:
    path = crypto.app_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(args: list[str], timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def download(feed: dict, progress=None) -> Path:
    """Скачивает архив, сверяет хеш и подпись, распаковывает; возвращает путь к проверенному Anonymizer.app."""
    verify_signature(feed["version"], feed["sha256"], feed["signature"])
    work = updates_dir() / f"{feed['version']}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    archive = work / "update.zip"
    digest = hashlib.sha256()
    try:
        with _open(feed["url"], 30) as response, archive.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_ARCHIVE_BYTES:
                    raise UpdateError("Файл обновления слишком большой.")
                digest.update(chunk)
                out.write(chunk)
                if progress and total:
                    progress(done / total)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError("Не удалось скачать обновление. Проверьте подключение к интернету.") from exc
    if digest.hexdigest() != feed["sha256"].lower():
        shutil.rmtree(work, ignore_errors=True)
        raise UpdateError("Скачанный файл не совпал с ожидаемым: обновление отклонено.")
    extracted = work / "extracted"
    done = _run(["/usr/bin/ditto", "-x", "-k", str(archive), str(extracted)])
    if done.returncode != 0:
        raise UpdateError("Не удалось распаковать обновление.")
    apps = [p for p in extracted.iterdir() if p.suffix == ".app"]
    if len(apps) != 1:
        raise UpdateError("Архив обновления устроен неожиданно.")
    new_app = apps[0]
    check_bundle(new_app, feed["version"])
    archive.unlink(missing_ok=True)
    return new_app


def check_bundle(app: Path, version: str) -> None:
    try:
        plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise UpdateError("В обновлении нет описания программы.") from exc
    if plist.get("CFBundleIdentifier") != BUNDLE_ID:
        raise UpdateError("Обновление относится к другой программе.")
    if str(plist.get("CFBundleShortVersionString", "")) != version:
        raise UpdateError("Версия внутри обновления не совпала с объявленной.")
    done = _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
    if done.returncode != 0:
        raise UpdateError("Подпись кода внутри обновления повреждена.")
    if not (app / "Contents" / "MacOS" / "Anonymizer").is_file():
        raise UpdateError("В обновлении нет исполняемого файла.")


SWAP_SCRIPT = r"""#!/bin/sh
# Подмена приложения после выхода программы. Аргументы: pid нового процесса ожидания, старый .app, новый .app, режим запуска.
OLD_PID="$1"; TARGET="$2"; NEW="$3"; MODE="$4"; LOG="$5"
exec >>"$LOG" 2>&1
echo "== $(date) swap $TARGET <- $NEW"
i=0
while kill -0 "$OLD_PID" 2>/dev/null && [ $i -lt 120 ]; do sleep 0.5; i=$((i+1)); done
# Окно и помощники того же пакета тоже должны выйти до подмены.
pkill -TERM -f "$TARGET/Contents/MacOS" 2>/dev/null
i=0
while pgrep -f "$TARGET/Contents/MacOS" >/dev/null 2>&1 && [ $i -lt 20 ]; do sleep 0.5; i=$((i+1)); done
pkill -KILL -f "$TARGET/Contents/MacOS" 2>/dev/null
PREV="$TARGET.previous"
rm -rf "$PREV"
if ! mv "$TARGET" "$PREV"; then echo "cannot move old app"; open "$TARGET"; exit 1; fi
if ! /usr/bin/ditto "$NEW" "$TARGET"; then
  echo "copy failed, rolling back"; rm -rf "$TARGET"; mv "$PREV" "$TARGET"; open "$TARGET"; exit 1
fi
/usr/bin/xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
if ! /usr/bin/codesign --verify --deep --strict "$TARGET"; then
  echo "verify failed, rolling back"; rm -rf "$TARGET"; mv "$PREV" "$TARGET"; open "$TARGET"; exit 1
fi
rm -rf "$(dirname "$(dirname "$NEW")")"
if [ "$MODE" = "background" ]; then
  nohup "$TARGET/Contents/MacOS/Anonymizer" --background >/dev/null 2>&1 &
else
  open "$TARGET"
fi
sleep 20
rm -rf "$PREV"
echo "done"
"""


def spawn_swap(new_app: Path, background: bool, wait_pid: int | None = None) -> None:
    """Запускает отдельный скрипт, который после выхода программы подменяет пакет и запускает новую версию."""
    bundle = app_bundle()
    blocker = install_blocker(bundle)
    if blocker or bundle is None:
        raise UpdateError(blocker or "Обновление невозможно.")
    script = updates_dir() / "swap.sh"
    script.write_text(SWAP_SCRIPT, "utf-8")
    script.chmod(0o700)
    log = updates_dir() / "update.log"
    subprocess.Popen(["/bin/sh", str(script), str(wait_pid or os.getpid()), str(bundle), str(new_app),
                      "background" if background else "window", str(log)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


# -- состояние для окна ---------------------------------------------------------------------

class UpdateState:
    """Хранит результат последней проверки и ход установки; безопасен для вызова из потоков сервера."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.info: dict | None = None        # результат check()
        self.error = ""
        self.phase = "idle"                  # idle | checking | downloading | ready | error
        self.progress = 0.0
        self.checked_at = 0.0
        self._stamp = crypto.app_data_dir() / "update-check.json"

    def public(self) -> dict:
        with self.lock:
            return {"phase": self.phase, "progress": round(self.progress, 3), "error": self.error, "checked_at": self.checked_at,
                    "info": public_info(self.info), "blocker": install_blocker(), "configured": bool(feed_url()), "current": __version__}

    def due(self) -> bool:
        try:
            last = json.loads(self._stamp.read_text("utf-8")).get("time", 0)
        except (OSError, ValueError):
            last = 0
        return time.time() - float(last) > CHECK_INTERVAL

    def check(self, force: bool = False) -> None:
        if not feed_url() or (not force and not self.due()):
            return
        with self.lock:
            if self.phase in ("checking", "downloading"):
                return
            self.phase, self.error = "checking", ""
        try:
            info = check()
            with self.lock:
                self.info, self.phase, self.checked_at = info, "idle", time.time()
            try:
                self._stamp.write_text(json.dumps({"time": time.time()}), "utf-8")
            except OSError:
                pass
        except UpdateError as exc:
            with self.lock:
                self.phase, self.error = ("idle" if not force else "error"), (str(exc) if force else "")

    def start_check(self, force: bool = False) -> None:
        threading.Thread(target=self.check, args=(force,), daemon=True).start()

    def install(self, background: bool, on_ready) -> None:
        """Скачивает и проверяет обновление в потоке; когда всё готово, вызывает on_ready(new_app) (подмена и выход)."""
        with self.lock:
            if self.phase in ("checking", "downloading") or not self.info or not self.info.get("available"):
                raise UpdateError("Нет обновления для установки. Сначала проверьте обновления.")
            blocker = install_blocker()
            if blocker:
                raise UpdateError(blocker)
            feed = self.info["feed"]
            self.phase, self.progress, self.error = "downloading", 0.0, ""

        def work() -> None:
            try:
                new_app = download(feed, self._progress)
                with self.lock:
                    self.phase = "ready"
                on_ready(new_app)
            except UpdateError as exc:
                with self.lock:
                    self.phase, self.error = "error", str(exc)
            except Exception as exc:
                with self.lock:
                    self.phase, self.error = "error", f"Не удалось установить обновление ({type(exc).__name__})."
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, value: float) -> None:
        with self.lock:
            self.progress = value
