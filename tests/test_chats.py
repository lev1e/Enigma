import os
import tempfile
import time
import unittest
from pathlib import Path

from anonymizer import crypto
from anonymizer.chats import ChatStore
from anonymizer.vault import Vault


class ChatStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key = os.urandom(32)
        self.store = ChatStore(self.root / "chats", key=self.key)
        self.vault = Vault(self.root / "vault.bin", key=self.key)

    def tearDown(self):
        self.tmp.cleanup()

    def files_on_disk(self):
        return [p for p in (self.root / "chats").rglob("*") if p.is_file()]

    # -- чаты -----------------------------------------------------------------

    def test_create_list_rename_roundtrip_and_newest_first(self):
        first = self.store.create("Договор")
        time.sleep(0.01)
        second = self.store.create("Письма")
        self.assertEqual([c["id"] for c in self.store.listing()], [second["id"], first["id"]])
        self.store.rename(first["id"], "Договор поставки")
        self.assertEqual(self.store.get(first["id"])["title"], "Договор поставки")
        with self.assertRaises(ValueError):
            self.store.rename(first["id"], "  ")

    def test_everything_on_disk_is_encrypted(self):
        chat = self.store.create("Секретный договор Иванова")
        record = self.store.add_file(chat["id"], "Иванов.docx", "OOXML", anon=b"PK-anon-content", restored=b"PK-real-Ivanov")
        for path in self.files_on_disk():
            raw = path.read_bytes()
            self.assertNotIn("Иванов".encode("utf-8"), raw)
            self.assertNotIn(b"PK-real", raw)
        self.assertEqual(self.store.read_blob(chat["id"], record["id"], "anon"), b"PK-anon-content")

    def test_foreign_key_cannot_read_chats(self):
        chat = self.store.create("A")
        other = ChatStore(self.root / "chats", key=os.urandom(32))
        self.assertIsNone(other.get(chat["id"]))
        self.assertEqual(other.listing(), [])

    def test_ids_are_validated_against_path_traversal(self):
        for bad in ("../x", "..", "a/b", "", "ABC123", "x" * 40):
            self.assertIsNone(self.store.get(bad))
        chat = self.store.create("A")
        self.assertIsNone(self.store.read_blob(chat["id"], "../../etc", "anon"))
        record = self.store.add_file(chat["id"], "a.docx", "OOXML")
        with self.assertRaises(ValueError):
            self.store.save_blob(chat["id"], record["id"], "bogus", b"x")

    # -- исходники ------------------------------------------------------------

    def test_originals_are_not_stored_without_the_checkbox(self):
        chat = self.store.create("A")
        record = self.store.add_file(chat["id"], "a.docx", "OOXML", anon=b"anon", orig=b"REAL-ORIGINAL")
        self.assertNotIn("orig", record["roles"])
        self.assertIsNone(self.store.read_blob(chat["id"], record["id"], "orig"))
        self.assertEqual(len(self.files_on_disk()), 2)        # chat.bin + anon

    def test_originals_stored_with_checkbox_and_erased_when_it_is_cleared(self):
        chat = self.store.create("A", keep_originals=True)
        record = self.store.add_file(chat["id"], "a.docx", "OOXML", anon=b"anon", orig=b"REAL-ORIGINAL")
        self.assertEqual(self.store.read_blob(chat["id"], record["id"], "orig"), b"REAL-ORIGINAL")
        self.store.set_keep_originals(chat["id"], False)
        self.assertIsNone(self.store.read_blob(chat["id"], record["id"], "orig"))
        self.assertNotIn("orig", self.store.get(chat["id"])["files"][0]["roles"])
        self.assertEqual(len(self.files_on_disk()), 2)

    # -- удаление -------------------------------------------------------------

    def test_delete_removes_files_and_keeps_vault_labels(self):
        token = self.vault.token_for("PERSON", "a", "Иванов")
        chat = self.store.create("A")
        self.store.add_file(chat["id"], "a.docx", "OOXML", tokens=[token], anon=b"x", restored=b"y")
        self.assertTrue(self.store.delete(chat["id"]))
        self.assertEqual(self.files_on_disk(), [])
        self.assertIsNone(self.store.get(chat["id"]))
        self.assertEqual(self.vault.token_for("PERSON", "a", "Иванов"), token)
        self.assertFalse(self.store.delete(chat["id"]))

    def test_wipe_removes_every_chat(self):
        for title in "abc":
            self.store.create(title)
        self.store.wipe()
        self.assertEqual(self.store.listing(), [])
        self.assertEqual(self.files_on_disk(), [])

    def test_remove_file_erases_all_its_versions(self):
        chat = self.store.create("A", keep_originals=True)
        record = self.store.add_file(chat["id"], "a.docx", "OOXML", anon=b"1", restored=b"2", orig=b"3")
        self.store.remove_file(chat["id"], record["id"])
        self.assertEqual(self.store.get(chat["id"])["files"], [])
        self.assertEqual(len(self.files_on_disk()), 1)

    # -- таблица замен --------------------------------------------------------

    def test_table_is_a_view_of_the_vault_and_follows_edits(self):
        t1 = self.vault.token_for("PERSON", "a", "Иванов")
        t2 = self.vault.token_for("PERSON", "b", "Ваня")
        c1 = self.vault.token_for("ORG", "o", "Орбита")
        chat = self.store.create("A")
        self.store.add_file(chat["id"], "f1.docx", "OOXML", tokens=[t1, c1])
        self.store.add_file(chat["id"], "f2.docx", "OOXML", tokens=[t1, t2])
        rows = self.store.table(chat["id"], self.vault)
        self.assertEqual([r["base"] for r in rows], ["Name1", "Name2", "Company1"])
        self.assertEqual(rows[0]["files"], 2)
        self.vault.merge("Name2", "Name1")
        rows = self.store.table(chat["id"], self.vault)
        self.assertEqual([r["base"] for r in rows], ["Name1", "Company1"])
        self.assertEqual(rows[0]["merged"], ["Name2"])
        self.assertEqual(rows[0]["files"], 2)
        self.vault.edit_value("Name1", 1, "Иванов И. И.")
        self.assertEqual(self.store.table(chat["id"], self.vault)[0]["variants"][0]["value"], "Иванов И. И.")

    def test_table_skips_tokens_that_are_not_in_the_vault(self):
        chat = self.store.create("A")
        self.store.add_file(chat["id"], "f.docx", "OOXML", tokens=["Name99", "not a token"])
        self.assertEqual(self.store.table(chat["id"], self.vault), [])

    def test_chats_using_finds_chat_by_labels_even_after_merge(self):
        t1 = self.vault.token_for("PERSON", "a", "Иванов")
        t2 = self.vault.token_for("PERSON", "b", "Петров")
        chat = self.store.create("A")
        self.store.add_file(chat["id"], "f.docx", "OOXML", tokens=[t2])
        self.vault.merge("Name2", "Name1")
        self.assertEqual(self.store.chats_using({t1.split("_")[0]}, self.vault), [chat["id"]])
        self.assertEqual(self.store.chats_using({"Name77"}, self.vault), [])

    # -- ход ленты ------------------------------------------------------------

    def test_steps_are_kept_and_capped(self):
        chat = self.store.create("A")
        for index in range(520):
            self.store.add_step(chat["id"], "anonymize", n=index)
        steps = self.store.get(chat["id"])["steps"]
        self.assertEqual(len(steps), 500)
        self.assertEqual(steps[-1]["n"], 519)

    # -- срок хранения --------------------------------------------------------

    def test_purge_drops_restored_versions_first_and_old_chats_later(self):
        old = self.store.create("old")
        fresh = self.store.create("fresh")
        record = self.store.add_file(fresh["id"], "a.docx", "OOXML", anon=b"a", restored=b"REAL")
        chat = self.store.get(fresh["id"])
        chat["files"][0]["roles"]["restored"]["time"] = time.time() - 40 * 86400
        self.store._write(chat)
        stale = self.store.get(old["id"])
        self.store._write(stale)
        # состарить чат: перезаписать служебное поле в обход _write
        import json
        from anonymizer import crypto as c
        stale["updated"] = time.time() - 400 * 86400
        path = self.root / "chats" / old["id"] / "chat.bin"
        path.write_bytes(c.encrypt_blob(json.dumps(stale).encode(), self.key))
        removed = self.store.purge(anon_days=180, restored_days=30)
        self.assertEqual(removed, 1)
        self.assertIsNone(self.store.get(old["id"]))
        self.assertIsNone(self.store.read_blob(fresh["id"], record["id"], "restored"))
        self.assertEqual(self.store.read_blob(fresh["id"], record["id"], "anon"), b"a")

    def test_zero_days_keeps_everything(self):
        chat = self.store.create("A")
        self.store.add_file(chat["id"], "a.docx", "OOXML", anon=b"a", restored=b"b")
        self.assertEqual(self.store.purge(0, 0), 0)
        self.assertEqual(len(self.files_on_disk()), 3)

    # -- миграция -------------------------------------------------------------

    def test_history_becomes_archived_chats_once(self):
        token = self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.log("anonymize", ["Файл1 (обезличено).docx"], {"Имена": 3}, {"tokens": [token]})
        self.vault.log("restore", ["Файл1.docx"], {"Имена": 3})
        self.assertEqual(self.store.import_history(self.vault), 2)
        self.assertEqual(self.store.import_history(self.vault), 0)
        items = self.store.listing()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i["archived"] for i in items))
        anon = next(i for i in items if i["title"].startswith("Файл1 (обез"))
        rows = self.store.table(anon["id"], self.vault)
        self.assertEqual([r["base"] for r in rows], ["Name1"])


if __name__ == "__main__":
    unittest.main()
