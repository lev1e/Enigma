"""Run targeted production taskpane renderer checks in Node, without browser services."""
import shutil
import subprocess
import unittest
from pathlib import Path


class FrontendSecurityTests(unittest.TestCase):
    def test_hostile_text_is_rendered_as_text(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for frontend renderer verification")
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run([node, str(root / "tests" / "test_frontend_security.js")],
                                cwd=root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
