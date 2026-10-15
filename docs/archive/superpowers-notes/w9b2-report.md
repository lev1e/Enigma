# W9B2: port of W9B (add-in self-service install) onto current main (dd23d49)

Ported ecfbd2c by hand against the U1/U2 files (not a merge).

- Settings: section "Word, Excel, PowerPoint" (heading "Надстройка Word, Excel, PowerPoint") in the settings dialog; status line in an aria-live region (Подключена / Не подключена / Ошибка: причина), primary "Установить надстройку", "Удалить надстройку", 44px targets, returned steps listed, certificate and Office-restart notes.
- Hint: `state()["addin_hint"]` (Windows/macOS, add-in not installed, not dismissed), `addin_hint_dismissed` in `DEFAULT_PREFS`, handled in `save_prefs` next to the other page prefs (the old allowlist no longer exists). Shown under the chat notice with "Открыть" (opens the section) and "Скрыть" (persists dismissal).
- Docs: `docs/WINDOWS_INSTALL.md` (from ecfbd2c; menu path rewritten for the profile menu), `QUICKSTART.md`. main's windows-verification.md untouched.
- Tests: `tests/test_ws_w9b.py` (13 tests, pass without changes).

Tests: w9b, webapp, helper, desktop, addin, ws_u1, ws_u2, ws_p1, ws_s13a, ws_s12c, ws_s12d, ws_s11a, chat_ux_page: 231 run, 1 failure.
`tests.test_desktop...test_selfcheck_reports_every_component_and_exits_zero` fails identically on plain dd23d49 (pre-existing).

Visual: checked live in the browser pane (dev_server, port 8791): hint and settings block render, install button 44px, hint buttons 44px, no horizontal overflow at 390 dark. Screenshot files NOT saved (browser tools return images only to the agent), so docs/superpowers/shots-w9b/ does not exist. The 1440 light view was cropped by the pane.
