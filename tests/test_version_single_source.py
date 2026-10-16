import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import gen_version_info  # noqa: E402


def _version() -> str:
    return gen_version_info.read_version(ROOT)


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _literal_app_versions(text: str) -> list[str]:
    # Tesseract's explicit four-part package version is a dependency pin, not
    # the application version. Mask only that argument, retaining its line.
    text = re.sub(r"(\bchoco install tesseract --version=)\d+(?:\.\d+){3}\b",
                  r"\1<dependency-version>", text)
    return re.findall(r"\b\d+\.\d+\.\d+\b", text)


class VersionSingleSourceTest(unittest.TestCase):
    def test_pyproject_is_dynamic(self):
        text = _read("pyproject.toml")
        self.assertRegex(text, r'dynamic\s*=\s*\["version"\]')
        self.assertIn('attr = "anonymizer.__version__"', text)
        self.assertIsNone(re.search(r'^version\s*=\s*"\d', text, re.M), "literal version in pyproject.toml")

    def test_version_info_matches_generator(self):
        self.assertEqual(_read("packaging", "version_info.txt").strip(), gen_version_info.render(_version()).strip())

    def test_generator_handles_any_bump(self):
        rendered = gen_version_info.render("3.14.1")
        self.assertIn("filevers=(3,14,1,0)", rendered)
        self.assertIn("StringStruct('FileVersion','3.14.1')", rendered)
        self.assertIn("StringStruct('ProductVersion','3.14.1')", rendered)

    def test_read_version_from_fake_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "anonymizer").mkdir()
            (Path(tmp) / "anonymizer" / "__init__.py").write_text('"""x"""\n\n__version__ = "9.8.7"\n', encoding="utf-8")
            self.assertEqual(gen_version_info.read_version(Path(tmp)), "9.8.7")

    def test_no_stale_literal_in_packaging_files(self):
        for parts in (("packaging", "Anonymizer.iss"), (".github", "workflows", "windows-build.yml"), ("build_windows.ps1",)):
            text = _read(*parts)
            for version in _literal_app_versions(text):
                # 0.0.0 is the WebView2 "not installed" sentinel in the .iss, not an app version.
                self.assertIn(version, ("3.12", "0.0.0"), f"{'/'.join(parts)} hard-codes version {version}")

    def test_dependency_pin_does_not_hide_stale_application_versions(self):
        command = "choco install tesseract --version=5.5.3.20260724 --no-progress -y"
        self.assertEqual(_literal_app_versions(command), [])
        for stale in ('APP_VERSION="2.3.0"', 'Anonymizer-Setup-2.3.0.exe', 'other_tool==2.3.0'):
            with self.subTest(stale=stale):
                self.assertIn("2.3.0", _literal_app_versions(command + " " + stale))
                self.assertIn("2.3.0", _literal_app_versions(command + "\n" + stale))

    def test_iss_requires_define_and_uses_it_for_file_name(self):
        iss = _read("packaging", "Anonymizer.iss")
        self.assertIn("#ifndef MyAppVersion", iss)
        self.assertIn("OutputBaseFilename=Anonymizer-Setup-{#MyAppVersion}", iss)

    def test_workflow_uses_version_and_checks_tag(self):
        wf = _read(".github", "workflows", "windows-build.yml")
        self.assertIn("anonymizer.__version__", wf)
        self.assertIn("/DMyAppVersion=", wf)
        self.assertIn('"v${ver}"', wf)
        self.assertIn("SHA256SUMS.txt", wf)
        self.assertIn("PYTHONUTF8", wf)
        self.assertIn("PYTHONIOENCODING", wf)


class Cp1252ConsoleTest(unittest.TestCase):
    def test_fetch_script_prints_russian_under_cp1252(self):
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        env.pop("PYTHONUTF8", None)
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_office_js.py"), "--dry-run"],
                                env=env, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn("Загрузка".encode("utf-8"), result.stdout)


if __name__ == "__main__":
    unittest.main()
