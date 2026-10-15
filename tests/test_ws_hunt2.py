"""Охота 2: общие списки при загрузке таблицы, открытый текст в рабочей папке, остатки в vault.bak."""
import os
import time
import unittest
from pathlib import Path

from anonymizer import service as svc
from anonymizer.chats import ChatStore

from .helpers import Env
from .test_review_fixes import finish, make_app, run_job
from .test_table_io import TableBase


class TableImportStaysInChat(TableBase):
    def test_apply_and_undo_leave_global_lists_empty(self):
        row = next(r for r in self.table() if r["kind"] == "PERSON")
        code = row["variants"][0]["token"]
        value = row["variants"][0]["value"]
        plan = self.preview([["Код", "Значение", "Скрывать", "Объединить с"], [code, value, "нет", ""]])      # «Скрывать» = нет → слово в «оставить»
        done = self.apply(plan["token"])
        self.assertEqual(done["applied"]["ai"], 1)
        self.assertEqual(self.app.vault.prefs["hide_terms"], [])
        self.assertEqual(self.app.vault.prefs["keep_terms"], [])
        self.assertTrue(self.app.chats.terms(self.chat)["keep_terms"])
        self.call("POST", f"/api/chats/{self.chat}/entities/{row['base']}", {"action": "undo", **done["undo"]})
        self.assertEqual(self.app.vault.prefs["keep_terms"], [])
        self.assertEqual(self.app.chats.terms(self.chat), {"hide_terms": [], "keep_terms": []})


class OutputRetention(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)
        self.job_id = run_job(self.app, "anonymize", [("a.txt", "Пётр Сидоров подписал договор. Пётр Сидоров согласен.\n")])
        finish(self.app, self.job_id)
        self.job = self.app.service.jobs[self.job_id]
        self.assertTrue(self.job.chat)
        self.out = Path(self.job.files[0].out_path)

    def age(self, seconds):
        stamp = time.time() - seconds
        os.utime(self.job.dir / "out", (stamp, stamp))

    def test_fresh_output_is_kept_and_downloadable(self):
        self.app.service.cleanup()
        self.assertTrue(self.out.is_file())
        self.assertIsNotNone(self.app.service.output_path(self.job_id, 0))

    def test_output_is_shredded_after_ttl(self):
        self.age(svc.OUTPUT_TTL + 5)
        self.app.service.cleanup()
        self.assertFalse(self.out.exists())
        self.assertFalse((self.job.dir / "out").exists())
        self.assertIsNone(self.app.service.output_path(self.job_id, 0))
        self.assertFalse(self.app.job_public(self.job_id)["files"][0]["downloadable"])

    def test_delivered_output_goes_after_grace_not_before(self):
        self.app.service.note_delivered(self.job_id)
        self.app.service.cleanup()
        self.assertTrue(self.out.is_file())                       # повторное «Сохранить» ещё работает
        self.job.delivered[0] = time.time() - svc.DELIVERED_GRACE - 5
        self.app.service.cleanup()
        self.assertFalse(self.out.exists())

    def test_output_not_in_chat_is_kept_until_job_ttl(self):
        self.job.chat = ""                                        # запись в чат не удалась: других копий нет
        self.age(svc.OUTPUT_TTL * 4)
        self.app.service.cleanup()
        self.assertTrue(self.out.is_file())

    def test_running_job_is_never_cleaned(self):
        self.job.state = "running"
        self.age(svc.OUTPUT_TTL * 4)
        self.app.service.cleanup(older_than=1, inputs_older_than=0)
        self.assertTrue(self.out.is_file())

    def test_cleanup_overwrites_before_unlinking(self):
        calls = []
        original = ChatStore._shred
        ChatStore._shred = staticmethod(lambda p: (calls.append(Path(p).name), original(p))[1])
        try:
            self.age(svc.OUTPUT_TTL + 5)
            self.app.service.cleanup()
        finally:
            ChatStore._shred = staticmethod(original)
        self.assertIn(self.out.name, calls)

    def test_maintenance_thread_runs_cleanup_and_stops(self):
        self.age(svc.OUTPUT_TTL + 5)
        self.app.MAINTENANCE_SECONDS = 0.05
        thread = self.app.start_maintenance()
        deadline = time.time() + 5
        while self.out.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.out.exists())
        self.app.stop.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class VaultBackupHoldsNoErasedData(unittest.TestCase):
    def test_forget_and_clear_drop_the_backup(self):
        env = Env()
        self.addCleanup(env.close)
        vault = env.vault
        bak = vault.path.with_suffix(".bak")
        app = make_app(env)
        self.addCleanup(app.cleanup_open)
        run_job(app, "anonymize", [("a.txt", "Пётр Сидоров подписал договор.\n")])
        vault.dirty = True
        vault.save()
        vault.dirty = True
        vault.save()
        self.assertTrue(bak.exists())                             # обычное сохранение держит копию прежнего состояния
        base = next(b for b, e in vault.entities.items() if e["kind"] == "PERSON")
        vault.forget(base)
        self.assertFalse(bak.exists())
        vault.save()
        vault.save()
        self.assertTrue(bak.exists())
        vault.clear()
        self.assertFalse(bak.exists())


if __name__ == "__main__":
    unittest.main()
