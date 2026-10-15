"""S12D: accessibility fixes of the file chat screen (preview panel announcements, composer, sheet tab cue)."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "anonymizer" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
CHAT = (WEB / "ai-chat.js").read_text(encoding="utf-8")


class PanelAnnouncements(unittest.TestCase):
    def test_panel_body_is_not_a_live_region(self):
        tag = re.search(r'<div class="pv-body" id="pv-body"[^>]*>', HTML).group(0)
        self.assertNotIn("aria-live", tag, "a table or text replaced inside a live region is read out in full")
        self.assertIn('aria-busy="false"', tag)

    def test_load_sets_busy_and_short_announcement(self):
        self.assertIn('b.setAttribute("aria-busy", "true")', HTML)
        self.assertIn('announce("Показано: "', HTML)
        msg = re.search(r"function pvMessage\(text\) \{.*\}", HTML).group(0)
        self.assertIn('"aria-busy", "false"', msg)
        self.assertIn("announce(text)", msg)

    def test_sr_status_region_exists_once(self):
        self.assertEqual(HTML.count('id="sr-status"'), 1)
        self.assertIn('role="status"', re.search(r'<p class="sr-only" id="sr-status"[^>]*>', HTML).group(0))


class Composer(unittest.TestCase):
    def test_shortcuts_are_exposed(self):
        self.assertIn('aria-keyshortcuts", "Enter Shift+Enter"', CHAT)
        self.assertIn("Enter отправляет, Shift+Enter переносит строку", CHAT)
        self.assertRegex(CHAT, r'e\.key === "Enter" && !e\.shiftKey && !e\.isComposing')

    def test_reply_done_is_announced(self):
        self.assertIn('say("Ответ ИИ получен.", "ok")', CHAT)


class Style(unittest.TestCase):
    def test_selected_sheet_tab_has_strong_border(self):
        rule = re.search(r'\.pv-sheettab\[aria-selected="true"\] \{[^}]*\}', HTML).group(0)
        self.assertIn("border-color: var(--text)", rule)

    def test_no_side_stripes_gradient_text_or_emoji(self):
        for text in (HTML, CHAT):
            self.assertIsNone(re.search(r"border-(left|right):\s*[2-9]", text))
            self.assertNotIn("background-clip: text", text)
            self.assertFalse([c for c in text if 0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF])

    def test_reduced_motion_rules_cover_panel_and_global(self):
        self.assertIn(".pv, .pv * { animation: none !important; transition: none !important; }", HTML)
        self.assertRegex(HTML, r"prefers-reduced-motion: reduce\) \{\s*\*, \*::before, \*::after \{ animation-duration: \.01ms")


if __name__ == "__main__":
    unittest.main()
