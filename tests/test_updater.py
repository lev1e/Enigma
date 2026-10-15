import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from anonymizer import updater


def make_feed(key: Ed25519PrivateKey, version="9.0.0", sha=None, **extra) -> dict:
    sha = sha or hashlib.sha256(b"archive").hexdigest()
    feed = {"version": version, "url": "https://updates.example.test/a.zip", "sha256": sha,
            "signature": base64.b64encode(key.sign(updater.signed_text(version, sha))).decode()}
    feed.update(extra)
    return feed


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def feed_file(self, feed: dict) -> str:
        path = Path(self.tmp.name) / "latest.json"
        path.write_text(json.dumps(feed), "utf-8")
        return path.as_uri()

    def use_key(self):
        original = updater.PUBLIC_KEY_B64
        updater.PUBLIC_KEY_B64 = self.public
        self.addCleanup(setattr, updater, "PUBLIC_KEY_B64", original)

    def test_versions_compare_numerically(self):
        self.assertGreater(updater.parse_version("2.10.0"), updater.parse_version("2.9.9"))
        self.assertEqual(updater.parse_version("2.2.0"), updater.parse_version("2.2.0+build5"))
        with self.assertRaises(updater.UpdateError):
            updater.parse_version("abc")

    def test_valid_signature_is_accepted_and_newer_version_reported(self):
        self.use_key()
        info = updater.check(self.feed_file(make_feed(self.key)), current="2.2.0")
        self.assertTrue(info["available"])
        self.assertEqual(info["version"], "9.0.0")

    def test_same_or_older_version_is_not_offered(self):
        self.use_key()
        self.assertFalse(updater.check(self.feed_file(make_feed(self.key, "2.2.0")), current="2.2.0")["available"])
        self.assertFalse(updater.check(self.feed_file(make_feed(self.key, "2.1.9")), current="2.2.0")["available"])

    def test_feed_signed_by_a_foreign_key_is_rejected(self):
        self.use_key()
        foreign = make_feed(Ed25519PrivateKey.generate())
        with self.assertRaises(updater.UpdateError):
            updater.check(self.feed_file(foreign), current="2.2.0")

    def test_tampered_hash_or_version_is_rejected(self):
        self.use_key()
        good = make_feed(self.key)
        for field, value in (("sha256", hashlib.sha256(b"evil").hexdigest()), ("version", "9.0.1")):
            with self.assertRaises(updater.UpdateError, msg=field):
                updater.check(self.feed_file({**good, field: value}), current="2.2.0")

    def test_broken_feed_is_reported_not_raised_raw(self):
        path = Path(self.tmp.name) / "latest.json"
        path.write_text("{not json", "utf-8")
        with self.assertRaises(updater.UpdateError):
            updater.fetch_feed(path.as_uri())

    def test_plain_http_to_a_remote_host_is_refused(self):
        self.assertFalse(updater._allowed_url("http://updates.example.test/latest.json"))
        self.assertTrue(updater._allowed_url("https://updates.example.test/latest.json"))
        self.assertTrue(updater._allowed_url("http://127.0.0.1:8000/latest.json"))
        self.assertFalse(updater._allowed_url("ftp://updates.example.test/a.zip"))

    def test_source_run_cannot_self_update(self):
        self.assertTrue(updater.install_blocker())

    def test_release_key_matches_the_key_in_the_program(self):
        # tools/release_mac.py подписывает ключом из ~/.anonymizer-release; без него тест пропускается (CI, чужой компьютер).
        pem = Path.home() / ".anonymizer-release" / "update-signing.pem"
        if not pem.exists():
            self.skipTest("нет ключа выпуска")
        key = serialization.load_pem_private_key(pem.read_bytes(), None)
        public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.assertEqual(public, updater.PUBLIC_KEY_B64)


if __name__ == "__main__":
    unittest.main()
