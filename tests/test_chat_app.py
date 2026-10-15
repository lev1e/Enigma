"""App: задания записываются в чаты, очистка хранилища уносит чаты, расшифрованные копии чистятся."""
import time
import unittest
from pathlib import Path

from anonymizer.chats import ChatStore
from anonymizer.webapp import App

from .helpers import Env

TEXT_A = "Договор подписал Пётр Сидоров из ООО «Орбита-Гидропроект». Пётр Сидоров согласен."
TEXT_B = "Письмо для Анна Кузнецова. Копия: Пётр Сидоров."


class ChatAppCase(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.app = App(self.env.vault, self.env.base / "work", "tok")

    def tearDown(self):
        self.app.cleanup_open()
        self.env.close()

    def run_job(self, kind, items, chat_id=None, options=None):
        ids = [self.app.add_upload(name, data.encode("utf-8") if isinstance(data, str) else data)["id"]
               for name, data in items]
        job_id = self.app.start_job(kind, ids, options or {}, chat_id=chat_id)
        self.app.runners[job_id].join(30)
        return self.app.job_public(job_id)

    def only_chat(self):
        listing = self.app.chats.listing()
        self.assertEqual(len(listing), 1, listing)
        return self.app.chats.get(listing[0]["id"])


class RecordingTests(ChatAppCase):
    def test_job_without_chat_id_creates_a_chat_named_after_the_original_file(self):
        job = self.run_job("anonymize", [("Иванов договор.txt", TEXT_A)], options={"neutral_names": True})
        self.assertEqual(job["state"], "done")
        chat = self.only_chat()
        self.assertEqual(job["chat"], chat["id"])
        self.assertEqual(chat["title"], "Иванов договор")
        self.assertEqual(len(chat["files"]), 1)
        self.assertEqual(chat["steps"][-1]["kind"], "anonymize")
        record = chat["files"][0]
        self.assertTrue(record["tokens"])
        anon = self.app.chats.read_blob(chat["id"], record["id"], "anon")
        self.assertNotIn("Сидоров".encode(), anon)
        self.assertEqual(record["names"]["anon"], job["files"][0]["out_name"])

    def test_originals_are_stored_by_default(self):
        self.run_job("anonymize", [("a.txt", TEXT_A)])
        chat = self.only_chat()
        self.assertTrue(chat["keep_originals"])
        self.assertIn("orig", chat["files"][0]["roles"])
        stored = list((self.env.base / "chats").rglob("*.orig.bin"))
        self.assertEqual(len(stored), 1)
        self.assertNotIn(TEXT_A.encode("utf-8")[:20], stored[0].read_bytes())

    def test_originals_are_not_stored_when_the_setting_is_off(self):
        self.env.vault.set_prefs(keep_originals=False)
        self.run_job("anonymize", [("a.txt", TEXT_A)])
        chat = self.only_chat()
        self.assertNotIn("orig", chat["files"][0]["roles"])
        self.assertEqual([p for p in (self.env.base / "chats").rglob("*.orig.bin")], [])

    def test_originals_are_stored_when_the_chat_keeps_them(self):
        chat = self.app.chats.create("Кейс", keep_originals=True)
        self.run_job("anonymize", [("a.txt", TEXT_A)], chat_id=chat["id"])
        record = self.app.chats.get(chat["id"])["files"][0]
        self.assertEqual(self.app.chats.read_blob(chat["id"], record["id"], "orig"), TEXT_A.encode("utf-8"))

    def test_second_job_with_chat_id_extends_the_same_chat(self):
        first = self.run_job("anonymize", [("a.txt", TEXT_A)])
        self.run_job("anonymize", [("b.txt", TEXT_B)], chat_id=first["chat"])
        chat = self.only_chat()
        self.assertEqual(len(chat["files"]), 2)
        self.assertEqual([s["kind"] for s in chat["steps"]], ["anonymize", "anonymize"])
        # Пётр Сидоров встретился в обоих файлах: таблица чата считает его в двух файлах.
        rows = self.app.chats.table(chat["id"], self.env.vault)
        self.assertEqual(max(r["files"] for r in rows), 2)

    def test_unknown_chat_is_refused_before_the_job_starts(self):
        upload = self.app.add_upload("a.txt", TEXT_A.encode("utf-8"))["id"]
        with self.assertRaises(KeyError):
            self.app.start_job("anonymize", [upload], {}, chat_id="nosuchchat1")
        self.assertEqual(self.app.chats.listing(), [])

    def test_restore_in_chat_attaches_the_restored_version_to_the_anonymized_file(self):
        job = self.run_job("anonymize", [("a.txt", TEXT_A)])
        chat_id = job["chat"]
        anon_name = job["files"][0]["out_name"]
        anon = self.app.chats.read_blob(chat_id, self.app.chats.get(chat_id)["files"][0]["id"], "anon")
        self.run_job("restore", [(anon_name, anon)], chat_id=chat_id)
        chat = self.app.chats.get(chat_id)
        self.assertEqual(len(chat["files"]), 1)
        record = chat["files"][0]
        restored = self.app.chats.read_blob(chat_id, record["id"], "restored")
        self.assertIn("Пётр Сидоров", restored.decode("utf-8"))
        self.assertEqual([s["kind"] for s in chat["steps"]], ["anonymize", "restore"])

    def test_restore_under_another_name_attaches_by_matching_tokens(self):
        job = self.run_job("anonymize", [("a.txt", TEXT_A), ("b.txt", TEXT_B)])
        chat_id = job["chat"]
        first = self.app.chats.get(chat_id)["files"][0]
        anon = self.app.chats.read_blob(chat_id, first["id"], "anon")
        self.run_job("restore", [("ответ модели.txt", anon)], chat_id=chat_id)
        chat = self.app.chats.get(chat_id)
        self.assertEqual(len(chat["files"]), 2)
        self.assertIn("restored", chat["files"][0]["roles"])
        self.assertNotIn("restored", chat["files"][1]["roles"])

    def test_restore_with_ambiguous_tokens_adds_a_new_record(self):
        job = self.run_job("anonymize", [("a.txt", TEXT_A), ("a2.txt", TEXT_A)])
        chat_id = job["chat"]
        first = self.app.chats.get(chat_id)["files"][0]
        anon = self.app.chats.read_blob(chat_id, first["id"], "anon")
        self.run_job("restore", [("ответ.txt", anon)], chat_id=chat_id)
        self.assertEqual(len(self.app.chats.get(chat_id)["files"]), 3)

    def test_restore_with_other_name_lands_in_the_matching_chat(self):
        job = self.run_job("anonymize", [("a.txt", TEXT_A)])
        anon = self.env.output_bytes(self.app.service.jobs[job["id"]])
        back = self.run_job("restore", [("чужой.txt", anon)])
        self.assertEqual(back["chat"], job["chat"])          # возврат из черновика ищет чат по меткам файла
        self.assertEqual(len(self.app.chats.listing()), 1)

    def test_file_errors_are_recorded_without_versions(self):
        job = self.run_job("anonymize", [("a.exe", b"MZ\x00\x00")])
        self.assertEqual(job["files"][0]["status"], "error")
        chat = self.only_chat()              # задание завершилось, но с ошибкой по файлу: это шаг чата
        self.assertEqual(chat["files"][0]["status"], "error")
        self.assertEqual(chat["files"][0]["roles"], {})

    def test_job_is_not_done_before_the_chat_is_written(self):
        for _ in range(5):
            ids = [self.app.add_upload("a.txt", TEXT_A.encode("utf-8"))["id"]]
            job_id = self.app.start_job("anonymize", ids, {})
            deadline = time.time() + 30
            while time.time() < deadline:
                info = self.app.job_public(job_id)
                if info["state"] != "running":
                    break
                time.sleep(0.001)
            self.assertEqual(info["state"], "done")
            self.assertTrue(info["chat"])
            self.assertTrue(self.app.chats.get(info["chat"])["files"])


class LifecycleTests(ChatAppCase):
    def test_clearing_the_vault_wipes_chats(self):
        self.run_job("anonymize", [("a.txt", TEXT_A)])
        self.assertTrue((self.env.base / "chats").exists())
        self.app.clear_vault()
        self.assertEqual(self.app.chats.listing(), [])
        self.assertEqual([p for p in (self.env.base / "chats").rglob("*") if p.is_file()], [])
        self.assertEqual(self.env.vault.entities, {})

    def test_startup_imports_history_once_and_purges_old_chats(self):
        self.env.vault.log("anonymize", ["x.docx"], {"Люди": 2}, {"tokens": ["Name1"]})
        self.env.vault.commit()
        (self.env.base / "chats" / "history-imported.bin").unlink(missing_ok=True)    # состояние до первой миграции
        app = App(self.env.vault, self.env.base / "work", "tok")
        self.assertEqual(len(app.chats.listing()), 1)
        self.assertTrue(app.chats.listing()[0]["archived"])
        app = App(self.env.vault, self.env.base / "work", "tok")
        self.assertEqual(len(app.chats.listing()), 1)

    def test_old_chats_are_purged_at_startup_by_retention(self):
        chat = self.app.chats.create("Старый")
        stored = self.app.chats.get(chat["id"])
        stored["updated"] = time.time() - 400 * 86400
        # запись напрямую, чтобы не обновить «updated»
        import json
        from anonymizer import crypto
        from anonymizer.util import atomic_write
        raw = json.dumps(stored, ensure_ascii=False).encode("utf-8")
        atomic_write(self.env.base / "chats" / chat["id"] / "chat.bin", crypto.encrypt_blob(raw, self.env.key))
        self.env.vault.prefs["retention_days"] = 180
        app = App(self.env.vault, self.env.base / "work", "tok")
        self.assertEqual(app.chats.listing(), [])


class OpenFolderTests(ChatAppCase):
    def test_materialize_decrypts_to_the_open_folder_and_cleanup_removes_it(self):
        job = self.run_job("anonymize", [("a.txt", TEXT_A)])
        chat = self.only_chat()
        record = chat["files"][0]
        path = self.app.materialize(chat["id"], record["id"], "anon")
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, job["files"][0]["out_name"])
        self.assertEqual(path.read_bytes(), self.app.chats.read_blob(chat["id"], record["id"], "anon"))
        self.assertNotIn(self.env.base / "chats", path.parents)
        self.app.cleanup_open()
        self.assertFalse(path.exists())
        self.assertFalse(self.app.open_dir.exists() and any(self.app.open_dir.rglob("*")))

    def test_materialize_missing_version_is_an_error(self):
        self.run_job("anonymize", [("a.txt", TEXT_A)])
        chat = self.only_chat()
        with self.assertRaises(KeyError):
            self.app.materialize(chat["id"], chat["files"][0]["id"], "restored")

    def test_stale_open_folder_is_cleaned_when_the_app_starts(self):
        stale = self.env.base / "work" / ".open" / "leftover"
        stale.mkdir(parents=True)
        (stale / "x.txt").write_text("secret")
        App(self.env.vault, self.env.base / "work", "tok")
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
