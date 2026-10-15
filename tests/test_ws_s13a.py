"""S13A: classic chat look (pill composer, file context chips and menu, quiet actions, panel file switcher) and per-message file choice."""
import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from anonymizer import keystore
from anonymizer.webapp import create_server

from .helpers import Env
from .llm_fake import TEST_KEY, FakeProvider
from .test_ws_llm_keystore import MemoryBackend

WEB = Path(__file__).resolve().parents[1] / "anonymizer" / "web"
JS = (WEB / "ai-chat.js").read_text(encoding="utf-8")
HTML = (WEB / "index.html").read_text(encoding="utf-8")
TEXTS = {"a.txt": "первая строка про aaauniq.\n", "b.txt": "вторая строка про bbbuniq.\n", "c.txt": "третья строка про ccculiq.\n".replace("ccculiq", "cccuniq")}


class Page(unittest.TestCase):
    def test_pill_composer_controls(self):
        for need in ('"aic-pill"', '"aic-plus"', '"aic-send"', 'aria-haspopup", "menu"', "aria-expanded", "С какими файлами работаем",
                     "menuitemcheckbox", "Файлы для следующего сообщения", "file_ids"):
            self.assertIn(need, JS)
        self.assertNotIn("Очистить беседу\"); bClear", JS)

    def test_one_main_visible_button_row(self):
        # no text buttons next to the textarea any more: attach, show request, clear and AI toggle live in the "+" menu
        for old in ('el("button", "btn", "Прикрепить файл")', 'el("button", "btn", "Показать запрос")', 'el("button", "btn", "Очистить беседу")'):
            self.assertNotIn(old, JS)
        for menu_item in ('"Прикрепить файл"', '"Показать запрос, который уйдёт провайдеру"', '"Очистить беседу"', '"ИИ включён для этого чата"'):
            self.assertIn(menu_item, JS)

    def test_send_turns_into_stop_and_keys(self):
        self.assertIn("i-stop", JS)
        self.assertIn('"Остановить" : "Отправить"', JS)
        self.assertRegex(JS, r'e\.key === "Enter" && !e\.shiftKey && !e\.isComposing')

    def test_column_and_empty_state(self):
        self.assertIn("max-width: 740px", JS)
        self.assertEqual(len(re.findall(r'"Перескажи файл в пяти пунктах"|"Найди в тексте опечатки и неточности"|"Поправь пункт 3: срок оплаты 30 дней"', JS)), 3)

    def test_actions_are_real(self):
        self.assertIn("navigator.clipboard.writeText", JS)
        self.assertIn("Сохранить ответ с возвратом значений", JS)

    def test_reduced_motion_and_transform_opacity_only(self):
        self.assertIn("prefers-reduced-motion: reduce", JS)
        self.assertRegex(JS, r"prefers-reduced-motion: reduce\) \{[^}]*animation: none; transition: none")
        css = JS[JS.index("const CSS"):JS.index("const ICON")]
        for bad in ("transition: width", "transition: height", "transition: margin", "transition: all", "bounce", "cubic-bezier(.34"):
            self.assertNotIn(bad, css)

    def test_no_external_urls_no_innerhtml_no_gradient_text(self):
        self.assertNotRegex(JS, r"https?://")
        self.assertNotRegex(JS, r"innerHTML\s*=")
        self.assertNotIn("background-clip", JS)
        self.assertNotRegex(JS, r"border-(left|right): [2-9]px")
        self.assertNotRegex(JS, "[\U0001F300-\U0001FAFF☀-➿]")

    def test_host_wires_files_and_panel_switcher(self):
        self.assertIn("getFiles:", HTML)
        self.assertIn("openFile:", HTML)
        self.assertIn("aiInline.refreshFiles()", HTML)
        tag = re.search(r'<select class="pv-switch" id="pv-switch"[^>]*>', HTML).group(0)
        self.assertIn('aria-label="Файл чата"', tag)
        self.assertIn('o.textContent =', HTML)       # option labels via textContent only


class Selection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app.keystore = keystore.Keystore(Path(cls.tmp.name), cls.env.vault._key, MemoryBackend())
        cls.fake = FakeProvider(chunks=["ok"]); cls.fake.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fake.__exit__(None, None, None)
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup(); cls.env.close()

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        head = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie, "X-Requested-With": "anonymizer", "Content-Type": "application/json"}
        conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, head)
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, (json.loads(data) if data else None)

    def chat(self):
        self.call("POST", "/api/ai/providers/loc", {"kind": "custom", "base_url": self.fake.url, "model": "m-one"})
        self.call("POST", "/api/ai/providers/loc/key", {"key": TEST_KEY})
        self.call("POST", "/api/ai/enabled", {"enabled": True})
        _, chat = self.call("POST", "/api/chats", {"title": "s13a"})
        ids = {}
        for name, text in TEXTS.items():
            rec = self.app.chats.add_file(chat["id"], name, "text", anon=text.encode(), names={"anon": name})
            ids[name] = rec["id"]
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        return chat["id"], ids

    def ask(self, chat, **extra):
        self.fake.requests.clear()
        status, res = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "перескажи", "with_files": True, **extra})
        if status == 200 and not res.get("blocked"):
            for _ in range(200):
                _, info = self.call("GET", f"/api/ai/runs/{res['run']}")
                if info["done"]:
                    break
                time.sleep(0.05)
        return status, res, "".join(json.dumps(r["body"], ensure_ascii=False) for r in self.fake.requests)

    def test_only_ticked_files_are_sent(self):
        chat, ids = self.chat()
        _, res, out = self.ask(chat, file_ids=[ids["b.txt"]])
        self.assertFalse(res["blocked"], res)
        self.assertIn("bbbuniq", out)
        self.assertNotIn("aaauniq", out)
        self.assertNotIn("cccuniq", out)

    def test_empty_list_means_no_files_and_missing_key_means_default(self):
        chat, ids = self.chat()
        _, _, out = self.ask(chat, file_ids=[])
        self.assertNotIn("uniq", out)
        _, _, out = self.ask(chat)                       # old clients: all current files
        self.assertIn("aaauniq", out)
        self.assertIn("bbbuniq", out)

    def test_unknown_and_foreign_ids_are_ignored_and_bad_type_refused(self):
        chat, ids = self.chat()
        _, other = self.call("POST", "/api/chats", {"title": "other"})
        foreign = self.app.chats.add_file(other["id"], "z.txt", "text", anon=b"zeta zzzuniq\n", names={"anon": "z.txt"})["id"]
        _, _, out = self.ask(chat, file_ids=[foreign, "nope", ids["c.txt"]])
        self.assertIn("cccuniq", out)
        self.assertNotIn("zzzuniq", out)
        self.assertNotIn("aaauniq", out)
        status, res, _ = self.ask(chat, file_ids="all")
        self.assertNotEqual(status, 200)
        self.fake.requests.clear()


if __name__ == "__main__":
    unittest.main()


class QuietRows(unittest.TestCase):
    """S13B: file rows in the history are quiet (no filled accent button per row), fit at 390 px, short placeholder on phones."""

    def test_row_buttons_are_ghost_and_nowrap(self):
        self.assertNotIn('r === "anon" ? " main"', HTML)
        self.assertRegex(HTML, r"\.step-files \.ver-btns \.btn\.sm \{[^}]*background: transparent[^}]*white-space: nowrap")
        self.assertRegex(HTML, r"@media \(max-width: 640px\) \{ \.step-files \.ver-btns \{ gap: 0;")
        self.assertRegex(HTML, r"\.ver-btns \{ display: flex; flex-wrap: wrap;")

    def test_short_placeholder_on_phone(self):
        self.assertIn('(max-width: 480px)', JS)
        self.assertIn('"Спросить ИИ"', JS)
        self.assertIn('"Спросить ИИ про эти файлы"', JS)

    def test_save_button_keeps_label_and_name(self):
        self.assertIn('data-savefile', HTML)
        self.assertIn('Сохранить как…', HTML)
