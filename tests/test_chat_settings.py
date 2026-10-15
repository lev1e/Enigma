"""Два уровня настроек: общие (vault.prefs) и переопределения одного чата. Чат побеждает только внутри себя."""
from __future__ import annotations

import unittest

from anonymizer.chat_api import public
from tests.helpers import Env
from tests.test_review_fixes import finish, make_app, run_job

TEXT = "Пётр Сидоров приехал из Германии. Пётр Сидоров согласен.\n"


class ChatSettings(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)

    def anon(self, chat_id, **options):
        run_job(self.app, "anonymize", [("a.txt", TEXT)], chat_id=chat_id, options=options)
        chat = self.app.chats.get(chat_id)
        return self.app.chats.read_blob(chat_id, chat["files"][-1]["id"], "anon").decode()

    def test_countries_hidden_by_global_default(self):
        chat = self.app.chats.create("A", keep_originals=True)
        self.assertNotIn("Германи", self.anon(chat["id"]))

    def test_chat_override_beats_global_only_inside_chat(self):
        mine = self.app.chats.create("Моя", keep_originals=True)
        other = self.app.chats.create("Чужая", keep_originals=True)
        self.app.chats.set_settings(mine["id"], {"countries": False})
        self.assertIn("Германи", self.anon(mine["id"]))
        self.assertNotIn("Германи", self.anon(other["id"]))
        self.assertTrue(self.env.vault.prefs["countries"])            # общая настройка не тронута

    def test_explicit_run_option_beats_chat_setting(self):
        chat = self.app.chats.create("A", keep_originals=True)
        self.app.chats.set_settings(chat["id"], {"countries": False})
        self.assertNotIn("Германи", self.anon(chat["id"], countries=True))

    def test_reset_returns_to_global(self):
        chat = self.app.chats.create("A", keep_originals=True)
        self.app.chats.set_settings(chat["id"], {"countries": False})
        self.app.chats.set_settings(chat["id"], {"countries": None})
        self.assertEqual(self.app.chats.get(chat["id"]).get("settings"), {})
        self.assertNotIn("Германи", self.anon(chat["id"]))

    def test_chat_terms_add_to_global_terms(self):
        self.env.vault.add_term("hide_terms", "приехал")
        chat = self.app.chats.create("A", keep_originals=True)
        self.app.chats.set_settings(chat["id"], {"hide_terms": ["согласен"]})
        out = self.anon(chat["id"])
        self.assertNotIn("приехал", out)
        self.assertNotIn("согласен", out)
        other = self.app.chats.create("B", keep_originals=True)
        self.assertIn("согласен", self.anon(other["id"]))

    def test_unknown_keys_ignored_and_public_exposes_settings(self):
        chat = self.app.chats.create("A", keep_originals=True)
        self.app.chats.set_settings(chat["id"], {"bogus": True, "strict": True})
        self.assertEqual(public(self.app.chats.get(chat["id"]))["settings"], {"strict": True})

    def test_rebuild_keeps_chat_setting(self):
        chat = self.app.chats.create("A", keep_originals=True)
        self.app.chats.set_settings(chat["id"], {"countries": False})
        self.anon(chat["id"])
        finish(self.app, self.app.apply_chat(chat["id"], {}))
        record = self.app.chats.get(chat["id"])["files"][0]
        self.assertIn("Германи".encode(), self.app.chats.read_blob(chat["id"], record["id"], "anon"))


if __name__ == "__main__":
    unittest.main()
