"""Метки файла: что встретилось именно в этом файле задания (нужно, чтобы чат знал свои соответствия)."""
import unittest

from anonymizer.tokens import base_of

from .helpers import Env

TEXT_A = "Договор подписал Пётр Сидоров из ООО «Орбита-Гидропроект». Пётр Сидоров согласен."
TEXT_B = "Письмо для Анна Кузнецова. Копия: Пётр Сидоров."
TEXT_C = "Ничего конфиденциального здесь нет."


class FileTokensTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_each_file_reports_its_own_tokens_even_when_shared(self):
        job = self.env.anonymize(("a.txt", TEXT_A), ("b.txt", TEXT_B), ("c.txt", TEXT_C))
        a, b, c = job.files
        self.assertTrue(a.tokens and b.tokens)
        self.assertEqual(c.tokens, [])
        shared = set(a.tokens) & set(b.tokens)
        self.assertEqual(len(shared), 1)       # Пётр Сидоров встретился в обоих файлах, метка одна
        self.assertGreater(len(set(a.tokens) | set(b.tokens)), len(shared))
        for token in a.tokens + b.tokens:
            self.assertEqual(base_of(token), token)

    def test_restore_reports_tokens_found_in_the_file(self):
        job = self.env.anonymize(("a.txt", TEXT_A))
        back = self.env.restore(self.env.as_upload(job))
        self.assertEqual(sorted(back.files[0].tokens), sorted(job.files[0].tokens))

    def test_tokens_are_not_in_public_payload(self):
        job = self.env.anonymize(("a.txt", TEXT_A))
        self.assertNotIn("tokens", job.files[0].public())


if __name__ == "__main__":
    unittest.main()
