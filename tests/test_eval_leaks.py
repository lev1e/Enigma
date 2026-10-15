"""Утечки, найденные оценкой tools/eval_text.py (корпус tests/eval/text_corpus_v1.jsonl):
значение должно быть закрыто находкой AUTO целиком."""
from __future__ import annotations

import unittest

from tests.helpers import Env, visible

_ENV = None


def scan(text):
    global _ENV
    if _ENV is None:
        _ENV = Env()
    d = _ENV.service.build_detector(_ENV.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


class EvalLeaks(unittest.TestCase):
    def covered(self, text, value, cat=None):
        start = text.index(value)
        end = start + len(value)
        auto = [f for f in scan(text) if f.decision.value == "AUTO"]
        got = sorted((f.start, f.end) for f in auto
                     if f.start < end and f.end > start and (cat is None or f.category == cat))
        pos = start
        for s, e in got:
            if s <= pos:
                pos = max(pos, e)
        self.assertGreaterEqual(pos, end, f"{value!r} не закрыт: {[(f.category, f.original) for f in auto]}")

    def test_ipv6(self):
        for v in ("2001:db8::1", "fe80::1ff:fe23:4567:890a",
                  "2001:0db8:85a3:0000:0000:8a2e:0370:7334", "::1"):
            self.covered(f"Source IP {v} blocked.", v, "IP_ADDRESS")

    def test_oms_spaced(self):
        self.covered("Полис ОМС 8233 7039 3747 2267.", "8233 7039 3747 2267", "OMS")

    def test_passport_series_number(self):
        self.covered("серия 4512 № 345678, выдан 12.03.2015", "4512 № 345678", "PASSPORT")

    def test_crypto_wallets(self):
        for v in ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
                  "0x1eeecbe2e7fa3034c97dccf3686e6cbb8745d87f"):
            self.covered(f"Wallet {v} received funds.", v, "SECRET")

    def test_password_after_dash(self):
        self.covered("Пароль от почты — Tr0ub4dor&3, никому не говорите.", "Tr0ub4dor&3", "SECRET")

    def test_login_labels(self):
        self.covered("Логин: ipetrov, пароль выдан отдельно.", "ipetrov", "USERNAME")
        self.covered("2026-10-08 12:00:01 INFO user=ipetrov ip=192.168.1.15 login ok", "ipetrov", "USERNAME")

    def test_title_before_surname(self):
        for t, v in (("Д-р Левицкий прочитал доклад.", "Левицкий"), ("Профессор Левицкий прочитал доклад.", "Левицкий"),
                     ("Доктору Левицкому передали письмо.", "Левицкому")):
            self.covered(t, v)

    def test_lowercase_plate(self):
        self.covered("Автомобиль с госномером к456мр178 припаркован.", "к456мр178", "VEHICLE_PLATE")

    def test_iso_birth_date(self):
        self.covered("Дата рождения: 1990-03-03.", "1990-03-03", "BIRTH_DATE")


class SpacingKept(unittest.TestCase):
    def test_phone_label_keeps_space_before_next_word(self):
        env = Env(); self.addCleanup(env.close)
        text = "Тел. +7 (913) 555-12-34 Иванов Иван\nТел. +7 (913) 555-12-34 звонить"
        job = env.anonymize(("e.txt", text))
        out = visible(env.output_bytes(job).decode())
        self.assertNotIn("Phone1Name", out)
        self.assertRegex(out, r"Phone1\w* Name1")
        back = visible(env.output_bytes(env.restore(env.as_upload(job))).decode())
        self.assertEqual(back, text)


class NoNewFalsePositives(unittest.TestCase):
    def test_versions_and_sections_not_ipv6(self):
        for t in ("Время 12:30:45 и 10:15.", "Раздел 3:1 Положения.",
                  "Счёт 1:2 в пользу гостей.", "Файл C:\\dir\\a.txt"):
            bad = [f for f in scan(t) if f.category == "IP_ADDRESS" and f.decision.value == "AUTO"]
            self.assertEqual(bad, [], t)


if __name__ == "__main__":
    unittest.main()
