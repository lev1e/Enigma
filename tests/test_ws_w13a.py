"""W13a: the file-chat view hosts the shared AI chat inline. Structural wiring checks (no browser)."""
import http.client
import re
import threading
import unittest
from pathlib import Path

from anonymizer.webapp import create_server

from .helpers import Env

WEB = Path(__file__).parent.parent / "anonymizer" / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
AI = (WEB / "ai.html").read_text(encoding="utf-8")
JS = (WEB / "ai-chat.js").read_text(encoding="utf-8")


class Wiring(unittest.TestCase):
    def test_index_hosts_inline_chat(self):
        self.assertIn('<script src="/ai-chat.js"></script>', INDEX)
        for i in ('id="aic-list"', 'id="aic-composer"', 'id="stage-chat"'):
            self.assertIn(i, INDEX)
        self.assertIn("AIChat.mount(", INDEX)
        self.assertIn("aiInline.setChat(", INDEX)           # chat id follows the open chat
        self.assertNotIn('id="link-ai"', INDEX)             # S10A: the top-right button is gone, the message line is always at the bottom
        self.assertGreater(INDEX.index('id="aic-composer"'), INDEX.index('id="drop-chat"'))   # message line below the file drop

    def test_ai_page_uses_shared_module(self):
        self.assertIn('<script src="/ai-chat.js"></script>', AI)
        self.assertIn("AIChat.mount(", AI)
        for gone in ("function send()", "EventSource", "function addMsg", "/prepare"):
            self.assertNotIn(gone, AI)                       # no second divergent implementation

    def test_module_paths_and_controls(self):
        for path in ("/api/ai/chats/", "/send", "/prepare", "/attach", "/export", "/api/ai/runs/", "/events", "/stop", "/toggle", "/history"):
            self.assertIn(path, JS)
        for need in ("Остановить", "Отправить", "Прикрепить файл", "Показать запрос", "aria-live", "isComposing", "Сохранить ответ с возвратом значений"):
            self.assertIn(need, JS)
        self.assertNotRegex(JS, r"https?://")                # no new network origins
        self.assertNotRegex(JS, r"innerHTML\s*=")            # text only via textContent
        self.assertNotIn("#000", JS)

    def test_stage_text_is_shown(self):
        self.assertIn("if (s.stage) $(\"#stage-\" + mode).textContent = s.stage;", INDEX)
        self.assertRegex(INDEX, r"#stage-chat \{[^}]*font-size")


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("GET", path, headers={"Cookie": f"anon_t={self.app.token}"} if cookie else {})
        r = c.getresponse()
        return r.status, r.getheader("Content-Security-Policy"), r.read()

    def test_js_route_authorized_only(self):
        self.assertEqual(self.get("/ai-chat.js", cookie=False)[0], 403)
        st, _csp, body = self.get("/ai-chat.js")
        self.assertEqual(st, 200)
        self.assertIn(b"AIChat", body)

    def test_csp_still_self_only(self):
        _st, csp, _b = self.get("/ai")
        self.assertIsNotNone(csp)
        self.assertIn("default-src 'self'", csp)
        self.assertNotRegex(csp, r"https?://")


if __name__ == "__main__":
    unittest.main()
