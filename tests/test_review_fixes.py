"""Регрессии по аудиту таблицы и рабочего стола: скрытие слова над готовой сущностью, частичная пересборка и др."""
from __future__ import annotations

import unittest

from tests.helpers import Env

DOC = "Иван Петров пришёл. Позвонить Петрову сегодня. Иван Петров согласен.\n"


class HideOverExistingEntity(unittest.TestCase):
    def test_hide_person_term_reuses_code_and_keeps_other_forms(self):
        env = Env()
        self.addCleanup(env.close)
        first = env.anonymize(("a.txt", DOC))
        self.assertNotIn("Петров", env.output_bytes(first).decode())
        before = set(env.vault.entities)
        env.vault.add_term("hide_terms", "Иван Петров")
        job = env.anonymize(("a.txt", DOC))
        out = env.output_bytes(job).decode()
        self.assertNotIn("Петров", out)
        self.assertNotIn("Term", out)
        self.assertEqual(set(env.vault.entities), before)          # новой сущности нет
        back = env.restore(env.as_upload(job))
        self.assertIn("Петров", env.output_bytes(back).decode())

    def test_hide_org_term_over_existing_org_keeps_one_entity(self):
        env = Env()
        self.addCleanup(env.close)
        doc = "Подписал ООО «Ромашка». Позвонить в Ромашку.\n"
        env.anonymize(("a.txt", doc))
        before = {b for b, e in env.vault.entities.items()}
        env.vault.add_term("hide_terms", "ромашка")
        job = env.anonymize(("a.txt", doc))
        self.assertNotIn("омашк", env.output_bytes(job).decode())
        self.assertEqual({b for b in env.vault.entities}, before)


class TextVaultMarker(unittest.TestCase):
    TEXT = "Пётр Сидоров подписал договор. Пётр Сидоров согласен.\n"

    def test_text_restore_refused_after_vault_cleared(self):
        env = Env()
        self.addCleanup(env.close)
        job = env.anonymize(("a.txt", self.TEXT))
        anon = env.as_upload(job)
        env.vault.clear()
        env.anonymize(("b.txt", "Анна Кузнецова пишет. Анна Кузнецова звонит.\n"))   # Name1 теперь другой человек
        back = env.restore(anon)
        self.assertEqual(back.files[0].status, "error")
        self.assertIn("другим хранилищем", back.files[0].messages[0]["text"])
        self.assertFalse(back.files[0].out_path)

    def test_text_restore_against_other_vault_refused(self):
        a, b = Env(), Env()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        anon = a.as_upload(a.anonymize(("a.txt", self.TEXT)))
        b.anonymize(("b.txt", "Анна Кузнецова пишет. Анна Кузнецова звонит.\n"))
        self.assertEqual(b.restore(anon).files[0].status, "error")

    def test_marker_is_invisible_and_stripped_on_restore(self):
        env = Env()
        self.addCleanup(env.close)
        job = env.anonymize(("a.txt", self.TEXT))
        shown = "".join(ch for ch in env.output_bytes(job).decode() if not 0xE0000 <= ord(ch) <= 0xE007F)
        self.assertEqual(shown.strip(), shown.strip())
        self.assertNotIn("Сидоров", shown)
        back = env.restore(env.as_upload(job))
        text = env.output_bytes(back).decode()
        self.assertEqual(text, self.TEXT)

    def test_old_text_without_marker_still_restores(self):
        env = Env()
        self.addCleanup(env.close)
        job = env.anonymize(("a.txt", self.TEXT))
        old = "".join(ch for ch in env.output_bytes(job).decode() if not 0xE0000 <= ord(ch) <= 0xE007F)
        back = env.restore(("old.txt", old))
        self.assertEqual(back.files[0].status in ("ok", "attention"), True)
        self.assertIn("Сидоров", env.output_bytes(back).decode())


def make_app(env):
    from anonymizer.webapp import App
    return App(env.vault, env.base / "work", "tok")


def run_job(app, kind, items, **kwargs):
    ids = [app.add_upload(name, data.encode("utf-8") if isinstance(data, str) else data)["id"] for name, data in items]
    job_id = app.start_job(kind, ids, kwargs.pop("options", {}), **kwargs)
    app.runners[job_id].join(30)
    return job_id


def finish(app, job_id):
    app.runners[job_id].join(30)
    return app.job_public(job_id)


class PartialRebuild(unittest.TestCase):
    A = "Пётр Сидоров подписал договор. Пётр Сидоров согласен.\n"
    B = "Письмо для Анна Кузнецова. Анна Кузнецова ждёт.\n"

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)

    def test_files_without_original_are_reported_and_stay_stale(self):
        app = self.app
        chat = app.chats.create("Кейс", keep_originals=False)
        run_job(app, "anonymize", [("a.txt", self.A)], chat_id=chat["id"])
        app.chats.set_keep_originals(chat["id"], True)
        run_job(app, "anonymize", [("b.txt", self.B)], chat_id=chat["id"])
        self.env.vault.add_term("hide_terms", "согласен")
        app.chats.add_step(chat["id"], "edit", action="hide", base="x")
        self.assertEqual(app.chat_summary(chat["id"])["pending_edits"], 1)
        job_id = app.apply_chat(chat["id"], {})
        public = finish(app, job_id)
        self.assertEqual(public["state"], "done")
        self.assertEqual(public["result"]["not_updated"], ["a.txt"])
        summary = app.chat_summary(chat["id"])
        self.assertEqual(summary["pending_edits"], 1)                    # правка к файлу a.txt так и не применена
        self.assertEqual(summary["stale_files"], 1)
        files = {f["name"]: f for f in app.chats.get(chat["id"])["files"]}
        self.assertTrue(files["a.txt"].get("stale"))
        self.assertFalse(files["b.txt"].get("stale"))

    def test_apply_with_all_originals_clears_pending(self):
        app = self.app
        chat = app.chats.create("Кейс", keep_originals=True)
        run_job(app, "anonymize", [("a.txt", self.A)], chat_id=chat["id"])
        app.chats.add_step(chat["id"], "edit", action="hide", base="x")
        public = finish(app, app.apply_chat(chat["id"], {}))
        self.assertEqual(public["result"].get("not_updated", []), [])
        self.assertEqual(app.chat_summary(chat["id"])["pending_edits"], 0)

    def test_apply_with_no_originals_still_errors(self):
        app = self.app
        chat = app.chats.create("Кейс", keep_originals=True)
        run_job(app, "anonymize", [("a.txt", self.A)], chat_id=chat["id"])
        app.chats.set_keep_originals(chat["id"], False)
        app.chats.set_keep_originals(chat["id"], True)
        with self.assertRaises(ValueError):
            app.apply_chat(chat["id"], {})


class RebuildOptionsAndPrevious(unittest.TestCase):
    TEXT = "Пётр Сидоров приехал из Германии. Пётр Сидоров согласен.\n"

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)

    def test_rebuild_uses_original_options_and_keeps_previous_version(self):
        app = self.app
        chat = app.chats.create("Кейс", keep_originals=True)
        run_job(app, "anonymize", [("a.txt", self.TEXT)], chat_id=chat["id"], options={"countries": False})
        record = app.chats.get(chat["id"])["files"][0]
        first = app.chats.read_blob(chat["id"], record["id"], "anon")
        self.assertIn("Германи".encode(), first)
        step = app.chats.get(chat["id"])["steps"][-1]
        self.assertEqual(step["options"]["countries"], False)
        # на главном экране параметры уже другие: пересборка чата их игнорирует
        self.env.vault.add_term("hide_terms", "согласен")
        public = finish(app, app.apply_chat(chat["id"], {"countries": True}))
        self.assertEqual(public["state"], "done")
        record = app.chats.get(chat["id"])["files"][0]
        second = app.chats.read_blob(chat["id"], record["id"], "anon")
        self.assertIn("Германи".encode(), second)
        self.assertNotIn("согласен".encode(), second)
        self.assertEqual(app.chats.read_blob(chat["id"], record["id"], "prev"), first)
        self.assertIn("prev", record["roles"])


class ChatWriteFailure(unittest.TestCase):
    def test_failed_chat_write_leaves_result_savable_with_warning(self):
        env = Env()
        self.addCleanup(env.close)
        app = make_app(env)
        self.addCleanup(app.cleanup_open)

        def boom(*args, **kwargs):
            raise OSError("disk full")
        app._write_chat = boom
        public = finish(app, run_job(app, "anonymize", [("a.txt", "Пётр Сидоров согласен. Пётр Сидоров здесь.\n")]))
        self.assertEqual(public["state"], "done")
        self.assertEqual(public["chat"], "")
        self.assertIn("не удалось записать в чат", public["warning"])
        self.assertTrue(public["files"][0]["downloadable"])


class HistoryImportIdempotent(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def store(self):
        from anonymizer.chats import ChatStore
        return ChatStore(self.env.base / "chats", key=self.env.key)

    def test_import_once_no_ghosts_no_resurrection(self):
        vault = self.env.vault
        vault.log("anonymize", ["old.docx"], {"Имена": 1}, {"tokens": []})
        store = self.store()
        self.assertEqual(store.import_history(vault), 1)
        ghost = store.listing()[0]["id"]
        store.delete(ghost)
        vault.log("anonymize", ["new.docx"], {"Имена": 1}, {"tokens": []})      # новое задание: у него свой настоящий чат
        store.create("new")
        for _ in range(2):                                                     # «перезапуск»: новое хранилище чатов на том же диске
            store = self.store()
            self.assertEqual(store.import_history(vault), 0)
        self.assertEqual([c["title"] for c in store.listing()], ["new"])

    def test_existing_real_chats_block_ghost_import(self):
        vault = self.env.vault
        store = self.store()
        chat = store.create("real")
        store.add_file(chat["id"], "a.txt", "TEXT", anon=b"x")
        vault.log("anonymize", ["a.txt"], {"Имена": 1}, {"tokens": []})
        self.assertEqual(store.import_history(vault), 0)
        self.assertEqual(len(store.listing()), 1)


class HideNewWordFromChat(unittest.TestCase):
    TEXT = "Пётр Сидоров подписал договор с Ромашкой. Пётр Сидоров согласен.\n"

    def setUp(self):
        from anonymizer import chat_api
        self.api = chat_api
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)
        self.chat = self.app.chats.create("Кейс", keep_originals=True)
        run_job(self.app, "anonymize", [("a.txt", self.TEXT)], chat_id=self.chat["id"])

    def post(self, data):
        return self.api.handle(self.app, "POST", f"/api/chats/{self.chat['id']}/entities/_", lambda: data)[1]

    def test_hide_new_word_is_persisted_marks_chat_stale_and_rebuilds(self):
        self.assertEqual(self.app.chat_summary(self.chat["id"])["pending_edits"], 0)
        answer = self.post({"action": "hide_new", "term": "договор"})
        self.assertFalse(answer["already_hidden"])
        self.assertIsNone(answer["covered_by"])
        self.assertIn("договор", self.app.chats.terms(self.chat["id"])["hide_terms"])   # слово чата, не общих настроек
        self.assertNotIn("договор", self.env.vault.prefs.get("hide_terms", []))
        self.assertEqual(self.app.chat_summary(self.chat["id"])["pending_edits"], 1)
        public = finish(self.app, self.app.apply_chat(self.chat["id"], {}))
        self.assertEqual(public["state"], "done")
        record = self.app.chats.get(self.chat["id"])["files"][0]
        self.assertNotIn("договор".encode(), self.app.chats.read_blob(self.chat["id"], record["id"], "anon"))
        self.assertEqual(self.app.chat_summary(self.chat["id"])["pending_edits"], 0)

    def test_hide_new_reports_already_covered_word(self):
        base = self.app.chats.table(self.chat["id"], self.env.vault)[0]["base"]
        spelling = self.env.vault.describe(base)["variants"][0]["original"]
        answer = self.post({"action": "hide_new", "term": spelling.lower()})
        self.assertEqual(answer["covered_by"], base)
        again = self.post({"action": "hide_new", "term": spelling.lower()})
        self.assertTrue(again["already_hidden"])

    def test_hide_new_rejects_empty_word(self):
        with self.assertRaises(ValueError):
            self.post({"action": "hide_new", "term": "  "})


class RestoreLandsInMatchingChat(unittest.TestCase):
    def test_restore_without_chat_id_uses_matching_chat(self):
        env = Env()
        self.addCleanup(env.close)
        app = make_app(env)
        self.addCleanup(app.cleanup_open)
        chat = app.chats.create("Кейс", keep_originals=True)
        run_job(app, "anonymize", [("a.txt", "Пётр Сидоров подписал. Пётр Сидоров согласен.\n")], chat_id=chat["id"])
        record = app.chats.get(chat["id"])["files"][0]
        anon = app.chats.read_blob(chat["id"], record["id"], "anon")
        public = finish(app, run_job(app, "restore", [("ИИ ответ.txt", anon)]))
        self.assertEqual(public["chat"], chat["id"])
        self.assertEqual(len(app.chats.listing()), 1)


if __name__ == "__main__":
    unittest.main()
