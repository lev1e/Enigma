"""Выпуск Anonymizer для macOS (Apple Silicon): сборка, подпись, самопроверка, DMG, архив обновления и подписанная лента.

    .venv312/bin/python tools/release_mac.py --base-url https://example.com/anonymizer [--notes "Что нового"] [--skip-build]

Результат в dist/release/:
    Anonymizer-<версия>-arm64.dmg   — для первой раздачи (перетащить в «Программы»)
    Anonymizer-<версия>-arm64.zip   — архив, который скачивает механизм обновления
    latest.json                     — лента обновлений (подписана ключом из ~/.anonymizer-release/update-signing.pem)

Выложить нужно все три файла в base-url; лента должна лежать по постоянному адресу <base-url>/latest.json.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = Path.home() / ".anonymizer-release" / "update-signing.pem"
sys.path.insert(0, str(ROOT))

README_TXT = """Как установить Anonymizer

1. Перетащите Anonymizer в папку «Программы» (рядом в этом окне) и запускайте оттуда.
2. Программа подписана без сертификата Apple Developer, поэтому при первом запуске macOS может написать,
   что не может проверить разработчика. Это ожидаемо:
   - macOS 14 и старше: нажмите правой кнопкой на Anonymizer, «Открыть», затем «Открыть» в окне;
   - macOS 15 и новее: попробуйте открыть программу, затем «Системные настройки», «Конфиденциальность и безопасность»,
     внизу «Всё равно открыть».
   Если программу скачали из интернета и macOS пишет «повреждено», выполните в Терминале:
       xattr -dr com.apple.quarantine /Applications/Anonymizer.app
3. Дальше программа обновляется сама: в «Настройках» (раздел «О программе») есть кнопка «Проверить».
   Подтверждать запуск повторно после обновления не нужно.

Требуется Mac на чипе Apple (M1 и новее), macOS 12 или новее.
Обезличивание выполняется локально. Если вы настроили ИИ-провайдера, выбранные данные
отправляются ему согласно настройкам; программа также проверяет обновления через GitHub.
"""


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def version() -> str:
    return re.search(r'__version__ = "([^"]+)"', (ROOT / "anonymizer" / "__init__.py").read_text("utf-8")).group(1)


def build(app: Path) -> None:
    # Refuse an incomplete release before replacing the previous artifacts. The
    # older dedicated build venv predates the NER dependency and silently omitted it.
    from anonymizer import ner
    if not ner.available():
        raise SystemExit("Сборка остановлена: NER (natasha) недоступен в окружении сборки.")
    if not (ROOT / "anonymizer" / "addin_web" / "vendor" / "office.js").is_file():
        raise SystemExit("Сборка остановлена: отсутствует локальный Office.js.")
    for helper in ("vision_ocr", "vision_barcode"):
        run(["swiftc", "-O", ROOT / "anonymizer" / "ocr_helpers" / f"{helper}.swift", "-o", ROOT / "anonymizer" / "ocr_helpers" / helper])
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "Anonymizer.spec"], cwd=ROOT)
    # Ad hoc подпись всего пакета, без hardened runtime: с ним системная библиотека Python другой команды не загрузится.
    run(["codesign", "--force", "--deep", "--sign", "-", app])
    run(["codesign", "--verify", "--deep", "--strict", app])


def selfcheck(app: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "selfcheck.json"
        done = subprocess.run([app / "Contents" / "MacOS" / "Anonymizer", "--selfcheck", report])
        print(report.read_text("utf-8") if report.exists() else "(отчёта нет)")
        if done.returncode != 0:
            raise SystemExit("Самопроверка собранной программы не пройдена.")


def make_dmg(app: Path, target: Path, name: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        run(["ditto", app, stage / "Anonymizer.app"])
        (stage / "Applications").symlink_to("/Applications")
        (stage / "Как установить.txt").write_text(README_TXT, "utf-8")
        run(["hdiutil", "create", "-volname", name, "-srcfolder", stage, "-ov", "-format", "UDZO", target], stdout=subprocess.DEVNULL)


def sign_feed(ver: str, sha: str) -> str:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from anonymizer.updater import PUBLIC_KEY_B64, signed_text, verify_signature
    key = load_pem_private_key(KEY_PATH.read_bytes(), None)
    signature = base64.b64encode(key.sign(signed_text(ver, sha))).decode()
    verify_signature(ver, sha, signature, PUBLIC_KEY_B64)         # ключ в программе и ключ выпуска обязаны совпадать
    return signature


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Папка на сервере, куда будут выложены файлы (без / в конце)")
    parser.add_argument("--notes", default="")
    parser.add_argument("--skip-build", action="store_true", help="Использовать уже собранный dist/Anonymizer.app")
    opts = parser.parse_args()
    if not opts.base_url.startswith("https://") and not opts.base_url.startswith("http://127.0.0.1"):
        raise SystemExit("base-url должен начинаться с https://")
    ver = version()
    app = ROOT / "dist" / "Anonymizer.app"
    if not opts.skip_build:
        build(app)
    selfcheck(app)
    out = ROOT / "dist" / "release"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    zip_name, dmg_name = f"Anonymizer-{ver}-arm64.zip", f"Anonymizer-{ver}-arm64.dmg"
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, out / zip_name])
    make_dmg(app, out / dmg_name, "Anonymizer")
    sha = hashlib.sha256((out / zip_name).read_bytes()).hexdigest()
    feed = {"version": ver, "url": f"{opts.base_url}/{zip_name}", "sha256": sha, "signature": sign_feed(ver, sha), "notes": opts.notes}
    (out / "latest.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nГотово: {out}\n  {dmg_name}  {(out / dmg_name).stat().st_size // 1024 // 1024} МБ\n  {zip_name}  "
          f"{(out / zip_name).stat().st_size // 1024 // 1024} МБ\n  latest.json -> {opts.base_url}/latest.json")


if __name__ == "__main__":
    main()
