# Bug hunt: silent persistence, stale UI state, destructive actions, hygiene

Method: HTTP client against `tools/dev_server.py` on a temp `ANONYMIZER_HOME`, with a snapshot of vault prefs / entities / pins / chat files / work dir before and after every user action (anonymize, chat settings, keep_originals, edit, keep, undo, hide_new, merge, forget), plus code reading of every writer (`set_prefs`, `add_term`, `set_settings`, `learn`).
Coverage is partial: the session hit its context budget before the dialog-by-dialog screenshot pass (import dialog, merge picker, add-in panel, narrow-window clipping), so those remain unchecked.

## Fixed

1. **Unchecking "Хранить оригиналы в этом чате" erased stored originals at once, no confirmation, no undo** (severity: high, data loss).
   Repro: chat with a file, open "О чате", untick the box: `ChatStore.set_keep_originals(False)` drops every `orig` blob immediately (snapshot showed `...orig.bin: 8f92ccb9 -> None`).
   Fix: `index.html` `#chat-keep` handler asks (`ask`, danger) when any file has `roles.orig`; Cancel restores the checkbox. Tests: `tests/test_ws_hunt.py`.

## Found, not fixed (dependent or design-level)

2. **Table import "Применить" writes GLOBAL `hide_terms` / `keep_terms`** (`table_io.apply_plan`, `vault.add_term`). Same family as the owner's bug: a "Скрывать"/"Оставить" mark in an uploaded table for one chat silently changes the global Settings lists. Severity high. Repro: import a table where a row's hide flag differs from the current state, apply, watch `prefs.hide_terms`. Proposed fix: route through the chat-scoped term lists that agent a70dbbdbb284f4899 introduces (do not duplicate before it is merged); the plan's `terms` tuples already carry the chat id via `apply_plan(app, chat_id, ...)`.
3. **Chat actions keep / hide / hide_new** (`chat_api._edit_entity`, `_hide_new`) and **`Service._remember`** write global lists: being fixed by agent a70dbbdbb284f4899 (not touched here). Their undo (`_undo_one` -> `vault.remove_term`) must be moved to the same scoped API.
4. **Plaintext job outputs stay in `work/<job>/out` up to 6 h** (`Service.cleanup(older_than=6*3600)`), including RESTORED files with real data; removal is a plain `rmtree`, not shredded, and cleanup runs only when a `Service` is created. Severity medium (hygiene). Proposed fix: after the user downloads or after the chat write succeeded, shred and drop `out/` after a short TTL (about 30 min), run `cleanup()` on a timer, and use `chats._shred` for the files.
5. **Vault entities are shared by all chats by design** (Name1 from chat A seeds the detector in chat B, edits/forget act everywhere). The panel hint says so; not a bug, but "Удалить чат" copy says tokens remain, which is accurate.

## Not yet examined (next hunt)

Import dialog / merge picker dirty-state, add-in panel state, theme and language indicators, tab order and focus traps, narrow-window overflow, logs with sensitive values, `vault.bak` behaviour, add-in endpoints.

## Hunt 2 (backend), results

Confirmed with a real run against a temp `ANONYMIZER_HOME` (tests in `tests/test_ws_hunt2.py`).

- **#2 Table import writes global lists: already fixed on main** (`table_io.apply_plan` uses `chats.add_term`, `_undo_one` uses `chats.remove_term`). Added regression test: after import/apply/undo `prefs.hide_terms`/`keep_terms` stay empty, chat lists are restored.
- **#4 Plaintext outputs for 6 h: fixed.** `Service.cleanup` now shreds (`shred_tree`) `out/` 30 min after the result is written to the chat, 10 min after the user has downloaded/saved every file (`note_delivered`, called by `/api/download/*` and the in-process bridge `save_result`/`save_all`), keeps the output of jobs whose chat write failed for the 6 h job TTL, and skips running jobs (needed now that cleanup is periodic: a job over 10 min would otherwise lose `in/`). `App.start_maintenance()` runs it every 2 min in the helper and the in-process app. `forget_job` and helper exit also shred. Expired outputs report `downloadable: false`, `output_path` returns None, download route answers 404 instead of 500. Retention documented in SECURITY.md.
- **vault.bak kept erased data: confirmed, fixed.** `Vault.save` copies the previous file to `.bak` on every save, so after `forget(base)` or `clear()` the `.bak` still held the whole old content (encrypted, same key) until another save. Repro: save twice, `forget`, `.bak` exists with old spellings. Now `forget`/`clear` save with `destructive=True`: write the new file, shred and delete `.bak`.
- **Window-side temp copies: fixed.** `RemoteApp.scratch` (`anonymizer-window-*` in system tmp) held decrypted saved files and was removed with a plain `rmtree`, and survived crashes forever. Now shredded on close; stale ones (older than 12 h) are swept at next window start.
- **Open / not fixed:**
  - Chat deletion does not remove the add-in `Originals` copy (7 days / 20 items by design, see addin.py comment); the pre-edit original of a document stays reachable from the add-in panel after the chat is deleted.
  - `vault.bak` still holds the previous value after a single `edit_value` (overwriting a spelling); only erase actions drop it.
  - Several routes return `str(exc)` of ValueError/KeyError to the client (webapp.py, addin.py 400 responses); the messages are authored texts, I found no path that echoes document values, but third-party parser errors (openpyxl/csv in table import) were not enumerated.
  - OCR helper temp (`anonymizer-ocr-<uid>` in system tmp, `ocr.py:67,103,283`) caches a compiled Vision helper, not user data; not verified for image intermediates on error paths. `formats.py:1698` / `restore.py:229` `mkstemp` in the output dir: removal on error paths not verified.
  - Not examined: settings "Готово" server-side dirty parity and stale indicators (UI-owned), concurrent add-in jobs, add-in stale document state. Add-in routes all go through `_api_authorized` (token + Origin + Sec-Fetch-Site) in `do_GET/do_POST/do_DELETE`.
- Test note: `tests.test_desktop.SelfCheckTests` fails in this worktree only because the untracked `anonymizer/addin_web/vendor/office.js` is absent here; unrelated to the change.
