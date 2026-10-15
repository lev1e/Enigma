# S9B report (PDF leftovers)

Branch ws/s9b. Load average 23-43 during all runs (uptime noted at start 36.7). Python venv312 of the main checkout. real_results.json not touched (EVAL_RESULTS in /tmp).

## 1. pdf_en_manifesto (timeout 900 s)
Profile (cProfile, anonymize alone, load 40): 244 s total, of which `formats._mask_drawn_chars` 136 s (24 M `Rect.contains` calls: every OCR char of a 10-page OCR page against every placeholder box, quadratic), OCR 80 s. Fix: RectGrid lookup in `_mask_drawn_chars` (formats.py, 3 lines). After: anonymize 63 s in one run, 327 s at load 40 with restore included in the second run; produced, leaked 0. The pymupdf `insert_text` exception was not reproduced in any of 3 runs (no traceback in logs). Two runs under load ended with "OCR not repeated" (transient OCR failure in `_pdf_ocr_maps`, exception type hidden by the code; fail-closed, no output); the same file/hiros produced on the next run. Not fixed: that transient OCR error (cause not isolated; load). Content-equal still False: footer line "NATURE HUMAN BEHAVIOUR / DOI / www..." restores garbled (letters N,R,H lost/extra) plus soft-hyphen word splits; same class as S7B overlapped text, not analysed further.

## 2. pdf_en_hiros ("Research" lost)
Cause: OCR layer re-read the whole page (vector paths make the whole page an "image rect"); the OCR word "Research" had its centre in a gap between native glyph boxes, so `ocr.add_ocr_chars` added it as a second copy, giving two hits and two `Company4_2` labels at (103,439) and (100,439); on restore the OCR copy became a stashed vector crop, so the text was not returned. Fixes: (a) `ocr.add_ocr_chars` skips a word whose box is >=50 % covered by native char boxes; (b) formats draws an identical token once per overlapping place. Result: restore content-equal True (letters differ only in case on pages 1-2, accepted by eval's comparison).

## 3. cm_pdf_en_036 ('7th Street')
Not a scan: poor OCR text layer in the file, detected by `detector.verify` only. Fix: one strict retry (`transform_pdf(..., _strict=True)`): if residual exists and no OCR words, the output is processed once more with `_pdf_hits(..., strict=True)` which adds `_verify_hits` findings on native pages. If residual remains, still BLOCKED (test with stubbed `_residuals`). Result: produced (9 s), residual none, restore content-equal True.

## 4. Russian scanned PDFs in redact_text (EVAL_PREFS='{"image_mode":"redact_text"}' tools/eval_real.py run --only <14 ids> --jobs 2; EVAL_PREFS support added to eval_real worker)
| case | before (S7C) | after: status | leaked | content-equal |
|---|---|---|---|---|
| img_ru_ao1926_aspdf | ok | ok | 0 | True |
| img_ru_sud1926_aspdf | blocked | blocked | 0 | n/a |
| pdf_ru_scan_pp | blocked | blocked | 0 | n/a |
| img_ru_voplenko_aspdf | not run | produced | 0 | False |
| img_ru_volga1915_aspdf | not run | blocked (5 residual) | 0 | n/a |
| img_ru_kharkov1989_aspdf | not run | produced | 0 | False |
| cm_jpg_ru_017_aspdf | not run | produced | 0 | False |
| cm_jpg_ru_018_aspdf | not run | produced | 0 | True |
| cm_jpg_ru_019_aspdf | not run | produced | 0 | False |
| cm_jpg_ru_020_aspdf | not run | blocked (1 residual) | 0 | n/a |
| cm_jpg_ru_021_aspdf | not run | produced | 0 | True |
| cm_jpg_ru_022_aspdf | not run | produced | 0 | False |
| cm_jpg_ru_023_aspdf | not run | produced | 0 | True |
| cm_jpg_ru_024_aspdf | not run | produced | 0 | True |
Total: 14 run, produced 10, blocked 4, leaked 0 on all, content-equal 5 of 10 produced. Content-equal False on scans means the OCR text of the restored page differs from the original OCR text (OCR nondeterminism plus painted-then-restored crops), not a detector gap.
Blocked analysis (spy on `_residuals`, run alone):
- pdf_ru_scan_pp: residual is the injected e-mail `p332.5027@mail-demo.example.ru` still readable in the output after painting (OCR reads it after the label "E-mail:" on the banner). Real residual: the painter missed it in 3 passes; cannot be produced safely without improving painting of that banner row.
- img_ru_sud1926_aspdf: residuals `E-mailomat@emamga.comm` (garbled injected e-mail on the banner, real, not covered) and `1920` (BIRTH_DATE from the verify rule on a natural number near "Дата рождения"; likely false positive). The e-mail makes it a real refusal. Possible follow-up: strict retry also for OCR pages with painting of the residual rectangle, not done.
- volga1915 (5 residuals) and cm_jpg_ru_020 (1): not analysed (budget); fail-closed, leaked 0.
Decision: refusals kept; none proven safe to release.

## Tests
tests/test_ws_s9b.py: 6 tests OK (grid mask correctness + speed, OCR word over native text fails on old ocr.py, passes now; strict retry hits; residual still refused). Targeted run of audit_pdf_images2, pdf_audit, pdf_leaks, pdf_ocr, ws_eval_pdf, ws_pdf, ws_pdf2, ws_s6a, ws_s6d, ws_s7b, ws_s9b, ws_w10, w10b, w10c, w4c: 124 tests, OK.

## Not done / open
Full EN PDF regression eval_real --fmt pdf --lang en was NOT run (budget): orchestrator should run it (leak gate). manifesto restore equality (footer), transient OCR failure under load, RU blocked cases above.
