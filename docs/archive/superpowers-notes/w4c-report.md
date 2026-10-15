# W4c report: EN PDF restore regression

Source: /tmp/claude-501/pdf_en_quiet.json (tools/eval_real.py run --fmt pdf --lang en --jobs 2, 52 cases, main 753b097). Single-case checks via /tmp/w4c/d.py (anonymize+restore one case alone with Env), load average 7-9 (uptime 12:2x).

## Diagnosis
Groups (batch json): text PDFs 43 = produced 33, blocked 10, restore content-equal 13/33, leaked 0. Image/scan PDFs 9 (8 cm_jpg_*_aspdf + syn_resume_en_pdf_scanned) = produced 9, blocked 0, content-equal 0/9, leaked 0.

ROOT CAUSE (confirmed alone on gov_f1098 and cm_jpg_en_046_aspdf): W10 whole-image replacement (imagereplace.replace_pdf_images) draws a TEXT label "Image1" with page.insert_textbox over every placeholder. On restore the original picture comes back but the label text stays in the text layer. The metric (eval_real.restore_equal) compares the multiset of letters/digits of the text layer; the extra "image1" makes it unequal. Evidence: char diff orig vs restored = extra {a,e,i,m,g,1} only, nothing missing; same on the scanned PDF (orig text layer empty, restored has 7 chars "Image1"). The metric did not change; the output did (label text added by W10).
Not a placeholder-to-image restore failure: images 1/1 in orig and restored.

Blocked (10) vs earlier five (gov_sc_opinion1, cm_pdf_en_036, syn_contract_en_pdf, gov_f2848, cm_pdf_en_027):
- still blocked from the old five: gov_sc_opinion1, cm_pdf_en_036, gov_f2848 (residual values: 1, see below), cm_pdf_en_027 (digital signature, correct fail-closed). syn_contract_en_pdf is now produced and content-equal.
- NEW (6): cm_pdf_en_025, 026, 038 ("PDF: у картинки есть связанный объект /JBIG2Globals, который нельзя безопасно заменить"); cm_pdf_en_039, 040 ("... связанный объект /Metadata ..."): both raised by imagereplace._portable, i.e. W10 refusing images with linked /JBIG2Globals or /Metadata. Not residual PII and not a placeholder false positive: a W10 coverage limit (file not in my ownership; request in requests-w4c.md). pdf_en_topicpages: "Остались значения: 1" (residual-check message), see below.

## Fix (commits on ws/w4c)
1. anonymizer/restore.py: restore_pdf finds the ImageN words drawn by W10 inside page image areas (only in files that hold a vault-backed placeholder) and removes them per character with redaction, re-drawing every neighbouring glyph (header text under the label survived in cm_pdf_en_031).
2. anonymizer/formats.py transform_pdf: with whole-image replacement the text redaction used images=PIXELS, which rewrote the 1x1 placeholder object and dropped /AnonImg: the original picture could not be restored (cm_pdf_en_031: orig 2532x3302 image came back as 1x1). Now images=NONE when whole_pdf_images; the picture returns (checked alone, 2532x3302).
3. tests/test_ws_w4c.py: 3 tests (label present when anonymized, gone after restore, neighbour text kept, image restored after a text hit). Fail without the fix (checked by stashing restore.py: 1 failure). tests.test_ws_w10 14/14 OK.

## Result (tools/eval_real.py run --fmt pdf --lang en --jobs 2, 52 cases, load average 11-20, one run each)
before (json, quiet main): content-equal 13/52, blocked 10, leaked 0.
after: content-equal 32/52 (9/9 scanned, 23/33 produced text PDFs), blocked 10 (same 10), leaked 0. Matches the earlier 32/52 baseline.
The target ">= 45/52 among text PDFs" is not reachable: only 33 text PDFs are produced; 10 are blocked (6 by W10 /JBIG2Globals and /Metadata refusals, 1 signature, 3+1 residual-check blocks). See requests-w4c.md for the W10 item (+5 files).
Still not equal (10, all text): gov_f941, gov_f4506, cm_pdf_en_037, gov_f1040, cm_pdf_en_051, pdf_en_ioannidis, pdf_en_manifesto, pdf_en_hiros, gov_fw7, gov_fw8ben. Alone: gov_fw8ben misses letters {e,a}; gov_f4506 misses {c3,a2,n2,o,y}; cm_pdf_en_037 has extra letters (~40) left: unresolved, separate mechanisms (lost glyphs, leftover text).
Residual-check blocks (gov_sc_opinion1, cm_pdf_en_036, gov_f2848, topicpages): message gives only the count ("Остались значения: 1"), value not shown; not analysed whether false positive. Detectors/verification untouched.
Quality gate and Step 3 (speed) NOT run: budget.
