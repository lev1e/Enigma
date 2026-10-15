"""W12 slice 2: settings API (masked metadata only, test connection, remove key)."""
import json
import secrets
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from anonymizer import chat_api, keystore

from .llm_fake import TEST_KEY, FakeProvider
from .test_ws_llm_keystore import MemoryBackend


def call(app, method, path, data=None):
    return chat_api.ai_handle(app, method, path, lambda: data or {})


class SettingsApiTests(unittest.TestCase):
    def test_full_flow_never_returns_key(self):
        with tempfile.TemporaryDirectory() as tmp, FakeProvider() as fake:
            app = SimpleNamespace(keystore=keystore.Keystore(Path(tmp), secrets.token_bytes(32), MemoryBackend()))
            seen = []
            seen.append(call(app, "POST", "/api/ai/providers/loc", {"kind": "custom", "base_url": fake.url, "model": "m-one"}))
            seen.append(call(app, "POST", "/api/ai/providers/loc/key", {"key": TEST_KEY}))
            test = call(app, "POST", "/api/ai/providers/loc/test")
            self.assertTrue(test[1]["ok"])
            self.assertEqual(test[1]["models"], ["m-one", "m-two"])
            seen.append(call(app, "GET", "/api/ai/providers"))
            seen.append(call(app, "POST", "/api/ai/enabled", {"enabled": True}))
            self.assertNotIn(TEST_KEY, json.dumps(seen))
            removed = call(app, "DELETE", "/api/ai/providers/loc/key")[1]
            self.assertFalse(removed["saved"])
            self.assertNotIn(TEST_KEY, json.dumps(call(app, "GET", "/api/ai/providers")))

    def test_unknown_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = SimpleNamespace(keystore=keystore.Keystore(Path(tmp), secrets.token_bytes(32), None))
            with self.assertRaises(KeyError):
                call(app, "GET", "/api/ai/nothing")


if __name__ == "__main__":
    unittest.main()
