handoff:v1
# Handoff, orchestrator shift 7 -> shift 8 (14.10)

## Merged on main this shift
S9A micro speedups (output identical, RSS 0.91 -> 0.58 GB, user CPU unchanged: 12 MB 60 s target NOT met), S9B PDF (manifesto, hiros, cm_pdf_en_036 now produced; RU scans redact_text 10 of 14 produced, 4 blocked fail-closed), S9C natasha follow-ups, S9D add-in pane tokens, S9E/S9F frontend (RU strings, focus rings, tap targets, settings wide), S9G natasha on markup-heavy md, checker fix 9024ee0 (occurrence-aware leaks), deliberate re-baseline (pinned real leaked 2 -> 0), SECURITY.md updated, windows-verification.md sections I/J/K added.
Branches/worktrees cleaned. Kept: backup-before-scrub, worktree-agent-* (+ .claude/worktrees/agent-*), tags preserve/*.

## Final chain numbers (clean sequential, load 15-60)
Unit: Ran 1578, 1 failure (test_ws_w12b "5 MB" vs RU "5 МБ"), test fixed in main (commit "tests: pin Russian size message") -> RE-RUN tests.test_ws_w12b to confirm, ideally the full suite once more.
quality_gate --full PASS: v1 678/679 fp2, v2 111/111 fp0, EN 798/800 fp1, noise 0, images leaked 0 restore 16/16, real pinned leaked 0/626, triage FP 28.
eval_real RU: 116 rows leaked 0; EN: 131 rows leaked 0 (EN PDF 52: 50 restore=True, cm_pdf_en_027 blocked by design, pdf_en_manifesto restore=False footer garbled).

## OPEN
1. e2e_window was started on main (/tmp/claude-501/e2e.sh, log final_e2e.log, status file /tmp/claude-501/e2e.status). Read result (expect 178+/178+).
2. cm_pdf_ru_006 timed out 900 s in the RU batch (load 30-60): re-time it alone; gh_curl_thanks (txt) restore=False in EN batch: rerun alone (`eval_real run --only gh_curl_thanks`), decide if regression (bisect) or pre-existing.
3. Worker S10A (worktree ../wt-s10a, branch ws/s10a, report docs/archive/superpowers-notes/s10a-report.md): owner feedback: remove top-right "ИИ-чат" button; persistent bottom composer in file chat; AI conversation + edit files by instruction as new versions. Merge when it reports; run its tests + test_ws_w12b/test_desktop/test_webapp, update SECURITY.md sentence about AI editing, add leak check outbound = 0.
4. Docs still to write: docs/superpowers/status-2026-10-14.md (tables of status-2026-10-13.md + before/after), README, queue.md, release-checklist.md gate numbers (G1 1578, G3), final handoff.
5. After all merges: one more clean sequential chain (unit, gate, eval ru/en, triage), then e2e alone last (tell owner first).
6. Natasha remaining: md_ru_putin 2 partial first names (Нормана, Хорстом); ORG/LOC off; pp1300 "Владимир Владимирович" REVIEW unverified through service.
7. Unverified list for final report: real AI provider, Keychain/DPAPI, Windows OCR/add-in in real Office/installer/PyInstaller with natasha (G12), natasha licence and value on private contracts, html_ru_putin/html_en_musk sources, add-in settings link (only focuses window), 4 RU scans blocked (pdf_ru_scan_pp, img_ru_sud1926_aspdf, img_ru_volga1915_aspdf, cm_jpg_ru_020_aspdf), speed target 60 s for 12 MB not proven.
Rules as in prompt-orchestrator-7.md (absolute venv path, /usr/bin/git, no foreground sleep, restore tests/eval/real_results.json after eval runs, case/ private).

## UPDATE (late 14.10)
- Merged: S10A (bottom composer, AI edit as new version for text formats), S10B (composer mobile/tap fixes). e2e rerun on main: 178 of 178 (first run failed once on a private xlsx "обезличивание завершено" timeout 240 s, not reproduced; test_case_files OK).
- Running: S11A (worktree ../wt-s11a, branch ws/s11a): research of Claude/ChatGPT/DeepSeek/Open WebUI/LibreChat/LobeChat -> docs/superpowers/research-chat-ui.md + right side file-preview panel in file chat (tabs anonymized/original/versions). Merge when it reports; check CSP/no-script, no original in the anonymized tab, targeted tests, then browser spot-check.
- Check /tmp/claude-501/two.log (gh_curl_thanks, cm_pdf_ru_006 timing) if still present.
- Still to do: docs (status-2026-10-14.md, README, queue.md, release-checklist numbers), final clean sequential chain after S11A, e2e alone last.
- two.log result: cm_pdf_ru_006 timed out again at 900 s (user CPU 1317 s: real slowness, not load; investigate in the RU PDF path, find which stage); gh_curl_thanks (txt) restore=False reproduced (anonymize 1.4 s): bisect vs previous merges, decide regression or pre-existing. Leaked 0 in both.
- S11A MERGED (right preview panel; preview.py, chat_api.py; state in prefs preview_open; research-chat-ui.md was written from memory, licences unverified). S11B shortlist docs/superpowers/research-reuse.md: awaiting OWNER APPROVAL to download vendor files (pdf.js, docx-preview+jszip, SheetJS CE 0.20.3, marked, DOMPurify, highlight.js, split.js) into anonymizer/web/vendor/ with MANIFEST + THIRD_PARTY notice; then replace hand-made preview parts where it improves results. Not verified: new-version marker after AI edit, 1440 light, keyboard-only.
- OWNER APPROVED the vendor download list (no PapaParse). Worker S11C running (../wt-s11c, branch ws/s11c, report docs/archive/superpowers-notes/s11c-report.md): downloads + MANIFEST + THIRD_PARTY_NOTICES.md + integration into the preview panel (pdf.js, marked+DOMPurify, highlight.js, docx-preview, SheetJS tabs, Split.js), network check = nothing leaves 127.0.0.1. Merge when it reports: verify sha256 vs MANIFEST test, PyInstaller spec includes web/vendor (windows build gate G12 note), THIRD_PARTY_NOTICES.md present, SECURITY.md mentions vendored libs, then browser spot-check.
- S11C MERGED: all 9 approved files vendored + verified (sha256/sha512), integrated: marked+DOMPurify (md), highlight.js (json/yaml/xml/ini/sql), multi-sheet xlsx via server preview (SheetJS vendored but NOT used). NOT integrated: pdf.js, docx-preview (need a raw-bytes endpoint, would drop placeholder chips), Split.js (grid shell). Candidate follow-up: raw-bytes endpoint with anonymized bytes only for pdf.js/docx-preview; vendored but unused: pdf.js, docx-preview, jszip, SheetJS, split.js (~2 MB dead weight: decide remove or integrate before release; keep THIRD_PARTY_NOTICES accurate). Unverified: 1440 light, 390 dark, docx/pdf in browser, keyboard walk of sheet tabs, merged cells render.
