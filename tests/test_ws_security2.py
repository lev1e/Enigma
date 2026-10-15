"""W5 hardening: clear/purge leave no readable copy, plaintext inputs do not outlive a job, local server checks."""
import http.client
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from anonymizer import crypto
from anonymizer.addin import Originals
from anonymizer.service import Upload
from anonymizer.vault import Vault
from anonymizer.webapp import create_server

from .helpers import Env


class VaultShredTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "vault.bin"
        self.key = os.urandom(32)
        self.vault = Vault(self.path, key=self.key)

    def tearDown(self):
        self.tmp.cleanup()

    def _fill(self):
        self.vault.token_for("PERSON", "иванов иван", "Иванов Иван")
        self.vault.save()
        self.vault.token_for("ORG", "ромашка", "Ромашка")
        self.vault.save()
        self.assertTrue(self.path.with_suffix(".bak").exists())     # ordinary saves keep a one-step backup

    def _readable_copies(self, needle: str) -> list[str]:
        found = []
        for p in Path(self.tmp.name).iterdir():
            try:
                if needle in crypto.decrypt_blob(p.read_bytes(), self.key).decode("utf-8"):
                    found.append(p.name)
            except Exception:
                continue
        return found

    def test_clear_leaves_no_decryptable_copy_of_old_entries(self):
        self._fill()
        self.vault.clear()
        self.assertEqual(self._readable_copies("Иванов"), [])
        self.assertEqual(self._readable_copies("Ромашка"), [])

    def test_retention_purge_leaves_no_decryptable_copy(self):
        self._fill()
        for entity in self.vault.entities.values():
            entity["used"] = time.time() - 400 * 86400
        self.vault.save()
        reopened = Vault(self.path, key=self.key)          # purge happens on load
        self.assertEqual(reopened.entities, {})
        reopened.commit()
        self.assertEqual(self._readable_copies("Иванов"), [])


class JobLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_plaintext_inputs_removed_when_job_ends(self):
        job = self.env.service.anonymize([Upload("a.txt", "Иванов Иван Петрович подписал.".encode("utf-8"))], {})
        self.assertEqual(job.state, "done")
        self.assertFalse((job.dir / "in").exists())
        self.assertTrue(any((job.dir / "out").iterdir()))   # the result is still there

    def test_restore_inputs_removed_too(self):
        anon = self.env.service.anonymize([Upload("a.txt", "Иванов Иван Петрович подписал.".encode("utf-8"))], {})
        out = Path(anon.files[0].out_path)
        job = self.env.service.restore([Upload(out.name, out.read_bytes())])
        self.assertFalse((job.dir / "in").exists())

    def test_rerun_still_works_after_inputs_are_gone(self):
        job = self.env.service.anonymize([Upload("a.txt", "Иванов Иван Петрович подписал.".encode("utf-8"))], {})
        again = self.env.service.rerun(job.id, {}, {})
        self.assertEqual(again.state, "done")

    def test_sweep_runs_when_a_new_job_starts(self):
        old = self.env.service.new_job("anonymize")
        old.state = "done"
        os.utime(old.dir, (time.time() - 7 * 3600,) * 2)
        self.env.service.new_job("anonymize")
        self.assertFalse(old.dir.exists())


class OriginalsPurgeTests(unittest.TestCase):
    def test_expired_copies_are_purged_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = os.urandom(32)
            store = Originals(Path(tmp), key)
            backup_id = store.save("anonymize", "a.docx", b"secret")
            long_ago = time.time() - 8 * 86400
            for p in Path(tmp).iterdir():
                os.utime(p, (long_ago, long_ago))
            meta = store.meta(backup_id)
            meta["time"] = long_ago
            import json
            from anonymizer.util import atomic_write
            atomic_write(Path(tmp) / f"{backup_id}.meta", crypto.encrypt_blob(json.dumps(meta).encode(), key))
            Originals(Path(tmp), key)                       # a restart must apply the 7 day rule
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [])


class DataDirTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_data_dir_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "profile"
            old = os.environ.get("ANONYMIZER_HOME")
            os.environ["ANONYMIZER_HOME"] = str(target)
            try:
                crypto.app_data_dir()
            finally:
                if old is None:
                    os.environ.pop("ANONYMIZER_HOME")
                else:
                    os.environ["ANONYMIZER_HOME"] = old
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.env.close()

    def post(self, path, body=b"{}", **extra):
        headers = {"Host": f"127.0.0.1:{self.port}", "Cookie": f"anon_t={self.app.token}",
                   "X-Requested-With": "anonymizer", "Content-Length": str(len(body)), **extra}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        response.read()
        conn.close()
        return response.status

    def test_foreign_origin_rejected_on_post(self):
        self.assertEqual(self.post("/api/prefs", Origin="https://evil.example"), 403)

    def test_own_origin_accepted_on_post(self):
        self.assertEqual(self.post("/api/prefs", Origin=f"http://127.0.0.1:{self.port}"), 200)

    def test_negative_content_length_is_a_clean_400(self):
        headers = {"Host": f"127.0.0.1:{self.port}", "Cookie": f"anon_t={self.app.token}",
                   "X-Requested-With": "anonymizer", "Content-Length": "-5"}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/prefs", body=b"", headers=headers)
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()


if __name__ == "__main__":
    unittest.main()
