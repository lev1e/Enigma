"""Окно программы: мост к системным диалогам, один экземпляр, соответствие страницы требованиям к дизайну."""
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path

from anonymizer import crypto, desktop
from anonymizer.vault import Vault
from anonymizer.webapp import WEB_DIR, create_server

from .helpers import Env, xlsx_bytes, xlsx_cells


class FakeWindow:
    """Подмена системных окон: отдаёт заранее заданные ответы и запоминает, о чём спросили."""

    def __init__(self):
        self.answers = []
        self.asked = []

    def create_file_dialog(self, dialog_type=10, directory="", allow_multiple=False, save_filename="", file_types=()):
        self.asked.append({"type": dialog_type, "directory": directory, "multiple": allow_multiple,
                           "name": save_filename, "types": tuple(file_types)})
        return self.answers.pop(0) if self.answers else None


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.server, self.app = create_server(self.env.vault, self.env.base / "work")
        self.window = FakeWindow()
        self.bridge = desktop.Bridge(self.app, lambda: self.window)
        self.folder = self.env.base / "user"
        self.folder.mkdir()

    def tearDown(self):
        self.server.server_close()
        self.env.close()

    def write(self, name, data):
        path = self.folder / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def anonymized(self):
        path = self.write("Данные.xlsx", xlsx_bytes({"A1": "ООО «Орбита-Гидропроект»", "B1": "Пётр Сидоров"}))
        self.window.answers = [(path,)]
        picked = self.bridge.pick_files()
        job_id = self.app.start_job("anonymize", [picked["files"][0]["info"]["id"]], {})
        self.app.runners[job_id].join(60)
        return job_id

    def test_pick_reads_files_from_disk_and_reports_each_one(self):
        good = self.write("a.xlsx", xlsx_bytes({"A1": "Иван Петров"}))
        old = self.write("старый.xls", b"x")
        self.window.answers = [(good, old, str(self.folder / "нет.txt"))]
        result = self.bridge.pick_files()
        first, second, third = result["files"]
        self.assertTrue(first["info"]["supported"])
        self.assertFalse(second["info"]["supported"])
        self.assertIn("xlsx", second["info"]["note"])
        self.assertIn("error", third)
        self.assertTrue(self.window.asked[0]["multiple"])
        self.assertTrue(any("xlsx" in t for t in self.window.asked[0]["types"]))

    def test_pick_cancelled_gives_an_empty_list(self):
        self.window.answers = [None]
        self.assertEqual(self.bridge.pick_files(), {"files": []})

    def test_a_dialog_failure_is_reported_as_a_line_not_an_exception(self):
        def broken(*args, **kwargs):
            raise RuntimeError("нет окна")
        self.window.create_file_dialog = broken
        self.assertIn("error", self.bridge.pick_files())
        self.assertIn("error", self.bridge.save_result("x", 0))

    def test_save_result_copies_the_file_and_remembers_the_folder(self):
        job_id = self.anonymized()
        target = self.folder / "результат.xlsx"
        self.window.answers = [(str(target),)]
        result = self.bridge.save_result(job_id, 0)
        self.assertEqual(result["path"], str(target))
        self.assertNotIn("Сидоров".encode(), target.read_bytes())
        ask = self.window.asked[-1]
        self.assertIn("(обезличено)", ask["name"])
        self.assertTrue(ask["name"].endswith(".xlsx"))
        self.window.answers = [(str(self.folder / "второй.xlsx"),)]
        self.bridge.save_result(job_id, 0)
        self.assertEqual(self.window.asked[-1]["directory"], str(self.folder))

    def test_save_result_accepts_a_plain_string_and_survives_cancel(self):
        job_id = self.anonymized()
        self.window.answers = [None]
        self.assertEqual(self.bridge.save_result(job_id, 0), {"cancelled": True})
        target = self.folder / "s.xlsx"
        self.window.answers = [str(target)]
        self.assertEqual(self.bridge.save_result(job_id, 0)["path"], str(target))

    def test_save_result_to_an_unwritable_place_is_one_line_with_an_action(self):
        job_id = self.anonymized()
        self.window.answers = [(str(self.folder / "нет" / "папки" / "f.xlsx"),)]
        result = self.bridge.save_result(job_id, 0)
        self.assertIn("error", result)
        self.assertIn("папк", result["error"])

    def test_unknown_job_is_a_line(self):
        self.assertIn("error", self.bridge.save_result("nope", 0))
        self.assertIn("error", self.bridge.save_all("nope"))

    def test_save_all_writes_into_a_folder_and_never_overwrites(self):
        one = self.write("один.txt", "Пётр Сидоров подписал договор с ООО «Орбита-Гидропроект»")
        two = self.write("два.txt", "Ольга Иванова")
        self.window.answers = [(one, two)]
        ids = [f["info"]["id"] for f in self.bridge.pick_files()["files"]]
        job_id = self.app.start_job("anonymize", ids, {"neutral_names": False})
        self.app.runners[job_id].join(60)
        target = self.env.base / "out"
        target.mkdir()
        (target / "один (обезличено).txt").write_text("занято", "utf-8")
        self.window.answers = [(str(target),)]
        result = self.bridge.save_all(job_id)
        self.assertEqual(sorted(result["saved"]), [0, 1])
        self.assertEqual((target / "один (обезличено).txt").read_text("utf-8"), "занято")
        self.assertTrue((target / "один (обезличено) (2).txt").exists())
        self.assertEqual(len(list(target.iterdir())), 3)

    def test_reveal_only_opens_files_the_program_saved(self):
        stranger = self.write("чужой.txt", "x")
        self.assertIn("error", self.bridge.reveal(stranger))
        self.assertIn("error", self.bridge.reveal("/etc/hosts"))

    def test_csv_is_saved_with_a_bom_for_excel(self):
        target = self.folder / "соответствия.csv"
        self.window.answers = [(str(target),)]
        result = self.bridge.save_text("соответствия.csv", "Группа;Было\r\nИмена;Пётр")
        self.assertEqual(result["path"], str(target))
        self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn("Пётр", target.read_text("utf-8-sig"))

    def test_backup_round_trip_through_the_bridge(self):
        self.anonymized()
        self.assertIn("error", self.bridge.export_backup("abc"))
        target = self.folder / "копия.anonkeys"
        self.window.answers = [(str(target),)]
        self.assertEqual(self.bridge.export_backup("надёжный-пароль")["path"], str(target))
        other = Env()
        try:
            _, other_app = create_server(other.vault, other.base / "work")
            other_bridge = desktop.Bridge(other_app, lambda: self.window)
            self.assertIn("error", other_bridge.import_backup("надёжный-пароль"))      # файл ещё не выбран
            self.window.answers = [(str(target),)]
            self.assertEqual(other_bridge.pick_backup(), {"name": "копия.anonkeys"})
            self.assertIn("error", other_bridge.import_backup("неверный пароль"))
            self.window.answers = [(str(target),)]
            other_bridge.pick_backup()
            result = other_bridge.import_backup("надёжный-пароль")
            self.assertNotIn("error", result)
            self.assertGreater(other.vault.stats()["entities"], 0)
        finally:
            other.close()


class SingleInstanceTests(unittest.TestCase):
    def test_second_lock_is_refused_until_the_first_is_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "instance.lock"
            first, second = desktop.InstanceLock(path), desktop.InstanceLock(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_a_second_launch_asks_the_first_window_to_come_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("ANONYMIZER_HOME")
            os.environ["ANONYMIZER_HOME"] = tmp
            server = None
            try:
                self.assertFalse(desktop.notify_existing(timeout=1))       # запущенной копии нет
                env = Env()
                server, app = create_server(env.vault, env.base / "work")
                called = []
                app.on_focus = lambda: called.append(True)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                desktop.instance_file().write_text(json.dumps({"port": server.server_address[1], "token": app.token}), "utf-8")
                self.assertTrue(desktop.notify_existing())
                self.assertEqual(called, [True])
                desktop.instance_file().write_text(json.dumps({"port": server.server_address[1], "token": "чужой"}), "utf-8")
                self.assertFalse(desktop.notify_existing(timeout=1))
                env.close()
            finally:
                if server:
                    server.shutdown()
                    server.server_close()
                if previous is None:
                    os.environ.pop("ANONYMIZER_HOME", None)
                else:
                    os.environ["ANONYMIZER_HOME"] = previous

    def test_webview2_check_is_skipped_outside_windows(self):
        import sys
        if sys.platform != "win32":
            self.assertTrue(desktop.webview2_installed())


class SelfCheckTests(unittest.TestCase):
    def test_selfcheck_reports_every_component_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("ANONYMIZER_HOME")
            os.environ["ANONYMIZER_HOME"] = tmp
            try:
                report = Path(tmp) / "report.json"
                self.assertEqual(desktop.selfcheck(report), 0)
                info = json.loads(report.read_text("utf-8"))
            finally:
                if previous is None:
                    os.environ.pop("ANONYMIZER_HOME", None)
                else:
                    os.environ["ANONYMIZER_HOME"] = previous
        self.assertTrue(info["ok"], info)
        self.assertEqual(set(info["checks"]), {"page_resource", "morphology_dictionary", "window_component", "server_and_page", "addin_https_page", "helper_and_window_client",
                                               "anonymize_and_restore"})
        self.assertTrue(info["pywebview"])


class PageContractTests(unittest.TestCase):
    """Требования к внешнему виду, которые легко нарушить правкой стилей."""

    @classmethod
    def setUpClass(cls):
        cls.html = (WEB_DIR / "index.html").read_text("utf-8")

    def test_no_gradients_or_glows_and_shadows_only_for_floating_surfaces(self):
        for word in ("gradient", "text-shadow", "filter:"):
            self.assertNotIn(word, self.html, word)
        css = self.html[:self.html.index("</style>")]
        # Тень допустима только у всплывающего: диалог, всплывающее сообщение, выезжающий список чатов на узком окне.
        for selector in re.findall(r"([^{}]+)\{[^{}]*box-shadow", css):
            self.assertRegex(selector.strip(), r"^(dialog|\.toast|\.side|\.row-menu)$", selector)

    def test_motion_is_short_one_shot_and_respects_reduced_motion(self):
        """Движение допустимо только как отклик на смену состояния: без повторов, отскока и анимации раскладки."""
        css = self.html[:self.html.index("</style>")]
        self.assertNotIn("infinite", css)
        self.assertNotRegex(css, r"cubic-bezier\([^)]*-\d")          # без отскока и пружины
        for body in re.findall(r"@keyframes \w+ \{(.*?\})\s*\}", css, flags=re.S):
            for prop in re.findall(r"([a-z-]+)\s*:", body):
                self.assertIn(prop, ("opacity", "transform"), prop)
        # Одна шкала длительностей, не длиннее 240 мс.
        durations = [float("0" + x) for x in re.findall(r"--dur-\d: (\.\d+)s", css)]
        self.assertEqual(len(durations), 3)
        self.assertLessEqual(max(durations), 0.24)
        for value in re.findall(r"(?:animation|transition)[^;{}]*?(\d*\.?\d+)m?s\b", css):
            self.assertIn(value, ("0", ".01", "0.01"), value)   # длительности только через --dur-*, кроме обнуления
        # Просьба системы убрать анимацию отключает всё разом.
        self.assertRegex(css, r"@media \(prefers-reduced-motion: reduce\) \{[^}]*animation-duration: \.01ms !important[^}]*transition-duration: \.01ms !important")
        self.assertIn("reduceMotion()", self.html)   # скрипт тоже не анимирует высоту блоков

    def test_width_handles_are_separators_with_keyboard_and_no_drag_transition(self):
        html = self.html
        for side in ("split-side", "split-pane"):
            tag = re.search(r'<div class="split" id="%s"[^>]*>' % side, html).group(0)
            for attr in ('role="separator"', 'aria-orientation="vertical"', 'aria-controls=', 'aria-label=', 'tabindex="0"'):
                self.assertIn(attr, tag, (side, attr))
        for needle in ('"aria-valuenow"', '"aria-valuemin"', '"aria-valuemax"', 'setPointerCapture', 'e.key === "Home"', 'e.key === "End"',
                       'e.key === "Enter"', "ondblclick", 'sidebar_width', 'pane_width'):
            self.assertIn(needle, html, needle)
        css = html[:html.index("</style>")]
        self.assertRegex(css, r"\.shell\.resizing\s*\{\s*transition:\s*none")
        self.assertRegex(css, r"\.split\s*\{[^}]*cursor:\s*col-resize")
        self.assertRegex(css, r"\.split\s*\{[^}]*width:\s*8px")      # размер ручки постоянный: меняется только цвет линии
        self.assertNotRegex(css, r"\.split:(hover|focus-visible)\s*\{[^}]*(width|margin|padding)")
        self.assertRegex(css, r"@media \(max-width: 720px\) \{\s*\.split \{ display: none")
        self.assertIn(".dlg-mode .split", css)

    def test_chat_row_menu_roles_keys_and_scope_of_delete(self):
        html = self.html
        self.assertIn('class="row-menu-btn" aria-haspopup="menu" aria-expanded="false" aria-label="Действия с чатом', html)
        self.assertRegex(html, r'id="row-menu" role="menu"')
        self.assertEqual(len(re.findall(r"<button role=.menuitem.", html)), 2)
        for key in ('"ContextMenu"', '"F10"', '"Delete"', '"Escape"', '"ArrowDown"', '"ArrowUp"', '"Home"', '"End"', 'contextmenu'):
            self.assertIn(key, html, key)
        css = html[:html.index("</style>")]
        self.assertRegex(css, r"\.row-menu-btn\s*\{[^}]*width:\s*32px[^}]*height:\s*32px")
        self.assertRegex(css, r"\.chat-item\s*\{[^}]*padding:\s*6px 36px 6px")     # место под кнопку занято всегда
        line = next(l for l in html.splitlines() if 'title: "Удалить чат?"' in l)
        for word in ("исходные файлы", "обезличенные и возвращённые версии", "история шагов", "Коды замен в хранилище останутся", "нельзя"):
            self.assertIn(word, line)
        self.assertIn("danger: true", line)

    def test_no_emoji_icons_or_images(self):
        self.assertIsNone(re.search("[\U0001F300-\U0001FAFF☀-➿⬀-⯿]", self.html))
        for tag in ("<svg", "<img", "<canvas"):
            self.assertNotIn(tag, self.html)

    def test_forbidden_words_are_absent(self):
        visible = re.sub(r"<style.*?</style>|<script.*?</script>", "", self.html, flags=re.S).lower()
        for word in ("умн", "магия", "магическ", "ии-помощник"):
            self.assertNotIn(word, visible)
        self.assertNotIn("!", re.sub(r"<style.*?</style>|<script.*?</script>", "", self.html, flags=re.S).replace("<!doctype", ""))

    def test_page_loads_nothing_from_the_network(self):
        self.assertIsNone(re.search(r"(src|href)=[\"']https?:", self.html))
        self.assertNotIn("@import", self.html)
        self.assertNotIn("url(http", self.html)

    def test_one_accent_colour_and_dark_theme_are_defined(self):
        self.assertIn("prefers-color-scheme: dark", self.html)
        self.assertIn("--accent:", self.html)
        # Акцент допустим только у главной кнопки и фокуса.
        uses = [m.start() for m in re.finditer(r"var\(--accent[a-z-]*\)|var\(--focus\)", self.html)]
        self.assertLessEqual(len(uses), 15)  # +1: включённый переключатель в настройках

    def test_ids_are_unique(self):
        ids = re.findall(r'\bid="([^"$]+)"', self.html)
        self.assertEqual(len(ids), len(set(ids)), sorted({i for i in ids if ids.count(i) > 1}))

    def test_every_control_has_a_visible_focus_style(self):
        self.assertIn(":focus-visible", self.html)
        self.assertNotIn("outline: none", self.html)
        self.assertNotIn("outline:0", self.html)

    def test_no_side_stripe_borders(self):
        self.assertIsNone(re.search(r"border-(left|right)\s*:\s*([2-9]|\d\d)px", self.html))

    def test_layout_stays_put_on_state_changes(self):
        html = self.html
        self.assertRegex(html, r"html\s*\{\s*scrollbar-gutter:\s*stable")
        # План не должен появляться пустым: строка занимает место до загрузки состояния.
        self.assertRegex(html, r'class="plan-line pending"[^>]*>[^<]+<')
        self.assertRegex(html, r"\.plan-line\.pending\s*\{\s*visibility:\s*hidden")
        # Подписи, меняющиеся по состоянию, не двигают соседей.
        for sel in ("#btn-reveal", "#btn-chat-anon", "#btn-addin-install"):
            self.assertRegex(html, re.escape(sel) + r"\s*\{\s*min-width:")
        # Заголовок чата: без рамки, при наведении и фокусе меняется только заливка.
        self.assertIn("input[type=text].chat-title:hover, input[type=text].chat-title:focus { background: var(--field); }", html)
        self.assertNotRegex(html, r"chat-title:hover[^}]*border-width")
        # Таблица: заметка о правке не раздвигает список, подсказка про значения не исчезает.
        self.assertRegex(html, r"\.undo-note\s*\{[^}]*position:\s*sticky")
        self.assertLess(html.index('id="table-body"'), html.index('id="pane-note"'))
        self.assertNotIn('$("#reveal-hint").hidden', html)
        # Диалог отвечает только после закрытия, иначе фокус возвращается на уже заменённую кнопку.
        self.assertIn("closeDialog_(dlg, () => resolve(value))", html)

    def test_resize_handles_have_explicit_grid_end_lines(self):
        # grid-area: 1 / 1 оставляет конец области автоматическим: у абсолютно позиционированного элемента он уезжает к краю окна.
        self.assertIn("#split-side { grid-area: 1 / 1 / 2 / 2;", self.html)
        self.assertIn("#split-pane { grid-area: 1 / 3 / 2 / 4;", self.html)

    def test_table_can_add_a_missed_word_and_warns_about_files_not_rebuilt(self):
        html = self.html
        self.assertIn('id="btn-pane-add"', html)
        self.assertIn('action: "hide_new"', html)
        self.assertIn("not_updated", html)

    def test_chat_title_is_styled_with_enough_specificity(self):
        # input[type=text] иначе перебивает .chat-title и название выглядит полем формы
        self.assertIn("input[type=text].chat-title", self.html)

    def test_one_place_for_extra_words_and_screen_reader_support(self):
        self.assertNotIn('id="hide-once"', self.html)
        self.assertEqual(self.html.count('id="extra-terms"'), 1)
        for needle in ('id="sr-status"', 'role="progressbar"', "prefers-reduced-motion" if False else "aria-expanded"):
            self.assertIn(needle, self.html)

    def test_user_text_says_code_not_label_in_the_table(self):
        table = self.html[self.html.index("/* ---------- таблица замен"):self.html.index("/* ---------- старт")]
        self.assertNotIn("метк", table.lower())


    # ---- аудит клавиатуры и доступности ----
    def test_reveal_button_state_is_in_its_label_not_aria_pressed(self):
        self.assertNotIn("aria-pressed", self.html)
        self.assertIn('"Скрыть значения" : "Показать значения"', self.html)

    def test_dialogs_are_named_and_ask_errors_are_announced(self):
        self.assertIn('<dialog id="settings" aria-labelledby="settings-title">', self.html)
        self.assertIn('id="settings-title"', self.html)
        self.assertIn('<dialog id="ask" aria-labelledby="ask-title">', self.html)
        self.assertIn('id="ask-error" role="alert"', self.html)
        self.assertIn('setAttribute("aria-invalid", "true")', self.html)

    def test_destructive_confirms_start_on_the_safe_button(self):
        self.assertIn('(danger ? $("#ask-cancel") : typed', self.html)
        for title in ("Удалить чат?", "Очистить хранилище и удалить все чаты?", "Удалить код ${base}?"):
            line = next(l for l in self.html.splitlines() if title in l)
            self.assertIn("danger: true", line, title)

    def test_clear_vault_dialog_says_everything_that_is_lost(self):
        line = next(l for l in self.html.splitlines() if "Очистить хранилище и удалить все чаты?" in l)
        for word in ("все чаты", "оригиналы", "обезличенные и возвращённые версии", "уже отдали ИИ", "нельзя"):
            self.assertIn(word, line)

    def test_focus_is_kept_after_remove_run_and_finish(self):
        self.assertIn("afterRemove", self.html)
        self.assertIn('st.focus({preventScroll: true})', self.html)
        self.assertIn('head.focus({preventScroll: true})', self.html)

    def test_escape_in_chat_title_does_not_close_the_pane(self):
        self.assertIn('if (e.target === $("#chat-title")) return;', self.html)

    def test_repeated_buttons_name_their_file(self):
        self.assertRegex(self.html, r'data-open="[^"]*" data-role="\$\{r\}" aria-label="Открыть «')
        self.assertRegex(self.html, r'data-savefile="[^"]*" data-role="\$\{r\}" aria-label="Сохранить как… «')

    def test_retention_hint_and_original_file_names_note(self):
        self.assertIn('id="retention-hint"', self.html)
        self.assertIn("после последнего изменения", self.html)
        self.assertIn("Названия файлов остаются исходными.", self.html)
        # Значения по умолчанию в подсказке совпадают с хранилищем.
        self.assertIn("180 : +p.retention_days", self.html)
        self.assertIn("30 : +p.restored_retention_days", self.html)

    def test_error_toasts_stay_until_dismissed(self):
        self.assertIn("if (!error) setTimeout(drop, 4500);", self.html)
        self.assertIn('toast(e.message, true)', self.html)

    def test_placeholder_and_field_border_contrast(self):
        """Подсказка в поле >= 4.5:1, рамка поля >= 3:1 в светлой и тёмной теме (расчёт по oklch)."""
        import math

        def rgb(L, C, h):
            a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
            l, m, s = (L + .3963377774 * a + .2158037573 * b) ** 3, (L - .1055613458 * a - .0638541728 * b) ** 3, (L - .0894841775 * a - 1.2914855480 * b) ** 3
            c = (4.0767416621 * l - 3.3077115913 * m + .2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s, -.0041960863 * l - .7034186147 * m + 1.7076147010 * s)
            return [min(1, max(0, x)) for x in c]

        def lum(c):
            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]

        def ratio(a, b):
            x, y = sorted((lum(rgb(*a)), lum(rgb(*b))), reverse=True)
            return (x + .05) / (y + .05)

        css = self.html[:self.html.index("</style>")]
        token = lambda name, i: [float(v) for v in re.findall(name + r": oklch\(([\d.]+) ([\d.]+) (\d+)\)", css)[i]]
        # i: 0 светлая, 1 тёмная (в @media), 2 тёмная (data-theme)
        for i, (bg, surface) in {0: ((.985, .003, 250), (.997, .002, 250)), 1: ((.205, .006, 255), (.24, .007, 255)), 2: ((.205, .006, 255), (.24, .007, 255))}.items():
            ph, line, field = token("--ph", i), token("--field-line", i), token("--field", i)
            for back in (bg, surface, field):
                self.assertGreaterEqual(ratio(ph, back), 4.5, ("--ph", i))
            self.assertGreaterEqual(ratio(line, surface), 3.0, ("--field-line", i))
        # Поля без рамки: отличаются заливкой, а при фокусе кольцом.
        self.assertRegex(css, r"textarea, input\[type=text\][^{]*\{[^}]*background: var\(--field\); border: 0")
        self.assertIn("--focus", css)
        self.assertIn("text-decoration-color: var(--field-line)", css)


if __name__ == "__main__":
    unittest.main()
