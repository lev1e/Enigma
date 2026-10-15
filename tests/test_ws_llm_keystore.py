"""W12 slice 2: keystore. Keys never reach the page, logs or the profile folder in clear text."""
import os
import secrets
import tempfile
import unittest
from pathlib import Path

from anonymizer import crypto, keystore, llm

from .llm_fake import TEST_KEY, FakeProvider


class MemoryBackend(keystore.Backend):
    name = "keychain"

    def __init__(self):
        self.items = {}

    def put(self, pid, secret):
        self.items[pid] = secret
        return True

    def get(self, pid):
        return self.items.get(pid)

    def delete(self, pid):
        self.items.pop(pid, None)


def profile_text(root: Path) -> bytes:
    blob = b""
    for path in root.rglob("*"):
        if path.is_file():
            blob += path.read_bytes()
    return blob


class KeystoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.vkey = secrets.token_bytes(32)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, backend=None):
        return keystore.Keystore(self.dir, self.vkey, backend)

    def test_public_view_is_masked(self):
        store = self.make(MemoryBackend())
        store.configure("p1", "openai", "", "gpt-x")
        view = store.set_secret("p1", TEST_KEY)
        self.assertTrue(view["saved"])
        self.assertTrue(view["masked"].endswith(TEST_KEY[-4:]))
        self.assertNotIn(TEST_KEY, str(store.listing()))
        self.assertEqual(store.secret("p1"), TEST_KEY)

    def test_backend_keeps_key_out_of_profile_folder(self):
        store = self.make(MemoryBackend())
        store.configure("p1", "anthropic")
        store.set_secret("p1", TEST_KEY)
        self.assertNotIn(TEST_KEY.encode(), profile_text(self.dir))

    def test_fallback_file_is_encrypted_and_marked_weak(self):
        store = self.make(None)
        store.configure("p1", "gemini")
        view = store.set_secret("p1", TEST_KEY)
        self.assertEqual(view["backend"], "file")
        self.assertTrue(view["weak"])
        self.assertNotIn(TEST_KEY.encode(), profile_text(self.dir))
        self.assertEqual(self.make(None).secret("p1"), TEST_KEY)         # survives a restart
        with self.assertRaises(crypto.KeyErrorSafe):
            crypto.decrypt_blob((self.dir / keystore.FILE_NAME).read_bytes(), secrets.token_bytes(32))

    def test_remove_key_everywhere(self):
        backend = MemoryBackend()
        store = self.make(backend)
        store.configure("p1", "openai")
        store.set_secret("p1", TEST_KEY)
        view = store.remove_secret("p1")
        self.assertFalse(view["saved"])
        self.assertIsNone(store.secret("p1"))
        self.assertEqual(backend.items, {})
        self.assertNotIn(TEST_KEY.encode(), profile_text(self.dir))

    def test_bad_inputs(self):
        store = self.make(None)
        with self.assertRaises(ValueError):
            store.configure("../x", "openai")
        with self.assertRaises(ValueError):
            store.configure("p1", "nope")
        with self.assertRaises(ValueError):
            store.configure("p1", "custom", "http://example.org")          # remote http
        store.configure("p1", "openai")
        with self.assertRaises(ValueError):
            store.set_secret("p1", "short")
        with self.assertRaises(ValueError):
            store.set_secret("p1", "has space inside key 123456")

    def test_mac_keychain_sends_key_over_stdin_not_argv(self):
        calls = []

        def run(args, stdin=None):
            calls.append((args, stdin))
            return 0, ""

        backend = keystore.MacKeychain(run)
        self.assertTrue(backend.put("p1", TEST_KEY))
        args, stdin = calls[0]
        self.assertNotIn(TEST_KEY, " ".join(args))
        self.assertIn(TEST_KEY, stdin)
        self.assertFalse(backend.put("p1", "bad'quote-key-123"))         # unsafe to quote: caller falls back

    def test_provider_for_request_and_test_connection(self):
        with FakeProvider() as fake:
            store = self.make(MemoryBackend())
            store.configure("loc", "custom", fake.url, "m-one")
            store.set_secret("loc", TEST_KEY)
            result = llm.test_connection(store.provider("loc"))
            self.assertTrue(result["ok"])
            self.assertEqual(fake.requests[0]["headers"]["authorization"], "Bearer " + TEST_KEY)
            self.assertNotIn(TEST_KEY, repr(store.provider("loc")))

    def test_clear_removes_everything(self):
        backend = MemoryBackend()
        store = self.make(backend)
        store.configure("p1", "openai")
        store.set_secret("p1", TEST_KEY)
        store.clear()
        self.assertEqual(backend.items, {})
        self.assertFalse((self.dir / keystore.FILE_NAME).exists())

    def test_ai_is_off_by_default(self):
        store = self.make(None)
        self.assertFalse(store.enabled())
        store.set_enabled(True)
        self.assertTrue(self.make(None).enabled())


if __name__ == "__main__":
    unittest.main()
