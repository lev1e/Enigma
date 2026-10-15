"""P2B: AI editing of docx / pptx / xlsx through validated JSON patches, end to end with the fake provider only (synthetic data)."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from anonymizer import docedit, keystore
from anonymizer.service import Upload
from anonymizer.webapp import create_server

from .helpers import Env, docx_bytes, pptx_bytes, xlsx_bytes
from .llm_fake import TEST_KEY, FakeProvider
from .test_ws_llm_keystore import MemoryBackend

NAME = "Иванов Пётр Сергеевич"
SECRET = "Zx9kLm2pQ77vRt"
LINE1 = f"Договор. Заказчик {NAME}. Срок 10 дней."
LINE2 = "Второй абзац без данных."
LINE3 = f"Пароль: {SECRET}. Срок 5 дней."
MAKERS = {
    "pptx": lambda: pptx_bytes([LINE1, LINE2], title="Итоги квартала"),
    "docx": lambda: docx_bytes([LINE1, LINE2]),
    "xlsx": lambda: xlsx_bytes({"A1": LINE1, "A2": LINE2}),
}


def elems(blob: bytes, name: str) -> list[dict]:
    out = []
    for c in docedit.outline(blob, name, text="full")["containers"]:
        out += [e for e in c["elements"] if e.get("kind") != "shape" and e.get("editable", True) and e.get("text")]
    return out


def text_of(blob: bytes, name: str) -> str:
    return "\n".join(e["text"] for e in elems(blob, name))


class P2B(unittest.TestCase):
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

    def setUp(self):
        self.call("POST", "/api/ai/providers/loc", {"kind": "custom", "base_url": self.fake.url, "model": "m-one"})
        self.call("POST", "/api/ai/providers/loc/key", {"key": TEST_KEY})
        self.call("POST", "/api/ai/enabled", {"enabled": True})
        self.fake.requests.clear(); self.fake.reply = None

    def make_chat(self, fmt, maker=None):
        name = f"doc.{fmt}"
        orig = (maker or MAKERS[fmt])()
        _, chat = self.call("POST", "/api/chats", {"title": "p2b"})
        job = self.app.service.anonymize([Upload(name, orig)], {})
        anon = Path(job.files[0].out_path).read_bytes()
        rec = self.app.chats.add_file(chat["id"], name, fmt, tokens=list(job.files[0].tokens or []), names={"anon": name},
                                      anon=anon, restored=orig, orig=orig)
        self.app.chats.add_step(chat["id"], "anonymize", files=[rec["id"]])
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        self.assertNotIn("Иванов", text_of(anon, name))
        return chat["id"], rec["id"], name, anon, orig

    def wait(self, run):
        for _ in range(400):
            _, info = self.call("GET", f"/api/ai/runs/{run}")
            if info["done"]:
                return info
            time.sleep(0.05)
        self.fail("no reply")

    def outbound(self):
        return "".join(json.dumps(r["body"], ensure_ascii=False) for r in self.fake.requests)

    def blob(self, chat, fid, role):
        st, data = self.call("GET", f"/api/chats/{chat}/files/{fid}/{role}")
        self.assertEqual(st, 200)
        return data

    def reply_patch(self, make):
        """Fake model: `make(blob_text_elems)` builds ops from the outline the app sent (parsed from the request body)."""
        def reply(body):
            ops = make(self.fake.base_elems)
            return ["Готово.\n```json\n" + json.dumps({"v": 1, "note": "правка", "ops": ops}, ensure_ascii=False) + "\n```"]
        self.fake.reply = reply

    def send(self, chat, text, **extra):
        _, res = self.call("POST", f"/api/ai/chats/{chat}/send", dict({"text": text, "with_files": True}, **extra))
        self.assertFalse(res.get("blocked"), res)
        return res, self.wait(res["run"])

    def text_edit_ops(self, anon, name, new_term="30 дней"):
        e = next(e for e in elems(anon, name) if "Срок 10 дней" in e["text"])
        return [{"op": "replace_text", "at": e["addr"], "expect": e["fp"], "text": e["text"].replace("10 дней", new_term)}], e

    def design_ops(self, fmt, anon, name):
        if fmt == "xlsx":
            return [{"op": "col_width", "at": "Лист1!A", "width": 40}]
        e = next(e for e in elems(anon, name) if "Срок 10 дней" in e["text"])
        return [{"op": "set_style", "at": e["addr"], "size": 28, "bold": True}]

    def propose(self, fmt, text, ops_fn, **extra):
        chat, fid, name, anon, orig = self.make_chat(fmt)
        ops = ops_fn(fmt, anon, name)
        ops = ops[0] if isinstance(ops, tuple) else ops
        self.fake.reply = lambda body: ["Готово.\n```json\n" + json.dumps({"v": 1, "note": "правка", "ops": ops}, ensure_ascii=False) + "\n```"]
        res, done = self.send(chat, text, **extra)
        return chat, fid, name, anon, orig, res, done

    def versions(self, chat):
        _, data = self.call("GET", f"/api/chats/{chat}")
        return data["files"]

    # ---- text and design edits, apply all ---------------------------------------------------------
    def test_text_edit_apply_all_and_restore(self):
        for fmt in ("pptx", "docx", "xlsx"):
            with self.subTest(fmt=fmt):
                chat, fid, name, anon, orig, res, done = self.propose(fmt, "поправь договор: срок 30 дней", lambda f, a, n: self.text_edit_ops(a, n))
                self.assertTrue(res["editing"])
                edit = done["edit"]
                self.assertFalse(edit["applied"])
                prop = edit["proposal"]
                self.assertEqual(prop["source"], "anonymized")
                self.assertEqual(prop["items"][0]["op"], "replace_text")
                self.assertIn("10 дней", prop["items"][0]["was"]); self.assertIn("30 дней", prop["items"][0]["now"])
                self.assertRegex(prop["items"][0]["text"], "[А-Яа-я]")          # Russian card line
                self.assertEqual(len(self.versions(chat)), 1)                    # nothing written yet
                st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "apply", "ops": "all"})
                self.assertEqual((st, r["ok"]), (200, True), r)
                files = self.versions(chat)
                self.assertEqual(len(files), 2)
                self.assertIn("правка ИИ 1", files[-1]["name"])
                self.assertEqual(self.blob(chat, fid, "anon"), anon)             # base untouched
                self.assertEqual(self.blob(chat, fid, "restored"), orig)
                restored = self.blob(chat, r["file"], "restored")
                expect = text_of(orig, name).replace("10 дней", "30 дней")
                self.assertEqual(text_of(restored, name), expect)                # edit applied, values back, nothing else changed
                self.assertIn("Иванов", text_of(restored, name))
                self.assertNotIn("Иванов", text_of(self.blob(chat, r["file"], "anon"), name))
                _, view = self.call("GET", f"/api/ai/chats/{chat}")
                self.assertEqual(view["proposals"], [])

    def test_design_edit_apply(self):
        for fmt in ("pptx", "docx", "xlsx"):
            with self.subTest(fmt=fmt):
                text = "сделай колонку шире" if fmt == "xlsx" else "сделай шрифт крупнее и жирным"
                chat, fid, name, anon, orig, res, done = self.propose(fmt, text, lambda f, a, n: self.design_ops(f, a, n))
                prop = done["edit"]["proposal"]
                self.assertTrue(prop["items"][0]["text"])
                st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "apply", "ops": "all"})
                self.assertTrue(r["ok"], r)
                self.assertEqual(len(self.versions(chat)), 2)
                new = self.blob(chat, r["file"], "anon")
                self.assertNotEqual(new, anon)
                self.assertEqual(text_of(self.blob(chat, r["file"], "restored"), name), text_of(orig, name))   # text intact
                # design mode sends placeholders, never the real text of the paragraph
                self.assertNotIn("Срок 10 дней", self.outbound())

    def test_subset_by_indices(self):
        chat, fid, name, anon, orig, res, done = self.propose(
            "docx", "перепиши договор", lambda f, a, n: [
                {"op": "replace_text", "at": e["addr"], "expect": e["fp"], "text": e["text"] + " ОК"} for e in elems(a, n)])
        prop = done["edit"]["proposal"]
        self.assertEqual(len(prop["items"]), 2)
        st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "apply", "ops": [1]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["left"], [0])
        restored = text_of(self.blob(chat, r["file"], "restored"), name)
        self.assertIn(LINE2 + " ОК", restored); self.assertNotIn("10 дней. ОК", restored)
        self.assertEqual(len(self.versions(chat)), 2)
        _, view = self.call("GET", f"/api/ai/chats/{chat}")
        self.assertEqual([p["id"] for p in view["proposals"]], [prop["id"]])
        st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "reject"})
        self.assertTrue(r["ok"])
        self.assertEqual(len(self.versions(chat)), 2)
        st, _ = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "apply", "ops": "all"})
        self.assertEqual(st, 404)

    def test_reject_changes_nothing(self):
        chat, fid, name, anon, orig, res, done = self.propose("pptx", "поправь срок на 30 дней", lambda f, a, n: self.text_edit_ops(a, n))
        pid = done["edit"]["proposal"]["id"]
        st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": pid, "action": "reject"})
        self.assertEqual((st, r["ok"]), (200, True))
        self.assertEqual(len(self.versions(chat)), 1)
        _, view = self.call("GET", f"/api/ai/chats/{chat}")
        self.assertEqual(view["proposals"], [])

    # ---- rejected patches --------------------------------------------------------------------------
    def check_rejected(self, ops_fn, fmt="docx", needle=None, **extra):
        chat, fid, name, anon, orig, res, done = self.propose(fmt, "поправь срок на 30 дней", ops_fn, **extra)
        edit = done["edit"]
        self.assertNotIn("proposal", edit, edit)
        self.assertFalse(edit["applied"])
        self.assertRegex(edit["note"], "[А-Яа-я]{4}")
        if needle:
            self.assertIn(needle, edit["note"])
        self.assertEqual(len(self.versions(chat)), 1)
        return edit

    def test_stale_expect_rejected(self):
        def ops(f, a, n):
            o, e = self.text_edit_ops(a, n); o[0]["expect"] = "00000000"; return o
        self.check_rejected(ops)

    def test_unknown_label_rejected(self):
        def ops(f, a, n):
            o, e = self.text_edit_ops(a, n); o[0]["text"] = o[0]["text"] + " Name99"; return o
        self.check_rejected(ops)

    def test_unknown_address_rejected(self):
        def ops(f, a, n):
            o, e = self.text_edit_ops(a, n); o[0]["at"] = "p999"; return o
        self.check_rejected(ops)

    def test_broken_json_rejected(self):
        chat, fid, name, anon, orig = self.make_chat("docx")
        self.fake.reply = lambda body: ["```json\n{\"v\":1,\"ops\":[\n```"]
        res, done = self.send(chat, "поправь срок на 30 дней")
        self.assertNotIn("proposal", done["edit"]); self.assertRegex(done["edit"]["note"], "формат")
        self.assertEqual(len(self.versions(chat)), 1)

    def test_plain_text_reply_is_not_an_edit(self):
        chat, fid, name, anon, orig = self.make_chat("pptx")
        self.fake.reply = lambda body: ["Не вижу, что менять."]
        res, done = self.send(chat, "поправь срок на 30 дней")
        self.assertNotIn("proposal", done["edit"]); self.assertEqual(len(self.versions(chat)), 1)

    def test_secret_mask_echo_rejected_in_originals_mode(self):
        chat, fid, name, anon, orig = self.make_chat("docx", lambda: docx_bytes([LINE1, LINE3]))
        e = next(e for e in elems(orig, name) if "Пароль" in e["text"])
        self.fake.reply = lambda body: ["```json\n" + json.dumps({"v": 1, "ops": [{"op": "replace_text", "at": e["addr"], "expect": e["fp"], "text": "Пароль: [секрет удалён]. Срок 7 дней."}]}, ensure_ascii=False) + "\n```"]
        res, done = self.send(chat, "поправь срок на 7 дней", sources={fid: "original"}, confirm_originals=True)
        self.assertNotIn("proposal", done["edit"], done["edit"])
        self.assertRegex(done["edit"]["note"], "[А-Яа-я]{4}")
        self.assertNotIn(SECRET, self.outbound())                                    # P1: secret never leaves
        self.assertEqual(len(self.versions(chat)), 1)

    # ---- selection ---------------------------------------------------------------------------------
    def test_selection_narrows_context(self):
        for fmt in ("pptx", "docx", "xlsx"):
            with self.subTest(fmt=fmt):
                chat, fid, name, anon, orig = self.make_chat(fmt)
                target = next(e for e in elems(anon, name) if "Срок 10 дней" in e["text"])
                self.fake.reply = lambda body: ["Не вижу, что менять."]
                res, done = self.send(chat, "поправь срок на 30 дней", selected=[target["addr"]], selected_file=fid)
                self.assertIn("ВЫДЕЛЕНО ПОЛЬЗОВАТЕЛЕМ: " + target["addr"], self.outbound())
                self.fake.requests.clear()
                res, done = self.send(chat, "поправь срок на 30 дней", selected=["no such addr"], selected_file=fid)

    def test_bad_selection_is_400(self):
        chat, fid, name, anon, orig = self.make_chat("pptx")
        st, r = self.call("POST", f"/api/ai/chats/{chat}/send", {"text": "поправь", "with_files": True, "selected": "x"})
        self.assertEqual(st, 400)

    # ---- originals ---------------------------------------------------------------------------------
    def test_originals_source_edit(self):
        for fmt in ("pptx", "docx", "xlsx"):
            with self.subTest(fmt=fmt):
                chat, fid, name, anon, orig = self.make_chat(fmt)
                o, _ = self.text_edit_ops(orig, name)
                self.fake.reply = lambda body: ["```json\n" + json.dumps({"v": 1, "ops": o}, ensure_ascii=False) + "\n```"]
                res, done = self.send(chat, "поправь срок на 30 дней", sources={fid: "original"}, confirm_originals=True)
                if res.get("needs_confirm_originals"):
                    self.fail(res)
                self.assertIn("Иванов", self.outbound())                    # allowed by the owner decision
                prop = done["edit"]["proposal"]
                self.assertEqual(prop["source"], "original")
                st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "apply", "ops": "all"})
                self.assertTrue(r["ok"], r)
                self.assertEqual(text_of(self.blob(chat, r["file"], "restored"), name), text_of(orig, name).replace("10 дней", "30 дней"))
                self.assertEqual(self.blob(chat, fid, "orig"), orig)
                new_anon = self.blob(chat, r["file"], "anon")
                self.assertNotIn("Иванов", text_of(new_anon, name))        # the anonymized copy is made by the normal pipeline
                self.assertEqual(len(self.versions(chat)), 2)
                self.fake.requests.clear()

    def test_original_edit_without_anon_copy_says_so(self):
        chat, fid, name, anon, orig = self.make_chat("docx")
        o, _ = self.text_edit_ops(orig, name)
        self.fake.reply = lambda body: ["```json\n" + json.dumps({"v": 1, "ops": o}, ensure_ascii=False) + "\n```"]
        res, done = self.send(chat, "поправь срок на 30 дней", sources={fid: "original"}, confirm_originals=True)
        prop = done["edit"]["proposal"]
        orig_service = self.app.service.anonymize
        self.app.service.anonymize = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": prop["id"], "action": "apply", "ops": "all"})
        finally:
            self.app.service.anonymize = orig_service
        self.assertTrue(r["ok"], r)
        self.assertIn("Обезличенной копии нет", r["note"])

    # ---- text path and guard ---------------------------------------------------------------------
    def test_text_files_keep_the_old_path(self):
        _, chat = self.call("POST", "/api/chats", {"title": "t"})
        job = self.app.service.anonymize([Upload("d.txt", LINE1.encode())], {})
        out = Path(job.files[0].out_path).read_bytes()
        rec = self.app.chats.add_file(chat["id"], "d.txt", "text", tokens=list(job.files[0].tokens or []), anon=out, names={"anon": "d.txt"})
        self.call("POST", f"/api/ai/chats/{chat['id']}/toggle", {"on": True})
        new = out.decode().replace("10 дней", "30 дней")
        self.fake.reply = lambda body: ["Ок.\n<<<ФАЙЛ>>>\n" + new + "\n<<<КОНЕЦ>>>"]
        res, done = self.send(chat["id"], "поправь срок: 30 дней")
        self.assertTrue(done["edit"]["applied"], done["edit"])
        self.assertNotIn("proposal", done["edit"])

    def test_outbound_guard_on_anonymized_path(self):
        chat, fid, name, anon, orig = self.make_chat("docx", lambda: docx_bytes([LINE1, LINE3]))
        self.fake.reply = lambda body: ["Не вижу, что менять."]
        self.send(chat, "поправь срок на 30 дней")
        out = self.outbound()
        for leak in ("Иванов", "Пётр", SECRET):
            self.assertNotIn(leak, out)

    # ---- proposals persist -----------------------------------------------------------------------
    def test_proposal_survives_restart(self):
        chat, fid, name, anon, orig, res, done = self.propose("docx", "поправь срок на 30 дней", lambda f, a, n: self.text_edit_ops(a, n))
        pid = done["edit"]["proposal"]["id"]
        self.app.ai_chats.runs.clear()                                               # proposals live in the encrypted chat data, not in memory
        _, view = self.call("GET", f"/api/ai/chats/{chat}")
        self.assertEqual([p["id"] for p in view["proposals"]], [pid])
        st, r = self.call("POST", f"/api/ai/chats/{chat}/patch", {"id": pid, "action": "apply", "ops": "all"})
        self.assertTrue(r["ok"], r)


if __name__ == "__main__":
    unittest.main()
