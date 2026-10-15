"""U1: anonymizer first, AI second. Page-structure checks (no browser): the AI bar is progressive, one add-files control, search hidden."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "anonymizer" / "web"
JS = (WEB / "ai-chat.js").read_text(encoding="utf-8")
HTML = (WEB / "index.html").read_text(encoding="utf-8")


class ProgressiveAi(unittest.TestCase):
    def test_no_ai_elements_without_provider(self):
        # configured = saved/local provider AND enabled; otherwise the whole dock is hidden
        self.assertIn('S.cfg = S.prov.length > 0 && d.enabled !== false', JS)
        self.assertIn('S.cfg = false', JS)
        self.assertIn("const on = !!S.cfg && chatFiles().length > 0; opts.composer.hidden = !on; box.hidden = !on;", JS)

    def test_bar_only_after_anonymized_result(self):
        # getFiles on the page returns only files that have an anonymized role
        self.assertRegex(HTML, r'getFiles: \(\) => .*roles && f\.roles\.anon')
        self.assertIn("chatFiles().length > 0", JS)
        self.assertIn("aiInline.refreshFiles()", HTML)

    def test_no_examples_or_greeting_on_page(self):
        self.assertIn("empty.hidden = true;", JS)
        self.assertNotIn("empty.hidden = false", JS)

    def test_chips_only_with_more_than_one_file(self):
        self.assertIn("if (chatFiles().length > 1) picked().forEach", JS)

    def test_options_under_one_disclosure(self):
        self.assertIn('bPlus.setAttribute("aria-label", "Параметры")', JS)
        self.assertIn('"Модель"', JS)                      # model picker moved into the menu
        self.assertIn("foot.hidden = true", JS)            # nothing but input, send and the options button at rest
        for item in ('"Версия: "', '"Прикрепить файл"', '"Провайдер и ключ"'):
            self.assertIn(item, JS)

    def test_ai_bar_label(self):
        self.assertIn("Спросить ИИ про эти файлы", JS)


class SingleAddAndSearch(unittest.TestCase):
    def test_single_add_files_control(self):
        self.assertNotIn("Добавить ответ ИИ или ещё файл", HTML)
        self.assertIn('compact ? "+" : "Выбрать файлы"', HTML)
        self.assertEqual(HTML.count('id="pick-chat"'), 1)
        self.assertIn("Перетащите файлы сюда или выберите", HTML)
        self.assertIn('window.addEventListener("drop"', HTML)   # drop anywhere in the window

    def test_search_hidden_by_default_and_ctrl_k(self):
        self.assertRegex(HTML, r'<input type="text" id="chat-search"[^>]* hidden>')
        self.assertIn('$("#chat-search").hidden = !searchOpen && !q;', HTML)
        self.assertNotIn('$("#chat-search").hidden = false;\n  const items', HTML)
        self.assertIn("if (chatList.length <= SEARCH_MIN) return;", HTML)
        self.assertRegex(HTML, r'e\.code === "KeyK"')
        self.assertRegex(HTML, r"const SEARCH_MIN = 3")

    def test_restore_stays_next_to_anonymize(self):
        self.assertRegex(HTML, r'id="btn-chat-anon"[^>]*>Обезличить</button><button class="link" id="btn-chat-rest"')

    def test_drop_note_no_ai_wording(self):
        m = re.search(r'id="drop-note">([^<]*)<', HTML)
        self.assertTrue(m)
        self.assertNotIn("ИИ", m.group(1))


if __name__ == "__main__":
    unittest.main()
