"""U2: one primary action per result row (Сохранить), row opens the preview, everything else in a "..." menu."""
import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "anonymizer" / "web" / "index.html").read_text(encoding="utf-8")
FN = HTML[HTML.index("function fileActionsHtml"):HTML.index("function stepHtml")]
STEP = HTML[HTML.index("function stepHtml"):HTML.index("function treeHtml")]
TREE = HTML[HTML.index("function treeHtml"):HTML.index("function projectStepHtml")]


class ResultRow(unittest.TestCase):
    def test_single_primary_button_in_row(self):
        self.assertEqual(len(re.findall(r'<button class="btn sm" type="button" data-savefile', FN)), 1)
        self.assertIn(">Сохранить</button>", FN)
        self.assertEqual(len(re.findall(r"data-more", FN)), 1)
        # rows are built only through the helper: no per-role Просмотр/Открыть/Сохранить как buttons any more
        self.assertNotIn('class="btn sm" data-preview', STEP + TREE)
        self.assertNotIn('class="btn sm" data-open', STEP + TREE)
        self.assertIn("fileActionsHtml(", STEP)
        self.assertIn("fileActionsHtml(", TREE)

    def test_menu_contents(self):
        for text in ("Просмотр", "Открыть в программе", "Сохранить как…"):
            self.assertIn(text, FN)
        self.assertIn('aria-haspopup="menu"', FN)
        self.assertIn('aria-expanded="false"', FN)
        self.assertIn('role="menu"', FN)
        self.assertEqual(FN.count('role="menuitem" tabindex="-1"'), 3)  # per version, looped over roles
        self.assertIn("ROLE_SHORT", FN)  # other versions (original, restored) are in the same menu

    def test_menu_keyboard_model(self):
        for key in ("Escape", "ArrowDown", "ArrowUp", "Home", "End", "Tab"):
            self.assertIn(f'e.key === "{key}"', HTML[HTML.index("function rowMenuClose"):HTML.index("const versionUrl")])
        self.assertRegex(HTML, r"(?s)function rowMenuClose\(noFocus\).*?b\.focus\(\)")
        self.assertRegex(HTML, r"\.more \{ width: 44px;")
        self.assertRegex(HTML, r"\.row-menu \.mi \{[^}]*min-height: 44px")
        self.assertRegex(HTML, r"\.fname \{[^}]*min-height: 44px")

    def test_preview_via_row_activation(self):
        self.assertIn('<button class="fname" type="button" data-preview=', FN)
        self.assertRegex(HTML, r'\.fname::after \{ content: ""; position: absolute; inset: 0;')
        self.assertIn('e.target.closest("[data-preview]")', HTML)  # the existing delegate opens the panel

    def test_save_handler_unchanged_and_bound(self):
        self.assertIn("saveVersion(b.dataset.savefile, b.dataset.role, b)", HTML)
        self.assertIn("openVersion(b.dataset.open, b.dataset.role)", HTML)

    def test_restore_stays_next_to_anonymize(self):
        self.assertIn('id="btn-chat-anon"', HTML)
        self.assertIn('rest.textContent = restore ? "Восстановить"', HTML)

    def test_no_aria_pressed_and_no_new_accent(self):
        self.assertNotIn("aria-pressed", HTML)
        block = HTML[HTML.index("/* U2:"):HTML.index("@media (max-width: 640px) { .step-files .ver-btns { gap: 0;")]
        self.assertNotIn("--accent", block)

    def test_no_new_external_urls(self):
        block = HTML[HTML.index("let rowMenuBtn"):HTML.index("const versionUrl")]
        self.assertNotIn("http", block)
        self.assertNotIn("innerHTML", block)


if __name__ == "__main__":
    unittest.main()
