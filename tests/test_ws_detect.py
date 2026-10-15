"""Поток C (08.10): заголовки таблиц, порча структуры, терпимый возврат меток, ZWSP, производительность."""
from __future__ import annotations

import csv
import io
import json
import re
import time
import unittest
from pathlib import Path

from anonymizer.service import Upload
from tests.helpers import Env, visible


def roundtrip(name: str, content: str, **options):
    env = Env()
    job = env.anonymize((name, content), options=options)
    out = visible(Path(job.files[0].out_path).read_text(encoding="utf-8"))
    back = Path(env.restore(env.as_upload(job)).files[0].out_path).read_text(encoding="utf-8")
    env.close()
    return out, visible(back)


SEED = "Клиент Смирнов Алексей Петрович, ИНН 7707083893, ООО «Ромашка», телефон +7 (916) 555-12-34, Москва.\n"


class RestoreVariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        job = cls.env.anonymize(("a.txt", SEED))
        cls.anon = visible(Path(job.files[0].out_path).read_text(encoding="utf-8"))
        cls.name = "Смирнов Алексей Петрович"

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def restore(self, text: str):
        job = self.env.restore(Upload("b.txt", text.encode("utf-8")))
        f = job.files[0]
        return Path(f.out_path).read_text(encoding="utf-8"), f

    def test_seed_tokens(self):
        self.assertIn("Name1", self.anon)
        self.assertIn("Inn1", self.anon)

    def test_markdown_underscore_emphasis(self):
        for src, want in (("_Name1_ подписал", f"_{self.name}_ подписал"),
                          ("__Name1__ подписал", f"__{self.name}__ подписал"),
                          ("a_Name1_b", f"a_{self.name}_b")):
            self.assertEqual(self.restore(src)[0], want, src)

    def test_variants_still_work(self):
        self.assertEqual(self.restore("Name1_2 x")[0], f"{self.name}_2 x")
        self.assertTrue(self.restore("Name1_2024 x")[0].startswith(self.name))

    def test_loose_forms(self):
        for src, want in (("вName1", f"в{self.name}"), ("Name 1 подписал", f"{self.name} подписал"),
                          ("Name 1 подписал", f"{self.name} подписал"),
                          ("Name​1 подписал", f"{self.name} подписал"),
                          ("Name-1 подписал", f"{self.name} подписал")):
            self.assertEqual(self.restore(src)[0], want, repr(src))

    def test_inn_glued_to_name(self):
        self.assertEqual(self.restore("Inn1Name1")[0], "7707083893" + self.name)
        self.assertEqual(self.restore("Name1Inn1")[0], self.name + "7707083893")

    def test_unknown_loose_token_left_alone(self):
        self.assertEqual(self.restore("Name 77 видов")[0], "Name 77 видов")

    def test_report_names_missing_token(self):
        text, f = self.restore("Только Name1 остался")
        messages = " ".join(m["text"] for m in f.messages)
        self.assertIn("Inn1", messages)
        self.assertIn("Company1", messages)


class Corruption(unittest.TestCase):
    def test_contract_number_keeps_sentence_period(self):
        out, back = roundtrip("a.txt", "Договор №12/2024-А. Следующее предложение. По договору № 45-17/К. Конец.\n")
        self.assertIn("Contract1.", out)
        self.assertIn("Contract2.", out)
        self.assertEqual(back, "Договор №12/2024-А. Следующее предложение. По договору № 45-17/К. Конец.\n")

    def test_phone_label_keeps_trailing_space(self):
        for label in ("Тел", "Тел.", "Моб", "факс", "Телефон:"):
            src = f"{label} +7 (913) 555-12-34 Смирнов Алексей Петрович подписал.\n"
            out, back = roundtrip("a.txt", src)
            self.assertNotIn("Phone1Name1", out, label)
            self.assertRegex(out, r"Phone1 \S*Name1", label)
            self.assertEqual(back, src)


class ZeroWidth(unittest.TestCase):
    def test_zwsp_inside_names_is_still_detected(self):
        z = "​"
        for src in (f"Клиент Смир{z}нов Алексей Петрович позвонил.\n", f"Подписал Иванов Иван Ива{z}нович.\n",
                    f"Письмо от Сидорова А{z}лексея Николаевича получено.\n"):
            out, back = roundtrip("a.txt", src)
            self.assertRegex(out, r"Name\d")
            self.assertNotRegex(out, r"Смир|Иван|Сидор|лексе")
            self.assertEqual(back, src)


class Performance(unittest.TestCase):
    @staticmethod
    def _seconds(lines: int) -> float:
        import random
        rnd = random.Random(1)
        first = ["Алексей", "Мария", "Иван", "Ольга", "Дмитрий", "Анна"]
        base = ["Смирнов", "Кузнецов", "Попов", "Волков", "Соколов", "Лебедев", "Козлов", "Новиков"]
        text = "\n".join(f"{i} {rnd.choice(base)}{rnd.choice(['', 'ский', 'ин'])} {rnd.choice(first)}, "
                          f"{rnd.choice(base)} {rnd.choice(first)}; Acme{i % 50}, Beta{i % 30} заказ {i}"
                          for i in range(lines)) + "\n"
        env = Env()
        started = time.perf_counter()
        env.anonymize(("a.log", text))
        elapsed = time.perf_counter() - started
        env.close()
        return elapsed

    def test_list_heavy_log_scales_roughly_linearly(self):
        small, large = self._seconds(700), self._seconds(2800)
        self.assertLess(large / max(small, 0.05), 9.0, f"{small:.2f}s -> {large:.2f}s for 4x lines")


class TableStructure(unittest.TestCase):
    def rows(self, text: str, delimiter: str):
        return list(csv.reader(io.StringIO(text), delimiter=delimiter))

    def test_separate_name_columns(self):
        src = "Фамилия,Имя,Отчество,Город\nСмирнов,Алексей,Петрович,Москва\nИванова,Мария,Сергеевна,Казань\n"
        out, back = roundtrip("a.csv", src)
        for secret in ("Смирнов", "Алексей", "Петрович", "Иванова", "Мария", "Сергеевна"):
            self.assertNotIn(secret, out)
        self.assertEqual({len(r) for r in self.rows(out, ",")}, {4})
        self.assertEqual(back, src)

    def test_surname_comma_name_patronymic_cell(self):
        src = 'Фамилия, Имя Отчество;Телефон\n"Смирнов, Алексей Петрович";+7 (916) 555-12-34\n"Иванова, Мария Сергеевна";+7 (916) 555-12-35\n'
        out, back = roundtrip("a.csv", src)
        for secret in ("Смирнов", "Алексей", "Иванова", "Мария", "555-12"):
            self.assertNotIn(secret, out)
        self.assertEqual({len(r) for r in self.rows(out, ";")}, {2})
        self.assertEqual(back, src)

    def test_tsv_columns_not_collapsed(self):
        src = "Смирнов\tАлексей\tПетрович\nИванова\tМария\tСергеевна\n"
        out, back = roundtrip("a.tsv", src)
        self.assertEqual({len(r) for r in self.rows(out, "\t")}, {3})
        self.assertNotIn("Смирнов", out)
        self.assertEqual(back, src)

    def test_quoted_cells_keep_quotes_and_person_is_not_org(self):
        src = 'ФИО,Док\n"Смирнов А.П.","ИНН 7707083893"\n"Иванов И.И.","ИНН 7707083894"\n'
        out, back = roundtrip("a.csv", src)
        self.assertEqual([len(r) for r in self.rows(out, ",")], [2, 2, 2])
        self.assertNotIn("Company", out)
        self.assertNotIn("7707083893", out)
        self.assertEqual(back, src)

    def test_minified_json_stays_valid(self):
        src = '{"status":"Paid","type":"Invoice","client":"Смирнов Алексей Петрович","tags":["Alpha","Beta","Gamma"]}'
        out, back = roundtrip("a.json", src)
        data = json.loads(out)
        self.assertEqual(data["status"], "Paid")
        self.assertEqual(data["tags"], ["Alpha", "Beta", "Gamma"])
        self.assertNotIn("Смирнов", out)
        self.assertEqual(back, src)
