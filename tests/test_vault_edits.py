import os
import tempfile
import unittest
from pathlib import Path

from anonymizer.tokens import KIND_BY_CODE
from anonymizer.vault import Vault

PERSON = KIND_BY_CODE["PERSON"]


class VaultEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "vault.bin"
        self.key = os.urandom(32)
        self.vault = Vault(self.path, key=self.key)

    def tearDown(self):
        self.tmp.cleanup()

    def value(self, number, variant=1):
        return self.vault.lookup(PERSON, number, variant).original

    # -- слияние --------------------------------------------------------------

    def test_merge_keeps_old_tokens_restorable_and_routes_new_ones(self):
        self.vault.token_for("PERSON", "a", "Иванов Иван")        # Name1
        self.vault.token_for("PERSON", "a", "Иванову И.")         # Name1_2
        self.vault.token_for("PERSON", "b", "Ваня Иванов")        # Name2
        self.vault.merge("Name2", "Name1")
        self.assertEqual(self.value(2), "Ваня Иванов")             # файл со старой меткой возвращается как раньше
        self.assertEqual(self.value(1), "Иванов Иван")
        self.assertEqual(self.vault.token_for("PERSON", "b", "Ваня Иванов"), "Name1_3")   # новое обезличивание
        self.assertEqual(self.vault.token_for("PERSON", "a", "Иванов Иван"), "Name1")

    def test_merge_survives_restart_and_reindexes(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.token_for("PERSON", "b", "Петров")
        self.vault.merge("Name2", "Name1")
        again = Vault(self.path, key=self.key)
        self.assertEqual(again.lookup(PERSON, 2).original, "Петров")
        self.assertEqual(again.token_for("PERSON", "b", "Петров"), "Name1_2")

    def test_merge_chain_collapses(self):
        for key, name in (("a", "А"), ("b", "Б"), ("c", "В")):
            self.vault.token_for("PERSON", key, name)
        self.vault.merge("Name3", "Name2")
        self.vault.merge("Name2", "Name1")
        self.assertEqual((self.value(1), self.value(2), self.value(3)), ("А", "Б", "В"))
        self.assertEqual(self.vault.describe("Name3")["base"], "Name1")

    def test_merge_refuses_other_kinds_self_and_secrets(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.token_for("ORG", "o", "Орбита")
        with self.assertRaises(ValueError):
            self.vault.merge("Company1", "Name1")
        with self.assertRaises(ValueError):
            self.vault.merge("Name1", "Name1")
        self.vault.token_for("SECRET", "s", None, secret=True)
        with self.assertRaises(ValueError):
            self.vault.merge("Secret1", "Secret1")

    # -- разделение -----------------------------------------------------------

    def test_split_gives_new_token_to_future_runs_and_keeps_old_files_valid(self):
        self.vault.token_for("PERSON", "a", "Иванов Иван")        # Name1
        self.vault.token_for("PERSON", "a", "Иванов П.")          # Name1_2: на деле другой человек
        new_base = self.vault.split("Name1", 2)
        self.assertEqual(new_base, "Name2")
        self.assertEqual(self.value(1, 2), "Иванов П.")            # старый файл с Name1_2 возвращается как раньше
        self.assertEqual(self.vault.token_for("PERSON", "a", "Иванов П."), "Name2")
        self.assertEqual(self.vault.token_for("PERSON", "a", "Иванов Иван"), "Name1")

    def test_split_survives_restart(self):
        self.vault.token_for("PERSON", "a", "Иванов Иван")
        self.vault.token_for("PERSON", "a", "Иванов П.")
        self.vault.split("Name1", 2)
        again = Vault(self.path, key=self.key)
        self.assertEqual(again.token_for("PERSON", "a", "Иванов П."), "Name2")

    def test_split_needs_at_least_two_spellings(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        with self.assertRaises(ValueError):
            self.vault.split("Name1", 1)

    # -- значения -------------------------------------------------------------

    def test_edit_value_changes_restore_but_not_detection(self):
        self.vault.token_for("PERSON", "a", "Ивонов Иван")
        self.vault.edit_value("Name1", 1, "Иванов Иван")
        self.assertEqual(self.value(1), "Иванов Иван")
        self.assertEqual(self.vault.token_for("PERSON", "a", "Ивонов Иван"), "Name1")   # новый вариант не заводится

    def test_edit_value_rejects_empty_and_unknown(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        with self.assertRaises(ValueError):
            self.vault.edit_value("Name1", 1, "  ")
        with self.assertRaises(ValueError):
            self.vault.edit_value("Name1", 5, "Х")
        with self.assertRaises(ValueError):
            self.vault.edit_value("Name9", 1, "Х")

    def test_forget_erases_values_but_keeps_the_number_taken(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.forget("Name1")
        self.assertEqual(self.vault.lookup(PERSON, 1).status, "removed")
        self.assertEqual(self.vault.token_for("PERSON", "b", "Петров"), "Name2")
        self.vault.save()
        self.assertNotIn("Иванов".encode("utf-8"), self.path.read_bytes())

    # -- таблица, термины, откат ----------------------------------------------

    def test_describe_shows_variants_edits_and_merged(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.token_for("PERSON", "a", "Иванову")
        self.vault.token_for("PERSON", "b", "Петров")
        self.vault.edit_value("Name1", 2, "Иванову И.")
        self.vault.merge("Name2", "Name1")
        row = self.vault.describe("Name2")
        self.assertEqual(row["base"], "Name1")
        self.assertEqual(row["merged"], ["Name2"])
        self.assertEqual([v["token"] for v in row["variants"]], ["Name1", "Name1_2", "Name1_3"])
        self.assertEqual(row["variants"][1]["value"], "Иванову И.")
        self.assertTrue(row["variants"][1]["edited"])

    def test_describe_never_reveals_secrets(self):
        self.vault.token_for("SECRET", "s", None, secret=True)
        row = self.vault.describe("Secret1")
        self.assertTrue(row["secret"])
        self.assertEqual(row["variants"], [])

    def test_a_term_lives_in_one_list_only(self):
        self.vault.add_term("hide_terms", "Орбита")
        self.vault.add_term("keep_terms", "орбита")
        self.assertEqual(self.vault.prefs["hide_terms"], [])
        self.assertEqual(self.vault.prefs["keep_terms"], ["орбита"])
        with self.assertRaises(ValueError):
            self.vault.add_term("other", "x")

    def test_rollback_undoes_edits(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.token_for("PERSON", "b", "Петров")
        snap = self.vault.snapshot()
        self.vault.merge("Name2", "Name1")
        self.vault.rollback(snap)
        self.assertEqual(self.vault.token_for("PERSON", "b", "Петров"), "Name2")

    def test_old_vault_files_without_new_fields_still_load(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.save()
        again = Vault(self.path, key=self.key)
        again.pins = {}
        self.assertEqual(again.lookup(PERSON, 1).original, "Иванов")

    def test_backup_roundtrip_keeps_merges(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.vault.token_for("PERSON", "b", "Петров")
        self.vault.merge("Name2", "Name1")
        blob = self.vault.export_backup("pw")
        fresh = Vault(Path(self.tmp.name) / "other.bin", key=os.urandom(32))
        fresh.import_backup(blob, "pw")
        self.assertEqual(fresh.lookup(PERSON, 2).original, "Петров")
        self.assertEqual(fresh.token_for("PERSON", "b", "Петров"), "Name1_2")

    # -- отмена ---------------------------------------------------------------

    def test_unmerge_restores_separate_labels_and_never_changes_a_meaning(self):
        self.vault.token_for("PERSON", "a", "Иванов Иван")
        self.vault.token_for("PERSON", "b", "Ваня Иванов")
        self.vault.merge("Name2", "Name1")
        merged_token = self.vault.token_for("PERSON", "b", "Ваня Иванов")      # выдана после слияния: Name1_2
        self.assertEqual(merged_token, "Name1_2")
        self.assertEqual(self.vault.unmerge("Name2"), "Name1")
        self.assertEqual(self.value(2), "Ваня Иванов")
        self.assertEqual(self.value(1, 2), "Ваня Иванов")                        # выданная после слияния метка осталась верной
        self.assertEqual(self.vault.token_for("PERSON", "b", "Ваня Иванов"), "Name2")
        self.assertEqual(self.vault.describe("Name2")["base"], "Name2")
        with self.assertRaises(ValueError):
            self.vault.unmerge("Name2")                                         # второй раз нечего отменять

    def test_unmerge_after_chain_keeps_earlier_merges(self):
        for key, text in (("a", "Иванов"), ("b", "Петров"), ("c", "Сидоров")):
            self.vault.token_for("PERSON", key, text)
        self.vault.merge("Name3", "Name2")
        self.vault.merge("Name2", "Name1")
        self.vault.unmerge("Name2")
        self.assertEqual([self.value(n) for n in (1, 2, 3)], ["Иванов", "Петров", "Сидоров"])
        self.assertEqual(self.vault.describe("Name3")["base"], "Name2")

    def test_edit_undo_and_term_undo(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        previous = self.vault.edit_value("Name1", 1, "Иванов-Первый")
        self.assertIsNone(previous)
        self.assertEqual(self.vault.edit_value("Name1", 1, "Иванов-Второй"), "Иванов-Первый")
        self.vault.restore_edit("Name1", 1, "Иванов-Первый")
        self.assertEqual(self.value(1), "Иванов-Первый")
        self.vault.restore_edit("Name1", 1, None)
        self.assertEqual(self.value(1), "Иванов")
        self.assertFalse(self.vault.describe("Name1")["variants"][0]["edited"])
        self.vault.add_term("hide_terms", "Альфа")
        info = self.vault.add_term("keep_terms", "Альфа")
        self.assertTrue(info["was_other"])
        self.vault.remove_term("keep_terms", "Альфа", back_to_other=True)
        self.assertEqual((self.vault.prefs["hide_terms"], self.vault.prefs["keep_terms"]), (["Альфа"], []))

    def test_describe_marks_kept_spellings(self):
        self.vault.token_for("PERSON", "a", "Иванов")
        self.assertFalse(self.vault.describe("Name1")["variants"][0]["kept"])
        self.vault.add_term("keep_terms", "иванов")
        self.assertTrue(self.vault.describe("Name1")["variants"][0]["kept"])


if __name__ == "__main__":
    unittest.main()
