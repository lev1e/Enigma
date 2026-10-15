"""S11C: vendored front-end libraries. Hashes match MANIFEST, nothing loads from the network, MIME types are right."""
import hashlib
import http.client
import json
import re
import threading
import unittest
from pathlib import Path

from anonymizer.webapp import create_server

from .helpers import Env

WEB = Path(__file__).resolve().parents[1] / "anonymizer" / "web"
VENDOR = WEB / "vendor"
MANIFEST = json.loads((VENDOR / "MANIFEST.json").read_text(encoding="utf-8"))["files"]


class Vendor(unittest.TestCase):
    def test_manifest_hashes_and_sizes(self):
        self.assertEqual(len(MANIFEST), 3)
        for m in MANIFEST:
            data = (VENDOR / m["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), m["sha256"], m["file"])
            self.assertEqual(len(data), m["bytes"], m["file"])
            self.assertTrue((VENDOR / m["license_file"]).is_file(), m["license_file"])
            self.assertTrue(m["license"] and m["version"] and m["url"].startswith("https://"))

    def test_no_unlisted_vendor_code(self):
        listed = {m["file"] for m in MANIFEST}
        present = {p.name for p in VENDOR.iterdir() if p.suffix in (".js", ".mjs", ".css")}
        self.assertEqual(present, listed)

    def test_no_network_fetch_targets_in_vendor_js(self):
        # Absolute URLs in these files are XML namespaces or licence comments. A URL is a network
        # target only as a literal argument of fetch / XMLHttpRequest.open / importScripts / import().
        pat = re.compile(r"""(?:fetch|importScripts|import)\s*\(\s*[`"']https?://|\.open\(\s*[`"'][A-Z]+[`"']\s*,\s*[`"']https?://""")
        for m in MANIFEST:
            if m["file"].endswith((".js", ".mjs")):
                text = (VENDOR / m["file"]).read_text(encoding="utf-8")
                self.assertIsNone(pat.search(text), m["file"])

    def test_page_references_only_local_resources(self):
        for name in ("index.html", "ai.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            for tag in re.findall(r"<(?:script|link|img|iframe)\b[^>]*>", html, re.I):
                for url in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", tag, re.I):
                    self.assertFalse(re.match(r"(?:https?:)?//", url), f"{name}: {url}")
        idx = (WEB / "index.html").read_text(encoding="utf-8")
        for src in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", idx):
            self.assertTrue(src.startswith("/vendor/") or src.startswith("/"), src)


class Serving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cookie = f"anon_t={cls.app.token}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.env.close()

    def get(self, path, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("GET", path, headers={"Cookie": self.cookie} if cookie else {})
        r = c.getresponse(); body = r.read(); c.close()
        return r.status, r.getheader("Content-Type"), len(body)

    def test_mime_and_size(self):
        for m in MANIFEST:
            status, ctype, n = self.get("/vendor/" + m["file"])
            self.assertEqual(status, 200, m["file"])
            self.assertTrue(ctype.startswith("text/javascript"), (m["file"], ctype))
            self.assertEqual(n, m["bytes"])

    def test_requires_session_and_blocks_traversal(self):
        self.assertEqual(self.get("/vendor/purify.min.js", cookie=False)[0], 403)
        for bad in ("/vendor/MANIFEST.json", "/vendor/../index.html", "/vendor/%2e%2e/index.html", "/vendor/licenses/dompurify.txt", "/vendor/nope.js"):
            self.assertEqual(self.get(bad)[0], 404, bad)


if __name__ == "__main__":
    unittest.main()


class PreviewIntegration(unittest.TestCase):
    def test_xlsx_all_sheets_and_lang(self):
        import io
        import openpyxl
        from anonymizer import preview
        wb = openpyxl.Workbook(); wb.active.title = "A"; wb.active.append(["Name1"])
        wb.create_sheet("B").append([1, 2]); wb.create_sheet("C")
        buf = io.BytesIO(); wb.save(buf)
        d = preview.render("b.xlsx", buf.getvalue())
        self.assertEqual([s["sheet"] for s in d["sheet_list"]], ["A", "B", "C"])
        self.assertEqual(d["sheets"], 3)
        self.assertEqual(d["rows"], d["sheet_list"][0]["rows"])
        self.assertEqual(preview.render("a.md", b"# x")["lang"], "markdown")
        self.assertNotIn("lang", preview.render("a.txt", b"x"))

    def test_panel_markup_only_through_dompurify(self):
        src = (WEB / "index.html").read_text(encoding="utf-8")
        block = src[src.index("/* S11A preview panel */"):src.index("/* end S11A */")]
        self.assertIn("DOMPurify.sanitize", block)
        self.assertNotIn("innerHTML", block.replace('innerHTML = ""', ""))
        for tag in ('"img"', '"iframe"', '"form"', '"style"'):
            self.assertIn(tag, block[block.index("FORBID_TAGS"):block.index("FORBID_TAGS") + 400])
        self.assertIn('"href"', block)
