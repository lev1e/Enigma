"""Панель Office: токены окна программы, предупреждения, ссылка на настройки (S9D)."""
import re
import unittest
from pathlib import Path

W = Path(__file__).resolve().parent.parent / "anonymizer"
CSS = (W / "addin_web" / "taskpane.css").read_text(encoding="utf-8")
HTML = (W / "addin_web" / "taskpane.html").read_text(encoding="utf-8")
JS = (W / "addin_web" / "taskpane.js").read_text(encoding="utf-8")
APP = (W / "web" / "index.html").read_text(encoding="utf-8")


class PaneDesign(unittest.TestCase):
    def test_tokens_copied_from_app(self):
        for name in ("--bg", "--text", "--accent", "--focus", "--warn", "--error", "--btn-fill"):
            app = re.search(re.escape(name) + r": (oklch\([^)]*\)|color-mix\([^;]*\));", APP).group(1)
            self.assertIn(app, CSS, name)
        self.assertIn('prefers-color-scheme: dark', CSS)
        self.assertIn(':root[data-theme="dark"]', CSS)

    def test_no_old_hex_palette_or_serif(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", CSS), [])
        self.assertNotIn("--serif", CSS)

    def test_no_small_text_or_side_stripes(self):
        for size in re.findall(r"font(?:-size)?:[^;]*?\b(\d+)px", CSS):
            self.assertGreaterEqual(int(size), 14)
        self.assertNotRegex(CSS, r"border-(left|right):\s*[2-9]")

    def test_warnings_and_settings_link(self):
        self.assertIn("Менее безопасный режим.", HTML)
        self.assertIn("Модель для имён не установлена в этой копии", HTML)
        self.assertIn("image_mode_unsafe", JS)
        self.assertIn("ner_available", JS)
        self.assertIn("settings: true", JS)
        self.assertIn("open-settings", HTML)

    def test_info_messages_shown(self):
        self.assertIn("const attention = messagesOf(job);", JS)


if __name__ == "__main__":
    unittest.main()
