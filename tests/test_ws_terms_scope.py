"""Решения о слове из чата живут в этом чате и не попадают в общие настройки."""
from __future__ import annotations

import unittest

from tests.helpers import Env
from tests.test_review_fixes import finish, make_app, run_job

TEXT = "Пётр Сидоров подписал договор с Ромашкой. Пётр Сидоров согласен.\n"


class TermsScope(unittest.TestCase):
    def setUp(self):
        from anonymizer import chat_api
        self.api = chat_api
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)
        self.a = self.app.chats.create("A", keep_originals=True)["id"]
        self.b = self.app.chats.create("B", keep_originals=True)["id"]
        run_job(self.app, "anonymize", [("a.txt", TEXT)], chat_id=self.a)
        run_job(self.app, "anonymize", [("b.txt", TEXT)], chat_id=self.b)

    def post(self, chat, base, data):
        return self.api.handle(self.app, "POST", f"/api/chats/{chat}/entities/{base}", lambda: data)[1]

    def prefs(self, name):
        return self.env.vault.prefs.get(name, [])

    def person(self, chat):
        return next(r for r in self.app.chats.table(chat, self.env.vault) if r["kind"] == "PERSON")

    def test_keep_and_hide_stay_in_chat(self):
        row = self.person(self.a)
        done = self.post(self.a, row["base"], {"action": "keep", "variant": 1})
        term = done["undo"]["term"]
        self.assertEqual(self.prefs("keep_terms"), [])
        self.assertEqual(self.app.chats.terms(self.a)["keep_terms"], [term])
        self.assertEqual(self.app.chats.terms(self.b)["keep_terms"], [])
        self.assertTrue(self.person(self.a)["variants"][0]["kept"])
        self.assertFalse(self.person(self.b)["variants"][0]["kept"])      # чат B решения не видит
        self.post(self.a, row["base"], {"action": "hide", "term": "договор"})
        self.assertEqual(self.prefs("hide_terms"), [])
        self.assertEqual(self.app.chats.terms(self.b)["hide_terms"], [])

    def test_undo_removes_chat_term_only(self):
        row = self.person(self.a)
        done = self.post(self.a, row["base"], {"action": "keep", "variant": 1})
        self.post(self.a, row["base"], {"action": "undo", **done["undo"]})
        self.assertEqual(self.app.chats.terms(self.a)["keep_terms"], [])
        self.assertFalse(self.person(self.a)["variants"][0]["kept"])

    def test_hide_new_and_opposite_decision(self):
        self.post(self.a, "_", {"action": "hide_new", "term": "Ромашка"})
        done = self.post(self.a, self.person(self.a)["base"], {"action": "keep", "term": "Ромашка"})
        self.assertEqual(self.app.chats.terms(self.a), {"hide_terms": [], "keep_terms": ["Ромашка"]})
        self.post(self.a, self.person(self.a)["base"], {"action": "undo", **done["undo"]})
        self.assertEqual(self.app.chats.terms(self.a), {"hide_terms": ["Ромашка"], "keep_terms": []})
        self.assertEqual(self.prefs("hide_terms"), [])

    def test_rerun_remembers_in_chat_and_keeps_terms(self):
        first = run_job(self.app, "anonymize", [("c.txt", "Дальше работаем по плану. Договор подписан.")], chat_id=self.a)
        finish(self.app, first)
        again = self.app.start_job("anonymize", [], {}, {"плану": "hide"}, rerun_of=first, chat_id=self.a)
        status = finish(self.app, again)
        self.assertEqual(status["state"], "done", status)
        self.assertEqual(self.app.chats.terms(self.a)["hide_terms"], ["плану"])
        self.assertEqual(self.prefs("hide_terms"), [])
        self.assertEqual(self.app.chats.terms(self.b)["hide_terms"], [])
        mine = self.app.service.settings_for(self.app.with_chat_settings(self.a, {}))
        self.assertIn("плану", mine.hide_terms)
        other = self.app.service.settings_for(self.app.with_chat_settings(self.b, {}))
        self.assertNotIn("плану", other.hide_terms)

    def test_chat_keep_beats_global_hide_only_in_that_chat(self):
        self.app.save_prefs({"hide_terms": ["Ромашка"]})
        self.app.chats.add_term(self.a, "keep_terms", "Ромашка")
        mine = self.app.service.settings_for(self.app.with_chat_settings(self.a, {}))
        self.assertNotIn("Ромашка", mine.hide_terms)
        self.assertIn("Ромашка", mine.keep_terms)
        other = self.app.service.settings_for(self.app.with_chat_settings(self.b, {}))
        self.assertIn("Ромашка", other.hide_terms)

    def test_settings_edit_is_global(self):
        self.app.save_prefs({"hide_terms": ["Орион"], "keep_terms": ["Альфа"]})
        self.assertEqual(self.prefs("hide_terms"), ["Орион"])
        for chat in (self.a, self.b):
            settings = self.app.service.settings_for(self.app.with_chat_settings(chat, {}))
            self.assertIn("Орион", settings.hide_terms)
            self.assertIn("Альфа", settings.keep_terms)


if __name__ == "__main__":
    unittest.main()
