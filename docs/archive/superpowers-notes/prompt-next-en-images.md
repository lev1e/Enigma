# Prompt for the next chat: English to zero leaks, images fully redacted (state as of 12.10)

Paste everything below the line into a fresh chat.

---

You are continuing work on Anonymizer (Python 3.12, offline, reversible document anonymizer, repo root = current dir, branch `main`). Read first, in this order: `docs/archive/superpowers-notes/handoff-next.md` (top section "SESSION 09.10 (14) FINAL", newest wins), `docs/superpowers/en-eval-0910.md`, `docs/superpowers/ocr-evaluation.md`, `tests/eval/triage.md`, `docs/superpowers/queue.md`. Use `.venv312/bin/python` by absolute path. NEVER write wrapper scripts into `.venv312/bin` or into homebrew python. Run `tools/e2e_window.py` ALONE and tell me first (it opens real windows). The `case/` folder is private customer data: never commit it, never copy its contents into tests, corpora or docs.

## Goal

Two goals, both measured, not asserted.

1. **English: zero leaks of injected values** on every English corpus, in every supported format, with restore intact.
2. **Images and scans: no readable PII left after redaction, or a clear refusal.** The product must never hand back an image or scanned PDF that still shows a value. If redaction cannot be guaranteed, fail closed with a plain message to the user, never output a partly redacted file silently.

"100%" means: the gates below show 0 leaks on the fixed corpora, plus an adversarial pass that finds nothing new. Do not claim 100% on real-world data; report remaining risk honestly.

## Current status (verified from the repo docs, not re-measured today)

English, synthetic: 48 files, 8 formats, 1385 gold values: 0 leaked after fixes (was 96). `tools/eval_text.py` gate ALL PASS on `text_corpus_en.jsonl` (800 gold, 2 misses, 62 hits with a different category label than gold: IBAN/NI/SSN; hidden but check the label logic).

English, real-document corpus (`tools/eval_real.py run --lang en`, quiet tree, 131 cases): gold 3503, leaked 51, recall .985.
- 43 PERSON leaks, almost all one value per PDF (`cm_pdf_en_*`, `gov_*`, `pdf_en_*`); not diagnosed; metadata and annotations are clean, so it is in page text or raw structure.
- 7 PASSPORT leaks in xml/tsv/log carriers (`wd_en_scientists_*`, `gh_*_pom`, `syn_mail_en_log`).
- 1 SECRET leak.
- Person leak through the OCR path on scans: `syn_resume_en_pdf_scanned`, `cm_jpg_en_044_aspdf`.
- Over-redaction (false positives): form words tagged as Company (Form W-9, IRS, Certification); earlier run counted 16040 FP strings on EN.

English PDF restore: 32/52 content-equal, leaked 0 everywhere (session 14). Causes found: a hit that crosses a page seam gets a token only on its first segment (`cm_pdf_en_025`, "Applicant" erased with no token); neighbour letters next to a restored token are deleted and `redraw_lost` does not redraw them (`gov_f4506`, `gov_fw8ben`, `gov_f1040`, `gov_fw7`); hyphenated line-end words re-flowed (`pdf_en_topicpages`). Undiagnosed: `cm_pdf_en_032/033/037/038/051`, `gov_f941`, `pdf_en_hiros`, `pdf_en_manifesto`, `pdf_en_ioannidis`. Fail-closed refusals not yet checked for false refusals: `gov_sc_opinion1`, `cm_pdf_en_036`, `syn_contract_en_pdf`, `gov_f2848`, `cm_pdf_en_027`.

Images and scanned PDFs (my report: "photos are not always fully removed"). Last quantified state is the 08.10 triage: 18 of 28 images and 4 PDFs refused (data still readable after painting, or signed); 72 of 248 values leaked in the 8 JPGs that were produced; TIFF and WebP unsupported; signed-PDF refusal is a hard block with no path forward. Since then OCR work landed (`anonymizer/ocr.py`, `imagetext.py`, `ocr_helpers/`; evaluation in `ocr-evaluation.md`: Apple Vision 100% redactable on the test set, Tesseract 5 `rus+eng` 87-100%, RapidOCR lower; Windows OCR path untested for lack of a Windows machine). The current image leak rate has NOT been re-measured: do that first.

Other known open items that touch the goals: dense-PDF and 12 MB txt performance (94 s vs 60 s target), XML output not well-formed after a secret line (triage defect 1; check it is fixed), `gh_curl_thanks` literal `n0name321` restored as token, QR/barcode PII in images (queue WS-A).

## Step 0: re-measure before changing anything (report a table, no code changes yet)

1. `tools/eval_text.py` on `text_corpus_v1.jsonl`, `_v2.jsonl`, `_en.jsonl`.
2. `tools/eval_real.py run --jobs 2 --lang en` on a quiet tree (no other agents editing). Then `tools/eval_triage.py`.
3. `tools/eval_images.py` (synthetic, independent re-OCR at 1x/2x/3x and 90° rotation) and the image and scanned-PDF cases in `tests/eval/real` (`cm_jpg_*`, `*_aspdf`, `img_*`, `syn_*_scanned*`).
4. Produce one table: per kind and per format, gold / leaked / FP, for EN text, EN real, images. Save it as `docs/superpowers/status-<date>.md`. This is the baseline every later claim is compared with.

## Workstream 1: English to zero

Work the leak list in this order, one cause at a time. For each leak: find the exact value and the exact rule or layer that missed it, fix the cause (not the single string), add a regression test in a NEW file `tests/test_ws_en5.py`, then re-run the three gates.

1. The 43 PDF PERSON leaks (diagnose with `tests/pdf_probe.views` on the output to see which text view still contains the surname).
2. The 7 PASSPORT leaks in xml/tsv/log carriers; the 1 SECRET leak.
3. OCR-path person leaks on English scans (shared with workstream 2).
4. English false positives: form words as Company, articles before legal forms, public URLs as DOMAIN. Every dictionary or rule addition must be re-run on the clean-prose false-positive check (`tools/en_clean_fp.py`) and on the Russian gate; never trade leaks for a worse FP rate unnoticed.
5. English PDF restore: seam-hit tokens, `redraw_lost` neighbours, then diagnose the undiagnosed list. Target 45/52 content-equal while keeping leaked 0.
6. Check the 62 wrong-label hits in the EN text corpus.

Do not add a neural NER in this pass. If rules plateau, list the residual leaks that rules cannot reach and propose NER as candidate-generator only (candidates go to the "uncertain, ask the user" list, never auto-replaced).

## Workstream 2: images and scans

Principle: fail closed. A value must be unreadable to an independent OCR at several scales and at 90° rotation, or the file is refused with an explanation.

1. Explain the 8 JPG leaks and the scanned-PDF leaks by cause: OCR missed the word (low contrast, rotation, small font, skew), OCR read it but the box was too small, box union too loose, text inside stamps/photos/handwriting, vector outlines, text in embedded images inside Office files, QR/barcodes.
2. Redaction must be pixel-destructive (fill the pixels and drop the original image stream; no overlay, no layer that can be removed, no EXIF/thumbnail/XMP copy of the original). Verify by extracting the raw image from the output file, not only by rendering the page.
3. Use more than one reading pass when it is cheap: multiple scales, rotations (0/90/180/270), and a second engine for cross-check (Apple Vision on macOS, Tesseract `rus+eng` as the portable path). A word seen by any pass is a redaction candidate when it matches detectors.
4. Add TIFF and WebP support or refuse them with a clear message (no silent pass-through). Handle QR/barcodes (warn or block).
5. For anything that cannot be guaranteed (handwriting, photos of screens, low-resolution scans) show the user a plain-language warning and a refusal, and say so in the report. Remove the false statement "images unchanged" wherever it appears.
6. Add gates: a new `tools/eval_images.py` threshold (0 leaked values on the synthetic set at all scales and rotations), plus per-case checks on the real image/scan cases. Tests in `tests/test_ws_img2.py`.

## Rules of work

- Test-first for every fix; each workstream in its own git worktree; add tests only in your own new test files; run the full unit suite before merging (currently ~1217 tests, previous full run green) and e2e alone at the end.
- Measure leaks with independent tools (text extraction in several views, OCR of rendered output), never with the product's own detector.
- Every change reports before/after numbers from the same tool on the same corpus. If a metric gets worse anywhere, stop and explain.
- Keep the Russian gate green (`tools/eval_text.py` v1/v2: recall ≥ .995, precision ≥ .997 is the current level; v2 has one pre-existing ORG miss, "Техноград").
- Be honest in the final report: list what is measured, what is not, and any remaining risk. Do not write "100%" for anything that is only a synthetic gate.

## Definition of done

- Baseline table (step 0) and final table, same tools, side by side.
- EN synthetic text, EN real-doc corpus, and all PDFs/images/scans: 0 leaked injected values; FP not higher than baseline.
- Every image and scanned PDF is either fully redacted (verified from raw image data and by independent OCR at 1x/2x/3x + 90°) or refused with a clear message.
- EN PDF restore content-equal ≥ 45/52 with leaked 0.
- New gates wired into a script that can run in CI and fails when leaks increase; new tests merged; handoff note appended to `docs/archive/superpowers-notes/handoff-next.md` in the `handoff:v1` format.
