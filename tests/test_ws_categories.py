"""Мелкие категории: каждый вид данных выключается отдельно, старые настройки переносятся на новые ключи."""
from __future__ import annotations

import unittest

from anonymizer import settings_schema as ss
from anonymizer import tokens
from tests.helpers import Env
from tests.test_review_fixes import make_app, run_job

INTERNAL = {"META", "TERM", "FILE"}
TEXT = ("ООО «Ромашка», ИНН 7707083893, КПП 770701001, ОГРН 1027700132195. Контакт: ivan@firma.ru. "
        "Офис в г. Казань, ул. Мира, 5, Китай.\n")


class SchemaCoverage(unittest.TestCase):
    def test_every_kind_is_reachable(self):
        listed = {item[0] for _, _, _, items in ss.KIND_GROUPS for item in items}
        self.assertEqual(listed, {k.code for k in tokens.KINDS} - INTERNAL)

    def test_switchable_kinds_have_keys_and_protected_are_locked(self):
        for _, _, _, items in ss.KIND_GROUPS:
            for code, *_ in items:
                if code in ss.PROTECTED_KINDS:
                    self.assertNotIn(ss.kind_key(code), ss.BY_KEY, code)
                else:
                    self.assertIn(ss.kind_key(code), ss.BY_KEY, code)
        self.assertEqual(ss.kind_key("COUNTRY"), "countries")
        self.assertEqual(ss.kind_key("KPP"), "hide_kind_KPP")

    def test_public_schema_groups(self):
        groups = ss.public_schema()["groups"]
        self.assertEqual([g["id"] for g in groups], ["people", "orgs", "requisites", "documents", "places", "contacts", "finance"])
        locked = {i["code"] for g in groups for i in g["items"] if i["locked"]}
        self.assertEqual(locked, set(ss.PROTECTED_KINDS))
        for g in groups:
            for i in g["items"]:
                self.assertEqual(i["key"] is None, i["locked"])

    def test_defaults_everything_on_except_business(self):
        d = ss.defaults()
        skip = ss.PROTECTED_KINDS | {"BUSINESS"}
        for key in (ss.kind_key(c) for _, _, _, items in ss.KIND_GROUPS for c, *_ in items if c not in skip):
            self.assertTrue(d[key], key)
        self.assertFalse(d["business_confidential"])
        self.assertEqual(ss.disabled_kinds(d), ())

    def test_presets_cover_every_kind_switch(self):
        for name in ("recommended", "maximum"):
            values = ss.PRESETS[name]["values"]
            self.assertTrue(values["hide_kind_KPP"] and values["countries"], name)


class Migration(unittest.TestCase):
    def test_legacy_keys_expand_to_kinds(self):
        out = ss.expand_legacy({"hide_tax_ids": False, "hide_places": False, "hide_names": True})
        for code in ("INN", "OGRN", "KPP", "BIK", "CITY", "REGION", "ADDRESS"):
            self.assertIs(out[ss.kind_key(code)], False, code)
        self.assertIs(out["hide_kind_PERSON"], True)
        self.assertNotIn("countries", out)           # старые «места» страны не включали
        self.assertFalse(any(k in out for k in ss.LEGACY_KEYS))

    def test_explicit_new_key_wins(self):
        out = ss.expand_legacy({"hide_tax_ids": False, "hide_kind_INN": True})
        self.assertIs(out["hide_kind_INN"], True)
        self.assertIs(out["hide_kind_KPP"], False)

    def test_disabled_kinds_accepts_legacy_and_never_protected(self):
        off = ss.disabled_kinds({"hide_tax_ids": False, "hide_orgs": False})
        self.assertEqual(set(off), {"INN", "OGRN", "KPP", "BIK", "ORG", "PROJECT"})
        self.assertFalse(set(ss.disabled_kinds({"hide_kind_PASSPORT": False})) & ss.PROTECTED_KINDS)

    def test_validate_patch_translates_and_rejects(self):
        self.assertEqual(ss.validate_patch({"hide_places": False}, "chat"),
                         {"hide_kind_CITY": False, "hide_kind_REGION": False, "hide_kind_ADDRESS": False})
        self.assertIsNone(ss.validate_patch({"hide_places": None}, "chat")["hide_kind_CITY"])
        with self.assertRaises(ValueError):
            ss.validate_patch({"hide_names": "no"})

    def test_stored_prefs_are_migrated_on_load(self):
        env = Env()
        self.addCleanup(env.close)
        env.vault._apply({"prefs": {"hide_tax_ids": False, "hide_places": False, "countries": False}})
        p = env.vault.prefs
        self.assertIs(p["hide_kind_INN"], False)
        self.assertIs(p["hide_kind_CITY"], False)
        self.assertIs(p["countries"], False)
        self.assertIs(p["hide_kind_EMAIL"], True)


class Behaviour(unittest.TestCase):
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

    def test_kpp_off_keeps_only_kpp(self):
        out = self.anon(hide_kind_KPP=False)
        self.assertIn("770701001", out)
        self.assertNotIn("7707083893", out)
        self.assertNotIn("1027700132195", out)

    def test_each_requisite_is_independent(self):
        for code, value in (("INN", "7707083893"), ("OGRN", "1027700132195")):
            out = self.anon(**{ss.kind_key(code): False})
            self.assertIn(value, out, code)
            for other in {"7707083893", "1027700132195", "770701001"} - {value}:
                self.assertNotIn(other, out, f"{code} off must not reveal {other}")

    def test_places_are_independent(self):
        out = self.anon(hide_kind_CITY=False)
        self.assertIn("Казань", out)
        self.assertNotIn("Китай", out)
        out = self.anon(countries=False)
        self.assertIn("Китай", out)
        self.assertNotIn("Казань", out)

    def test_macro_region_independent_of_country(self):
        text = "Рынки: Азия и Африка, а также Китай.\n"
        out = self.anon(text, hide_kind_REGION=False)
        self.assertIn("Азия", out)
        self.assertNotIn("Китай", out)
        out = self.anon(text, countries=False)
        self.assertIn("Китай", out)
        self.assertNotIn("Азия", out)
        out = self.anon(text, countries=False, hide_kind_REGION=False)
        self.assertIn("Китай", out)
        self.assertIn("Азия", out)

    def test_chat_override_precedence(self):
        self.app.save_prefs({"hide_kind_KPP": False})
        chat = self.app.chats.create("c", keep_originals=True)["id"]
        self.assertIn("770701001", self.anon(chat=chat))
        self.app.chats.set_settings(chat, {"hide_kind_KPP": True})
        self.assertNotIn("770701001", self.anon(chat=chat))
        self.assertIn("770701001", self.anon(chat=chat, hide_kind_KPP=False))
        self.app.chats.set_settings(chat, {"hide_kind_KPP": None})
        self.assertEqual(self.app.chats.get(chat)["settings"], {})

    def test_legacy_chat_setting_still_applies(self):
        chat = self.app.chats.create("c", keep_originals=True)["id"]
        self.app.chats.set_settings(chat, {"hide_tax_ids": False})
        self.assertIs(self.app.chats.get(chat)["settings"]["hide_kind_INN"], False)
        self.assertIn("7707083893", self.anon(chat=chat))

    def test_protected_kinds_stay_hidden(self):
        text = "Паспорт 4510 123456, карта 4276 3800 1234 5675.\n"
        out = self.anon(text, hide_kind_PASSPORT=False, hide_kind_CARD=False)
        self.assertNotIn("4276 3800", out)


if __name__ == "__main__":
    unittest.main()
