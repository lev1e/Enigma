"""Состояние чата для панели Office: сводка, привязка документа, поиск чата по меткам, чат на открытие в окне."""
import json
import unittest

from anonymizer.tokens import base_of

from .test_chat_app import TEXT_A, TEXT_B, ChatAppCase


class SummaryTests(ChatAppCase):
    def test_summary_none_for_unknown_chat(self):
        self.assertIsNone(self.app.chat_summary("nochat1"))

    def test_summary_tracks_steps_and_pending_edits(self):
        job = self.run_job("anonymize", [("a.txt", TEXT_A)])
        chat_id = job["chat"]
        info = self.app.chat_summary(chat_id)
        self.assertEqual((info["state"], info["last_step_kind"], info["pending_edits"]), ("anonymized", "anonymize", 0))
        self.assertGreater(info["replaced_total"], 0)
        self.app.chats.add_step(chat_id, "edit", action="keep", base="Name1")
        self.app.chats.add_step(chat_id, "edit", action="edit", base="Name1")        # правка значения не требует пересборки
        self.assertEqual(self.app.chat_summary(chat_id)["pending_edits"], 1)
        anon = self.app.chats.read_blob(chat_id, self.app.chats.get(chat_id)["files"][0]["id"], "anon")
        back = self.run_job("restore", [(job["files"][0]["out_name"], anon)], chat_id=chat_id)
        self.assertEqual(back["state"], "done")
        info = self.app.chat_summary(chat_id)
        self.assertEqual((info["state"], info["last_step_kind"]), ("restored", "restore"))
        self.run_job("anonymize", [("a.txt", TEXT_A)], chat_id=chat_id)
        self.assertEqual(self.app.chat_summary(chat_id)["pending_edits"], 0)

    def test_empty_chat_has_no_state(self):
        chat = self.app.chats.create("Пустой")
        info = self.app.chat_summary(chat["id"])
        self.assertEqual((info["state"], info["last_step_kind"], info["files"]), ("none", None, 0))

    def test_bind_and_backup_setters(self):
        chat = self.app.chats.create("Кейс")
        self.app.chats.bind(chat["id"], "Договор.docx")
        self.app.chats.set_backup(chat["id"], "abc12345")
        got = self.app.chats.get(chat["id"])
        self.assertEqual((got["bound_doc"], got["addin_backup"]), ("Договор.docx", "abc12345"))
        self.assertEqual(self.app.chat_summary(chat["id"])["bound_doc"], "Договор.docx")
        self.assertEqual(self.app.chats.listing()[0]["bound_doc"], "Договор.docx")
        with self.assertRaises(KeyError):
            self.app.chats.bind("nochat1", "x.docx")

    def test_match_by_tokens_needs_a_unique_best_chat(self):
        a = self.run_job("anonymize", [("a.txt", TEXT_A)])
        b = self.run_job("anonymize", [("b.txt", TEXT_B)])
        tokens_a = self.app.chats.get(a["chat"])["files"][0]["tokens"]
        tokens_b = self.app.chats.get(b["chat"])["files"][0]["tokens"]
        self.assertEqual(self.app.match_chat_by_tokens(tokens_a), a["chat"])
        self.assertIsNone(self.app.match_chat_by_tokens([]))
        self.assertIsNone(self.app.match_chat_by_tokens(["Unknown99"]))
        shared = {base_of(t) for t in tokens_a} & {base_of(t) for t in tokens_b}
        if shared:      # общая метка у двух чатов: по одной ей выбрать нельзя
            self.assertIsNone(self.app.match_chat_by_tokens([t for t in tokens_a if base_of(t) in shared][:1]))

    def test_state_route_returns_open_chat_once(self):
        import threading
        import urllib.request

        from anonymizer.webapp import create_server
        from .helpers import Env
        server, app = create_server(self.env.vault, self.env.base / "work2", port=0)
        app.token = "t0k"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def state():
                req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/state",
                                             headers={"Cookie": "anon_t=t0k", "X-Requested-With": "anonymizer"})
                return json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
            self.assertEqual(state()["open_chat"], "")
            app.open_chat = "abc123"
            self.assertEqual(state()["open_chat"], "abc123")
            self.assertEqual(state()["open_chat"], "")
        finally:
            server.shutdown()
            server.server_close()
            app.cleanup_open()


if __name__ == "__main__":
    unittest.main()
