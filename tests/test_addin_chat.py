"""Add-in и чаты (этап 4): задание из панели пишется в чат, повтор пополняет тот же чат, состояние документа,
поиск чата по меткам, короткий список замен, открытие чата в программе, откат по копии чата."""
import json
import time
import unittest
import urllib.parse

from .helpers import docx_bytes, docx_text
from .test_addin import AddinCase

SECRET = "Смирнов Алексей Петрович"
OTHER = "Кузнецова Мария Ивановна"


class PanelChatTests(AddinCase):
    def op(self, kind, name, data, chat=None, options=None):
        headers = {"X-Filename": urllib.parse.quote(name), "X-Options": urllib.parse.quote(json.dumps(options or {}))}
        if chat:
            headers["X-Chat"] = chat
        status, started = self.json("POST", f"/api/addin/{kind}", data, headers)
        self.assertEqual(status, 200, started)
        for _ in range(600):
            status, job = self.json("GET", f"/api/addin/jobs/{started['job']}")
            if job["state"] != "running":
                return started, job
            time.sleep(0.1)
        self.fail("задание не завершилось")

    def doc(self, text=SECRET):
        return docx_bytes([f"Директор {text}.", f"Подписал {text}."])

    def state(self, chat):
        status, body = self.json("GET", f"/api/addin/doc-state?chat={chat}")
        self.assertEqual(status, 200)
        return body

    # -- задания --

    def test_job_creates_chat_named_after_document_and_reports_it(self):
        started, job = self.op("anonymize", "Договор.docx", self.doc())
        self.assertEqual(job["state"], "done", job)
        self.assertTrue(job["chat"])
        chat = self.app.chats.get(job["chat"])
        self.assertEqual(chat["title"], "Договор")
        self.assertEqual(chat["bound_doc"], "Договор.docx")
        self.assertEqual(chat["addin_backup"], started["backup"])

    def test_second_anonymize_with_chat_id_tops_up_same_chat(self):
        _, first = self.op("anonymize", "Договор.docx", self.doc())
        _, second = self.op("anonymize", "Договор.docx", self.doc(OTHER), chat=first["chat"])
        self.assertEqual(second["chat"], first["chat"])
        self.assertEqual(len(self.app.chats.listing()), 1)
        chat = self.app.chats.get(first["chat"])
        self.assertEqual([s["kind"] for s in chat["steps"]], ["anonymize", "anonymize"])
        self.assertEqual(len(chat["files"]), 1)          # то же имя документа: запись заменена, дубля нет
        self.assertEqual(chat["files"][0]["name"], "Договор.docx")
        _, third = self.op("anonymize", "Письмо.docx", self.doc(), chat=first["chat"])
        self.assertEqual(len(self.app.chats.get(first["chat"])["files"]), 2)      # другое имя: новая запись

    def test_unknown_chat_id_is_404_before_anything_starts(self):
        status, _ = self.json("POST", "/api/addin/anonymize", self.doc(), {"X-Filename": "a.docx", "X-Chat": "nochat1"})
        self.assertEqual(status, 404)
        self.assertEqual(self.app.uploads, {})

    def test_restore_without_chat_attaches_by_tokens(self):
        _, anon = self.op("anonymize", "Договор.docx", self.doc())
        hidden = self.result(anon["id"])
        _, back = self.op("restore", "Скан-копия.docx", hidden)
        self.assertEqual(back["state"], "done", back)
        self.assertEqual(back["chat"], anon["chat"])
        self.assertEqual(len(self.app.chats.listing()), 1)
        self.assertEqual(self.state(anon["chat"])["chat"]["state"], "restored")
        self.assertIn(SECRET, docx_text(self.result(back["id"])))

    def test_restore_without_matching_chat_creates_one(self):
        _, anon = self.op("anonymize", "Договор.docx", self.doc())
        hidden = self.result(anon["id"])
        self.assertTrue(self.app.chats.delete(anon["chat"]))
        _, back = self.op("restore", "Договор.docx", hidden)
        self.assertEqual(back["state"], "done")
        self.assertEqual(len(self.app.chats.listing()), 1)

    # -- состояние --

    def test_doc_state_follows_the_chat(self):
        _, anon = self.op("anonymize", "Договор.docx", self.doc())
        chat = anon["chat"]
        info = self.state(chat)["chat"]
        self.assertEqual((info["state"], info["last_step_kind"], info["title"]), ("anonymized", "anonymize", "Договор"))
        self.assertGreater(info["replaced_total"], 0)
        self.assertTrue(info["has_backup"])
        self.assertEqual(info["pending_edits"], 0)
        table = self.app.chats.table(chat, self.app.vault)
        self.json("POST", f"/api/chats/{chat}/entities/{table[0]['base']}", json.dumps({"action": "hide", "variant": 1}).encode(),
                  {"Content-Type": "application/json"})
        self.assertEqual(self.state(chat)["chat"]["pending_edits"], 1)
        self.op("anonymize", "Договор.docx", self.doc(), chat=chat)
        self.assertEqual(self.state(chat)["chat"]["pending_edits"], 0)
        self.assertEqual(self.state(chat)["chat"]["state"], "anonymized")

    def test_doc_state_unknown_or_malformed_chat(self):
        self.assertEqual(self.state("nochat1"), {"found": False})
        self.assertEqual(self.state("../../x"), {"found": False})
        self.assertEqual(self.json("GET", "/api/addin/doc-state")[1], {"found": False})

    def test_backup_missing_means_no_rollback(self):
        started, anon = self.op("anonymize", "Договор.docx", self.doc())
        self.api.originals.discard(started["backup"])
        info = self.state(anon["chat"])["chat"]
        self.assertFalse(info["has_backup"])
        self.assertIsNone(info["backup"])

    def test_rollback_through_chat_backup_returns_the_original(self):
        original = self.doc()
        _, anon = self.op("anonymize", "Договор.docx", original)
        info = self.state(anon["chat"])["chat"]
        status, _, data = self.call("GET", f"/api/addin/backup/{info['backup']}")
        self.assertEqual((status, data), (200, original))
        # Возврат не затирает копию до обезличивания: откат по-прежнему возможен.
        self.op("restore", "Договор.docx", self.result(anon["id"]))
        self.assertTrue(self.state(anon["chat"])["chat"]["has_backup"])

    def test_match_finds_chat_by_tokens_only_when_unambiguous(self):
        _, anon = self.op("anonymize", "Договор.docx", self.doc())
        _, other = self.op("anonymize", "Письмо.docx", self.doc(OTHER))
        hidden = self.result(anon["id"])
        status, found = self.json("POST", "/api/addin/match", hidden, {"X-Filename": "x.docx"})
        self.assertEqual(status, 200)
        self.assertEqual((found["found"], found["chat"]["id"]), (True, anon["chat"]))
        self.assertEqual(self.json("POST", "/api/addin/match", self.doc(), {"X-Filename": "x.docx"})[1], {"found": False})
        self.assertEqual(self.json("POST", "/api/addin/match", b"junk", {"X-Filename": "x.docx"})[1], {"found": False})
        self.assertEqual(self.json("POST", "/api/addin/match", b"junk", {"X-Filename": "x.txt"})[1], {"found": False})
        # Документ с метками двух чатов поровну: однозначного ответа нет.
        both = docx_bytes([docx_text(hidden).splitlines()[0], docx_text(self.result(other["id"])).splitlines()[0]])
        self.assertEqual(self.json("POST", "/api/addin/match", both, {"X-Filename": "x.docx"})[1], {"found": False})

    # -- список замен --

    def test_chat_table_is_masked_and_capped(self):
        names = ["Смирнов Алексей Петрович", "Кузнецова Мария Ивановна", "Орлов Сергей Николаевич"]
        _, anon = self.op("anonymize", "Договор.docx", docx_bytes([f"Директор {n}." for n in names]))
        status, body = self.json("GET", f"/api/addin/chat-table?chat={anon['chat']}")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["rows"]), 3)
        text = json.dumps(body, ensure_ascii=False)
        for full in ("Алексей", "Кузнецова", "Николаевич", "Смирнов Алексей"):
            self.assertNotIn(full, text)
        row = body["rows"][0]
        self.assertTrue(row["value"].endswith("•"))
        self.assertEqual(len(row["value"]), 7 if len(row["value"]) > 7 else len(row["value"]))
        status, shown = self.json("GET", f"/api/addin/chat-table?chat={anon['chat']}&reveal=1")
        self.assertIn(names[0].split()[0], json.dumps(shown, ensure_ascii=False))

    def test_chat_table_row_cap(self):
        from anonymizer import addin
        saved = addin.CHAT_TABLE_ROWS
        addin.CHAT_TABLE_ROWS = 2
        try:
            _, anon = self.op("anonymize", "Договор.docx", docx_bytes([f"Директор {n}." for n in
                                                                      (SECRET, OTHER, "Орлов Сергей Николаевич")]))
            body = self.json("GET", f"/api/addin/chat-table?chat={anon['chat']}")[1]
        finally:
            addin.CHAT_TABLE_ROWS = saved
        self.assertEqual(len(body["rows"]), 2)
        self.assertGreater(body["total"], 2)

    def test_new_routes_require_token_origin_and_known_chat(self):
        _, anon = self.op("anonymize", "Договор.docx", self.doc())
        for method, path in (("GET", f"/api/addin/doc-state?chat={anon['chat']}"), ("GET", f"/api/addin/chat-table?chat={anon['chat']}"),
                             ("POST", "/api/addin/match"), ("POST", "/api/addin/open-app")):
            self.assertEqual(self.call(method, path, b"{}" if method == "POST" else None, token=False)[0], 403, path)
            self.assertEqual(self.call(method, path, b"{}" if method == "POST" else None, auth=False)[0], 403, path)
            self.assertEqual(self.call(method, path, b"{}" if method == "POST" else None,
                                       headers={"Origin": "https://evil.example"})[0], 403, path)
            headers = {"X-Addin-Token": "wrong"}
            status, _, _ = self.call(method, path, b"{}" if method == "POST" else None, token=False,
                                     headers={"X-Requested-With": "anonymizer", **headers})
            self.assertEqual(status, 403, path)
        self.assertEqual(self.json("GET", "/api/addin/chat-table?chat=nochat1")[0], 404)

    # -- открыть в приложении --

    def test_open_app_with_chat_sets_open_chat_once(self):
        _, anon = self.op("anonymize", "Договор.docx", self.doc())
        calls = []
        self.app.on_focus = lambda: calls.append(1)
        status, _ = self.json("POST", "/api/addin/open-app", json.dumps({"chat": anon["chat"]}).encode(),
                              {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(calls, [1])
        self.assertEqual(self.app.open_chat, anon["chat"])
        self.assertEqual(self.app.take_open_chat(), anon["chat"])
        self.assertEqual(self.app.take_open_chat(), "")
        self.json("POST", "/api/addin/open-app", json.dumps({"chat": "nochat1"}).encode(), {"Content-Type": "application/json"})
        self.assertEqual(self.app.open_chat, "")


if __name__ == "__main__":
    unittest.main()


class DialogPageTests(AddinCase):
    """Страница `/addin/chat` для диалога Office: та же страница окна с настройкой ANON_DIALOG и токеном."""
    op = PanelChatTests.op
    doc = PanelChatTests.doc

    def chat_id(self):
        return self.op("anonymize", "Договор.docx", self.doc())[1]["chat"]

    def page(self, chat, **kw):
        return self.call("GET", f"/addin/chat?chat={chat}", **kw)

    def test_page_carries_chat_and_token_before_other_scripts(self):
        chat = self.chat_id()
        status, headers, data = self.page(chat, auth=False)          # страницу открывает Office без заголовков API
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        html = data.decode("utf-8")
        self.assertIn("window.ANON_DIALOG=" + json.dumps({"chat": chat, "token": self.api.token}), html)
        self.assertLess(html.index("window.ANON_DIALOG"), html.index('"use strict"'))
        self.assertIn('id="btn-dialog-close"', html)

    def test_malformed_chat_id_is_404_and_does_not_inject(self):
        for bad in ("", "A", "ab", "x" * 40, "<script>", "abc/../def", "abc%3Cdef"):
            status, _, data = self.page(bad, auth=False)
            self.assertEqual(status, 404, bad)
            self.assertNotIn(b"ANON_DIALOG=", data)

    def test_state_and_jobs_need_the_token(self):
        chat = self.chat_id()
        for path in ("/api/state", "/api/jobs/abc123", f"/api/chats/{chat}"):
            self.assertEqual(self.call("GET", path, token=False)[0], 403, path)
            self.assertEqual(self.call("GET", path, auth=False)[0], 403, path)
        status, state = self.json("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertNotIn("open_chat", state)         # забирает только окно программы
        self.assertEqual(self.json("GET", "/api/jobs/zzzzzz")[0], 404)

    def test_chat_routes_work_with_token_from_page(self):
        chat = self.chat_id()
        status, body = self.json("GET", f"/api/chats/{chat}")
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], chat)
        self.assertTrue(body["table"])
        status, renamed = self.json("POST", f"/api/chats/{chat}", json.dumps({"title": "Новое имя"}).encode(), {"Content-Type": "application/json"})
        self.assertEqual(status, 200, renamed)
        self.assertEqual(self.json("GET", f"/api/chats/{chat}")[1]["title"], "Новое имя")

    def test_page_script_has_dialog_mode_contract(self):
        from anonymizer.addin import WEB_DIR
        html = (WEB_DIR / "index.html").read_text("utf-8")
        self.assertIn('"X-Addin-Token"', html)
        self.assertIn('messageParent("close")', html)
        self.assertIn("/addin/vendor/office.js", html)
        self.assertNotIn('<script src="/addin/vendor/office.js"', html)      # office.js грузится только в режиме диалога
