"""Чат-интерфейс окна: список чатов сворачивается, перед запуском видно, что будет скрыто, страны скрываются по умолчанию."""
import http.client
import json
import re
import threading
import unittest
from pathlib import Path

from anonymizer.vault import DEFAULT_PREFS
from anonymizer.webapp import create_server

from .helpers import Env

WEB = Path(__file__).resolve().parent.parent / "anonymizer" / "web" / "index.html"


class PrefsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.env.close()

    def call(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Cookie": f"anon_t={self.app.token}", "X-Requested-With": "anonymizer", "Content-Type": "application/json"}
        conn.request(method, path, json.dumps(payload) if payload is not None else None, headers)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_standard_profile_hides_countries_and_not_numbers(self):
        self.assertTrue(DEFAULT_PREFS["countries"])
        self.assertTrue(DEFAULT_PREFS["neutral_names"])
        self.assertFalse(DEFAULT_PREFS["numbers"])
        self.assertFalse(DEFAULT_PREFS["strict"])

    def test_sidebar_choice_is_unset_then_saved_and_survives_other_pref_saves(self):
        self.assertIsNone(self.call("GET", "/api/state")[1]["prefs"]["sidebar_collapsed"])
        status, state = self.call("POST", "/api/prefs", {"sidebar_collapsed": True})
        self.assertEqual(status, 200)
        self.assertIs(state["prefs"]["sidebar_collapsed"], True)
        # Окно «Настройки» сохраняет свои поля и не должно сбрасывать выбор списка чатов.
        status, state = self.call("POST", "/api/prefs", {"numbers": True})
        self.assertIs(state["prefs"]["sidebar_collapsed"], True)
        self.assertTrue(self.call("GET", "/api/state")[1]["prefs"]["sidebar_collapsed"])
        self.call("POST", "/api/prefs", {"numbers": False, "sidebar_collapsed": False})

    def test_column_widths_are_saved_validated_and_reset(self):
        prefs = self.call("GET", "/api/state")[1]["prefs"]
        self.assertIsNone(prefs["sidebar_width"])
        self.assertIsNone(prefs["pane_width"])
        state = self.call("POST", "/api/prefs", {"sidebar_width": 300, "pane_width": 500})[1]
        self.assertEqual((state["prefs"]["sidebar_width"], state["prefs"]["pane_width"]), (300, 500))
        state = self.call("POST", "/api/prefs", {"numbers": True})[1]      # чужие поля ширину не трогают
        self.assertEqual(state["prefs"]["sidebar_width"], 300)
        state = self.call("POST", "/api/prefs", {"sidebar_width": 9999, "pane_width": "x"})[1]   # вне пределов или не число: по умолчанию
        self.assertIsNone(state["prefs"]["sidebar_width"])
        self.assertIsNone(state["prefs"]["pane_width"])


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = WEB.read_text(encoding="utf-8")

    def test_sidebar_toggle_is_keyboard_reachable_and_labelled(self):
        for needle in ('id="btn-side-close"', 'id="btn-side-open"', 'aria-controls="side"', 'aria-expanded="true"',
                       "Скрыть список чатов", "Показать список чатов", 'e.code !== "KeyB"', ".shell.side-off"):
            self.assertIn(needle, self.html)
        # Скрытый список выпадает из порядка Tab: visibility:hidden включается после перехода, а не только сдвиг за край.
        self.assertRegex(self.html, r"\.shell\.side-off \.side \{ visibility: hidden; transition: visibility 0s linear var\(--dur-3\); \}")

    def test_sidebar_choice_is_stored_in_app_prefs_not_in_the_window_origin(self):
        self.assertIn("sidebar_collapsed: sideOff", self.html)
        self.assertNotIn("localStorage.", self.html)   # адрес окна каждый раз новый: localStorage не переживёт перезапуск

    def test_collapsed_state_widens_the_page_and_keeps_the_table_pane(self):
        # колонка чтения растёт вместе с окном, пока не упрётся в 1100 px; отдельного правила для скрытой панели нет
        self.assertIn("max-width: clamp(760px, 68%, 1100px)", self.html)
        self.assertNotIn(".shell.side-off .page.wide", self.html)
        self.assertIn("grid-template-columns: var(--side-w) minmax(0, 1fr) var(--pane-w)", self.html)   # колонки меняются одним переходом

    def test_narrow_window_hides_the_list_by_itself_and_header_wraps(self):
        self.assertIn('narrowScreen()', self.html)
        self.assertIn("body:not(.dlg-mode) .chat-head { flex-wrap: wrap;", self.html)
        self.assertIn(".composer { position: static; max-height: none; }", self.html)   # на низком окне поле файла не съедает половину экрана

    def test_plan_summary_is_shown_before_the_run_button_with_all_four_options_inside(self):
        order = [self.html.index(x) for x in ('id="plan-line"', 'id="opts"', 'id="opt-countries"', 'id="opt-strict"', 'id="btn-chat-anon"')]
        self.assertEqual(order, sorted(order))
        self.assertIn("Стандартное обезличивание", self.html)
        self.assertIn("Будут скрыты:", self.html)
        self.assertIn("Не скрываются:", self.html)
        # Обычное и рискованное разведено по разным группам.
        self.assertLess(self.html.index("Включено по умолчанию"), self.html.index("Может скрыть лишнее"))
        self.assertLess(self.html.index('id="opt-names"'), self.html.index("Может скрыть лишнее"))
        self.assertGreater(self.html.index('id="opt-numbers"'), self.html.index("Может скрыть лишнее"))

    def test_rules_are_explained_in_user_language_in_settings(self):
        block = self.html[self.html.index('id="rules"'):self.html.index('id="gen-words"')]
        for word in ("ФИО", "Компании", "Города и адреса", "Страны", "Контакты", "Реквизиты", "Числа в Excel", "Сомнительные слова", "Ваши слова"):
            self.assertIn(word, block)
        self.assertIn("может пропустить", block)

    def test_late_answer_for_a_previous_chat_is_ignored(self):
        self.assertIn("const seq = ++openSeq;", self.html)
        self.assertIn("if (seq !== openSeq) return;", self.html)
        self.assertRegex(self.html, r"function startDraft\(\) \{\s*openSeq\+\+;")

    def test_switching_chats_is_blocked_while_a_file_is_processed(self):
        self.assertIn("Идёт обработка файла. Дождитесь результата.", self.html)
        self.assertIn("if (busy()) return;", self.html)

    def test_focus_after_deleting_a_chat_goes_to_a_visible_control(self):
        self.assertIn('(sideOff ? $("#btn-side-open") : next || $("#btn-new-chat")).focus();', self.html)

    def test_original_version_is_marked_as_not_for_ai(self):
        self.assertIn('orig: "Исходный, не для ИИ"', self.html)
        self.assertIn('anon: "Для ИИ"', self.html)

    def test_long_chat_titles_have_a_tooltip(self):
        self.assertRegex(self.html, r'class="chat-item" data-id="\$\{esc\(it\.id\)\}" title="\$\{esc\(shownTitle\(it\)\)\}"')

class ResultBlockContractTests(unittest.TestCase):
    """Результат: один понятный шаг (сохранить файл), замечания названы, сомнительные слова свёрнуты и ограничены по высоте."""
    html = (Path(__file__).resolve().parent.parent / "anonymizer" / "web" / "index.html").read_text("utf-8")

    def test_suspects_are_collapsed_by_default_and_bounded(self):
        self.assertNotIn('class="more-words" open', self.html)
        self.assertNotIn('class="more-words"${strong.length ? " open"', self.html)
        self.assertIn("Программа не уверена в", self.html)
        self.assertRegex(self.html, r"\.sus-list \{[^}]*max-height: min\(45dvh")
        self.assertIn('data-sus="all"', self.html)
        self.assertIn("Скрыть выбранное", self.html)
        self.assertIn('class="sus-foot"', self.html)

    def test_warning_names_what_is_wrong_and_links_to_it(self):
        self.assertIn('data-goto="more-words"', self.html)
        self.assertIn('data-goto="result-notes"', self.html)
        self.assertNotIn("Прочитайте замечания ниже", self.html)

    def test_save_button_comes_before_the_lists_and_next_steps_are_visible(self):
        body = self.html[self.html.index("function renderResult"):self.html.index("function saveButtonHtml")]
        self.assertLess(body.index("saveButtonHtml(job"), body.index("nextStepsHtml()"))
        self.assertLess(body.index("nextStepsHtml()"), body.index("anonymizeExtras(job)"))
        self.assertIn("<h4>Что дальше</h4>", self.html)
        self.assertNotIn("<summary>Что дальше</summary>", self.html)

    def test_composer_collapses_after_a_result_and_scroll_keeps_clear_of_it(self):
        self.assertIn(".drop-more { display: grid; grid-template-rows: 1fr;", self.html)
        self.assertIn("grid-template-rows: 0fr", self.html)
        self.assertIn("scroll-padding-bottom: var(--composer-h", self.html)
        self.assertIn("--composer-h", self.html)

    def test_rerun_replaces_the_result_in_place(self):
        self.assertIn('redo.classList.add("busy")', self.html)
        self.assertIn(".result.still { animation: none; }", self.html)


class ProjectMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = WEB.read_text(encoding="utf-8")

    def test_folder_choice_and_texts(self):
        for text in ("Добавить в чат как проект", "Обезличить отдельно, без чата", "Папка с ответом ИИ", "Остановить",
                     "Оригиналы не хранятся: «Обезличить заново» и «Вернуть заново» не будут работать.",
                     "Не будут обработаны", "Вернуть значения в проект"):
            self.assertIn(text, self.html)
        for ident in ('id="pick-folder-answer"', 'id="btn-cancel-job"', 'data-fmode="project"', 'role="radiogroup"'):
            self.assertIn(ident, self.html)

    def test_project_requests_and_progress(self):
        self.assertIn('"/api/folder/project"', self.html)
        self.assertIn('"/api/cancel"', self.html)
        self.assertIn("Обработано ${s.processed || 0} из ${s.total}", self.html)

    def test_feed_tree_and_save_project(self):
        for text in ("Сохранить весь проект как папку…", "Файлы проекта (", 'data-saveproj="${role}"', "save_project", "/project/${role}.zip"):
            self.assertIn(text, self.html)
        self.assertIn(".trow .btn.sm { min-height: 36px; }", self.html)
        self.assertIn("max-height: 340px", self.html)

    def test_project_label_in_sidebar_and_header(self):
        self.assertIn("Проект · ${filesWord(it.files)}", self.html)
        self.assertIn('c.project ? "Проект · " : ""', self.html)
        self.assertIn("Пересоберутся все файлы проекта", self.html)


if __name__ == "__main__":
    unittest.main()
