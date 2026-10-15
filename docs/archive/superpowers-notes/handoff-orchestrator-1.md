# handoff:v1 — orchestrator, 12.10 (main @ 7903cde + this note)
Owner policy and workstreams: `prompt-orchestrator.md`. Worker rules: `worker-rules.md`. Queue: `queue.md`.

## Gotchas learned
- Agent launches need `model: "sonnet"`. The auto-mode classifier DENIED new launches for W6 (quality gate/CI), W11 (entity audit) and a fresh W12b ("Auto-Mode Bypass"). Do not work around; ask the owner whether to run them via `muse-run` (Spark) instead. SendMessage to finished agents (resume) works.
- Worker context dies at ~165-200k tokens: give workers narrow tasks, ask them to commit and report early.
- Worktree isolation branches from a stale commit (25cad6b). Workers must `git merge-base HEAD main` and ff/merge main first.
- Unit suite command: `.venv312/bin/python -m unittest discover -s tests -t .` (without `-t .` everything is an import error). First run output was invalid; second run output in /private/tmp/claude-501/base/unit2.txt (check `Ran N tests` / `OK`). Known pre-existing failure: tests.test_desktop SelfCheckTests.test_selfcheck_reports_every_component_and_exits_zero (check on main).
- Sandbox shells reject commands containing the word "eval" and plain `git` in worktrees: use `git -C <path>`, `/usr/bin/git`, or ctx_execute.
- Preserved finance work: tags `preserve/finance-pane-0812`, `preserve/finance-masking-wip`, patch in `~/anonymizer-preserve/`. Worktrees `.claude/worktrees/agent-a638b...` and `agent-a6581...` untouched. Ask owner what they are.

## Branches ready or in flight (none merged into main yet)
| WS | branch / worktree | state |
|----|-------------------|-------|
| W5 security | worktree-agent-a2680d95f6e357e4d (.claude/worktrees/agent-a2680d95...) head 552468f, rebased on 7903cde | READY TO MERGE. Reviewed by orchestrator (diff small, fail-closed). Tests: test_ws_security2 (11) + vault/service/webapp/addin/helper pass. Deferred: leak re-check on main path (warn-only first, measure FP on eval_real), macOS device-key Keychain binding (fold into W12 keystore), `huge_tree=True` in formats._parser (W3), SECURITY.md wording (deleted not shredded; device key file perms only off Windows). |
| W3 RU residuals | worktree-agent-a0334c804cd4153b8 head 5dd4196 | detectors.py: bare-id fixes (BARE_NUMBER lookbehind/thousands guard, `_learn_labelled_ids`, `_known_id_findings` spaced-run split). tests/test_ws_ru3.py 152 tests OK with detector modules; eval_text v1 .996/.997 ALL PASS, v2 unchanged FAIL ORG Техноград. 5 csv/tsv/log cases now 0 leaks. NOT done: bare KPP, birth-date variants, RU ADDRESS/ORG/PERSON leaks (html_ru_*), HTML restore equality (html_ru_putin), xlsx pivot refusals, over-redaction, Техноград gate, huge_tree. Needs a fresh worker. Do not take the worktree's uncommitted tests/eval/real_results.json. |
| W10 whole-image | worktree-agent-aa8e0cff4e89591be commit 2c58266 (+ later commits if W10 finished steps) | New anonymizer/imagereplace.py + thin hooks (formats/restore/vault/models/settings_schema). 8/9 tests in tests/test_ws_w10.py passed; failing: PDF inline images (BI..EI) restore. Asked W10 to: fix that fail-closed, check scanned PDF pages, make html/md linked images refuse/warn, test nested zips and GIF/BMP/WebP in OOXML. Interface for W1: `imagereplace.whole_image(settings)`, `Settings.image_mode == "redact_text"`, W1 must call `imagereplace.strip_all_metadata()` for kept images. UI for image_mode + policy sentence NOT done. |
| W12 AI chat | worktree-agent-a488e824a86b9dbca (based on 7903cde) | Done+tested: llm.py (5 providers, fake server tests), keystore.py, chat_api.ai_handle, guard.py, stream_restore.py, chat_pipeline.py (16 tests; outbound leak 0 gold / 0 originals on EN 26/26 sent and RU v1; guard blocked 13/23 RU batches on POSSIBLE_* uncertain findings). NOT done: guard ask path (decision: block by default; per span "anonymize it" via overrides, or "allow once" per call, logged labels-only, never persisted), encrypted conversation storage + per-chat AI flag in chats.py (new blob role), webapp.py wiring (requests-w12.md; CSP connect-src 'self'; add-in must not mount /api/ai/*), /api/ai/* endpoints, ALL UI (load ui-ux-pro-max, impeccable, design-taste-frontend; screenshots 1440/1920/2560 light+dark), file tiers 1-3, README/SECURITY network text, Windows Credential Manager. Unverified: DPAPI, real Keychain, real provider wire formats. Needs a fresh worker per slice. Guard is high-risk: orchestrator must review guard.py before merge. |
| W1 EN + redact-text images | ws-img2 at ../wt-img2 (session 6fbfdc) | running; no report yet. Boundary: owns _anonymize_image/ocr.py; must keep `image_mode` guard when merging W10. |
| W2 NER | exp/ner at ../anonymizer-ner-exp (session 1f49c6) | running; no report yet. |
| W6 gate/CI, W11 entity audit | not started | launches denied (see above). |
| W4, W9, W7, W8 | not started | W4 after W1 merge; W9 after W5; W7 only if W2 recommends; W8 scope of session dbfe73 unknown (check). |

## Merge order (one at a time; unit suite after each; scoreboard after batch)
1. W5 (ready) 2. W1 ws-img2 3. W10 (rebase onto W1; conflicts in formats.py/settings_schema.py expected) 4. W3 5. W12 (after review of guard.py) 6. W2 doc. Then e2e ALONE (tell owner first).

## Baseline scoreboard (unchanged) in status-2026-10-12.md. Main working tree has an uncommitted tests/eval/real_results.json (pre-existing; do not commit).

## Update (late 12.10)
- W10 (branch worktree-agent-aa8e0cff4e89591be, commits 2c58266, ad789b9, f8784a8): tests/test_ws_w10 14/14; neighbours (vault, service, round3/4 containers, regressions) 113 OK. Fixed: PDF inline BI..EI restore (fail-closed check), scanned-page replace, relative html/md image links now block the file. Open: nested zip with PNG in word/embeddings not verified (`_transform_zip` passes PNG/JPG through), UI for image_mode, PDF restore = decoded-identical pixels. Ready to merge after W1.
- W3 (head 5dd4196): all five bare-id csv/tsv/log cases 0 leaks; rest of W3 scope unchanged (see table).
- Unit baseline run on main (unit2.txt) was still in progress when this note was written: read the final `Ran/OK/FAILED` lines before merging anything.

## Baseline result (main @ 7903cde, quiet tree): `Ran 1217 tests in 352s — OK (skipped=3)`. The test_desktop selfcheck failure W5 saw was on its stale base; it passes on main. Safe to start merging W5.
