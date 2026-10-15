# W9A: single version source and release workflow

## Changed
- `anonymizer.__version__` is the only version. pyproject.toml uses `dynamic = ["version"]` (setuptools attr), with a new `[build-system]` and `packages = ["anonymizer"]`.
- `tools/gen_version_info.py` generates `packaging/version_info.txt` (called from the workflow and build_windows.ps1).
- `packaging/Anonymizer.iss`: `#ifndef MyAppVersion` -> `#error` if not passed; installer name `Anonymizer-Setup-{#MyAppVersion}`.
- Workflow: reads the version into `APP_VERSION`, fails on tag push if tag != `v<version>`, passes `/DMyAppVersion`, produces `dist/SHA256SUMS.txt` (lowercase hex, `<hash> *<name>`), uploads and attaches it, release notes mention SmartScreen and the Office checkbox.
- CI fix: job-level `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`; `fetch_office_js.py` and `run_tests.py` reconfigure stdout/stderr to UTF-8; `fetch_office_js.py --dry-run` added; build_windows.ps1 sets the same env vars.
- `Anonymizer.spec` now bundles `THIRD_PARTY_NOTICES.md` (to `.`).

## Tests
`tests.test_spec_datas`, `tests.test_version_single_source` (11 tests, OK): spec datas, pyproject dynamic, version_info equals generator output, generator with a fake version, no stale literals in iss/workflow/ps1, workflow contents, cp1252 subprocess run of the fetch script.

## Unverified / caveats
- The workflow has never run; YAML not parsed locally (no PyYAML).
- `THIRD_PARTY_NOTICES.md` does not exist in this tree: PyInstaller will fail until another worker adds it.
- pyproject build with setuptools not executed.
- The spec's `web/vendor` is covered by the whole-folder `anonymizer/addin_web` entry; the exe archive is not inspected (only `--selfcheck`).
- version_info.txt lost a trailing blank line after regeneration (harmless).
