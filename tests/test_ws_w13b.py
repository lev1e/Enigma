"""W13b: живой статус этапов обезличивания: настоящие этапы, только названия, без найденных значений."""
import unittest
from unittest import mock

from anonymizer import service as svc
from anonymizer.detectors import Detector, STAGE_HOOK
from anonymizer.models import Settings
from anonymizer.service import Upload

from .helpers import Env

PEOPLE = ["Иванов Пётр Сергеевич", "Смирнова Анна Олеговна", "Кузнецов Дмитрий Андреевич"]
SECRETS = ["petr.ivanov@example.org", "+7 (495) 123-45-67", "7707083893", "Ромашка"]


def body(seed: int) -> str:
    rows = []
    for i in range(160):
        rows.append(f"{PEOPLE[(i + seed) % 3]} тел. +7 (495) 123-45-6{i % 10}, почта petr.ivanov{i}@example.org, "
                    f"ИНН 7707083893, ООО «Ромашка» г. Москва, ул. Ленина {i}.")
    return "\n".join(rows)


class StageHookTests(unittest.TestCase):
    def test_no_hook_changes_nothing(self):
        d = Detector([], Settings(suggest=True))
        text = body(0)
        plain = [(f.start, f.end, f.category) for f in d.scan(text, "f", "l")]
        calls = []
        token = STAGE_HOOK.set(calls.append)
        try:
            hooked = [(f.start, f.end, f.category) for f in d.scan(text, "f", "l")]
        finally:
            STAGE_HOOK.reset(token)
        self.assertEqual(plain, hooked)
        self.assertTrue({"entities", "names", "pii"} <= set(calls))


class LiveStageTests(unittest.TestCase):
    def test_stage_changes_in_order_without_leaking_values(self):
        env = Env()
        self.addCleanup(env.close)
        job = env.service.new_job("anonymize", {})
        seen: list[str] = []
        percents: list[float] = []
        def record(percent, stage):
            seen.append(stage)
            percents.append(percent)

        original_set = svc.StageTracker.set

        def record_transition(tracker, *args, **kwargs):
            original_set(tracker, *args, **kwargs)
            record(tracker.job.percent, tracker.job.stage)

        uploads = [Upload(f"doc{i}.txt", body(i).encode("utf-8")) for i in range(3)]
        # Capture actual writes and public progress notifications. Sampling a
        # background thread can miss arbitrarily short stages (including done)
        # when dwell is disabled, regardless of whether the product is correct.
        with mock.patch.object(svc, "STAGE_DWELL", 0), \
                mock.patch.object(svc.StageTracker, "set", record_transition):
            env.service.anonymize(uploads, {}, None, record, job=job)
        order: list[str] = []
        for stage in seen:
            if stage and (not order or order[-1] != stage):
                order.append(stage)
        distinct = set(order)
        self.assertGreaterEqual(len(distinct), 6, order)
        self.assertTrue(any(s.startswith("Файл 2 из 3: ") for s in distinct), order)
        self.assertTrue(any("ФИО" in s for s in distinct), order)
        self.assertTrue(any("организации" in s for s in distinct), order)
        self.assertTrue(any("контакты" in s for s in distinct), order)
        self.assertTrue(any("Проверяю результат" in s for s in distinct), order)
        self.assertIn("Готово", order[-1])
        first_check = next(i for i, s in enumerate(order) if "Проверяю результат" in s)
        first_work = next(i for i, s in enumerate(order) if "Обезличиваю" in s)
        self.assertLess(first_work, first_check)
        self.assertTrue(any("Собираю" in s for s in distinct), order)
        self.assertEqual(percents, sorted(percents), "процент не должен убывать")
        everything = " | ".join(distinct).casefold()
        for value in PEOPLE + SECRETS + ["Иванов", "Смирнова", "Москва", "Ленина"]:
            self.assertNotIn(value.casefold(), everything)


if __name__ == "__main__":
    unittest.main()
