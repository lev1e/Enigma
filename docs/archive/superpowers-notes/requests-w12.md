# W12 requests to owners of other files

Additive changes needed outside W12 files (not made here):

1. `anonymizer/webapp.py` (W5):
   - In `App.__init__`: `self.keystore = keystore.Keystore(<profile dir>/"ai", vault key)` (same key argument as `ChatStore`).
   - In `Handler` GET/POST/DELETE: route `chat_api.is_ai_path(path)` to `chat_api.ai_handle(app, method, path, body)` with the same
     token check and the same KeyError(404) / ValueError(400) mapping as `_chat_call`.
   - `App.clear_vault()`: also call `self.keystore.clear()`.
   - CSP header (`_send`): `connect-src 'self'` only, no other origin (slice 3).
2. Backups: `vault.export_backup` must stay free of `keystore` data (it is: keys are not in the vault).
3. `addin.py` (W5): do not mount `/api/ai/*` on the Office add-in handler.

## Status (this branch)

Done: webapp wiring (keystore, /api/ai/*, /ai page, clear_vault clears keystore; CSP already connect-src 'self'), guard ask path
(POSSIBLE_* block; per-span anonymize / allow once), encrypted label-form conversation (ai.bin) with per-chat flag, UI page
anonymizer/web/ai.html (linked from the chat header in index.html), e2e outbound leak test, README/SECURITY.
Not done: file transform / in-place AI edit; attachments. Not verified: real provider, real Keychain/DPAPI, page in a real browser.
tests/test_desktop selfcheck addin_https_page fails in a worktree only because addin_web/vendor is untracked (pre-existing).

## W12b status (branch ws/w12b)

Done: file attachments in /ai (POST /api/ai/chats/<id>/attach: anonymized by the service pipeline, text extracted from the
anonymized output without Office properties/theme parts, guard-checked; error/needs-review/empty/scan/oversize (5 MB, 120k chars,
3 files per message) files are refused with a reason and never sent; the file name is never sent, the message carries `[Файл N]`);
local export of an AI answer (POST .../export: labels restored through the vault, plain-text download; unknown or damaged
labels are reported and need an explicit confirm, never guessed); SSE (GET /api/ai/runs/<id>/events, 15 s keepalive, 900 s cap,
30 s write timeout, polling kept as fallback; stop button unchanged); leak e2e over attachments and exports (tests/test_ws_w12b.py).
Limits: the edited result is restored text (.txt), not a rebuilt .docx/.xlsx; images and scans are not sent.
No change needed in service.py/formats.py/detectors.py. Not verified: a real browser (layout, dark/light, keyboard), real provider.
