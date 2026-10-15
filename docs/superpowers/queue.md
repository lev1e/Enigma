# Execution queue (single source of truth; coordinator = orchestrator session)
Updated 12.10. Baseline numbers: `status-2026-10-12.md`. Policy and workstream definitions: `prompt-orchestrator.md` (sections 1, 1b, 4). Worker rules: `worker-rules.md`.
Preserved (do not touch): tags `preserve/finance-pane-0812` (cb51c8b), `preserve/finance-masking-wip` (2ea63cc); uncommitted finance edits backed up in `~/anonymizer-preserve/`; worktrees `.claude/worktrees/agent-a638b...` and `agent-a6581...` stay as they are.

| WS | Owner | Branch | Owns (files) | Status |
|----|-------|--------|--------------|--------|
| W1 EN + redact-text images | session 6fbfdc | ws-img2 (../wt-img2) | formats.py `_anonymize_image` and OCR verify/paint, ocr.py, tests/test_ws_img2.py | running |
| W2 NER experiment | session 1f49c6 | exp/ner (../anonymizer-ner-exp) | tools/ner_experiment.py, docs ner-experiment.md | running |
| W10 whole-image default + metadata | agent | ws/w10 | NEW anonymizer/imagereplace.py, vault image storage, container hooks (thin) in formats.py, tests/test_ws_w10.py. Boundary with W1: W1 keeps redact-text mode; W10 never edits `_anonymize_image`/ocr.py | launching |
| W6 gate/CI/corpus | agent | ws/w6 | tools/eval_*.py, tools/quality_gate.py, tests/eval/, .github/workflows/ | launching |
| W11 entity audit | agent | ws/w11 | NEW docs entity-coverage.md, tools/eval_entities.py | launching |
| W12 AI chat | agent | ws/w12 | NEW llm.py, keystore.py, chat_api.py, chats.py, chat/settings parts of web/index.html, tests/test_ws_llm*.py | launching |
| W3 RU residuals | agent | ws/w3 | detectors.py, colctx.py, textstruct.py, text-format funcs in formats.py | launching |
| W5 security/service | agent | ws/w5 | service.py, vault.py (coordinate W10/W12), crypto.py, addin.py, helper.py | launching |
| W4 PDF restore+perf | - | - | PDF funcs | after W1 merges |
| W9 formats | - | - | format detection | after W5 |
| W7 NER integration | - | - | conditional on W2 | waiting |
| W8 release readiness | session dbfe73? | - | docs, build | to confirm scope |
Pending decisions made by orchestrator: keystore uses macOS `security` CLI and Windows DPAPI via ctypes (no `keyring` dependency, so no install approval needed).

## Third shift, 12.10
Unit baseline main @ f9c0d56 (quiet tree): Ran 1217 tests in 349s, OK (skipped=3). tests.test_desktop SelfCheckTests passes on main (the failure was only on W5 stale base).
W1 12.10: ws-img2 @ 13b9d6c standalone jpg/png: 0 produced -> all produced except cm_jpg_ru_024 (tiff/webp still unsupported); 9 injected values still readable in 6 produced files: NOT ready to merge (see handoff-next.md top).
- W1 (ws-img2, 12.10 part 3): images+scans 0 leaked values in produced files (eval_images 0/16, eval_real subset 87/90 leaked=0, 3 csv/log not image); 16 cases refused (fail-closed), see handoff-next.md. Ready to merge on the leak criterion; availability regression noted.
- W1 (ws-img2, 12.10 part 4, HEAD c073006): eval_real subset (cm_jpg,syn_,img_ru,aspdf,scanned) 90 cases: produced 85 / refused 5 (was 74 / 16); leaked values in produced image+scan files 0 (87/90 leaked=0, the 3 others are csv/log, diagnosed in requests-w1.md); eval_images 16 cases leaked 0 blocked 0 restore_exact 15/16; targeted tests 37 OK. Refused: tiff, webp (unsupported by design), cm_jpg_ru_020_aspdf (part of an account number really stays readable), cm_jpg_en_048_aspdf (passport MRZ digits), cm_jpg_ru_024 (jpg, own-label misread). Ready to merge.

## Fourth pass, 12.10 (single session)
Merged to main: W3 (bare ids before label, tab-joined ids), W12 backend slices (llm adapters, keystore, guard, chat_pipeline, stream_restore; NOT wired: webapp.py does not mount `ai_handle`, no send path reachable, no CSP change yet). Test fixes: legacy image tests pin `image_mode=redact_text` (whole-image replace is the default since W10); OCR stub follows the new `_residuals` signature.
Unit on main after merges: Ran 1309 tests in 362s, OK (skipped=3). Before the fixes: 1265 run, 11 failures + 1 error, all from the image_mode default change.
NOT done: eval_real / eval_images re-run on merged main, e2e (opens windows), W12 slices 3-5 (wiring, encrypted storage, UI, outbound leak e2e), W6 gate/CI, W11 audit, W4 perf, W9 formats, W8 Windows build. W2 NER branch: report only, unmerged.
- W3b (ws/w3b): cue-surname review candidates (RU/EN), OCR initial/sk-live rules done; remaining tasks (KPP, birth dates, csv/log column ctx, huge_tree, over-redaction) not started.

W12 (AI chat, branch worktree-agent-a5e64a86893934e46): web wiring, ask-path guard, encrypted label-form chats, /ai page, e2e leak test (88 requests, 0 leaks), docs. Not done: file transform. Unverified: real provider/Keychain/DPAPI.
- W10b (ws/w10b): images outside /media/, nested zip images, OLE .bin with image refused, TIFF/WebP/GIF/BMP whole-image, PDF placeholder OCR skip, image_mode warning in settings; tests/test_ws_w10b.py (13). Touched outside ownership (small): restore.py, service.py (restore ext, claim text), formats.py detect/_pdf_image_rect.
- W9 (ws/w9): refusal registry anonymizer/refusals.py (25 refused extensions tested), macro-bearing OOXML no longer leaves as unchanged copy, disguised text files refused; ODF/RTF/legacy not implemented (need owner decision on converter); tests/test_ws_w9.py 11 tests.

## Fifth pass, 13.10 (orchestrator 4)
- Main green work: strict-numbering test now label-agnostic (Name vs Term label kind differs between strict and manual hide, not a leak); detector learns an org found after "компания" so other mentions are replaced (fixed test_case_files residual; regression tests/test_orch4.py).
- Full unit on main @ fa5ba5c: Ran 1366, FAILED 1 (tests.test_ws_w10.TestText.test_html_and_md_data_uri). It is FLAKY and PRE-EXISTING: the markdown data-URI restore fails ~7% of runs (also on the commit before this shift's fix; 1-4 of 40 loops). Passes alone usually. Needs an owner (W10 restore).
- Merged W3d (ws/w3d) and W9 (ws/w9). Text gate after merge: v1 gold 679 full 676 fp 2; v2 110/110 fp 0; EN 798/800 fp 1; noise 0 replaced; PASS. 89 targeted tests OK.
- Running: W4 (wt-w4), W6c (wt-w6c), W12b (wt-w12b). Not started: W3e extra ids (owner approved all types incl. foreign ids, VIN/IMEI/MAC, medical, salary), W10 md-restore flake, natasha decision (owner: decide at the end).

## Sixth pass, 13.10 (orchestrator 5)
- Full unit on main @ 753b097 (machine load ~25 from unrelated jobs): Ran 1421 tests in 641s, OK (skipped=3). The earlier flaky md data-URI failure did not recur.
- Launching W4c (ws/w4c, ../wt-w4c): EN PDF restore regression diagnosis, then fix, then speed. Brief: docs/archive/superpowers-notes/brief-w4c.md (in that worktree).
- Shift 6 (13.10): fcc37de fixed 11 unit failures: (1) W3f regression: case forms of explicitly recognised one-word company names (ООО «Орбита» -> Орбиты/Орбите) and hide-terms (Ромашку) were NOT hidden = leak; restored for explicit entities, adjectives still not spread; (2) natasha ON by default made rule-based detector tests see extra NER findings: those suites now pin ner_candidates=False (NER has its own suites test_ws_ner/w7b). Image check (own run, defaults): pptx/docx/xlsx/pdf(raster)/png/jpg all replace image whole; redact_text keeps logo and paints text (cause of owner screenshots not found in code: stored pref, older build, or vector logo + brand paint). Workers launched: S6A ../wt-s6a (PDF leftovers + speed), S6B ../wt-s6b (image mode UI/warnings), S6C ../wt-s6c (small leftovers).
- S7A: normalize fast path (3.2x on normalize), rule prefilter, fold cache; identical hashes on 31 fixtures; 12 MB user CPU -9 %, target 60 s NOT proven; see docs/archive/superpowers-notes/s7a-report.md
- s8a: NER learning/corroboration/veto done, ORG/LOC not shipped; see s8a-report.md

## Shift 8 (14.10)
- Merged: S12A (RU PDF 1317 s -> 63.5 s CPU), S12B (restore digit-glued tokens), S12C (vendor cleanup, resize handle), S12D (a11y), S13A/B (ChatGPT-style chat), S14 (AI editing spec), P1 (providers/originals/policy), P2A (docedit engine), P2B/C (backend), P2D (frontend), P2E (contract fixes, verification), detectors: sk-proj-/sk-ant- keys are secrets.
- Final chain: unit 1717 OK; gate --full PASS (v1 678/679 fp2, v2 111/111, EN 798/800 fp1, noise 0, images 0/16 restore 16/16, real 0/626, triage FP 28); eval RU 116 leaked 0; EN 131 leaked 0. See status-2026-10-14.md.
- Open: restore=False on 5 RU PDFs + pdf_en_manifesto; 12 MB txt speed; engine gaps (real comments, theme ops); owner answers on Тедорра API/auth/TLS, policy.json owner.
- U1 (ws/u1): progressive AI bar, single +, hidden search; see u1-report.md

- 2026-10-15 AI review (`codex/ai-review`): final outbound guard preserves preparation part indexes so per-span consent survives sending and remains scoped to its message; three deterministic regression tests added in `tests/test_ai_review_guard.py`. W13b records actual stage transitions plus progress callbacks, retaining all assertions without scheduler-dependent polling. Tests deferred to coordinator's serialized verification; no external providers called.
- 2026-10-15, codex/linux-quality: inspected archived Linux (39 errors/failures) and Windows (30 errors/failures) CI logs. Fixed platform dependencies/fonts, UTF-8 filename byte limits, unavailable-OCR image warnings, Windows resource counters/pythonnet guard, vendor LF checkout, deterministic transport error tests, Windows OCR cleanup fixture. Tests delegated to coordinator for serial execution; no remote CI, downloads or installs performed.
