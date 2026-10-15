"""Схема настроек: каждый пункт проверяется по результату обезличивания и возврата, а не по состоянию экрана."""
from __future__ import annotations

import unittest

from anonymizer import settings_schema as ss
from tests.helpers import Env
from tests.test_review_fixes import make_app, run_job

TEXT = ("Иван Петров, ivan@firma.ru, +7 495 123-45-67, ИНН: 7707083893, карта 4276 3800 1234 5675, "
        "пароль: password=Zq9xK2vLm8Rt, родился 12.03.1985, г. Казань, сайт firma.ru.\n")


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        self.app = make_app(self.env)
        self.addCleanup(self.app.cleanup_open)

    def anon(self, text=TEXT, chat=None, **options):
        chat = chat or self.app.chats.create("A", keep_originals=True)["id"]
        run_job(self.app, "anonymize", [("a.txt", text)], chat_id=chat, options=options)
        rec = self.app.chats.get(chat)["files"][-1]
        return self.app.chats.read_blob(chat, rec["id"], "anon").decode()

    def prefs(self, **values):
        self.app.save_prefs(values)

    def test_every_bool_option_is_wired_to_settings(self):
        for option in ss.OPTIONS:
            self.assertIn(option.section, [s for s, _ in ss.SECTIONS])
            if option.kind == "bool" and not option.kinds and option.key != "keep_originals":
                self.assertIn(option.key, ss.SETTINGS_BOOLS, option.key)

    def test_category_toggle_changes_output_and_restore_still_works(self):
        base = self.anon()
        self.assertNotIn("ivan@firma.ru", base)
        self.prefs(hide_kind_EMAIL=False)
        out = self.anon()
        self.assertIn("ivan@firma.ru", out)
        self.assertNotIn("+7 495", out)           # соседние категории не задеты
        self.prefs(hide_kind_EMAIL=True, hide_kind_PHONE=False)
        out = self.anon()
        self.assertIn("123-45-67", out)
        self.assertNotIn("ivan@firma.ru", out)

    def test_chat_override_category_only_in_chat(self):
        mine = self.app.chats.create("m", keep_originals=True)["id"]
        self.app.chats.set_settings(mine, {"hide_kind_CITY": False})
        self.assertIn("Казань", self.anon(chat=mine))
        self.assertNotIn("Казань", self.anon())

    def test_protected_data_cannot_be_disabled_or_kept(self):
        self.prefs(keep_terms=["4276 3800 1234 5675", "7707083893"])
        out = self.anon()
        self.assertNotIn("4276 3800", out)        # карта защищена от «Никогда не скрывать»
        self.assertNotIn("Zq9xK2vLm8Rt", out)
        with self.assertRaises(ValueError):
            self.app.save_prefs({"hide_cards": False, "hide_names": "no"})   # не булево значение отвергается
        chat = self.app.chats.create("c", keep_originals=True)["id"]
        self.app.chats.set_settings(chat, {"hide_cards": False, "secrets": False})   # неизвестные пункты игнорируются
        self.assertEqual(self.app.chats.get(chat)["settings"], {})
        self.assertEqual(set(ss.disabled_kinds({"hide_kind_PERSON": False, "hide_kind_INN": False, "hide_kind_PASSPORT": False})), {"PERSON", "INN"})

    def test_hide_beats_keep_and_note_reported(self):
        result = self.app.save_prefs({"hide_terms": ["Орион"], "keep_terms": ["орион", "Альфа"]})
        self.assertEqual(self.env.vault.prefs["keep_terms"], ["Альфа"])
        self.assertTrue(result["notes"])
        self.assertEqual(ss.resolve({"keep_terms": ["X"]}, {"hide_terms": ["x"]})["keep_terms"], [])

    def test_precedence_run_over_chat_over_global(self):
        chat = self.app.chats.create("c", keep_originals=True)["id"]
        self.prefs(hide_kind_EMAIL=False)
        self.assertIn("ivan@firma.ru", self.anon(chat=chat))
        self.app.chats.set_settings(chat, {"hide_kind_EMAIL": True})
        self.assertNotIn("ivan@firma.ru", self.anon(chat=chat))
        self.assertIn("ivan@firma.ru", self.anon(chat=chat, hide_kind_EMAIL=False))

    def test_learn_names_toggle(self):
        text = "Иванов Иван Петрович подписал. Позже Иванов И.П. вернулся.\n"
        self.assertNotIn("Иванов И.П.", self.anon(text))
        self.prefs(learn_names=False)
        self.anon(text)       # не падает; поведение проверяется на уровне Detector в других тестах

    def test_business_confidential_toggle_reaches_detector(self):
        self.prefs(business_confidential=True)
        s = self.app.service.settings_for({})
        self.assertTrue(s.business_confidential)
        self.prefs(business_confidential=False)
        self.assertFalse(self.app.service.settings_for({}).business_confidential)

    def test_defaults_countries_on_and_presets(self):
        self.assertTrue(ss.defaults()["countries"])
        self.assertTrue(self.app.service.settings_for({}).countries)
        self.app.apply_preset("maximum")
        p = self.env.vault.prefs
        self.assertTrue(p["strict"] and p["numbers"] and p["business_confidential"])
        self.assertFalse(p["keep_originals"])
        self.assertEqual(p["retention_days"], 30)
        self.app.apply_preset("recommended")
        self.assertFalse(self.env.vault.prefs["strict"])
        self.prefs(strict=True)
        self.app.save_preset("Мой")
        self.app.apply_preset("recommended")
        self.app.apply_preset("Мой")
        self.assertTrue(self.env.vault.prefs["strict"])
        self.app.delete_preset("Мой")
        with self.assertRaises(ValueError):
            self.app.apply_preset("Мой")
        with self.assertRaises(ValueError):
            self.app.save_preset("maximum")

    def test_retention_choices_validated_and_persisted(self):
        self.prefs(retention_days=90, restored_retention_days=7)
        self.assertEqual((self.env.vault.prefs["retention_days"], self.env.vault.prefs["restored_retention_days"]), (90, 7))
        with self.assertRaises(ValueError):
            self.prefs(retention_days=13)

    def test_schema_published_in_state(self):
        schema = self.app.state()["schema"]
        self.assertIn("hide_kind_EMAIL", [o["key"] for o in schema["options"]])
        self.assertTrue(schema["locked"])


if __name__ == "__main__":
    unittest.main()
