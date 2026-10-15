"""W12b: AI chat attachments, local export of answers, SSE, and the outbound-leak check over attachments. Synthetic data only."""
import base64
import http.client
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from anonymizer import guard, keystore
from anonymizer.webapp import create_server

from .helpers import Env, docx_bytes
from .llm_fake import TEST_KEY, FakeProvider
from .test_ws_llm_e2e import corpus, norm
from .test_ws_llm_keystore import MemoryBackend

NAMES_TEXT = "the contract with Ivan Petrovsky, email ivan.petrovsky@acme-test.org, phone +7 495 123-45-67, please summarize."


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class W12b(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app.keystore = keystore.Keystore(Path(cls.tmp.name), cls.env.vault._key, MemoryBackend())
        cls.fake = FakeProvider(chunks=["Understood. ", "Noted."])
        cls.fake.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fake.__exit__(None, None, None)
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()
        cls.env.close()

    def setUp(self):
        self.fake.reply = None

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        head = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie, "X-Requested-With": "anonymizer",
                "Content-Type": "application/json"}
        conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, head)
        resp = conn.getresponse()
        data = resp.read()
        ctype = resp.getheader("Content-Type", "")
        conn.close()
        return resp.status, (json.loads(data) if data and ctype.startswith("application/json") else data), resp

    def setup_ai(self):
        self.call("POST", "/api/ai/providers/loc", {"kind": "custom", "base_url": self.fake.url, "model": "m-one"})
        self.call("POST", "/api/ai/providers/loc/key", {"key": TEST_KEY})
        self.call("POST", "/api/ai/enabled", {"enabled": True})
        _, chat, _ = self.call("POST", "/api/chats", {"title": "ai"})
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        return chat["id"]

    def wait_run(self, run):
        for _ in range(300):
            _, info, _ = self.call("GET", f"/api/ai/runs/{run}")
            if info["done"]:
                return info
            time.sleep(0.05)
        self.fail("reply did not finish")

    def attach(self, chat, name, data):
        status, res, _ = self.call("POST", f"/api/ai/chats/{chat}/attach", {"name": name, "data": b64(data)})
        self.assertEqual(status, 200, res)
        return res

    # -- attachments ----------------------------------------------------------------------------

    def test_attachment_is_anonymized_before_send(self):
        chat = self.setup_ai()
        self.fake.requests.clear()
        att = self.attach(chat, "contract.docx", docx_bytes([NAMES_TEXT]))
        self.assertTrue(att["ok"], att)
        self.assertNotIn("Petrovsky", json.dumps(att))
        _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Summarize the file", "attachments": [att["id"]]})
        self.assertFalse(res["blocked"], res)
        self.wait_run(res["run"])
        raw = b"".join(r["raw"] for r in self.fake.requests).decode("utf-8", "replace")
        for secret in ("Petrovsky", "ivan.petrovsky", "495 123"):
            self.assertNotIn(secret, raw)
        self.assertRegex(raw, r"Name\d|Email\d|Phone\d")

    def test_refused_files_are_not_sent(self):
        chat = self.setup_ai()
        self.fake.requests.clear()
        for name, data in (("a.xyz", b"hello"), ("empty.txt", b"")):
            res = self.attach(chat, name, data)
            self.assertFalse(res["ok"], name)
            self.assertTrue(res["reason"])
        big = self.attach(chat, "big.txt", b"x" * (5 * 1024 * 1024 + 10))
        self.assertFalse(big["ok"])
        self.assertIn("5 МБ", big["reason"])
        status, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "hi", "attachments": ["nope"]})
        self.assertEqual(status, 400)
        self.assertEqual(self.fake.requests, [])

    def test_attachment_of_other_chat_is_refused(self):
        chat = self.setup_ai()
        att = self.attach(chat, "n.txt", NAMES_TEXT.encode())
        _, other, _ = self.call("POST", "/api/chats", {"title": "other"})
        self.call("POST", f"/api/ai/chats/{other['id']}/toggle", {"on": True})
        status, _, _ = self.call("POST", f"/api/ai/chats/{other['id']}/send", {"text": "hi", "attachments": [att["id"]]})
        self.assertEqual(status, 400)

    # -- export ----------------------------------------------------------------------------------

    def _chat_with_label(self):
        chat = self.setup_ai()
        _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": NAMES_TEXT})
        self.assertFalse(res["blocked"], res)
        self.wait_run(res["run"])
        _, view, _ = self.call("GET", f"/api/ai/chats/{chat}")
        label = re.search(r"Name\d+", view["messages"][0]["label_text"]).group()
        return chat, label

    def test_export_restores_locally(self):
        chat, label = self._chat_with_label()
        self.fake.reply = lambda body: ["Dear ", label[:2], label[2:], ", thanks."]
        _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Write a thank-you"})
        self.wait_run(res["run"])
        _, view, _ = self.call("GET", f"/api/ai/chats/{chat}")
        index = max(i for i, m in enumerate(view["messages"]) if m["role"] == "assistant")
        status, data, resp = self.call("POST", f"/api/ai/chats/{chat}/export", {"index": index})
        self.assertEqual(status, 200)
        self.assertIn("attachment", resp.getheader("Content-Disposition"))
        self.assertIn("Ivan", data.decode("utf-8"))
        self.assertNotIn(label, data.decode("utf-8"))

    def test_export_reports_unknown_labels_and_never_guesses(self):
        chat, label = self._chat_with_label()
        self.fake.reply = lambda body: ["Hello Name99999 and ", label, "."]
        _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Write again"})
        self.wait_run(res["run"])
        _, view, _ = self.call("GET", f"/api/ai/chats/{chat}")
        index = max(i for i, m in enumerate(view["messages"]) if m["role"] == "assistant")
        _, ask, _ = self.call("POST", f"/api/ai/chats/{chat}/export", {"index": index})
        self.assertFalse(ask["ok"])
        self.assertTrue(ask["needs_confirm"])
        self.assertIn("Name99999", ask["report"]["unknown"])
        status, data, _ = self.call("POST", f"/api/ai/chats/{chat}/export", {"index": index, "accept_damaged": True})
        self.assertEqual(status, 200)
        self.assertIn("Name99999", data.decode("utf-8"))       # left as is, not replaced by a similar value
        status, _, _ = self.call("POST", f"/api/ai/chats/{chat}/export", {"index": 0})      # a user message
        self.assertEqual(status, 400)

    # -- SSE -------------------------------------------------------------------------------------

    def sse(self, run):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", f"/api/ai/runs/{run}/events", headers={"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader("Content-Type").startswith("text/event-stream"))
        body = resp.read().decode("utf-8")
        conn.close()
        events = []
        for block in body.split("\n\n"):
            m = re.match(r"event: (\w+)\ndata: (.*)", block, re.S)
            if m:
                events.append((m.group(1), json.loads(m.group(2))))
        return events

    def test_sse_stream_never_shows_half_label(self):
        chat, label = self._chat_with_label()
        self.fake.reply = lambda body: ["Hi ", label[:2], label[2:4], label[4:], " ok ", "Name 99999", "."]
        _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Greet"})
        events = self.sse(res["run"])
        self.assertEqual(events[-1][0], "done")
        text = "".join(d["text"] for n, d in events if n == "delta")
        self.assertIn("Ivan", text)
        self.assertNotIn(label, text)
        for _, d in [e for e in events if e[0] == "delta"]:
            self.assertNotRegex(d["text"], r"Na$|Nam$|Name$")       # no cut label at an event edge
        _, poll, _ = self.call("GET", f"/api/ai/runs/{res['run']}")
        self.assertEqual(text, poll["text"])
        self.assertEqual(events[-1][1]["length"], len(text))

    def test_sse_unknown_run_and_auth(self):
        status, _, _ = self.call("GET", "/api/ai/runs/nope/events")
        self.assertEqual(status, 404)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/ai/runs/nope/events", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(conn.getresponse().status, 403)

    def test_stop_ends_stream(self):
        chat, _ = self._chat_with_label()
        self.fake.reply = lambda body: ["word "] * 400
        _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Long answer"})
        self.call("POST", f"/api/ai/runs/{res['run']}/stop")
        events = self.sse(res["run"])
        self.assertEqual(events[-1][0], "done")

    # -- outbound leak over attachments and edits ----------------------------------------------

    def test_outbound_leak_attachments_and_edits(self):
        chat = self.setup_ai()
        self.fake.requests.clear()
        golds, files, texts, refused, edits = [], 0, 0, 0, 0
        for lang, name in (("ru", "text_corpus_v1.jsonl"), ("en", "text_corpus_en.jsonl")):
            for n, row in enumerate(corpus(name)[:30]):
                golds += [s["text"] for s in row["spans"]]
                if n % 2:
                    att = self.attach(chat, f"doc{n}.docx", docx_bytes([row["text"]]))
                else:
                    att = self.attach(chat, f"note{n}.txt", row["text"].encode("utf-8"))
                if not att["ok"]:
                    refused += 1
                    continue
                files += 1
                _, res, _ = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Edit this document", "attachments": [att["id"]]})
                if res["blocked"]:
                    refused += 1
                    continue
                self.wait_run(res["run"])
                texts += 1
                _, view, _ = self.call("GET", f"/api/ai/chats/{chat}")
                idx = max(i for i, m in enumerate(view["messages"]) if m["role"] == "assistant")
                status, _, _ = self.call("POST", f"/api/ai/chats/{chat}/export", {"index": idx, "accept_damaged": True})
                edits += status == 200
        self.assertGreater(texts, 10)
        originals = [o for o, _ in guard.vault_originals(self.env.vault)]
        leaks = []
        for req in self.fake.requests:
            blob = norm(req["raw"].decode("utf-8", "replace") + " " + req["path"])
            self.assertNotIn(norm(TEST_KEY), blob)
            for value in golds + originals:
                value = norm(value)
                if len(value) >= 4 and value in blob:
                    leaks.append(value[:3] + "..")
        print(f"\n[w12b-e2e] requests={len(self.fake.requests)} files_attached={files} sent_with_file={texts} "
              f"refused={refused} exports={edits} golds={len(golds)} originals={len(originals)} leaks={len(leaks)}")
        self.assertEqual(leaks, [])

    def test_page_has_attach_and_sse_and_no_emoji(self):
        _, page, _ = self.call("GET", "/ai")
        _, mod, _ = self.call("GET", "/ai-chat.js")
        html = page.decode("utf-8") + mod.decode("utf-8")   # the page and the shared chat module it loads
        self.assertIn('type = "file"', html)
        self.assertIn("EventSource", html)
        self.assertNotIn("innerHTML", html)
        self.assertNotRegex(html, r"[\U0001F300-\U0001FAFF☀-➿]")
        self.assertNotRegex(html, r"#(?:000|fff)(?:000|fff)?\b")


if __name__ == "__main__":
    unittest.main()
