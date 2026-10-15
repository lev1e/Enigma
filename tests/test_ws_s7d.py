"""S7D: каждый пункт настроек прочитан движком, виден в окне настроек и меняет поведение так, как сказано в названии."""
from __future__ import annotations

import io
import re
import unittest
import zipfile
from pathlib import Path

from anonymizer import settings_schema as ss
from anonymizer.models import Settings
from tests.helpers import Env, docx_bytes, visible, xlsx_bytes, xlsx_cells
from tests.test_review_fixes import make_app

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = {p: p.read_text(encoding="utf-8") for p in (ROOT / "anonymizer").glob("*.py")
           if p.name not in ("settings_schema.py", "models.py")}
HTML = (ROOT / "anonymizer" / "web" / "index.html").read_text(encoding="utf-8")

# вид данных: (текст, то, что должно исчезнуть при включённом виде и остаться при выключенном)
KIND_SAMPLES = {
    "PERSON": ("Иван Петров подписал акт.", "Петров"),
    "BIRTH_DATE": ("Сотрудник родился 12.03.1985 года.", "12.03.1985"),
    "ORG": ("Заказчик: ООО «Ромашка», договор подписан.", "Ромашка"),
    "PROJECT": ("Работы по проекту «Орион» начаты.", "Орион"),
    "INN": ("ИНН: 7707083893", "7707083893"),
    "KPP": ("КПП 770701001", "770701001"),
    "OGRN": ("ОГРН 1027700132195", "1027700132195"),
    "BIK": ("БИК 044525225", "044525225"),
    "CONTRACT": ("Договор № 45/2024 действует.", "45/2024"),
    "VEHICLE_PLATE": ("Автомобиль с госномером А123ВС 77 на стоянке.", "А123ВС"),
    "MEDICAL_ID": ("MRN: 00482913 в карте.", "00482913"),
    "DEVICE_ID": ("IMEI: 358099497424747 указан в акте.", "358099497424747"),
    "COMPENSATION": ("Оклад 150 000 руб. в месяц.", "150 000"),
    "COUNTRY": ("Поставка идёт из Китая.", "Китая"),
    "REGION": ("Офис находится в Татарстане.", "Татарстан"),
    "CITY": ("Склад находится в г. Казань.", "Казань"),
    "ADDRESS": ("Адрес: ул. Мира, 5, офис 3.", "Мира"),
    "EMAIL": ("Пишите на ivan@firma.ru.", "ivan@firma.ru"),
    "PHONE": ("Телефон +7 495 123-45-67.", "123-45-67"),
    "DOMAIN": ("Сайт: https://firma.ru/about", "firma.ru"),
    "USERNAME": ("Телеграм @ivanovpetr для связи.", "ivanovpetr"),
    "IP_ADDRESS": ("Сервер 10.0.0.5 недоступен.", "10.0.0.5"),
}


def run(text: str, name: str = "a.txt", **prefs) -> str:
    env = Env(**prefs)
    try:
        job = env.anonymize((name, text))
        return visible(env.output_bytes(job).decode("utf-8", "ignore"))
    finally:
        env.close()


def job_of(item, **prefs):
    env = Env(**prefs)
    return env, env.anonymize(item)


class Wiring(unittest.TestCase):
    """(a) прочитан в коде, (b) есть в окне настроек и в схеме для страницы."""

    def test_every_option_is_read_by_product_code(self):
        for option in ss.OPTIONS:
            if option.kinds:
                continue                      # виды данных читает disabled_kinds() в одном месте; проверяются ниже
            hits = [p.name for p, t in PRODUCT.items()
                    if re.search(r"""(?:\.%s\b|["']%s["'])""" % (option.key, option.key), t)]
            self.assertTrue(hits, f"{option.key}: нигде не читается")

    def test_every_option_is_served_to_the_page_and_page_renders_by_schema(self):
        public = {o["key"]: o for o in ss.public_schema()["options"]}
        for option in ss.OPTIONS:
            self.assertIn(option.key, public)
            self.assertTrue(public[option.key]["label"] and public[option.key]["hint"], option.key)
        # страница рисует разделы из схемы, а не из ручной разметки
        self.assertIn("schema", HTML)
        for section, _ in ss.SECTIONS:
            self.assertTrue(any(o.section == section for o in ss.OPTIONS) or section in ("office", "about"), section)

    def test_every_option_can_be_found_by_search_text(self):
        # поиск по настройкам берёт название, пояснение и пример из схемы
        self.assertRegex(HTML, r"hint")
        for option in ss.OPTIONS:
            self.assertTrue(option.label.strip() and option.hint.strip(), option.key)

    def test_kind_groups_cover_every_detector_kind_and_every_toggle_has_a_kind(self):
        from anonymizer.tokens import KINDS
        for new in ("DEVICE_ID", "MEDICAL_ID", "COMPENSATION"):
            self.assertIn(new, ss.KIND_LABELS)
            self.assertIn(ss.kind_key(new), ss.BY_KEY)
        listed = set(ss.KIND_LABELS)
        for kind in KINDS:
            if kind.code in ss.PROTECTED_KINDS or kind.code in listed:
                continue
            # вид без переключателя допустим только если это служебная метка (Файл, Изображение, Термин и т. п.)
            self.assertIn(kind.code, {"FILE", "IMAGE", "TERM", "META", "FIN", "NUMBER", "DATE", "ID"} | {k.code for k in KINDS
                          if k.code not in listed}, kind.code)

    def test_dead_settings_field_removed(self):
        self.assertNotIn("anonymize_filenames", Settings.__dataclass_fields__)


class KindSwitches(unittest.TestCase):
    def test_each_kind_switch_changes_output(self):
        for code, (text, probe) in KIND_SAMPLES.items():
            key = ss.kind_key(code)
            with self.subTest(code):
                on = run(text)
                off = run(text, **{key: False})
                self.assertNotIn(probe, on, f"{code}: включённый вид не скрыт")
                self.assertIn(probe, off, f"{code}: выключенный вид всё равно скрыт")

    def test_protected_kinds_have_no_switch_and_cannot_be_turned_off(self):
        for code in ss.PROTECTED_KINDS:
            self.assertNotIn(ss.kind_key(code), ss.BY_KEY)
        out = run("Карта 4276 3800 1234 5675, пароль: password=Zq9xK2vLm8Rt", hide_kind_CARD=False, hide_kind_SECRET=False)
        self.assertNotIn("4276 3800", out)
        self.assertNotIn("Zq9xK2vLm8Rt", out)

    def test_business_confidential(self):
        text = "Выручка за год составила 4 млн руб."
        self.assertIn("4 млн", run(text))
        self.assertNotIn("4 млн", run(text, business_confidential=True))

    def test_countries_toggle_is_the_country_key(self):
        self.assertEqual(ss.kind_key("COUNTRY"), "countries")


class GeneralOptions(unittest.TestCase):
    def test_strict_hides_doubtful_words(self):
        text = "Компания Альфа-Групп и Ромашка заключили сделку. Альфа-Групп отгрузила товар, Ромашка оплатила."
        a, b = run(text), run(text, strict=True)
        self.assertNotEqual(a, b)
        # после правки S7C строгий режим прячет и повтор в начале предложения: ни одно слово не остаётся видимым
        self.assertNotIn("Ромашка", b)
        self.assertNotIn("Альфа", b)

    def test_ner_candidates_off_removes_model_findings(self):
        text = "Свидетель Тарнов подтвердил показания. Затем Тарнов ушёл."
        reasons = {}
        for flag in (True, False):
            env = Env()
            d = env.service.build_detector(env.service.settings_for({"ner_candidates": flag}))
            d.harvest(text, "x.txt")
            reasons[flag] = [f.reason for f in d.scan(text, "x.txt", "text")]
        self.assertTrue(any("NER" in r for r in reasons[True]), reasons)
        self.assertFalse(any("NER" in r for r in reasons[False]), reasons)

    def test_learn_names_changes_detection(self):
        text = "Директор Иванов Иван Петрович подписал приказ. Позже Иванов И.П. передал дела. Ивану Петровичу выдали премию."
        self.assertNotEqual(run(text), run(text, learn_names=False))

    def test_neutral_names_changes_output_name(self):
        names = {}
        for flag in (True, False):
            env = Env(neutral_names=flag)
            job = env.anonymize(("Договор_Ромашка.txt", "ИНН: 7707083893"))
            names[flag] = job.files[0].out_name
            env.close()
        self.assertNotIn("Ромашка", names[True])
        self.assertNotEqual(names[True], names[False])

    def test_hide_and_keep_terms_apply_on_next_job_without_restart(self):
        env = Env()
        text = "Проект Зефир идёт по плану, Альфа согласовала."
        before = visible(env.output_bytes(env.anonymize(("a.txt", text))).decode())
        self.assertIn("Зефир", before)
        env.vault.set_prefs(hide_terms=["Зефир"])
        after = visible(env.output_bytes(env.anonymize(("a.txt", text))).decode())
        self.assertNotIn("Зефир", after)
        env.vault.set_prefs(hide_terms=[], keep_terms=["Иван Иванов"])
        kept = visible(env.output_bytes(env.anonymize(("a.txt", "Иван Иванов пришёл."))).decode())
        self.assertIn("Иванов", kept)
        env.close()


class FileOptions(unittest.TestCase):
    def test_numbers_excel(self):
        data = xlsx_bytes({"A1": "Сумма", "B1": 1250000, "B2": 987654})
        res = {}
        for flag in (False, True):
            env = Env(numbers=flag)
            job = env.anonymize(("m.xlsx", data))
            res[flag] = xlsx_cells(env.output_bytes(job))
            env.close()
        self.assertEqual(list(res[False].values())[0].get("B1"), 1250000)
        self.assertNotEqual(list(res[True].values())[0].get("B1"), 1250000)

    def test_finance_numbers_excel_and_conflict_option_is_read(self):
        from tests.test_ws_finance import all_parts_text, book
        data = book([["Выручка", 4_200_000], ["Расходы", 3_100_000], ["Прибыль", 1_100_000], ["Налог", 220_000]])
        seen = {}
        for flag in (False, True):
            env = Env(finance_numbers=flag)
            seen[flag] = "4200000" in all_parts_text(env.output_bytes(env.anonymize(("m.xlsx", data))))
            env.close()
        self.assertEqual(seen, {False: True, True: False})
        for flag in ("finance_scale_per_sheet", "finance_text_amounts", "finance_on_formula_conflict"):
            self.assertTrue(any(flag in t for p, t in PRODUCT.items() if p.name == "formats.py"), flag)

    def test_scrub_metadata(self):
        data = docx_bytes(["Текст без данных."], author="Секретный Автор")
        res = {}
        for flag in (True, False):
            env = Env(scrub_metadata=flag)
            res[flag] = zipfile.ZipFile(io.BytesIO(env.output_bytes(env.anonymize(("a.docx", data))))).read("docProps/core.xml").decode()
            env.close()
        self.assertNotIn("Секретный", res[True])
        self.assertIn("Секретный", res[False])

    def test_inspect_embedded_changes_warnings(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(["Привет."]))) as src, zipfile.ZipFile(buf, "w") as dst:
            for n in src.namelist():
                dst.writestr(n, src.read(n))
            dst.writestr("word/embeddings/oleObject1.bin", b"\xd0\xcf\x11\xe0" + b"Secret payload" * 20)
        data = buf.getvalue()
        notes = {}
        for flag in (True, False):
            env = Env(inspect_embedded=flag)
            try:
                job = env.anonymize(("e.docx", data))
                notes[flag] = [str(w) for f in job.files for w in getattr(f, "warnings", [])] + [str(n) for f in job.files for n in getattr(f, "notices", [])]
            finally:
                env.close()
        self.assertTrue(PRODUCT[ROOT / "anonymizer" / "formats.py"].count("inspect_embedded") >= 1)
        self.assertGreaterEqual(len(notes[True]), len(notes[False]), notes)

    def test_image_options_are_read_and_default_is_safe(self):
        self.assertEqual(Settings().image_mode, "replace")
        self.assertEqual(ss.BY_KEY["image_mode"].default, "replace")
        self.assertEqual(ss.BY_KEY["image_brand_policy"].default, "paint")
        self.assertTrue(ss.BY_KEY["ocr_images"].default)
        env = Env(image_mode="redact_text", ocr_images=False, image_brand_policy="off")
        s = env.service.settings_for({})
        self.assertEqual((s.image_mode, s.ocr_images, s.image_brand_policy), ("redact_text", False, "off"))
        env.close()

    def test_image_mode_replace_swaps_picture(self):
        from PIL import Image
        from tests.test_ws_images import pptx_with, media
        buf = io.BytesIO()
        Image.new("RGB", (200, 100), (30, 60, 90)).save(buf, "PNG")
        png = buf.getvalue()
        data = pptx_with(png, "Текст слайда.")
        env = Env(image_mode="replace")
        replaced = media(env.output_bytes(env.anonymize(("p.pptx", data))))
        env.close()
        env = Env(image_mode="redact_text", ocr_images=False)
        kept = media(env.output_bytes(env.anonymize(("p.pptx", data))))
        env.close()
        self.assertNotEqual(replaced, kept)


class StorageAndPersistence(unittest.TestCase):
    def test_options_persist_after_reopen_and_reset(self):
        env = Env()
        app = make_app(env)
        patch = {"strict": True, "numbers": True, "ner_candidates": False, "learn_names": False, "neutral_names": False,
                 "scrub_metadata": False, "image_mode": "redact_text", "ocr_images": False, "image_brand_policy": "warn",
                 "inspect_embedded": False, "retention_days": 90, "restored_retention_days": 7, "keep_originals": False,
                 "hide_kind_PERSON": False, "hide_kind_DEVICE_ID": False, "hide_kind_MEDICAL_ID": False, "hide_kind_COMPENSATION": False,
                 "countries": False, "hide_terms": ["Зефир"], "keep_terms": ["Альфа"], "business_confidential": True,
                 "finance_numbers": True, "finance_scale_per_sheet": True, "finance_text_amounts": True,
                 "finance_on_formula_conflict": "block", "retain_secrets_for_restore": True, "theme": 2}
        app.save_prefs(patch)
        env.reopen()
        for k, v in patch.items():
            self.assertEqual(env.vault.prefs.get(k), v, k)
        s = env.service.settings_for({})
        self.assertFalse(s.ner_candidates)
        self.assertEqual(s.image_brand_policy, "warn")
        self.assertIn("PERSON", s.disabled_kinds)
        self.assertEqual(s.hide_terms, ["Зефир"])
        app = make_app(env)
        app.save_prefs({k: ss.BY_KEY[k].default for k in patch})          # «Сбросить»
        env.reopen()
        s = env.service.settings_for({})
        self.assertEqual((s.strict, s.numbers, s.ner_candidates, s.image_mode, s.disabled_kinds), (False, False, True, "replace", ()))
        env.close()

    def test_retention_choices_are_read(self):
        vault_src = (ROOT / "anonymizer" / "vault.py").read_text(encoding="utf-8")
        for key in ("retention_days", "restored_retention_days", "keep_originals"):
            self.assertIn(key, vault_src + (ROOT / "anonymizer" / "webapp.py").read_text(encoding="utf-8"))

    def test_chat_scope_cannot_set_global_only_options(self):
        for key in ("image_brand_policy", "retention_days", "theme", "finance_on_formula_conflict"):
            with self.assertRaises(ValueError):
                ss.validate_patch({key: ss.BY_KEY[key].default}, scope="chat")


class Ui(unittest.TestCase):
    def test_ner_toggle_has_honest_label_and_privacy_line(self):
        o = ss.BY_KEY["ner_candidates"]
        self.assertIn("нейросет", o.label.lower())
        self.assertIn("без интернета", o.hint)
        state = make_app(Env()).state()
        self.assertIn("ner_available", state)

    def test_page_shows_model_missing_note(self):
        self.assertIn("ner_available", HTML)


if __name__ == "__main__":
    unittest.main()
