"""S6E: static checks of the settings schema rows and the narrow-screen CSS guards in the web UI."""
import re
import unittest
from pathlib import Path

from anonymizer import settings_schema

WEB = Path(__file__).resolve().parent.parent / "anonymizer" / "web"


class SettingsRowsTest(unittest.TestCase):
    def test_new_category_rows_and_toggles_present(self):
        text = Path(settings_schema.__file__).read_text(encoding="utf-8")
        for key in ("DEVICE_ID", "MEDICAL_ID", "COMPENSATION", "ner_candidates", "image_mode"):
            self.assertIn(f'"{key}"', text, key)

    def test_settings_section_cannot_widen_on_phones(self):
        css = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.set-sec \{[^}]*grid-template-columns: minmax\(0, 1fr\)")
        self.assertRegex(css, r"@media \(max-width: 720px\)[^{]*\{[^@]*\.srow \{ flex-wrap: wrap")

    def test_known_english_server_errors_have_russian_text(self):
        js = (WEB / "ai-chat.js").read_text(encoding="utf-8")
        for phrase in ("AI is switched off in the settings", "AI is switched off for this chat", "Stopped"):
            self.assertIn(phrase, js)
        self.assertNotRegex(js, r"#000\b|#fff\b")


if __name__ == "__main__":
    unittest.main()
