# Security audit (W5), 2026-10-12

Scope: SECURITY.md threat model vs code in `service.py`, `vault.py`, `crypto.py`, `addin.py`, `webapp.py`, `helper.py` (read in full; `formats.py`/`restore.py` only where they set XML parsers). Method: code reading, no dynamic scanning. Nothing here is a measured guarantee; the fixes carry tests in `tests/test_ws_security2.py`.

Ranking: P0 = exploitable data exposure by a remote party, P1 = SECURITY.md claim is false or data survives a delete/clear, P2 = hardening gap or weak default, P3 = minor.

## Findings

| # | Pri | Finding | Evidence | Status |
|---|-----|---------|----------|--------|
| 1 | P0 | None found. Server binds 127.0.0.1 only, per-session token in an HttpOnly/SameSite=Strict cookie, Host allow-list, `X-Requested-With` forces a CORS preflight that no handler answers, add-in API needs Host + Origin + Sec-Fetch-Site + header + token. No remote path to vault contents found. | `webapp.py` `_host_ok/_authorized`, `addin.py` `_api_authorized` | n/a |
| 2 | P1 | `Vault.clear()` and retention purge do not erase data: `save()` copies the previous encrypted file to `vault.bak` before every write, so after "Clear vault" (and after retention expiry) the old mapping table is still on disk, decryptable with the same device key. SECURITY.md promises "полная очистка". | `vault.py` `save()` lines 132-136 | Fix (F1) |
| 3 | P1 | Plaintext originals stay in `work/<job>/in/<n>/<file>` for the whole job lifetime (up to 6 h, or until the user clicks forget), although nothing reads them after the job finishes (rerun uses in-memory `job.inputs`). SECURITY.md says only "удаляются при закрытии и через шесть часов". | `service.py` `anonymize/restore` write `in/`, never remove | Fix (F2) |
| 4 | P1 | The 6 h work-dir sweep runs only in `Service.__init__`. The background helper is a long-lived process (autostart, stays while the add-in is installed), so in practice jobs, outputs and originals are never swept until the next restart. | `service.py` `cleanup()` callers: `__init__` only | Fix (F3): sweep on every new job |
| 5 | P1 | Partial outputs of a failed transform stay in `out/` (not downloadable, but on disk until the sweep); the failing `Exception` path does not remove them. | `service.py` `_anonymize_one` except branches | Fix (F2, removed with the dir sweep and explicit unlink) |
| 6 | P1 | Post-transform leak check is missing in the main window path: `job.replaced` (all replaced originals) is only used by the add-in's `verify_document`. A file where a replaced value survives in an unscanned part is returned with status ok. | `service.py` `_anonymize_one`; `addin.py` `_leaks` | Deferred (see below) |
| 7 | P2 | Add-in originals: `Originals.purge()` (7 days / 20 copies) runs only inside `save()`. If the user stops using the add-in, copies older than 7 days stay. SECURITY.md says "не дольше 7 дней". | `addin.py` `Originals.save` | Fix (F4): purge at construction |
| 8 | P2 | POSIX data dir is created with default mode (755 on Linux). `instance.json` (session token), `work/` files and job dirs are world-readable on shared Linux hosts. macOS `~/Library` is already 700; Windows uses per-user ACLs. | `crypto.app_data_dir`, `helper.py` `instance_file().write_text` | Fix (F5): mkdir/chmod 0700 |
| 9 | P2 | Device key on macOS/Linux is `RAW1:` plaintext next to `vault.bin`. Copying the profile directory yields vault plus key, contradicting "перенести файл бесполезно" on POSIX (true only on Windows/DPAPI). The user's own account is the stated trust boundary, but Keychain binding is the natural step. | `crypto.load_device_key` | Deferred: needs `keyring` or `security` CLI and a key-migration path; owner decision; overlaps W12 keystore |
| 10 | P2 | Web server does not check `Origin`. Not exploitable today (SameSite=Strict cookie plus preflight-forcing header), but SECURITY.md describes the add-in as stricter than the main page. | `webapp.py` `do_POST` | Fix (F6): reject a foreign `Origin` on POST |
| 11 | P2 | Negative or non-numeric `Content-Length` raises or blocks a handler thread (`rfile.read(-1)` waits for EOF). Authenticated callers only. | `webapp.py` `_body` | Fix (F6) |
| 12 | P2 | `formats._parser()` uses `huge_tree=True`, which disables libxml2 depth and size limits. Entities are not resolved (`resolve_entities=False`), so billion-laughs is not expanded, but a deeply nested or huge text node can exhaust memory. Total unpacked size is capped at 1 GB by `unpacked_size_problem`; Python's zipfile stops reading an entry at its declared size, so a lying header cannot exceed that. | `formats.py:358` | Request to the `formats.py` owner (W3/W4) |
| 13 | P2 | `addin.py` parses with default `etree.fromstring` (entity resolution depends on the lxml version). Inputs are user documents. | `addin.py` 158-235 | Fix (F7): hardened parser |
| 14 | P3 | Add-in token is injected into `taskpane.html`, which any process that sends the right Host header can fetch. Cross-origin pages cannot read it (no CORS); local same-user processes can read `addin.token` anyway. | `addin.py` `_static` | Accepted: same trust boundary as the token file |
| 15 | P3 | `shutil.rmtree` is not a secure erase (SSD wear levelling, journaling). SECURITY.md should say "deleted", not "shredded". | `service.forget_job` | Accepted; wording |
| 16 | P3 | Windows reserved device names (`CON.txt`, `NUL`) pass `safe_name`. A write to `in/0/CON.txt` on Windows can hit the device. | `service.safe_name` | Accepted/low; Windows unverified here |
| 17 | P3 | `peek()` uses a shared `work/peek/<name>` path; concurrent same-name uploads race and the `finally` removes the shared parent. Wrong preview at worst, no leak. | `service.peek` | Deferred |
| 18 | P3 | Log hygiene: `log_message` is a no-op, no logging module use found in the owned files, error text carries exception class names only for unexpected errors. `ValueError`/`KeyError` messages are passed through to the page (written in-house, no document content). Add-in debug log is opt-in by env var and truncates to 500 chars of panel steps. | grep of owned files | OK |
| 19 | P3 | Dependency of `unpacked_size_problem` on the central directory only: tolerable (see 12). | `service.py` | Accepted |
| 20 | P3 | Fail-closed positives confirmed: container/encoding/BLOCKED/openability errors blank `out_path`, so `downloadable` is false and `zip_outputs`/`output_path` skip them; restore refuses files from another vault; unreadable vault is set aside, never overwritten. | `service.py`, `vault.py` | OK |

## Deferred or accepted, with reason

- 6 (post-transform leak check in the main window path): the add-in already has `_leaks` word-boundary matching; wiring it into `_anonymize_one` as a status downgrade would change the status of existing results and needs an FP measurement on `eval_real` (short replaced values such as short names occur inside other words). Not done without that number. Proposed for the orchestrator: warn-only first, measure FP, then block.
- 9 (Keychain/DPAPI option on POSIX): needs a dependency or a `security` CLI shim plus key migration; ask the owner. Until then SECURITY.md should state that on macOS the device key is a file protected by file permissions only.
- 12: request to the owner of `formats.py`.
- 14-17, 19: accepted as listed.

## Fix list (Phase 2, tests in `tests/test_ws_security2.py`)

F1 `.bak` removed on clear and retention purge; F2 plaintext `in/` dir and partial outputs removed when a job ends; F3 work-dir sweep before each new job; F4 add-in originals purged at startup; F5 data dir 0700 on POSIX; F6 `Origin` check and `Content-Length` validation on the page server; F7 hardened parser in `addin.py`.
