# Requests from W6c to other workstreams

1. Test owners (tests/test_desktop.py): `SelfCheckTests` calls `desktop.selfcheck`, which needs `pywebview` metadata; on the ubuntu CI runner (pywebview/pythonnet filtered out of requirements) it fails. Add
   `from tests._guards import requires_pywebview` and decorate `class SelfCheckTests` (helper exists in `tests/_guards.py`, owned by W6c). Same decorator for any other test that calls `desktop.selfcheck` or opens a window
   (tests/test_helper.py imports `desktop`: import is lazy for `webview`, so only window-opening tests need it).
2. Orchestrator: `tests/eval/baseline.json` "real" section was measured with html cases blocked by the harness `<img>`; after the harness fix `syn_contract_ru_html` (pinned) is measured for real. Re-baseline with `quality_gate.py --full --update-baseline` after review (owner decision).
3. Product findings from html cases now measurable (eval_real --fmt html): leaked values html_en_musk 16, html_ru_putin 5, html_ru_tver 1 (total 22 of 644 gold); owner W3/W9.
4. Local light-job run: tests.test_desktop.SelfCheckTests fails only on check `addin_https_page` (False, no error text) in this sandboxed worktree session; 1366 tests, 1 failure, 15 skipped. Owner W5 (addin.py): confirm whether it is environmental (local cert/keychain) or real.
