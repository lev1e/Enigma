# S12A report
Branch ws/s12a. Commits: c49725c (fix + tests) and the report commit. Files: anonymizer/formats.py (`_only_own_labels`, used in `_residuals`), tests/test_ws_s12a.py (4 tests OK, no private data), this report.

## Task 1: cm_pdf_ru_006 (69-page text PDF, CC0 CV, not a scan)
Cause (cProfile, Env.anonymize, load 30-78): pass 1 (no OCR) takes about 53 s user CPU. Its verification found one "residual": `Company51email4@example.com`, i.e. two of our own placeholder labels glued without a space (`Company51` + `email4@example.com`); `detector.verify` read the glued string as an e-mail and `TOKEN_RE.fullmatch` did not match. A residual triggers the strict second pass; the pass-1 output has about 100 small vector rects per page (white label boxes and underlines), which crosses `VECTOR_TEXT_MIN_PATHS` (30) in `_pdf_image_rect`, so `_pdf_ocr_maps` OCRed 66 pages (4 OCR passes each). Stage breakdown before (profile, 599 s wall, interrupted by the 600 s alarm): `_pdf_ocr_maps` 420 s cumulative, `ocr_image_layers` 390 s, rest of the time in the second transform_pdf.
Fix: `_only_own_labels(text)`: a verify hit made only of our labels (INNER_TOKEN_RE / GLUED_EMAIL_TOKEN) with nothing left over is not a residual. Any extra character (a glued real word, e.g. `Gaboremail4@example.com`) is still a residual (tests cover both).
After: Env.anonymize status ok, user CPU 63.5 s (80 s wall) vs 1317 s before (eval_real timeout 900 s). eval_real --only cm_pdf_ru_006 --jobs 1: produced, gold=44, leaked=0, opens=True, anonymize 39 s, restore=False (before: no data, it timed out; restore equality not investigated).
Not done: a general cap for a strict-retry OCR over a vector-heavy native page (a different residual could still trigger the 400 s path). Fail-fast refusal not added; I did not want to change the retry design without a second repro.

## Task 2: pdf_en_manifesto footer
Not fixed, behaviour unchanged. I did not run a new repro (a run costs about 60 s CPU plus restore under load 30-78) and did not find a safe change by reading. Known cause from S9B: the footer line "NATURE HUMAN BEHAVIOUR / DOI / www..." restores with letters lost/extra, same class as S7B overlapped text (OCR layer re-reading vector text over native glyphs plus soft-hyphen word splits). Needs a char-level diff of original vs restored footer on page 1.

## Unverified
No full-suite or neighbouring PDF test run (only tests.test_ws_s12a). Orchestrator should run the PDF test group (test_ws_pdf, ws_pdf2, ws_s9b, pdf_leaks) and the EN PDF leak eval. real_results.json untouched (EVAL_RESULTS in /tmp).
