"""W12 end-to-end outbound leak test: web app -> local server -> fake local provider. Synthetic corpora only (tests/eval)."""
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

from .helpers import Env
from .llm_fake import TEST_KEY, FakeProvider
from .test_ws_llm_keystore import MemoryBackend

CORPORA = Path(__file__).parent / "ev" "al"
PER_LANG = 45


def corpus(name):
    rows = [json.loads(line) for line in (CORPORA / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("spans") and len(r["text"]) < 400]
    rows.sort(key=lambda r: r["id"])
    return rows[:: max(1, len(rows) // PER_LANG)][:PER_LANG]


def norm(text):
    return re.sub(r"\s+", " ", text.casefold()).strip()


class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app.keystore = keystore.Keystore(Path(cls.tmp.name), cls.env.vault._key, MemoryBackend())   # never the real Keychain
        cls.fake = FakeProvider(chunks=["Understood. ", "Noted."])
        cls.fake.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fake.__exit__(None, None, None)
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()
        cls.env.close()

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        head = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie, "X-Requested-With": "anonymizer",
                "Content-Type": "application/json"}
        conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, head)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, (json.loads(data) if data and resp.getheader("Content-Type", "").startswith("application/json") else data)

    def setup_ai(self):
        self.call("POST", "/api/ai/providers/loc", {"kind": "custom", "base_url": self.fake.url, "model": "m-one"})
        self.call("POST", "/api/ai/providers/loc/key", {"key": TEST_KEY})
        self.call("POST", "/api/ai/enabled", {"enabled": True})
        _, chat = self.call("POST", "/api/chats", {"title": "ai"})
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        return chat["id"]

    def wait_run(self, run):
        for _ in range(300):
            _, info = self.call("GET", f"/api/ai/runs/{run}")
            if info["done"]:
                return info
            time.sleep(0.05)
        self.fail("reply did not finish")

    def test_ai_routes_need_token_and_are_not_on_addin(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/ai/providers", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(conn.getresponse().status, 403)
        from anonymizer import addin
        self.assertNotIn("/api/ai", Path(addin.__file__).read_text(encoding="utf-8"))

    def test_csp_connect_src_self_only(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/ai/providers", headers={"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie})
        csp = conn.getresponse().getheader("Content-Security-Policy")
        self.assertEqual(re.findall(r"connect-src [^;]*", csp), ["connect-src 'self'"])

    def test_ai_page_is_served_locally_without_external_urls(self):
        status, page = self.call("GET", "/ai")
        self.assertEqual(status, 200)
        html = page.decode("utf-8")
        self.assertNotRegex(html, r"https?://")                      # no external origin in the page at all
        self.assertIn('type="password"', html)                       # key entry is masked
        self.assertNotIn("innerHTML", html)                          # model and user text only through textContent
        self.assertNotIn(TEST_KEY, html)

    def test_off_by_default_nothing_sent(self):
        self.setup_ai()
        _, chat = self.call("POST", "/api/chats", {"title": "off"})
        before = len(self.fake.requests)
        status, _ = self.call("POST", f"/api/ai/chats/{chat['id']}/send", {"text": "Hello there"})
        self.assertEqual(status, 400)
        self.assertEqual(len(self.fake.requests), before)

    def test_outbound_leak_ru_en(self):
        chat = self.setup_ai()
        self.fake.requests.clear()
        golds, sent, blocked = [], 0, {"ru": 0, "en": 0}
        for lang, name in (("ru", "text_corpus_v1.jsonl"), ("en", "text_corpus_en.jsonl")):
            for row in corpus(name):
                golds += [s["text"] for s in row["spans"]]
                status, result = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": row["text"]})
                self.assertEqual(status, 200, result)
                if result["blocked"]:
                    blocked[lang] += 1
                    continue
                self.wait_run(result["run"])
                sent += 1
        self.assertGreater(sent, 10)
        originals = [o for o, _ in guard.vault_originals(self.env.vault)]
        leaks = []
        for req in self.fake.requests:
            blob = norm(req["raw"].decode("utf-8", "replace") + " " + req["path"] + " "
                        + " ".join(v for k, v in req["headers"].items() if k not in ("authorization", "x-api-key", "x-goog-api-key")))
            self.assertNotIn(norm(TEST_KEY), blob)
            for value in golds + originals:
                value = norm(value)
                if len(value) >= 4 and value in blob:
                    leaks.append(value[:3] + "..")
        print(f"\n[e2e] requests={len(self.fake.requests)} sent={sent} blocked={blocked} golds={len(golds)} "
              f"originals={len(originals)} leaks={len(leaks)}")
        self.assertEqual(leaks, [])

    def test_key_not_in_logs_pages_files(self):
        chat = self.setup_ai()
        self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "Please summarize the plan."})
        _, page = self.call("GET", "/api/ai/providers")
        self.assertNotIn(TEST_KEY, json.dumps(page))
        for path in [*self.app.chats.dir.rglob("*"), *Path(self.tmp.name).rglob("*")]:
            if path.is_file():
                self.assertNotIn(TEST_KEY.encode(), path.read_bytes(), path.name)
        index = (Path(__file__).parent.parent / "anonymizer" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(TEST_KEY, index)

    def test_conversation_stored_in_label_form_encrypted(self):
        chat = self.setup_ai()
        _, res = self.call("POST", f"/api/ai/chats/{chat}/send",
                           {"text": "Write a note about Ivan Petrovsky, email ivan.petrovsky@acme-test.org"})
        if not res["blocked"]:
            self.wait_run(res["run"])
        raw = b"".join(p.read_bytes() for p in (self.app.chats.dir / chat).rglob("*") if p.is_file())
        self.assertNotIn(b"Petrovsky", raw)
        self.assertNotIn("Petrovsky", json.dumps(self.app.ai_chats.load(chat)["messages"]))

    def test_possible_findings_carry_no_values(self):
        chat = self.setup_ai()
        _, res = self.call("POST", f"/api/ai/chats/{chat}/prepare", {"text": "Ask Zdenek Kowalczyk about the invoice"})
        self.assertNotIn("Kowalczyk", json.dumps({k: v for k, v in res.items() if k not in ("anonymized", "dry_run")}))
        ids = [f["id"] for f in res["findings"] if f["possible"]]
        if ids:
            _, ok = self.call("POST", f"/api/ai/chats/{chat}/prepare",
                              {"text": "Ask Zdenek Kowalczyk about the invoice", "resolve": {"anonymize": ids}})
            self.assertNotIn("Kowalczyk", json.dumps(ok["dry_run"] or {}))


if __name__ == "__main__":
    unittest.main()
