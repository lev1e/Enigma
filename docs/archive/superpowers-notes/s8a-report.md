# S8A: natasha as a permanent layer working with the rules

Labels: [M] measured, [S] static. Corpus for prose numbers: 7 committed Russian documents tests/eval/real txt_ru_* and md_ru_* (700,063 chars, first 150k chars each), Service path, `ner_candidates` False vs True. Scripts were in the scratchpad, not committed. Python 3.12, natasha 1.6.0.

## What changed
- `anonymizer/ner.py` (decide/review area only): reason constants (`REASON_AUTO/REVIEW/BOTH`), `spans_cached()` (harvest and scan of the same text run the model once), `learnable_names()`, `review_candidates()` uses the cache. Removed a dead duplicated `return False` in `is_full_name`.
- `anonymizer/detectors.py`: scan hook replaced by `_ner_findings()`; new `_ner_learn()` called in `harvest()` before the initials sweep; helpers `_ner_known()`, `_ner_vetoed()`.
- Tests: `tests/test_ws_s8a.py` (14 tests). Two older tests encoded a flawed invariant and were adapted: `test_ws_w7b.WithModel` (looks for any AUTO name, not for the old reason string) and `test_ws_ner.test_auto_set_unchanged` (NER may shift a boundary; it may not drop a finding).

## Step 1 LEARNING [M]
Every full name with posterior >= 0.9 is registered like a rule-found name (`_harvest_at`, else NER order heuristics: patronymic position, known given name, surname shape, default "Имя Фамилия"), unless the rules already know the person (`_ner_known`). Test doc "Бекбулат Айтказин ... Айтказина ... Б. Айтказин ... Айтказин ... Айтказину": before, the first name "Бекбулат" stayed in the output next to a replaced surname (the NER finding lost to the rule finding in `_resolve`: a leak); now all 5 mentions are one person_id, one Name token, restore equals the original. Same with surname-first order, and in a second file of the same job.
A real-corpus side effect: "Свидетель Павел Олегович Пеговук": the rules had hidden "Свидетель Павел Олегович" and left the surname readable; with NER on the whole name is hidden (4 such lines in the probe set).

## Step 2 CORROBORATION [M]
A rule POSSIBLE_PERSON REVIEW inside a NER full name (posterior >= 0.9) becomes AUTO, reason "<rule reason>; Имя по модели NER, подтверждено правилами". A NER full name that strictly contains a rule PERSON AUTO takes that person_id (priority above PERSON). Exact same span as a rule AUTO: NER stays silent, rules win. Rule AUTO is never demoted (test).

## Step 3 VETO [M]
`_ner_vetoed`: user keep_terms (whole literal or any word), NOT_A_PERSON list, and names whose words are all stop/common words and not given names/patronymics. "Счёт Фактура" is no longer AUTO (test). hide_terms are untouched (entity path). Not done: publisher-type words unknown to every dictionary (e.g. "Политиздат" is still promoted in a list context).

## Step 4 NER ORG/LOC: NOT SHIPPED [M]
Slovnet ORG/LOC spans not covered by any rule finding, same corpus: 1,459 occurrences = 2.29 per 1k chars (776 distinct = 1.2 per 1k); at posterior >= 0.9 still 470 distinct (0.74 per 1k). Budget was 0.3 per 1k. Precision as real organisations/places on 100 random distinct strings, by eye: about 88 (mostly public bodies and streets: "МВД", "Волга", "Государственной думе", "Фрунзенской набережной"), with misses such as "Звук", "Труд", "Правление", "Прайм|access-date". These are public entities, privacy value is low, review volume is 4 to 8 times the limit. Decision: not implemented.

## Step 5 ALL PATHS [M, tests]
Anonymize then restore returns the original for txt (exact), docx (name restored), and anonymize output hides the NER-only name in docx, pptx, html, md, xlsx (long prose cell), pdf text layer. The harvest of every format passes the joined text, so learning works there; a table-like joined text is ineligible for the model in harvest, but long prose cells are still scanned per cell (learning then happens only from the cells scanned, later cells). OCR: images go through the same `harvest(views)` and `scan(view)`; a hard-wrapped OCR-like text test passes; actual OCR painting was not run here [U]. Known limit: per-cell texts shorter than 12 chars are skipped by design.

## Step 6 UI honesty [M]
Reasons: "Полное имя по модели NER" (auto), "Имя по модели NER" (review), "...; Имя по модели NER, подтверждено правилами" (corroborated). Learned names show the ordinary rule reasons ("Имя и фамилия"), which is truthful: the rules found them.

## Numbers
| | before | after |
|---|---|---|
| gates text_v1 / v2 / en / noise | 678/679 fp2 / 111 fp0 / 798 fp1 / 0 | 678/679 fp2 / 111/111 fp0 / 798/800 fp1 / 0 (PASS) |
| prose corpus AUTO findings (NER off -> on), 7 docs | n/a | 7265 -> 7334 (+69) |
| distinct extra AUTO strings with NER | S7C: 104 (10 docs, as NER AUTO) | 93, hand-judged sample of all 93: about 90 persons, wrong: "Политиздат", "Старику Вергилия", "Украины" (country, rule reason) |
| extra REVIEW per 1k chars | 0.066 (W7b) | 0.029 (48 distinct, 30 judged: 27 names) |
| first interim regression found and fixed | text_v1 leak 1 -> 13 (duplicate person record from dative forms: "Совпадает с несколькими сотрудниками") | fixed by `_ner_known` |
Unit: test_ws_s8a 14, test_ws_w7b, test_ws_ner, test_ws_s7c: OK.

## Open
- Lone-word REVIEW names the user confirms are not learned (only full names at >= 0.9 are); the existing hide-by-decision path replaces them as a literal.
- Per-cell xlsx learning order (above). S8B owns inference and chunking.
