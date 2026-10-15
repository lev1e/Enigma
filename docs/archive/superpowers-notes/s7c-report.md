# S7C report

## Task 1: html_ru_tver / txt_ru_moscow / md_ru_gazprom "leaks" (measured with tools/eval_real.py run --only ... --jobs 2, plus a script printing the leaked gold value)
Result: all three are false alarms of the checker, not detector misses. No detector change, so no gate risk.

| case | "leaked" gold | what is in the produced file |
|---|---|---|
| txt_ru_moscow | ORG "Рубеж" | injected occurrence (`АО «Рубеж»`, 1 in input) is gone (0 as a word in output). Needle `рубеж` is matched inside the natural word "зарубежные" because `canon()` strips spaces/punctuation and uses substring search |
| md_ru_gazprom | ORG "Рубеж" | same: injected `АО «Рубеж»` replaced; match is "зарубежья" / "за рубеж" in natural text |
| html_ru_tver | ADDRESS "Вознесенская" | 3 injected `ул. Вознесенская, д. 30, кв. 91` all replaced; the 1 remaining is the natural Wikipedia sentence "возведены Вознесенская церковь" (a church name, not an address) |

Cause is in tools/eval_real.py `needles()` (not my file): the ambiguity guard exists only for PERSON. Request written to docs/archive/superpowers-notes/requests-s7c.md.

## Task 2: Russian scans (eval_real run --only img_ru_,cm_jpg_ru_,pdf_ru_scan --jobs 2; 27 cases: 13 aspdf PDFs, 13 png/jpg, pdf_ru_scan_pp)
Default image_mode=replace [M]. Every case: leaked 0 of 44 injected, restore content-equal True, output opens. Status "attention" for all except pdf_ru_scan_pp ("ok"), because the message says the pictures were replaced whole by Image1.. labels (that is the by-design warning). Output PDFs are ~1.3 KB (one placeholder text page, 0 readable pixels), output png/jpg 15-52 KB placeholders. So 0 leaks is true but vacuous for OCR painting: nothing of the original page survives, and no page text layer exists in these scans. pdf_ru_scan_pp: 4 images replaced, 2 text-layer entities replaced. Nothing to fix in detectors; page-text-layer and OCR painting are not exercised in replace mode.
Opt-in image_mode=redact_text (OCR painting) results: see below (script run separately, may be incomplete).

## Task 3: natasha on real Russian prose (10 documents from tests/eval/real, raw, no injection, no case/; Service path ner_candidates False vs True; 6 prose docs + 4 PDFs)
Corpus: txt_ru_putin, txt_ru_gazprom, txt_ru_pushkin, txt_ru_sber, txt_ru_moscow, md_ru_gazprom, html_ru_cheb, pdf_ru_ukaz1843, pdf_ru_pp962, cm_pdf_ru_005 (~0.7 M characters of text). Strings that only NER produced (not found by rules as AUTO or REVIEW), judged by eye.
| doc | rules AUTO count | NER extra AUTO | of which wrong | NER extra REVIEW |
|---|---|---|---|---|
| txt_ru_putin | 585 | 38 | 0 | 22 (about 17 names, 5 not names: Библиография, Президенте, РВК, РККА, РПЦЗ) |
| txt_ru_gazprom | 301 | 5 | 0 (2 lone surnames) | 1 name |
| txt_ru_pushkin | 331 | 26 | 2 (Дед, "Старику Вергилия") | 30 (about 24 names, 6 not) |
| txt_ru_sber | 275 | 6 | 0 | 0 |
| txt_ru_moscow | 301 | 8 | 2 (Политиздат, Феория) | 8 (4 names) |
| md_ru_gazprom | 749 | 0 | 0 | 0 |
| html_ru_cheb | 244 | 21 | 2 sure (Биография, Чебурахать), 2 doubtful (Пол, Лев); 3 fictional characters | 18 (about 8 names) |
| 3 PDFs | 0-2 | 0 | 0 | 0 |
Totals: 104 extra AUTO strings, about 93 real people (inflected forms count separately, e.g. Башар Асад / Башара Асада / Башару Асаду), 6 wrong, 2 doubtful, 3 fictional. About 92 % precision. Extra REVIEW about 80 strings, about 70 % names.
Honest reading: the gain is real on encyclopaedic/news prose (public figures that the directories and context rules do not know); in these 6 prose docs NER adds about 93 correct names against thousands of rule hits. Whether it matters for private contracts and letters is NOT measured (case/ off limits; earlier synthetic gold gain was 0 and still is: the gain is only on names without a label or directory entry). Time: no stable difference at this load (document times 2-10 s either way). Wrong AUTO hits are common nouns / titles, so false replacements cost little. Raw data /tmp/s7c_ner10.json (not committed).

## Orchestrator follow-up (S7D requests)
1. strict=True, sentence-initial repeat of a name (entities.py `_learn_words`): previously only mid-sentence occurrences were counted, so one mid-sentence plus one sentence-initial mention was not "repeated". Now a brand-like word seen mid-sentence at least once and also at a sentence start (and never written lowercase in the document) counts as repeated. Fixed; tests in tests/test_ws_s7c.py (3 tests, incl. two negative: ordinary capitalised noun "Стол", only-initial "Лампа"). Gates after the change: text_v1 678/679 fp 2, text_v2 111/111 fp 0, text_en 798/800 fp 1, noise 0 replaced: PASS.
2. keep_terms with only the surname: decided as intended, not changed. A lone "Иванов" stays visible, "Иван Иванов" stays hidden as a whole (otherwise the first name would remain readable next to the replacement). Pinned by a test. The settings hint ("слова, ошибочно принятые за имена") could say "для полного имени внесите его целиком" (settings_schema is S7D's file).

### Opt-in image_mode=redact_text on the same scans (partial: 3 of 14 cases finished when the shift ended; 60+ s per case at this load)
pdf_ru_scan_pp BLOCKED (fail-closed: "could not reliably remove source data from the PDF"), img_ru_ao1926_aspdf ok (96 replacements, 0 of 44 leaked, restore content-equal), img_ru_sud1926_aspdf BLOCKED. Blocks belong to PDF structure/OCR code (S7B), not to detectors. Remaining cases not run; log /tmp/s7c_redact.log (script in scratchpad, not committed).
