"""S9G: NER на Markdown/вики-разметке работает по прозе, а не отключается целиком (синтетические данные)."""
import unittest

from anonymizer import ner
from tests.helpers import Env

HAVE = ner.available()
PROSE = ("Председатель правления Алексей Миллер выступил на собрании акционеров. "
         "Позже Дмитрий Козак подтвердил решение совета директоров компании. " * 3)
WIKI = ("{{Карточка компании\n|название = Тест\n|руководитель = [[Миллер, Алексей Борисович|Алексей Миллер]]\n"
        "|сайт = https://example.org/Иван_Петров\n}}\n\n# История\n\n" + PROSE * 8 +
        "\nСм. [[Категория:Компании]] и [[Иван Петров]] в {{cite web|url=http://x.ru|title=Сидоров Пётр}}.\n"
        "```\nкод Фёдор Сорокин\n```\n")


@unittest.skipUnless(HAVE, "natasha не установлена")
class ProseWindows(unittest.TestCase):
    def test_markup_head_no_longer_vetoes_prose(self):
        self.assertTrue(ner._MARKUP.search(WIKI[:4000]))
        self.assertTrue(ner.eligible(WIKI))
        self.assertTrue(ner.person_spans(WIKI))

    def test_offsets_are_original_offsets(self):
        spans = ner.person_spans(WIKI)
        lits = {WIKI[s:e] for s, e, _ in spans}
        self.assertTrue(any("Миллер" in x for x in lits))
        for s, e, _ in spans:
            self.assertEqual(WIKI[s:e], WIKI[s:e].strip())
            self.assertNotIn("\n", WIKI[s:e])

    def test_template_url_fence_not_scanned(self):
        masked = ner.working_text(WIKI)
        self.assertEqual(len(masked), len(WIKI))
        self.assertNotIn("Сидоров", masked)          # внутри {{cite web ...}}
        self.assertNotIn("Фёдор Сорокин", masked)    # блок кода
        self.assertNotIn("example.org", masked)
        self.assertNotIn("Миллер, Алексей Борисович", masked)   # цель ссылки
        self.assertIn("Алексей Миллер выступил", masked)
        for s, e, _ in ner.person_spans(WIKI):
            self.assertNotIn("Сидоров", WIKI[s:e])
            self.assertNotIn("Сорокин", WIKI[s:e])

    def test_name_split_by_markup_is_not_matched(self):
        text = ("Позже Дмитрий {{примечание}} Козак подтвердил решение. " + PROSE + "{{x}}")
        for s, e, _ in ner.person_spans(text):
            self.assertNotIn("{{", text[s:e])

    def test_mostly_markup_keeps_whole_document_veto(self):
        code = "{{a|b=1}}\n" * 300 + "```\n" + "x = [[1, 2]]\n" * 200 + "```\n" + "Иван Петров был здесь. "
        self.assertGreater(ner._mask_markup(code)[1], ner.MARKUP_MAX_SHARE)
        self.assertFalse(ner.eligible(code))
        self.assertEqual(ner.person_spans(code), [])
        html = '<div class="a" data-x="Иван Петров"><span style="color:red">Иван Петров был здесь.</span></div>\n' * 100
        self.assertFalse(ner.eligible(html))
        self.assertEqual(ner.person_spans(html), [])

    def test_no_markup_text_untouched(self):
        self.assertIs(ner.working_text(PROSE), PROSE)
        self.assertTrue(ner.eligible(PROSE))

    def test_vetoed_document_output_identical_with_ner_on_and_off(self):
        html = ('<div class="alpha beta gamma" data-x="Иван Петров" style="color:red;margin:0;padding:0"><span class="delta epsilon" id="zz">Позже Айтказин ответил. Иван Петров был здесь.</span></div>\n') * 80
        outs = []
        for flag in (True, False):
            env = Env()
            job = env.anonymize(("a.txt", html), options={"ner_candidates": flag})
            r = job.result
            outs.append((r["groups"], r["suggestions"], r["total"]))
            env.close()
        self.assertEqual(outs[0], outs[1])   # вывод содержит случайные метки, поэтому сравниваем найденное

    def test_service_md_finds_prose_names(self):
        env = Env()
        text = WIKI.replace("Миллер", "Айтказин")
        job = env.anonymize(("a.md", text), options={"ner_candidates": True})
        out = env.output_bytes(job).decode("utf-8")
        self.assertNotIn("Айтказин", out.split("```")[0].split("# История")[1])
        back = env.restore(env.as_upload(job))
        self.assertEqual(env.output_bytes(back).decode("utf-8"), text)
        env.close()


if __name__ == "__main__":
    unittest.main()
