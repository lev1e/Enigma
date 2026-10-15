import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class SpecDatasTest(unittest.TestCase):
    """Static check of Anonymizer.spec: the onefile build must bundle the UI, the add-in (with web/vendor) and the notices."""

    def setUp(self):
        self.spec = (ROOT / "Anonymizer.spec").read_text(encoding="utf-8")

    def test_web_dirs_bundled(self):
        for folder in ("anonymizer/web", "anonymizer/addin_web"):
            self.assertRegex(self.spec, r'\(\s*"%s"\s*,\s*"%s"\s*\)' % (re.escape(folder), re.escape(folder)))

    def test_vendor_is_inside_bundled_dir(self):
        # Office.js is fetched to anonymizer/addin_web/vendor, which the whole-folder entry above covers.
        fetch = (ROOT / "tools" / "fetch_office_js.py").read_text(encoding="utf-8")
        self.assertIn('"addin_web" / "vendor"', fetch)
        self.assertNotIn("excludes=[\"vendor\"", self.spec)

    def test_third_party_notices_bundled(self):
        self.assertRegex(self.spec, r'\(\s*"THIRD_PARTY_NOTICES\.md"\s*,\s*"\."\s*\)')


if __name__ == "__main__":
    unittest.main()
