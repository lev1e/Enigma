"""Only Windows' missing symlink privilege may skip the cases-directory test."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_ws_w6c


class SymlinkPrivilegeTests(unittest.TestCase):
    def run_case(self, platform, error):
        case = test_ws_w6c.CasesDirTests("test_symlinked_cases_dir_is_replaced_not_followed")
        result = unittest.TestResult()
        # Construct temporary Paths before simulating the platform; pathlib must
        # continue to use the host filesystem implementation.
        with patch.object(Path, "symlink_to", side_effect=error), patch("sys.platform", platform):
            case.run(result)
        return result

    def test_windows_privilege_error_skips(self):
        error = OSError("A required privilege is not held by the client")
        error.winerror = 1314
        result = self.run_case("win32", error)
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("WinError 1314", result.skipped[0][1])
        self.assertFalse(result.errors)
        self.assertFalse(result.failures)

    def test_other_errors_are_not_skipped(self):
        for platform, winerror in (("win32", 5), ("win32", None), ("darwin", 1314), ("linux", 1314)):
            with self.subTest(platform=platform, winerror=winerror):
                error = OSError("symlink creation failed")
                if winerror is not None:
                    error.winerror = winerror
                result = self.run_case(platform, error)
                self.assertFalse(result.skipped)
                self.assertEqual(len(result.errors), 1)
                self.assertFalse(result.failures)


if __name__ == "__main__":
    unittest.main()
