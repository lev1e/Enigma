"""S12C: only vendored libraries that the page really loads are shipped; preview panel resize handle."""
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "anonymizer" / "web"
VENDOR = WEB / "vendor"
ROOT = WEB.parents[1]
MANIFEST = json.loads((VENDOR / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
REMOVED = ("pdf.min.mjs", "pdf.worker.min.mjs", "docx-preview.min.js", "jszip.min.js", "xlsx.mini.min.js", "split.min.js",
           "split.js", "sheetjs", "jszip", "pdfjs")


class VendorUsed(unittest.TestCase):
    def test_every_vendored_file_is_listed_and_loaded(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        loaded = set(re.findall(r"""<script[^>]+src=["']/vendor/([^"']+)["']""", html))
        listed = {m["file"] for m in MANIFEST}
        self.assertEqual(listed, loaded, "MANIFEST and the <script> tags of index.html must match")
        files = {p.name for p in VENDOR.iterdir() if p.is_file()} - {"MANIFEST.json"}
        self.assertEqual(files, listed, "unlisted or unused file in vendor/")

    def test_licences_match_manifest(self):
        lic = {p.name for p in (VENDOR / "licenses").iterdir()}
        self.assertEqual(lic, {Path(m["license_file"]).name for m in MANIFEST})

    def test_notices_list_exactly_the_manifest(self):
        text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        rows = [r.split("|")[1].strip() for r in text.splitlines() if r.startswith("| ") and not r.startswith(("| Component", "|---"))]
        self.assertEqual(sorted(rows), sorted(m["name"] for m in MANIFEST))

    def test_removed_libraries_are_not_referenced(self):
        for path in [WEB / "index.html", WEB / "ai.html", ROOT / "Anonymizer.spec", ROOT / "anonymizer" / "webapp.py", ROOT / "anonymizer" / "preview.py"]:
            if path.is_file():
                text = path.read_text(encoding="utf-8").lower()
                for name in REMOVED:
                    self.assertNotIn(name, text, f"{path.name}: {name}")


class ResizeHandle(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "index.html").read_text(encoding="utf-8")

    def test_preview_handle_is_an_accessible_separator(self):
        m = re.search(r'<div class="split" id="split-pv"[^>]*>', self.html)
        self.assertIsNotNone(m)
        tag = m.group(0)
        for attr in ('role="separator"', 'aria-orientation="vertical"', 'aria-controls="pv"', 'tabindex="0"', "aria-label="):
            self.assertIn(attr, tag)

    def test_handle_wired_to_shared_split_code(self):
        self.assertIn('pv: {el: $("#split-pv"), pref: "preview_width"', self.html)
        # arrows 16 px, Home/End, Enter and double click reset: one shared handler for all handles
        self.assertIn('for (const k of SPLIT_KEYS) {\n  const el', self.html)
        self.assertIn("aria-valuenow", self.html)

    def test_pref_is_stored_and_validated(self):
        from anonymizer.vault import DEFAULT_PREFS
        self.assertIn("preview_width", DEFAULT_PREFS)
        self.assertIn("preview_width", (ROOT / "anonymizer" / "webapp.py").read_text(encoding="utf-8"))

class PanelFixes(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "index.html").read_text(encoding="utf-8")

    def test_narrow_overlay_makes_page_behind_inert(self):
        self.assertIn("function pvBackdrop()", self.html)
        self.assertGreaterEqual(self.html.count("pvBackdrop()"), 3)   # show, hide, media-query change

    def test_tab_focus_ring_not_clipped(self):
        self.assertIn(".pv-tab:focus-visible, .pv-sheettab:focus-visible { outline-offset: -3px; }", self.html)

    def test_table_headers_do_not_break_mid_word(self):
        line = next(l for l in self.html.splitlines() if l.startswith(".pv th, .pv td {"))
        self.assertIn("overflow-wrap: break-word", line)
        self.assertNotIn("anywhere", line)


if __name__ == "__main__":
    unittest.main()
