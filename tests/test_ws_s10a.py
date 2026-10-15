"""S10A: persistent bottom composer, files as label-form context, AI edit as a new file version (fake provider only)."""
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
TEXT = "Договор с Иваном Петровским, email ivan.petrovsky@acme-test.org, телефон +7 495 123-45-67.\nПункт 3. Срок оплаты 10 дней.\n"
SECRETS = ("Петровск", "ivan.petrovsky", "495 123")


class S10A(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app.keystore = keystore.Keystore(Path(cls.tmp.name), cls.env.vault._key, MemoryBackend())
        cls.fake = FakeProvider(chunks=["ok"])
        cls.fake.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fake.__exit__(None, None, None)
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup(); cls.env.close()

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        head = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie, "X-Requested-With": "anonymizer", "Content-Type": "application/json"}
        conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, head)
        resp = conn.getresponse(); data = resp.read(); ctype = resp.getheader("Content-Type", ""); conn.close()
        return resp.status, (json.loads(data) if data and ctype.startswith("application/json") else data)

    def setup_ai(self):
        self.call("POST", "/api/ai/providers/loc", {"kind": "custom", "base_url": self.fake.url, "model": "m-one"})
        self.call("POST", "/api/ai/providers/loc/key", {"key": TEST_KEY})
        self.call("POST", "/api/ai/enabled", {"enabled": True})

    def chat_with_file(self, name="dogovor.txt", text=TEXT):
        _, chat = self.call("POST", "/api/chats", {"title": "s10a"})
        rec = self.app.chats.add_file  # file as the job pipeline stores it: label form
        job = self.app.service.anonymize([__import__("anonymizer.service", fromlist=["Upload"]).Upload(name, text.encode())], {})
        out = Path(job.files[0].out_path).read_bytes()
        record = rec(chat["id"], name, "text", tokens=list(job.files[0].tokens or []), anon=out, names={"anon": name})
        self.app.chats.add_step(chat["id"], "anonymize", files=[record["id"]])
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        return chat["id"], record["id"], out.decode()

    def wait(self, run):
        for _ in range(300):
            _, info = self.call("GET", f"/api/ai/runs/{run}")
            if info["done"]:
                return info
            time.sleep(0.05)
        self.fail("no reply")

    def outbound(self):
        return "".join(json.dumps(r["body"], ensure_ascii=False) for r in self.fake.requests)

    def test_files_go_as_labels_and_edit_makes_new_version(self):
        self.setup_ai()
        chat, fid, label_text = self.chat_with_file()
        self.assertNotIn("Петровск", label_text)
        new_label = label_text.replace("10 дней", "30 дней")
        self.fake.requests.clear()
        self.fake.reply = lambda body: ["Готово.\n<<<ФАЙЛ>>>\n", new_label, "\n<<<КОНЕЦ>>>\nСрок изменён."]
        _, res = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "поправь пункт 3: срок 30 дней", "with_files": True})
        self.assertFalse(res["blocked"], res)
        self.assertTrue(res["editing"])
        done = self.wait(res["run"])
        self.assertTrue(done["edit"]["applied"], done)
        for secret in SECRETS:                                   # outbound leak check: zero
            self.assertNotIn(secret, self.outbound())
        self.assertIn("Срок оплаты 10 дней", self.outbound())    # file text did go along, in label form
        _, data = self.call("GET", f"/api/chats/{chat}")
        self.assertEqual(len(data["files"]), 2)                  # original kept, new version added
        new = data["files"][-1]
        self.assertIn("правка ИИ 1", new["name"])
        _, restored = self.call("GET", f"/api/chats/{chat}/files/{new['id']}/restored")
        self.assertIn("Петровск", restored.decode())             # values restored locally
        self.assertIn("30 дней", restored.decode())
        _, anon = self.call("GET", f"/api/chats/{chat}/files/{new['id']}/anon")
        for secret in SECRETS:
            self.assertNotIn(secret, anon.decode())
        _, orig = self.call("GET", f"/api/chats/{chat}/files/{fid}/anon")
        self.assertEqual(orig.decode(), label_text)              # previous version untouched
        self.assertEqual(data["steps"][-1]["kind"], "ai_edit")

    def test_damaged_labels_do_not_create_version(self):
        self.setup_ai()
        chat, fid, label_text = self.chat_with_file()
        self.fake.reply = lambda body: ["<<<ФАЙЛ>>>\nДоговор с Name99 и Phone77\n<<<КОНЕЦ>>>"]
        _, res = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "перепиши договор", "with_files": True})
        done = self.wait(res["run"])
        self.assertFalse(done["edit"]["applied"])
        self.assertIn("метки", done["edit"]["note"])
        _, data = self.call("GET", f"/api/chats/{chat}")
        self.assertEqual(len(data["files"]), 1)

    def test_unsupported_format_says_so(self):
        self.setup_ai()
        from .helpers import pdf_bytes
        _, chat = self.call("POST", "/api/chats", {"title": "d"})
        job = self.app.service.anonymize([__import__("anonymizer.service", fromlist=["Upload"]).Upload("a.pdf", pdf_bytes(TEXT))], {})
        out = Path(job.files[0].out_path).read_bytes()
        rec = self.app.chats.add_file(chat["id"], "a.pdf", "pdf", anon=out, names={"anon": "a.docx"})
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        self.fake.requests.clear(); self.fake.reply = None
        _, res = self.call("POST", f"/api/ai/chats/{chat['id']}/send", {"text": "поправь пункт 3 в договоре", "with_files": True})
        self.assertFalse(res["editing"])
        self.assertIn("нельзя", res["note"])
        done = self.wait(res["run"])
        self.assertFalse(done["edit"]["applied"])
        for secret in SECRETS:
            self.assertNotIn(secret, self.outbound())
        _, data = self.call("GET", f"/api/chats/{chat['id']}")
        self.assertEqual(len(data["files"]), 1)

    def test_plain_question_sends_files_without_edit(self):
        self.setup_ai()
        chat, fid, label_text = self.chat_with_file()
        self.fake.requests.clear(); self.fake.reply = None
        _, res = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Что в договоре?", "with_files": True})
        self.assertFalse(res["editing"])
        self.wait(res["run"])
        self.assertIn("Срок оплаты", self.outbound())
        for secret in SECRETS:
            self.assertNotIn(secret, self.outbound())

    def test_no_provider_gives_clear_error(self):
        other = keystore.Keystore(Path(self.tmp.name) / "empty", self.env.vault._key, MemoryBackend())
        keep, self.app.keystore = self.app.keystore, other
        try:
            _, chat = self.call("POST", "/api/chats", {"title": "x"})
            self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
            status, res = self.call("POST", f"/api/ai/chats/{chat['id']}/send", {"text": "привет", "with_files": True})
            self.assertEqual(status, 400)
            self.assertIn("настройках", json.dumps(res, ensure_ascii=False))
        finally:
            self.app.keystore = keep


class Page(unittest.TestCase):
    def test_button_gone_composer_last_and_hint_link(self):
        index = (WEB / "index.html").read_text(encoding="utf8")
        js = (WEB / "ai-chat.js").read_text(encoding="utf8")
        self.assertNotIn("ИИ-чат</a>", index)
        self.assertNotIn('id="link-ai"', index)
        self.assertGreater(index.index('id="aic-composer"'), index.index('id="drop-chat"'))
        self.assertIn("position: sticky; bottom: 0", index)
        self.assertIn("ensureChat", js)
        self.assertIn("Открыть настройки провайдера", js)
        self.assertNotRegex(index + js, "[\U0001F300-\U0001FAFF☀-➿]")
        self.assertTrue((WEB / "ai.html").exists())          # /ai route still served


if __name__ == "__main__":
    unittest.main()
