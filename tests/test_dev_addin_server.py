"""tools/dev_addin_server.py поднимается и отдаёт двойник Office.js и API панели по обычному HTTP."""
import json
import threading
import unittest
import urllib.request
from pathlib import Path

from .helpers import Env


class DevAddinServerTests(unittest.TestCase):
    def test_boots_and_serves_fake_office_and_api(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "dev_addin_server.py"
        spec = importlib.util.spec_from_file_location("dev_addin_server", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env = Env()
        server, api, app = module.create(0, env.base)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            fake = urllib.request.urlopen(base + "/addin/vendor/office.js", timeout=10).read().decode("utf-8")
            self.assertIn("__fake", fake)
            req = urllib.request.Request(base + "/api/addin/info", headers={"X-Requested-With": "anonymizer", "X-Addin-Token": api.token})
            self.assertTrue(json.loads(urllib.request.urlopen(req, timeout=10).read())["ok"])
            bad = urllib.request.Request(base + "/api/addin/info", headers={"X-Requested-With": "anonymizer", "X-Addin-Token": "x"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad, timeout=10)
        finally:
            server.shutdown()
            server.server_close()
            app.cleanup_open()
            env.close()


if __name__ == "__main__":
    unittest.main()
