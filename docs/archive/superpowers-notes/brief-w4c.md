# W4c brief: English PDF restore regression, diagnosis first

Repo worktree: <repo>/Downloads/wt-w4c (branch ws/w4c, from main 753b097). Python: <repo>/Downloads/Anonymizer-1.0.0-Windows-build-kit 2/.venv312/bin/python (absolute path; never write into .venv312/bin). Use /usr/bin/git, /usr/bin/grep, /usr/bin/sed. Use absolute paths. Commit early. WRITE your report to <repo>/Downloads/wt-w4c/docs/archive/superpowers-notes/w4c-report.md (under 40 lines; tell me in the final message in under 15 lines). Read docs/superpowers/worker-rules.md first. `case/` is private: never touch it. Max `--jobs 2`.

## Problem
`tools/eval_real.py run --fmt pdf --lang en --jobs 2` (52 cases) on quiet main: leaked 0, produced 42, blocked 10 (earlier baseline: blocked 5), restore content-equal 13/52 (earlier baseline 32/52; byte-equal 0). Raw earlier result: /tmp/claude-501/pdf_en_quiet.json. Suspected cause: whole-image replacement default (W10) for scanned PDFs (cm_jpg_*_aspdf restore=False) and/or a changed restore metric. Undiagnosed. Previous worker found batch results NOT reproducible per case under machine load (gov_fw9 differs alone vs batch): so confirm each key finding by re-running that single case ALONE via eval_real.worker, and record `uptime` load average with every measurement.

## Step 1: diagnosis (do this, report it, commit the report)
1. Split the 52 EN PDFs into text PDFs (have an extractable text layer) vs image/scan PDFs (cm_jpg_*_aspdf, *_scanned, etc.). Report per group: produced, blocked, restore content-equal, leaked.
2. List the 10 blocked cases; mark which are among the earlier five (gov_sc_opinion1, cm_pdf_en_036, syn_contract_en_pdf, gov_f2848, cm_pdf_en_027) and which are NEW. For each new one: block reason (exact message), and whether the cause is a real residual or a placeholder false positive.
3. For text PDFs that are not content-equal: find out WHY (what differs: whitespace, ligatures, reordering, placeholder text not restored, image placeholder). Find the commit that changed it if possible (git log/bisect on a few representative cases, e.g. gov_fw9, cm_pdf_en_025, pdf_en_manifesto). Check how "content-equal" is computed in eval_real.py and whether the metric itself changed.

## Step 2: fix restore equality (only after step 1 report is committed)
Target: >= 45/52 content-equal among TEXT PDFs, without weakening anonymization (leaked must stay 0; do not loosen detectors, verification, or block rules; do not edit tests to pass). Add tests in a NEW file tests/test_ws_w4c.py. You own: PDF functions in anonymizer/formats.py (pdf anonymize), anonymizer/restore.py PDF parts. If you need other files, write docs/archive/superpowers-notes/requests-w4c.md.
Run targeted tests only: tests/test_ws_w4c.py, tests/test_ws_w4.py-like PDF tests (grep tests for "pdf"), and quality gate default: `.venv312/bin/python tools/quality_gate.py` (report PASS/FAIL).

## Step 3 (only if steps 1-2 are done and committed): speed with IDENTICAL output
Sparse 100-page PDF <= 30 s, 12 MB txt <= 60 s, RSS < 2 GB. Output must be byte-identical to before on the 52 EN PDFs and the txt case (prove it by hash/compare). If not achievable in remaining budget, report measured numbers only.

Report: every claim with number, tool, corpus, load average.
