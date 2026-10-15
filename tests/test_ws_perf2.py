"""Large-input timing guards (generous bounds: they catch quadratic regressions, not small slowdowns).

The heavy 12 MB / 200k-row cases run only when ANONYMIZER_HEAVY_PERF=1 (several minutes); the rest is quick.
"""
from __future__ import annotations

import os
import random
from anonymizer.util import peak_memory_mb
import time
import unittest

from tests.helpers import Env

HEAVY = os.environ.get("ANONYMIZER_HEAVY_PERF") == "1"
LOG_LINE = "2026-10-09 12:%02d:%02d INFO user Иван Петров (ivan%d@mail.ru) вошёл с адреса 10.0.%d.%d, ООО «Ромашка», г. Москва\n"


class LargeInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def run_txt(self, name: str, text: str) -> tuple[float, str]:
        t = time.time()
        job = self.env.anonymize((name, text.encode("utf-8")))
        return time.time() - t, self.env.output_bytes(job).decode("utf-8")

    def test_company_lines_6000(self):
        random.seed(2)
        names = ["ООО «Ромашка-%d»", "АО «Север %d»", "ПАО «Газпром»", "Siemens AG", "ЗАО «Вектор-%d»"]
        text = "\n".join(random.choice(names).replace("%d", str(i)) + ", ИНН 77%08d" % i for i in range(6000)) + "\n"
        elapsed, out = self.run_txt("co.txt", text)
        self.assertLess(elapsed, 60, f"6000 company lines took {elapsed:.1f}s")
        self.assertNotIn("Ромашка-17", out)

    def test_log_4000_lines_linear(self):
        def build(n):
            return "".join(LOG_LINE % (i % 60, i % 60, i, i % 255, i % 200) for i in range(n))
        small, _ = self.run_txt("a.log", build(500))
        big, out = self.run_txt("b.log", build(4000))
        self.assertLess(big, max(small, 0.5) * 16, f"500 lines {small:.1f}s vs 4000 lines {big:.1f}s")
        self.assertNotIn("ivan3999@mail.ru", out)

    @unittest.skipUnless(HEAVY, "set ANONYMIZER_HEAVY_PERF=1")
    def test_log_16k_lines(self):
        elapsed, out = self.run_txt("c.log", "".join(LOG_LINE % (i % 60, i % 60, i, i % 255, i % 200) for i in range(16000)))
        self.assertLess(elapsed, 90, f"16k log lines took {elapsed:.1f}s")
        self.assertNotIn("Петров", out)

    @unittest.skipUnless(HEAVY, "set ANONYMIZER_HEAVY_PERF=1")
    def test_text_12mb(self):
        random.seed(3)
        paras = [f"Генеральный директор ООО «Ромашка-{i}» Иван Петров (тел. +7 (916) 123-45-{i % 90 + 10}) приехал из Твери в Москву. "
                 f"Компания Siemens и банк «Север» подписали договор №{i} с Анной Смирновой, ИНН 77{i:08d}.\n\n" for i in range(400)]
        parts, size = [], 0
        while size < 12_000_000:
            p = random.choice(paras)
            parts.append(p)
            size += len(p.encode("utf-8"))
        elapsed, out = self.run_txt("big.txt", "".join(parts))
        rss = peak_memory_mb()
        self.assertLess(elapsed, 60, f"12 MB took {elapsed:.1f}s")
        self.assertLess(rss, 1024, f"peak RSS {rss:.0f} MB")
        self.assertNotIn("Смирновой", out)


if __name__ == "__main__":
    unittest.main()
