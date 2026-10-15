"""Макрорегионы («Азия, Африка, Ближний Восток») скрываются как Region и возвращаются обратно."""
import unittest

from tests.helpers import Env


class Regions(unittest.TestCase):
    def test_macro_regions_are_hidden_and_restored(self):
        env = Env(); self.addCleanup(env.close)
        text = "Рынки: Азия, Африка, Ближний Восток и Латинская Америка."
        job = env.anonymize(("a.txt", text.encode("utf-8")))
        out = env.output_bytes(job).decode("utf-8")
        for word in ("Азия", "Африка", "Ближний Восток", "Латинская Америка"):
            self.assertNotIn(word, out)
        self.assertIn("Region", out)
        back = env.restore(env.as_upload(job))
        self.assertEqual(env.output_bytes(back).decode("utf-8"), text)


if __name__ == "__main__":
    unittest.main()
