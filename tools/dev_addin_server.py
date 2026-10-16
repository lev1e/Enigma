"""Панель Office для разработки: обычный HTTP на фиксированном порту, случайный токен сеанса, двойник Office.js.

Открыть URL, напечатанный при запуске: он содержит ключ текущего сеанса и имя документа.
Параметры двойника описаны в tools/fake_office.js. Документ лежит в памяти сервера (переживает перезагрузку страницы),
`&fresh=1` возвращает исходный файл из case/. Только разработка: маршруты /dev/* только для своего Origin и с X-Requested-With, HTTPS и сертификатов нет.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anonymizer import addin  # noqa: E402
from anonymizer.addin import AddinApi, AddinHandler, AddinServer, Originals  # noqa: E402
from anonymizer.vault import Vault  # noqa: E402
from anonymizer.webapp import App  # noqa: E402

FAKE_OFFICE = Path(__file__).resolve().parent / "fake_office.js"
CASE = ROOT / "case"
DOCS: dict[str, dict] = {}          # имя документа -> {"bytes": ..., "meta": ...}


class DevHandler(AddinHandler):
    def _origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def _dev_allowed(self) -> bool:
        return (self._host_ok() and self.headers.get("X-Requested-With") == "anonymizer"
                and (not self.headers.get("Origin") or self.headers.get("Origin") in self._origins()))

    def _name(self) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return Path((query.get("name") or [""])[0]).name

    def _fresh(self) -> bool:
        return bool(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("fresh"))

    def _doc(self, reset: bool = False) -> dict | None:
        name = self._name()
        if reset and self._fresh():
            DOCS.pop(name, None)
        if name not in DOCS:
            source = CASE / name
            if not name or not source.is_file():
                return None
            DOCS[name] = {"bytes": source.read_bytes(), "meta": {}}
        return DOCS[name]

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/dev/") and not self._dev_allowed():
            return self._error(403, "Нет доступа")
        if path == "/addin/vendor/office.js":
            return self._send(200, FAKE_OFFICE.read_bytes(), addin.MIME[".js"])
        if path in ("/dev/doc/bytes", "/dev/doc/meta"):
            # `fresh` сбрасывает документ при чтении байтов (первое обращение страницы); чтение метаданных идёт следом.
            doc = self._doc(reset=path.endswith("bytes"))
            if doc is None:
                return self._error(404, "Нет такого файла в case/")
            if path.endswith("bytes"):
                return self._send(200, doc["bytes"], "application/octet-stream")
            return self._json(doc["meta"])
        return super().do_GET()

    def do_PUT(self) -> None:
        self._cached_body = None
        if not self._dev_allowed():
            self.close_connection = True
            return self._error(403, "Нет доступа")
        path = urllib.parse.urlparse(self.path).path
        doc = self._doc() if path in ("/dev/doc/bytes", "/dev/doc/meta") else None
        if doc is None:
            return self._error(404, "Не найдено")
        body = self._body()
        if path.endswith("bytes"):
            doc["bytes"] = body
        else:
            doc["meta"] = json.loads(body.decode("utf-8") or "{}")
        self._json({"ok": True})

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/dev/structure":
            if not self._dev_allowed():
                self.close_connection = True
                return self._error(403, "Нет доступа")
            self._cached_body = None
            body = self._body()
            try:
                info = addin.structure_of(body, Path(self._name()).suffix)
            except Exception:
                info = {}
            return self._json(info)
        return super().do_POST()


def create(port: int = 8792, home: Path | None = None) -> tuple[AddinServer, AddinApi, App]:
    home = home or Path(os.environ.get("ANONYMIZER_HOME") or tempfile.mkdtemp(prefix="anonymizer-dev-addin-"))
    os.environ["ANONYMIZER_HOME"] = str(home)
    app = App(Vault(home / "vault.bin"), home / "work", secrets.token_urlsafe(24))
    api = AddinApi(app, Originals(home / "originals"), secrets.token_urlsafe(24))
    handler = type("BoundDevHandler", (DevHandler,), {"app": app, "api": api, "port": port})
    server = AddinServer(("127.0.0.1", port), handler)
    handler.port = server.server_address[1]
    return server, api, app


if __name__ == "__main__":
    from anonymizer.addin import pane_key
    server, api, app = create(int(os.environ.get("PORT", "8792")))
    print(f"http://127.0.0.1:{server.server_address[1]}/addin/taskpane.html?k={pane_key(api.token)}&host=Word&doc="
          f"{urllib.parse.quote('Договор.docx')}  (token {api.token})", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    app.stop.wait()
