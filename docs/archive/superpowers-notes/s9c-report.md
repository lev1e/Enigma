# S9C: natasha follow-ups (branch ws/s9c)
Labels: [M] measured, [S] static. Python 3.12, natasha 1.6.0. Corpus: public Russian documents of tests/eval/real (not case/), Detector path (harvest+scan), first 150k chars per document, html tag-stripped, `ner_candidates` False vs True (default is True). Scripts in the scratchpad, not committed.

## 1. Confirmed lone names are learned [M, tests]
Before: the user confirms "Айтказин" in the review list -> only that form and the stems the Term matcher caught were hidden: "Айтказиным" stayed readable; confirming the form "Айтказина" hid only genitive/dative and left the nominative.
Now (`Detector._ner_confirmed_lone`, `_lone_forms`, called from `_ner_learn`): a single-word hide term that the model also returned as a person in this document gets every case form (given-name or surname declension, nominative reconstructed from inflected forms, plus the other spellings the model found in the document) registered as spellings of the same Term entity. Evidence from the model is required, so an ordinary hide word ("Коробка") is not expanded. Result in the 5-sentence test text: confirm "Айтказин" or "Айтказина" -> 0 readable forms (baseline: 1 left); restore equals the original. Limit: "Б. Айтказин" keeps the readable initial "Б." (Term replaces the surname only).

## 2. xlsx prose cells, two-pass [M]
Probed 5 workbooks (lone inflected form in an early prose cell, full name in a later cell): output identical before and after, all cells consistent (Name1/Name1_2/Name1_3 variants of one entity). The xlsx pipeline already learns before replacing, so S8A's "learning order" worry does not reproduce. I did NOT add a general per-cell pre-pass (it would cost model time for no measured gain); the per-line branch exists only when the user has hide terms (so item 1 also works in xlsx). Test: `XlsxTwoPass` (3 tests; two also pass on the baseline, they pin the behaviour).

## 3. NER ORG/LOC
Not shipped, stays REVIEW-less and OFF: S8A measured 0.74 to 2.29 extra review items per 1k chars against the 0.3 limit. Nothing changed; there is no in-repo ORG/LOC measuring script (S8A's was scratch), so the numbers are S8A's, not re-measured.

## 4. natasha off vs on on the Russian real corpus [M]
Per document: AUTO findings (all categories), distinct AUTO person strings, review items. "Extra" = person strings only present with natasha on (triaged by reading them; all strings are public figures).
| doc | chars | AUTO off | AUTO on | person strings off | on | extra | wrong (read by eye) | review off -> on |
|---|---|---|---|---|---|---|---|---|
| txt_ru_putin | 150000 | 1438 | 1472 | 276 | 291 | 24 | 0 | 655 -> 654 |
| txt_ru_gazprom | 48668 | 668 | 671 | 69 | 72 | 5 | 0 | 96 -> 96 |
| txt_ru_pushkin | 77259 | 756 | 776 | 190 | 191 | 4 | 1 (Дед) | 214 -> 253 |
| txt_ru_sber | 49193 | 597 | 602 | 28 | 29 | 2 | 0 | 119 -> 116 |
| txt_ru_moscow | 101250 | 851 | 857 | 113 | 118 | 6 | 2 (Политиздат, Феория) | 233 -> 239 |
| pdf_ru_pp1300 (text layer) | 64353 | 1930 | 1918 | 675 | 667 | 24 | 1 (Романович) | 103 -> 105 |
| md_ru_gazprom, md_ru_putin | 123693 / 150000 | 1415 / 1540 | same | 112 / 316 | same | 0 | - | same |
| html_ru_cheb, gazprom, moscow, pushkin, sber, tver | 38k-150k | 477 .. 2216 | same | 67 .. 426 | same | 0 | - | same |
| pdf_ru_pp962, ukaz1843 | 3 | scans, no text layer | | | | | | |
Total 65 extra person strings, 4 wrong (about 94 % right); all wrong ones are common nouns or a publisher, hiding them costs little. pp1300 is a name list: the "AUTO on < AUTO off" is boundary merging (surname + name + patronymic from separate lines become one finding), not lost names.
Key finding [M]: natasha does nothing at all on md and html here: `ner.eligible()` rejects the whole document if the first 4000 chars contain `{{` or `[[` (Wikipedia markup). With the veto disabled (experiment): md_ru_putin +8 extra names (+23 review), html_ru_cheb +3 names but review 100 -> 209. Request written (requests-s9c.md); not changed here (ner.py is S9A's).

### Regressions found by this measurement and fixed [M]
Char-coverage diff of PERSON AUTO (off vs on) showed that natasha ON made names un-hidden:
| cause | examples (public docs) | fix (detectors.py only) |
|---|---|---|
| learned a bogus person "surname=patronymic" from "Мария Алексеевна" | "Марии", "Натальи" (pushkin) went AUTO -> REVIEW because "Имя человека, названного в документе" needs a unique given name | 2-word names containing a patronymic are not registered |
| learned a second person with an already known surname | "Аркадий"/"Ротенберг", "Вяхиреву" -> "Совпадает с несколькими" | `_ner_known` also true when the surname is already someone's |
| NER boundary overlapped a rule span and removed the rest | "Путина Владислав" -> "Владислав Сурков", "Путина" visible; "Черномырдина Рему", "Старикова, Н. Э." | rule remainder that has a name word stays AUTO (`_ner_findings` tail) |
| (guard) NER review next to rule AUTO | | review never replaces a PERSON AUTO of the same place |
Chars of PERSON AUTO coverage lost / gained (on vs off): putin 6/276, gazprom 1/24, pushkin 2/29, sber 1/28, moscow 2/43 (lost = whitespace/punctuation only); pp1300 110/77 (lost words are "Владимир Владимирович" twice, now REVIEW "Совпадает с несколькими"; formats.apply_overrides turns such ambiguity into an AUTO separate label in the Service, so no leak in the product path [S]).
Before the fixes the same table had lost words "Аркадий", "Ротенберг", "Вяхирев(а/у)", "Марии", "Натальи", "Наталья", "Украины", "Путина", "Черномырдина", "Жуковского", "Старикова".
Leaked (tools/eval_real.py run --lang ru --only txt_ru_putin,txt_ru_gazprom,txt_ru_pushkin,txt_ru_sber,txt_ru_moscow,md_ru_gazprom,html_ru_cheb --jobs 2): gold 44 each, leaked 0 on all 7, restore True, before (9024ee0) and after. It checks only the injected gold values, so natural-name effects are not visible there; the char-coverage table above is the natural-name measure.

## 5. Model unavailable note [M]
`tests/test_ws_s6c` (note appears once per job, not when the model is present) passes: part of the 99 targeted tests below.

## 6. requests-s7d
1. strict=True sentence-initial repeat: already fixed by S7C (entities `_learn_words`); verified by my test `StrictAndKeep.test_strict_sentence_initial_repeat_hidden` (passes).
2. keep_terms=["Иванов"] vs "Иван Иванов": decision = current behaviour is intended (a lone "Иванов" stays visible, the full name is hidden as a whole, otherwise the given name would stay readable next to the replacement). Pinned by `test_keep_surname_does_not_unhide_full_name`; the settings hint now says "Слово оставляет открытым только его самого; чтобы не скрывать полное имя, впишите его целиком."

## Numbers
- Gates (`quality_gate.py --only text_v1,text_v2,text_en,noise`): v1 678/679 fp 2, v2 111/111 fp 0, EN 798/800 fp 1, noise 0 replaced: PASS, identical to before.
- Tests: test_ws_s9c 14 OK (3 NoShadowing tests fail on the baseline); test_ws_s9c + s8a + ner + w7b + s7c + s7d + s8b + s6c = 99 OK; detector suites (test_detector, _fixes, test_ws_detect/2/3/4/_en) 173 OK (1 skipped).
