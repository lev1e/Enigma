"""W9B: установка add-in пользователем: блок в Настройках, подсказка, задача установщика."""
import http.client
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from anonymizer import addin_install
from anonymizer.webapp import create_server

from .helpers import Env

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "anonymizer" / "web" / "index.html").read_text("utf-8")
ISS = (ROOT / "packaging" / "Anonymizer.iss").read_text("utf-8")


class SettingsBlockMarkup(unittest.TestCase):
    def test_block_title_and_buttons(self):
        self.assertIn("Надстройка Word, Excel, PowerPoint", HTML)
        self.assertIn(">Установить надстройку<", HTML)
        self.assertIn(">Удалить надстройку<", HTML)
        self.assertEqual(HTML.count('id="btn-addin-install"'), 1)

    def test_status_is_live_region_and_targets_44px(self):
        self.assertRegex(HTML, r'id="addin-status"[^>]*aria-live="polite"')
        self.assertRegex(HTML, r'id="addin-result"[^>]*aria-live="polite"')
        self.assertIn(".btn.tap { min-height: 44px; }", HTML)
        self.assertRegex(HTML, r'class="btn main tap" id="btn-addin-install"')

    def test_status_wording_and_certificate_note(self):
        for text in ("Подключена", "Не подключена", "Ошибка:", "сертификат", "Перезапустите"):
            self.assertIn(text, HTML)

    def test_hint_is_dismissible(self):
        self.assertIn('id="addin-hint"', HTML)
        self.assertIn("addin_hint_dismissed: true", HTML)
        self.assertRegex(HTML, r'id="addin-hint-close"[^>]*aria-label=')

    def test_no_emoji_in_block(self):
        block = HTML[HTML.index('id="addin-block"'):HTML.index('id="btn-quit"')]
        self.assertIsNone(re.search("[\U0001F300-\U0001FAFF☀-➿]", block))


class InstallerTask(unittest.TestCase):
    def test_addin_run_line_requires_task(self):
        lines = [l for l in ISS.splitlines() if "--install-addin" in l and not l.lstrip().startswith(";")]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"Tasks:\s*addin\b")

    def test_task_declared_and_checked_by_default(self):
        task = next(l for l in ISS.splitlines() if l.startswith('Name: "addin"'))
        self.assertNotIn("unchecked", task)
        self.assertIn("Подключить к Word, Excel и PowerPoint", task)

    def test_uninstall_removes_addin(self):
        self.assertIn("--uninstall-addin", ISS)


class Endpoints(unittest.TestCase):
    """Реестр и Keychain не затрагиваются: install/uninstall/is_installed/status подменены."""

    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.env.close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        head = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie, **(headers or {})}
        conn.request(method, path, body=body, headers=head)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def post_json(self, path, payload):
        return self.request("POST", path, json.dumps(payload).encode(),
                            {"Content-Type": "application/json", "X-Requested-With": "anonymizer"})

    def test_state_hint_logic(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(addin_install, "is_installed", return_value=False):
            self.assertTrue(self.app.addin_hint())
            _, body = self.request("GET", "/api/state")
            self.assertTrue(json.loads(body)["addin_hint"])
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(addin_install, "is_installed", return_value=True):
            self.assertFalse(self.app.addin_hint())
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(self.app.addin_hint())

    def test_dismiss_is_remembered(self):
        try:
            status, _ = self.post_json("/api/prefs", {"addin_hint_dismissed": True})
            self.assertEqual(status, 200)
            with mock.patch.object(sys, "platform", "win32"), mock.patch.object(addin_install, "is_installed", return_value=False):
                self.assertFalse(self.app.addin_hint())
        finally:
            self.app.vault.set_prefs(addin_hint_dismissed=False)

    def test_install_endpoint_returns_steps(self):
        steps = [{"name": "register", "ok": True, "message": "Add-in зарегистрирован. Перезапустите Office."}]
        with mock.patch.object(addin_install, "install", return_value=steps) as fake, \
                mock.patch.object(addin_install, "is_installed", return_value=True):
            status, body = self.post_json("/api/addin/install", {})
        self.assertEqual(status, 200, body)
        fake.assert_called_once()
        self.assertEqual(json.loads(body)["steps"], steps)

    def test_uninstall_endpoint_does_not_install(self):
        steps = [{"name": "register", "ok": True, "message": "Add-in удалён из Office."}]
        with mock.patch.object(addin_install, "uninstall", return_value=steps) as fake, \
                mock.patch.object(addin_install, "install") as inst, \
                mock.patch.object(addin_install, "is_installed", return_value=False):
            status, body = self.post_json("/api/addin/uninstall", {})
        self.assertEqual(status, 200, body)
        fake.assert_called_once()
        inst.assert_not_called()

    def test_status_endpoint(self):
        fake = {"installed": False, "trusted": False, "port": 47831, "autostart": False, "supported": True}
        with mock.patch.object(addin_install, "status", return_value=fake):
            status, body = self.request("GET", "/api/addin/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["installed"])
        self.assertIn("server_error", data)


if __name__ == "__main__":
    unittest.main()
