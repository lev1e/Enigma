# S6A report (PDF: false residuals, JBIG2/Metadata images, restore equality, speed)

Branch ws/s6a. Python venv312 from the main checkout. Machine very noisy (load average 30-58 during all runs).

## (a) 4 refused PDFs ("1 value remains"), single-case runs with a spy on formats._residuals
| case | residual | verdict | action |
|---|---|---|---|
| gov_sc_opinion1 | 'com' (ORG AUTO finding) read as the tail of our own placeholder `email1@example.com` | FALSE POSITIVE of the check (value inside our own label) | fixed in formats._residuals: an occurrence fully inside a TOKEN_RE / EMAIL_TOKEN_RE span is not a residual. Now produced (97.9 s alone, load 33). |
| cm_pdf_en_036 | alone now fails earlier in W10: image dict with indirect /Length ("связанный объект /Length"); after fixing that, residual '7th Street' read by OCR in the scanned map text next to "Joplin" | REAL residual (address survives painting on the image) | /Length fix in imagereplace._portable (resolved to the number). Stays blocked, fail-closed, correct. |
| gov_f2848 | 'Errors & Reminders' (ORG AUTO) still readable on page 1 top: "Check Form for Common Errors & Reminders" | REAL by rule: a detected AUTO value was not redacted on that occurrence. The finding itself is a false-positive detection (form heading, detectors.py not mine) | not changed; stays blocked. Request: detector should not tag form headings as ORG, or redaction of this occurrence must be investigated. |
| pdf_en_topicpages | not reproduced: alone it produced (attention, 31.7 s) | residual was nondeterministic or already gone | none |

## (b) /JBIG2Globals and /Metadata (imagereplace.py)
Supported. /Metadata of an image is dropped (policy scrubs metadata anyway; restored image has no /Metadata). /JBIG2Globals: the globals stream (raw bytes + Length/Filter/DecodeParms, no object numbers) is stashed once per distinct globals object in the vault under `pdfglb_<random>`; the placeholder's stashed dict carries a marker; on restore a new object is created and referenced. Image stream bytes restore byte-exact (test). If the globals are missing in the vault the placeholder is kept instead of a broken image. Tests: tests/test_ws_s6a.py (TestJbig2AndMetadata, TestPortableLength). Note: after restore, two identical images collapse into one object on save (garbage=4 dedup); content equal.

## Leak gate: tools/eval_real.py run --fmt pdf --lang en --jobs 2 (52 cases, EVAL_RESULTS in scratch, load average 18-39)
| | produced | blocked | leaked | content-equal |
|---|---|---|---|---|
| before (baseline given) | 42 | 10 | 0 | 32/52 |
| after (this branch, 3 commits) | 48 | 4 | 0 | 37/52 |
Blocked now: cm_pdf_en_036 (real residual '7th Street', correct), gov_f2848 (see (a)), cm_pdf_en_027 (digital signature, correct), pdf_en_topicpages (in the batch it again says "1 value remains"; alone it produced, so the residual depends on state/order: value not identified, NOT resolved). cm_pdf_en_025/026/039/040 and sc_opinion1 are produced and content-equal; cm_pdf_en_038 is produced but NOT content-equal (see below).

## (c) restore content-equality: partial diagnosis only (not fixed)
Not equal after this run (11): gov_f941, gov_f4506, cm_pdf_en_037, pdf_en_manifesto, gov_f1040, cm_pdf_en_051, cm_pdf_en_038, pdf_en_ioannidis, pdf_en_hiros, gov_fw7, gov_fw8ben (gov_fw7 mismatch is mixed missing/extra letters on page 0; gov_fw8ben misses {e,a} on page 0).
- cm_pdf_en_038 (newly produced, so new in the "not equal" list): extra letters {a,i,e,g,m,7} on page 7. In the anonymized file the label "ImageN" on page 7 (above the header line, y 0-33) is partly eaten by a text redaction: only the "7" is left as a text char; restore then does not recognise a label word (fullmatch Image\d+ fails) and the leftover differs. Cause is in restore._placeholder_label_boxes (word-level recognition) plus the redaction clipping the label. Fix idea not implemented: recognise labels from the text view regex (as _erase_placeholder_labels does) and/or draw the label away from header text.
- gov_fw8ben, gov_fw7, gov_f4506, cm_pdf_en_037: lost/extra glyphs on page 0, separate mechanisms, not analysed further (budget).

## (d) Speed: NOT DONE (no profiling, no change; context budget exhausted). No timing claims.

## Files
anonymizer/imagereplace.py, anonymizer/formats.py (_residuals only), tests/test_ws_s6a.py (4 tests, OK), this report.
Tests run: tests.test_ws_s6a only (OK, 4). tests.test_ws_w10/w10b/w10c/test_pdf*/test_ws_w4c NOT run by me after the changes: orchestrator should run them.
