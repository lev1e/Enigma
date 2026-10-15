# S6D report (speed, ORG heading FP, restore labels)
Branch ws/s6d. Machine load average 20-35 for every run below (noted per line).

## Task 1 speed: NOT achieved for txt, PDF target already met on my fixture; NO speed code changed
Tool: tools/s6d_bench.py (pdf|txt [--prof]); prints seconds, load, RSS, sha256 of output text (per-job invisible tag stripped; PDF: per-page text).
- Sparse 100-page synthetic PDF (tools/s6d_bench.py sparse_pdf: 3 short lines/page, PII on every page): 9.0 s anonymize (uptime load 35), 16 s under cProfile (load 24-26), RSS 0.10 GB. Hash b722fcf6f5dd...a49e8. Target <= 30 s met with the current code. The older 60-113 s figure (en-eval-0910.md) was measured on a different fixture/load; I could not reproduce it.
- 12 MB txt (corpus v1 texts repeated, 12,000,000 bytes): 582 s under cProfile at load 29-35 (profile overhead ~3x; unprofiled earlier figure 94 s at lower load), RSS 0.57 GB. Output hash 19bd6f2c157797d70cbcd758fd61ed0061440c2d8aae47fbd7abd7c0edc1d39c (baseline for any future change).
- Profile (tottime of 582 s): _rule_findings 77 s (regex finditer, 2 PERSON keyword rules = 37 % of rule time: 1.6 of 4.3 s per MB), normalize._normalize 33 s + fold 12.7 s (25.8 M calls), en_rules.org_spans 21 s, entities._known_hits 22.6 s, ner.person_spans+_raw_spans 27 s, _residuals/verify 72 s cumulative (whole-file second scan), harvest 227 s cumulative (explicit_spans 120 s). Flat profile, no single safe hot spot; no change made because none could be proven identical in budget. Candidates: prefilter the 2 PERSON keyword regexes, cache fold(), skip second full scan in verify/_residuals.

## Task 2 done: "Errors & Reminders" no longer ORG
en_rules.org_spans: bare "X & Y" skipped when both words are in _HEADING_WORDS (errors, reminders, terms, conditions, ...). "Smith & Wesson" still ORG. Gate (tools/quality_gate.py): PASS; v1 678/679 fp 2, v2 111/111 fp 0, EN 798/800 fp 1, noise 0 files hit. gov_f2848 is now produced (was blocked).

## Task 3 partly done
cm_pdf_en_038 page 7: root cause was NOT restore recognition; the label "Image7" (24 pt, at the top of a full-page image placeholder) was drawn first and then partly erased by the text-redaction pass (only "7" left). Fix: imagereplace.replace_pdf_images now queues labels (ctx pdf_pending_labels) and imagereplace.draw_pending_labels draws them after the redaction loop in formats.transform_pdf. Output now keeps "Image7" intact and restore removes it. cm_pdf_en_037 also became content-equal.
Not fixed: gov_fw8ben, gov_fw7, gov_f2848 (page 0): restored page has word fragments instead of whole words ("Paperwork Reduction Act Notice", "see separate instructions" lines become 'P','ion','na','rk','Reduct', ...) i.e. collateral glyphs next to a placeholder are lost/split by redaction + redraw_lost / restore re-draw; mechanism not isolated (budget). Other non-equal text PDFs: gov_f941, gov_f4506, gov_f1040, cm_pdf_en_051, pdf_en_ioannidis, pdf_en_manifesto, pdf_en_hiros (not analysed).

## Task 4: not done. pdf_en_topicpages still blocked in the batch; value not identified.

## EN PDF eval (eval_real run --fmt pdf --lang en --jobs 2, load 20-35)
leaked 0 on all 52. produced 49 (was 48), blocked 3 (was 4: cm_pdf_en_036 real residual, cm_pdf_en_027 signed, pdf_en_topicpages), content-equal 39/52 (was 37).
Tests OK (85): test_ws_s6d (new, 3), test_ws_s6a, w10, w10b, w10c, w4c, test_pdf_audit, test_pdf_leaks, test_ws_pdf, test_ws_pdf2.
Files: anonymizer/en_rules.py, anonymizer/imagereplace.py, anonymizer/formats.py (2 lines), tools/s6d_bench.py, tests/test_ws_s6d.py.
