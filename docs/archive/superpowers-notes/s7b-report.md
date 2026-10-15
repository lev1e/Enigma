# S7B report (PDF restore equality, topicpages, 036)

Branch ws/s7b. Single-case checks: anonymize + restore of one case, letter multiset of the text layer compared as eval_real.restore_equal does. Load average 11-40.

## Mechanisms found and fixed (anonymizer/restore.py, tokens.py, formats.py; tests/test_ws_s7b.py)
1. Overlapped text (gov_f941, gov_f4506, gov_f1040, gov_fw8ben, gov_f2848, pdf_en_ioannidis, cm_pdf_en_051; the fragments 'P','ion','rk' in fw7/fw8ben/f2848). The eval injects PII lines on top of the footer line ("For Paperwork Reduction Act Notice..."). Anonymize already redraws the covered foreign glyphs one by one (hence fragments in the extracted text, they are cosmetic). Restore had two defects:
   a. `_collateral_runs` treated every glyph whose centre lies inside a placeholder box as the placeholder's own and never redrew it. Now only the placeholder's own glyphs (same letter, same point, taken from the token ids) are skipped; foreign text under the box is redrawn.
   b. `redraw_lost` ran AFTER the restored values were drawn, so a restored value with the same letters nearby (an email) made lost foreign letters look alive. Now redraw_lost runs before the values are drawn (fw8ben: 'e','a' lost, now equal).
2. Glued placeholders (gov_fw7): "(MM/DD/YYYY)" became "Company3/Company4Company5/..." with the slash drawn separately, so two tokens read as one word `Company4Company5`, which TOKEN_RE rejects and restore left in place (extra 'ompany' letters, lost 'd','y'). restore now splits a word made entirely of several tokens (`_glued_tokens`, tokens.INNER_TOKEN_RE).
3. pdf_en_topicpages (task 3): NOT cross-file state. eval_real runs each case in its own subprocess with `python -I` and OMP_THREAD_LIMIT=1; alone with that environment it is reproduced (96 s). The value is `@ACCESS` (category USERNAME, from detector.verify on OCR text): the open-lock icon of the "OPEN ACCESS" journal logo on an image is read as "@". Different tesseract threading gives a different reading, hence batch-only. Fix: formats._residuals ignores OCR-text USERNAME findings equal to "@access" unless an anonymized original contains it (`_OCR_LOGO_WORDS`); any other handle/email/secret residual is unchanged (test: a real email still residual). With the fix it is produced (27 s, same environment). Fail-closed unchanged.

## Single-case results after the fixes (restore content-equal, letters)
gov_f941 True, gov_f4506 True, gov_f1040 True, gov_fw8ben True, gov_fw7 True, gov_f2848 True, pdf_en_ioannidis True, cm_pdf_en_051 True (images 2/2).

## Not fixed
- pdf_en_hiros (page 0 of 4): letters of one word "Research" (r,e,s,e,a,r,c,h) missing. In the anonymized file `Company4_2` ("Research") is drawn twice at almost the same spot ((103,439) and (100,439)) for a single occurrence in the heading "Expert Working Group on Research and Development Financing" that wraps over two lines; the word "Group" on the second line (57,437) is also gone in the anonymized file and is not returned. Cause is on the anonymize side (a multi-line entity split into overlapping pieces of the same token); not isolated further.
- pdf_en_manifesto: anonymize alone took 335 s (load 20-30) with a pymupdf insert_text exception in the log; in the batch run (--jobs 2) the worker hit the 900 s timeout, so the case counts as blocked (no output, no leak). Not analysed (topicpages was unblocked by the fix, so this case replaced it in the blocked list). Needs a profile of that file.
- cm_pdf_en_036 (task 4): the residual `7th Street` is NOT on a scanned image (ocr_text False): page 3 has a poor OCR text layer ("0.8h 71 at 7th Street In Joplin") that the main pass does not detect (findings contain only 'Bast Street' and 'Pint Street') but `detector.verify` on the final text detects as ADDRESS. So the cause is a detection gap in detectors (not my file) plus no retry for non-OCR files: the second pass is only taken when OCR words or unreadable images exist. Kept as a refusal with the existing message ("Остались значения: 1"). Suggested follow-up: on a residual that verify finds, feed the verify findings as extra AUTO findings into one more pass (only strengthens redaction); needs a hook in transform_pdf and was not done for lack of budget.

## Tests
tests/test_ws_s7b.py (5): overlapped footer line returns letter-exact (fails on the old restore.py: checked), glued tokens split, ordinary words untouched, `@ACCESS` logo not a residual, real email still residual.

## Final EN PDF run (tools/eval_real.py run --fmt pdf --lang en --jobs 2, OMP_THREAD_LIMIT as the tool sets, load 11-30)
before: produced 49, blocked 3, leaked 0, content-equal 39/52.
after:  produced 49, blocked 3 (cm_pdf_en_036 real refusal, cm_pdf_en_027 signature, pdf_en_manifesto worker timeout 900 s), leaked 0 on all 52, content-equal 48/52 (every produced file except pdf_en_hiros).
Unit tests (90, OK): test_ws_s6a s6d w10 w10b w10c w4c test_pdf_audit test_pdf_leaks test_ws_pdf test_ws_pdf2 test_ws_s7b.
real_results.json not touched (EVAL_RESULTS pointed at scratch).
