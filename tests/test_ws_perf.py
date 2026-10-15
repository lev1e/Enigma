"""Scaling guards for plain-text anonymization: generous thresholds, they only catch quadratic regressions."""
from __future__ import annotations

import time
import unittest

from tests.helpers import Env

PARAGRAPH = ("Генеральный директор ООО «Ромашка» Иван Петров (тел. +7 (916) 123-45-67) приехал из Твери в Москву. "
             "Компания Siemens и банк «Север» подписали договор №%d с Анной Смирновой.\n\n")


class PerfGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def run_detector(self, text: str) -> tuple[float, list]:
        d = self.env.service.build_detector(self.env.service.settings_for({}))
        t = time.process_time()
        d.harvest(text, "x.txt")
        found = d.scan(text, "x.txt", "text")
        return time.process_time() - t, found

    def test_text_scales_linearly(self):
        def build(n):
            return "".join(PARAGRAPH % i for i in range(n))

        small, _ = self.run_detector(build(400))
        big, _ = self.run_detector(build(3200))
        self.assertLess(big, small * 20, f"400 paragraphs {small:.1f}s, 3200 paragraphs {big:.1f}s: worse than linear + slack")

    def test_many_latin_runs_and_geo_names_do_not_go_quadratic(self):
        line = "В отчёте Pernod Ricard и Coca Cola упомянуты, в ОП Луговско и г. Тверь тоже. Директор Петров И.И.\n"

        def build(n):
            return line * n

        small, _ = self.run_detector(build(400))
        big, _ = self.run_detector(build(3200))
        self.assertLess(big, small * 20, f"{small:.1f}s vs {big:.1f}s")

    def test_huge_text_is_chunked_with_correct_offsets(self):
        from anonymizer.detectors import Detector
        old_threshold, old_target = Detector.CHUNK_THRESHOLD, Detector.CHUNK_TARGET
        Detector.CHUNK_THRESHOLD, Detector.CHUNK_TARGET = 2000, 700
        try:
            text = "".join(PARAGRAPH % i for i in range(60))
            self.assertGreater(len(Detector._chunk_bounds(text)), 3)
            bounds = Detector._chunk_bounds(text)
            self.assertEqual(bounds[0][0], 0)
            self.assertEqual(bounds[-1][1], len(text))
            self.assertTrue(all(a[1] == b[0] for a, b in zip(bounds, bounds[1:])))
            _, found = self.run_detector(text)
        finally:
            Detector.CHUNK_THRESHOLD, Detector.CHUNK_TARGET = old_threshold, old_target
        for f in found:
            self.assertEqual(text[f.start:f.end], f.original)
        phones = [f for f in found if f.category == "PHONE"]
        self.assertEqual(len(phones), 60)
        # Names learned in one piece are recognised in the others.
        persons = {f.key for f in found if f.category == "PERSON" and "Петров" in f.original}
        self.assertEqual(len(persons), 1)

    def test_csv_many_rows(self):
        rows = "\n".join(f"{i},Иван Петров,ООО «Ромашка»,+7 (916) 123-{i % 100:02d}-67" for i in range(3000))
        data = ("id,name,company,phone\n" + rows + "\n").encode("utf-8")
        t = time.process_time()
        job = self.env.anonymize(("rows.csv", data))
        elapsed = time.process_time() - t
        self.assertLess(elapsed, 120, f"3000 csv rows took {elapsed:.1f}s")
        self.assertNotIn("Петров", self.env.output_bytes(job).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
