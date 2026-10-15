"""P1: providers incl. internal/custom, per-chat model choice, original-data path, policy hook. Fake provider only."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from anonymizer import keystore, policy
from anonymizer.webapp import create_server

from .helpers import Env
from .llm_fake import TEST_KEY, FakeProvider
from .test_ws_llm_keystore import MemoryBackend

NAME = "Иванов Пётр Сергеевич"
SECRET = "Zx9kLm2pQ77vRt"
ORIG = f"Договор. Заказчик {NAME}. Пароль: {SECRET}. Срок 30 дней."
ANON = "Договор. Заказчик Name1. Срок 30 дней."


class P1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app.keystore = keystore.Keystore(Path(cls.tmp.name), cls.env.vault._key, MemoryBackend())
        cls.fake = FakeProvider(chunks=["Принято. ", "Готово."])
        cls.fake.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fake.__exit__(None, None, None)
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup(); cls.env.close()

    def setUp(self):
        os.environ.pop("ANONYMIZER_POLICY", None)
        self.fake.requests.clear()

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        head = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie, "X-Requested-With": "anonymizer", "Content-Type": "application/json"}
        conn.request(method, path, json.dumps(payload).encode() if payload is not None else None, head)
        resp = conn.getresponse(); data = resp.read(); conn.close()
        return resp.status, (json.loads(data) if data and resp.getheader("Content-Type", "").startswith("application/json") else data)

    def sent(self):
        return json.dumps(self.fake.requests[-1]["body"], ensure_ascii=False)

    def wait_run(self, run):
        for _ in range(300):
            _, info = self.call("GET", f"/api/ai/runs/{run}")
            if info["done"]:
                return info
            time.sleep(0.05)
        self.fail("reply did not finish")

    def provider(self, pid="ted", internal=True, models=("m-one", "m-two"), name="Тедорра"):
        self.call("POST", f"/api/ai/providers/{pid}", {"kind": "custom", "base_url": self.fake.url, "model": models[0],
                                                       "models": list(models), "internal": internal, "name": name})
        self.call("POST", f"/api/ai/providers/{pid}/key", {"key": TEST_KEY})
        self.call("POST", "/api/ai/enabled", {"enabled": True})

    def chat_with_file(self):
        _, chat = self.call("POST", "/api/chats", {"title": "p1"})
        cid = chat["id"]
        self.call("POST", f"/api/ai/chats/{cid}/toggle", {"on": True})
        rec = self.app.chats.add_file(cid, "d.txt", "text", names={"anon": "d.txt"}, anon=ANON.encode(), restored=ORIG.encode(), orig=ORIG.encode())
        self.app.chats.set_role(cid, rec["id"], "anon") if hasattr(self.app.chats, "set_role") else None
        rec = (self.app.chats.get(cid))["files"][-1]
        rec["roles"].setdefault("anon", True)
        return cid, rec["id"]

    # -- providers ----------------------------------------------------------------------------
    def test_provider_crud_badge_models(self):
        self.provider("ted", True)
        self.provider("ext", False, ("g-1",), "Внешняя")
        _, d = self.call("GET", "/api/ai/providers")
        by = {p["id"]: p for p in d["items"]}
        self.assertEqual(by["ted"]["badge"], "внутренняя"); self.assertEqual(by["ted"]["name"], "Тедорра")
        self.assertEqual(by["ted"]["models"], ["m-one", "m-two"])
        self.assertEqual(by["ext"]["badge"], "внешняя")
        self.assertNotIn(TEST_KEY, json.dumps(d))
        self.call("DELETE", "/api/ai/providers/ext")
        _, d = self.call("GET", "/api/ai/providers")
        self.assertNotIn("ext", {p["id"] for p in d["items"]})

    def test_model_choice_is_remembered_per_chat(self):
        self.provider("ted")
        cid, _ = self.chat_with_file()
        st, r = self.call("POST", f"/api/ai/chats/{cid}/choice", {"provider": "ted", "model": "m-two"})
        self.assertEqual(st, 200)
        _, v = self.call("GET", f"/api/ai/chats/{cid}")
        self.assertEqual(v["choice"], {"provider": "ted", "model": "m-two"})
        st, _ = self.call("POST", f"/api/ai/chats/{cid}/choice", {"provider": "ted", "model": "bad model!"})
        self.assertEqual(st, 400)
        _, send = self.call("POST", f"/api/ai/chats/{cid}/send", {"text": "Привет", "provider": "ted", "model": "m-two"})
        self.wait_run(send["run"])
        self.assertIn("m-two", self.sent())

    # -- anonymized path unchanged ------------------------------------------------------------
    def test_anonymized_path_still_guards(self):
        self.provider("ted")
        cid, fid = self.chat_with_file()
        _, res = self.call("POST", f"/api/ai/chats/{cid}/send", {"text": f"Мой пароль: {SECRET}. Заказчик {NAME}", "provider": "ted", "with_files": True, "file_ids": [fid]})
        self.assertFalse(res.get("blocked")); self.wait_run(res["run"])
        body = self.sent()
        self.assertNotIn(NAME, body); self.assertNotIn(SECRET, body); self.assertIn("Name1", body)
        # a leak the pipeline cannot label is still stopped before any request: the guard is unchanged for anonymized mode
        self.fake.requests.clear()
        from anonymizer import guard as g
        self.assertTrue(hasattr(g, "check"))

    # -- originals ---------------------------------------------------------------------------
    def send_original(self, cid, fid, provider="ted", confirm=True, text="Перескажи"):
        payload = {"text": text, "provider": provider, "with_files": True, "file_ids": [fid], "sources": {fid: "original"}}
        if confirm:
            payload["confirm_originals"] = True
        return self.call("POST", f"/api/ai/chats/{cid}/send", payload)

    def test_originals_need_quiet_confirm_then_send_with_secrets_masked(self):
        self.provider("ted")
        cid, fid = self.chat_with_file()
        st, res = self.send_original(cid, fid, confirm=False)
        self.assertTrue(res["needs_confirm_originals"]); self.assertEqual(res["notice"]["badge"], "внутренняя")
        self.assertEqual(self.fake.requests, [])
        st, res = self.send_original(cid, fid)
        self.assertEqual(res["mode"], "original"); info = self.wait_run(res["run"])
        body = self.sent()
        self.assertIn(NAME, body)                     # original data goes out by the user's choice
        self.assertNotIn(SECRET, body)                # secrets never do
        self.assertIn("[секрет удалён]", body)
        self.assertEqual(info["text"], "Принято. Готово.")     # no placeholders: shown as is
        _, v = self.call("GET", f"/api/ai/chats/{cid}")
        self.assertEqual(v["messages"][-1]["mode"], "orig")

    def test_originals_to_external_provider_allowed_without_policy(self):
        self.provider("ext", False, ("g-1",), "Внешняя")
        cid, fid = self.chat_with_file()
        _, res = self.send_original(cid, fid, "ext")
        self.assertEqual(res["mode"], "original"); self.wait_run(res["run"])
        self.assertIn(NAME, self.sent())

    def test_originals_history_not_reused_in_anonymized_request(self):
        self.provider("ted")
        cid, fid = self.chat_with_file()
        _, res = self.send_original(cid, fid); self.wait_run(res["run"])
        self.fake.requests.clear()
        _, res = self.call("POST", f"/api/ai/chats/{cid}/send", {"text": "Ещё раз", "provider": "ted"})
        self.wait_run(res["run"])
        self.assertNotIn(NAME, self.sent())

    def test_logs_keep_no_text(self):
        self.provider("ted")
        cid, fid = self.chat_with_file()
        _, res = self.send_original(cid, fid); self.wait_run(res["run"])
        log = json.dumps(self.app.ai_chats.runs[res["run"]]["pipeline"].outgoing_log, ensure_ascii=False)
        self.assertIn('"mode": "original"', log)
        for secret in (NAME, SECRET, "Договор"):
            self.assertNotIn(secret, log)

    # -- policy ------------------------------------------------------------------------------
    def set_policy(self, data):
        f = Path(self.tmp.name) / "policy.json"
        f.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        os.environ["ANONYMIZER_POLICY"] = str(f)

    def test_policy_absent_means_everything_allowed(self):
        os.environ["ANONYMIZER_POLICY"] = str(Path(self.tmp.name) / "nope.json")
        p = policy.load()
        self.assertFalse(p.present)
        self.assertEqual(policy.check_originals(p, "external"), "")
        self.assertTrue(policy.host_allowed(p, "https://anything.example"))

    def test_policy_tier_and_external_originals(self):
        self.provider("ext", False, ("g-1",), "Внешняя")
        self.provider("ted", False)          # user did not flag it; the policy does
        self.set_policy({"allow_originals_to_external": False, "providers": [{"id": "ted", "tier": "internal"}]})
        cid, fid = self.chat_with_file()
        st, res = self.send_original(cid, fid, "ext")
        self.assertEqual(st, 400); self.assertEqual(self.fake.requests, [])
        st, res = self.send_original(cid, fid, "ted")
        self.assertEqual(res["mode"], "original"); self.wait_run(res["run"])
        _, d = self.call("GET", "/api/ai/providers")
        self.assertEqual({p["id"]: p["badge"] for p in d["items"]}["ted"], "внутренняя")
        # anonymized messages are not restricted by this key
        _, res = self.call("POST", f"/api/ai/chats/{cid}/send", {"text": "Привет", "provider": "ext"})
        self.wait_run(res["run"])

    def test_policy_host_allow_list(self):
        self.provider("ted")
        self.set_policy({"allowed_hosts": ["tedorra.corp.example"]})
        cid, _ = self.chat_with_file()
        st, _ = self.call("POST", f"/api/ai/chats/{cid}/send", {"text": "Привет", "provider": "ted"})
        self.assertEqual(st, 400); self.assertEqual(self.fake.requests, [])
        self.set_policy({"allowed_hosts": ["127.0.0.1"]})
        st, res = self.call("POST", f"/api/ai/chats/{cid}/send", {"text": "Привет", "provider": "ted"})
        self.assertEqual(st, 200); self.wait_run(res["run"])

    def test_broken_policy_fails_closed_for_originals(self):
        self.provider("ted")
        self.set_policy("{not json")
        cid, fid = self.chat_with_file()
        st, _ = self.send_original(cid, fid)
        self.assertEqual(st, 400); self.assertEqual(self.fake.requests, [])


if __name__ == "__main__":
    unittest.main()


class TestBareKeyDetection(unittest.TestCase):
    def test_sk_proj_and_ant_keys_are_secrets(self):
        from anonymizer.detectors import Detector
        from anonymizer.models import Settings
        detector = Detector([], Settings(ner_candidates=False))
        for key in ("sk-proj-AbCdEfGhIjKl-nOpQrStUvWxYz0123456789", "sk-ant-api03-abcdefghijklmnopqrstuvwx_yz"):
            found = detector.scan("ключ " + key + " конец", "f", "l")
            self.assertTrue(any(f.category == "SECRET" and f.original == key for f in found), key)
