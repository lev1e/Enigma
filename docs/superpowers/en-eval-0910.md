# English evaluation 09.10 (session 12)

## Synthetic English corpus (tools/make_en_corpus.py run, 48 files, 8 formats, 1385 gold values)

| kind | gold | leaked before | leaked after |
|---|---|---|---|
| BIRTH_DATE | 184 | 42 (recall .772) | 0 |
| PASSPORT | 113 | 30 (.735) | 0 |
| CITY | 238 | 23 (.903) | 0 |
| PERSON | 365 | 1 | 0 |
| ADDRESS, CARD, EMAIL, IBAN, IP, NI, ORG, PHONE, SECRET, SSN | 530 | 0 | 0 |
| total | 1385 | 96 (.931) | 0 (1.000) |

Restore equality (content equal, irreversibly removed secrets masked): 39/48 before, 48/48 after.
Causes fixed: bare passport/DOB/city under headers in tab/aligned txt and in pipe/ruled PDF tables (colctx.grid_from_tabs, learn_pdf_tables); ordinal dates "23th of January 1957" in column check; P.O. Box read as a person (token glued to "Box", unrestorable); column city inside a street address split the address; secrets with &amp; in HTML cut at ";" (tail leaked); "Passport1" token re-detected as a passport (case-insensitive value); hyphen + O'Connell surnames; caps dateline "SACRAMENTO · ...". Harness fixes: HTML-escaped secrets and PDF label masking in restore comparison.

## Text gate (tools/eval_text.py)
v1+v2 (Russian gate): ALL PASS (recall .995, precision .997). en jsonl: ALL PASS before and after.

## Clean English prose false positives
Hand-written common-word prose (Will/Mark/Grace/Rose/Bill/May/Reading/Hull, Dr. Brown, Settings menu): only by-design hits (countries, regions, Dr. Brown repeated, Johnson & Johnson). Fixed: "Vitamin D.", "Plan B.", "I. The ..." read as initials+surname; quoted code words ("True", "TypeError", dunder) read as ORG. tools/en_clean_fp.py runs the same on Python's pydoc topics (technical prose; remaining hits are code identifiers, AS-prefix legal form, @decorators).

## Real-corpus run (tools/eval_real.py run --jobs 2 --lang en), BEFORE only
178 anonymize files, gold 5301, leaked 2392 (recall .549), FP 16040 strings, 7 blocked, restore content-equal 106/171.
Per kind recall: ADDRESS .002, ORG .072, SSN .050, BIRTHDATE .173, PERSON .254, PASSPORT .591, PHONE .988, SECRET .971, CARD/EMAIL/IBAN/IP 1.000.
NOTE: that run overlapped with in-progress code edits, and the injected values leak wholesale in some files (e.g. txt_en_lincoln, gh_curl_thanks: all 5 PERSON, 3 ORG, 3 ADDRESS, 2 SSN, 2 BIRTHDATE), a pattern that points to the injection step (tools/eval_inject.py) or a per-file failure rather than detector recall, because the same kinds are 1.000 on the synthetic corpus above. NOT investigated or re-run after the fixes: next step is to rerun it on a quiet tree, take one wholesale-leak file (txt_en_lincoln) and diff injected text vs output.

## Real-corpus run, quiet tree (session 13) - before/after
Scope: the 131 English cases that the current run actually executes (the .549 figure above also counted 47 stale `off_*` results that are not in this tree's corpus and came from an older code state).

Triage of the "leaks everything" files: txt_en_lincoln and gh_curl_thanks leak 0 of 31 on a quiet, merged tree. The injection and gold matching in tools/eval_inject.py / eval_real.py are correct (input.txt tail checked against output); the earlier numbers came from stale code plus overlapping edits. No tool bug.

| kind | gold | leaked quiet baseline | leaked after fixes |
|---|---|---|---|
| PERSON | 565 | 87 (.85) | 43 (.92) |
| ORG | 339 | 3 (.99) | 0 |
| ADDRESS | 339 | 10 (.97) | 0 |
| PHONE | 452 | 7 (.98) | 0 |
| PASSPORT | 226 | 19 (.92) | 7 (.97) |
| SECRET | 226 | 1 | 1 |
| SSN, BIRTHDATE, EMAIL, CARD, IBAN, IP | 1337 | 0 | 0 |
| total | 3503 | 127 (recall .964) | 51 (recall .985) |

Restore content-equal: 65/113 both runs (not changed by these fixes). By format: pdf 5/47 (PDF comparison counts redrawn text as different; same on ru), tsv 0/2 (`Company3` token left), all other formats 66/66 except html 5/7, md 9/10, txt 10/11.

Fixed (by cause):
- csv: a column headed "country" dropped every PERSON/ORG finding, including injected free-text rows (gapminder: 10 leaks). Now only vocabulary-like cells are dropped (initials, digits, ":", "@", "<", 5+ words keep detection).
- csv: a second header row in the middle of a file ("Name,Phone,...,Passport") had no column context (bare passports leaked, numeric-column drop). Blocks are now split at inner headers in colctx.learn_grid and textstruct._column_drops.
- html: `data-*` attributes with sentence text (hidden `data-owner="Ship to ... contact X +1-..."`) were not scanned.
- "alt. contact Kowalczyk, John; Halcyon Dynamics": the list-neighbour rule registered "John" as an ORG, which stole the surname-first person; single ASCII given names are now skipped there.
- Code/pydoc false positives: python decorators (@before_first_request, @with_appcontext) as handles; `+000000120` as a phone (no country code starts with 0); "AS IS" as the Estonian "AS" legal form and as a quoted ORG; `flask.app`, `app.route`, `org.apache.commons.io` as domains; `package.json`, `res.status(status).json`, `response.json` as file names.
Tests: tests/test_ws_en4.py (8 tests). tools/eval_text.py v1 ALL PASS; v2 has one pre-existing ORG miss (Russian "Техноград", POSSIBLE_ENTITY/REVIEW) that is identical before these changes. tests.test_ws_en2/en3/en4 and test_detector* green.

Remaining: 43 PERSON leaks, almost all one value per PDF (cm_pdf_en_*, gov_*, pdf_en_*; not diagnosed, metadata and annotations of the output are clean, so it is in the page text or raw structure); 7 PASSPORT in xml/tsv/log carriers (wd_en_scientists_*, gh_*_pom, syn_mail_en_log); restore of PDF and a case where a literal `n0name321` in the source is restored as a token (restorer's relaxed pass; gh_curl_thanks); NATURAL (non-injected) replacements still high on name lists (gh_curl_thanks 462, gh_django_authors 786) by design.

## Session 14: PDF performance and English PDF restore diagnosis

### Performance (task 1)
Cause: `transform_pdf` / `restore_pdf` called `page.add_redact_annot` once per character sliver; PyMuPDF's annotation list handling is quadratic per page (dense 10 pages: 18679 annots, 17M `pdf_next_annot` calls, apply_redactions 14.7 s/page). Fixes: `PageChars.slivers` merges consecutive same-line slivers into one rect only when the merged rect touches no character that the separate slivers would not touch (grid lookup; gap at most 1.5 em), so the redaction result is identical; restore's `_room_right` (cubic over words x labels) is now a grid lookup (`_Room`); `colctx.learn_pdf_tables` stops running `find_tables` after 24000 characters per file (markdown/tab learning still runs on all pages).
Measured (same machine, other agents running, so noisy): dense 10 pages anonymize 395 s -> 14 s, restore 185 s -> 3.9 s; dense 100 pages anonymize 151 s, restore 40 s (targets 180 / 60 met); sparse 100 pages anonymize 60-113 s (target 30 s NOT met: the rest is the text detector itself, harvest 14 s, `_pdf_hits` 23 s, normalize/entities.find, PageChars built twice per page 6 s, save 2 s; not touched).
Verified: anonymized and restored output of a 2-page dense file are word-for-word identical between old and new code; the 100-page dense anonymized file has no email/surname in any `tests.pdf_probe.views` view; tests.test_pdf_audit test_ws_pdf test_ws_pdf2 test_ws_pdf4 test_pdf_ocr test_pdf_leaks: 65 tests OK; tests/test_ws_pdf5.py 4 tests.

### English PDF restore (task 2), state: 32/52 content-equal, leaked 0 everywhere
`tools/eval_real.py` now marks a refused restore as `restore_na` (not a mismatch, excluded from the restore percentage). Fail-closed outputs (no anonymized file): gov_sc_opinion1, cm_pdf_en_036, syn_contract_en_pdf, gov_f2848, cm_pdf_en_027 (signed). Residual refusals were NOT yet investigated for false refusal.
Non-equal (15): gov_f941, gov_f4506, cm_pdf_en_025, gov_f1040, pdf_en_manifesto, cm_pdf_en_037, cm_pdf_en_051, pdf_en_ioannidis, cm_pdf_en_038, pdf_en_hiros, cm_pdf_en_032, gov_fw7, cm_pdf_en_033, gov_fw8ben, pdf_en_topicpages. (gov_f1099msc and gov_fw4 are equal now.)
Diagnosis so far (old and new code give the same diffs, so not a regression):
- cm_pdf_en_025: the word "Applicant" at the top of page 2 is erased by the anonymizer and has no token (a hit that continues across the page seam; only the first segment of a hit gets a token, later segments are blanked). The restorer cannot bring back text that has no token. Fix to do: either do not extend seam hits over label words, or draw a continuation token on the second page.
- gov_f4506, gov_fw8ben, gov_f1040, gov_fw7: restored text loses a few letters inside ordinary words next to tokens ("Paperwork Reduction Act Notice" splits into fragments, 2-6 letters missing per file): neighbours of a restored token are deleted by the restore redaction and `redraw_lost` does not redraw them. To do: compare `kept_chars` input with the cuts for those words.
- pdf_en_topicpages: hyphenated line-end words ("computa-tional", "Mietchen4") are re-flowed by the restore, only whitespace/hyphen difference plus 2 letters lost.
Not diagnosed yet: cm_pdf_en_032/033/037/038/051, gov_f941, pdf_en_hiros, pdf_en_manifesto, pdf_en_ioannidis, form-word over-redaction (Form W-9, IRS, Certification tagged Company), scans syn_resume_en_pdf_scanned and cm_jpg_en_044_aspdf (person leak through OCR path). Goal 45/52 not reached.
