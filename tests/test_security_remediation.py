"""Regression coverage for the Blender remediation: integrity and dev boundaries."""
import hashlib
import http.client
import importlib.util
import os
import stat
import tempfile
from types import SimpleNamespace
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from anonymizer import docedit, ocr
from anonymizer.docedit_core import fingerprint
from anonymizer.webapp import create_server
from .helpers import Env, docx_bytes
from .test_ws_p2a import by_text


class FingerprintTests(unittest.TestCase):
    def test_old_prefix_collision_cannot_authorize_a_stale_edit(self):
        old, new = "Paragraph 58800", "Paragraph 87560"
        self.assertEqual(hashlib.sha1(old.encode()).hexdigest()[:8], hashlib.sha1(new.encode()).hexdigest()[:8])
        stale = by_text(docedit.outline(docx_bytes([old]), "a.docx"), old)
        current = docx_bytes([new])
        with self.assertRaises(docedit.PatchRejected) as error:
            docedit.apply_patch(current, "a.docx", {"ops": [{"op": "replace_text", "at": stale["addr"],
                                  "expect": stale["fp"], "text": "Updated paragraph"}]})
        self.assertEqual(error.exception.code, "stale")
        self.assertNotEqual(fingerprint(old), fingerprint(new))
        self.assertEqual(len(fingerprint(old)), 64)


class NativeCacheTests(unittest.TestCase):
    def test_native_helpers_use_private_fresh_directory(self):
        directory = ocr._native_cache_dir()
        self.assertEqual(directory, ocr._native_cache_dir())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        legacy = directory.parent / f"anonymizer-ocr-{os.getuid()}" if hasattr(os, "getuid") else None
        self.assertNotEqual(directory, legacy)
        self.assertEqual(ocr.VisionProvider()._cached().parent, directory)

    @unittest.skipUnless(hasattr(os, "getuid"), "Unix legacy helper cache")
    def test_existing_binary_in_old_predictable_location_is_never_used(self):
        ocr._native_cache_dir()  # Allocate outside the simulated shared temporary root.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helpers = root / "ocr_helpers"
            helpers.mkdir()
            source = helpers / "vision_barcode.swift"
            source.write_text("trusted bundled source")
            digest = hashlib.sha1(source.read_bytes()).hexdigest()[:10]
            legacy = root / f"anonymizer-ocr-{os.getuid()}"
            legacy.mkdir()
            planted = legacy / f"vision_barcode-{digest}"
            planted.write_text("untrusted pre-planted executable")

            def compile_helper(command, **kwargs):
                Path(command[-1]).write_text("compiled trusted source")
                return SimpleNamespace(returncode=0)

            with patch.object(ocr, "HERE", root), patch.object(ocr.tempfile, "gettempdir", return_value=tmp), \
                    patch.object(ocr.shutil, "which", return_value="swiftc"), \
                    patch.object(ocr.subprocess, "run", side_effect=compile_helper) as compiler:
                built = ocr._helper_binary("vision_barcode")
            compiler.assert_called_once()
            self.assertNotEqual(built, planted)
            self.assertEqual(built.read_text(), "compiled trusted source")
            built.unlink()


class PresetAuthorizationTests(unittest.TestCase):
    def test_delete_requires_session_host_origin_and_requested_header(self):
        env = Env()
        server, app = create_server(env.vault, env.base / "work")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            app.save_preset("security-test")
            with patch.object(app, "delete_preset", wraps=app.delete_preset) as delete:
                base = {"Cookie": f"anon_t={app.token}", "X-Requested-With": "anonymizer"}
                bad = [{"X-Requested-With": "anonymizer"}, {**base, "Host": "attacker.invalid"},
                       {**base, "Origin": "https://attacker.invalid"}, {"Cookie": f"anon_t={app.token}"}]
                for headers in bad:
                    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    c.request("POST", "/api/prefs/preset", b'{"delete":"security-test"}', headers)
                    r = c.getresponse(); r.read(); c.close()
                    self.assertEqual(r.status, 403)
                delete.assert_not_called()
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                c.request("POST", "/api/prefs/preset", b'{"delete":"security-test"}', base)
                r = c.getresponse(); r.read(); c.close()
                self.assertEqual(r.status, 200)
                delete.assert_called_once_with("security-test")
        finally:
            server.shutdown(); server.server_close(); app.cleanup_open(); env.close()


class DevBoundaryTests(unittest.TestCase):
    def test_dev_tokens_are_random_and_fixture_routes_reject_foreign_requests(self):
        path = Path(__file__).resolve().parent.parent / "tools/dev_addin_server.py"
        spec = importlib.util.spec_from_file_location("security_dev_addin", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env = Env()
        with patch.dict(os.environ):
            server, api, app = module.create(0, env.base)
            second, other, other_app = module.create(0, env.base / "other")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.assertNotEqual(api.token, other.token)
            self.assertNotEqual(app.token, other_app.token)
            self.assertGreaterEqual(len(api.token), 32)
            for method, route in (("GET", "/dev/doc/meta"), ("PUT", "/dev/doc/meta"), ("POST", "/dev/structure")):
                for headers in ({}, {"X-Requested-With": "anonymizer", "Origin": "https://attacker.invalid"},
                                {"X-Requested-With": "anonymizer", "Host": "attacker.invalid"}):
                    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                    c.request(method, route, b"{}" if method != "GET" else None, headers)
                    r = c.getresponse(); r.read(); c.close()
                    self.assertEqual(r.status, 403, (method, headers))
            module.DOCS["security-fixture.txt"] = {"bytes": b"demo", "meta": {}}
            headers = {"X-Requested-With": "anonymizer",
                       "Origin": f"http://127.0.0.1:{server.server_address[1]}"}
            for method, route, body in (("GET", "/dev/doc/meta?name=security-fixture.txt", None),
                                        ("PUT", "/dev/doc/meta?name=security-fixture.txt", b'{"saved":true}'),
                                        ("POST", "/dev/structure?name=security-fixture.txt", b"demo")):
                c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                c.request(method, route, body, headers)
                r = c.getresponse(); r.read(); c.close()
                self.assertEqual(r.status, 200, method)
            self.assertEqual(module.DOCS["security-fixture.txt"]["meta"], {"saved": True})
        finally:
            server.shutdown(); server.server_close(); second.server_close()
            app.cleanup_open(); other_app.cleanup_open(); env.close()
