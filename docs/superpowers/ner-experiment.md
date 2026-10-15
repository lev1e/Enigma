# NER as a second detector: measurement (12.10)

Question: would a local, offline NER model on top of the rule detector close a meaningful share of the remaining leaks, at an acceptable false-positive (FP) cost?
Measurement only. No product code was changed. Tool: `tools/ner_experiment.py` (stages `product`, `ner`, `analyze`, `consistency`, `--probe`). Raw dumps live outside the repo. `case/` was not read.

## 1. What was measured, and what was not

| Set | What it is | Size | Gold? |
|---|---|---|---|
| Synthetic corpora v1+v2 (ru), en | `tests/eval/text_corpus_*.jsonl`, the sets the product was tuned on | 581 ru + 512 en sentences; soft-kind gold: 421 ru, 552 en | yes |
| **Novelty probe** (new, synthetic) | names/orgs built from syllables, 5 contexts for persons, 3 for orgs/cities; half the persons are bare surnames | 792 sentences (396 ru, 396 en) | yes, by construction |
| Public real documents | 110 text-extractable documents from `tests/eval/real` (pdftotext / docx / xlsx / pptx / plain / html), 2.98M chars ru, 4.60M chars en | 110 docs | **no** (unlabelled; only "what NER adds" is measurable) |

Not measured: rescue on real documents (no gold), images/OCR, PDF layout, structured ids (NER cannot know them), the private `case/` data, a multilingual transformer (the first two candidates gave a clear enough signal that I did not ask to download it).
The synthetic corpora cannot show a gain: the product already leaks only 4 (ru) and 2 (en) soft values there. Any gain claim rests on the probe, which is synthetic too (see 6).

## 2. Versions, licences

| Component | Version | Licence (package metadata) | Disk |
|---|---|---|---|
| natasha (ru NER via slovnet + navec) | 1.6.0 / slovnet 0.6.0 / navec 0.10.0 | MIT | package 36 MB (NER weights 2.3 MB, rest embeddings); no torch |
| spaCy | 3.8.16 | MIT | 28 MB + thinc, numpy etc. |
| en_core_web_sm | 3.8.0 | MIT | 15 MB |
| en_core_web_md | 3.8.0 | MIT | 54 MB |

Throwaway venv `~/ner-exp-venv` (256 MB total), fully offline after install. Training-data licences (OntoNotes for spaCy; the news corpus for natasha) were **not verified**. Check them before shipping.
Label mapping: PER/PERSON to PERSON; ORG to ORG (and PROJECT); LOC/GPE/FAC to CITY/REGION/COUNTRY/ADDRESS (coarse).
Confidence: natasha = posterior of the decoded tag from a forward-backward pass over the slovnet CRF (min over the span's tokens). spaCy = beam-parse probability mass of the span. **The spaCy proxy is nearly useless for thresholds**: from 0.5 to 0.99 only 475 to 304 of 641 spans (sm) drop out. Many spans sit at 1.0.

## 3. Results

### 3a. Synthetic corpora (soft kinds: PERSON, ORG, PROJECT, CITY, REGION, COUNTRY, ADDRESS)

| | gold | product leaks | NER rescues (strict label) | NER rescues (any label) | NER extra FP τ=0 | extra FP τ=0.9 |
|---|---|---|---|---|---|---|
| ru, natasha | 421 | 4 (2 PERSON, 2 ORG) | 3 | 4 | 52 (41 unlabelled + 11 on negative spans) | 12 |
| en, spaCy sm | 552 | 2 (CITY) | 0 | 2 | 67 | 25 |
| en, spaCy md | 552 | 2 (CITY) | 0 | 2 | 51 | 21 |

Net on the synthetic corpora: at most +4 rescued (ru) / +2 (en) against 12 to 67 extra FP. That is a loss, but the ceiling is tiny.
NER alone (strict, whole span covered), for reference: ru PERSON 212/267 (79%), ORG 52/73, CITY 50/56. en sm PERSON 212/288 (74%), CITY 102/152; en md PERSON 233/288 (81%), CITY 131/152. ADDRESS ~0 (NER does not return street addresses).

### 3b. Novelty probe (unknown names): where the hypothesis is tested

Leaks = gold value not covered by AUTO product findings. Union = product AUTO plus NER spans of a compatible label (no threshold).

| kind | n | product leaks | union leaks: ru natasha | en sm | en md |
|---|---|---|---|---|---|
| PERSON | 300 per language | ru 158, en 149 | 31 | 47 | 51 |
| ORG | 36 | ru 24, en 1 | 24 | 1 | 0 |
| CITY | 60 | ru 12, en 60 | 7 | 26 | 14 |
| all | 396 | ru 194, en 210 | 62 | 74 | 65 |

So on unknown names NER does close roughly two thirds of the leaks. Product failures there are mostly bare surnames, even after a cue ("Свидетель X", "Witness X", "Applicant: X": ru 60/60 leaked). In ru, 78 of 158 PERSON leaks were at least in the review list; in en 0 of 149 (the product did not flag them at all).
NER misses: the table-row/fragment context "Surname&lt;TAB&gt;role&lt;TAB&gt;City" (natasha finds 30/60 persons, 3/20 cities; spaCy md 44/60 persons), and ru ORG introduced by "Контракт с компанией X" or "Поставщик: X" (0/24).

Threshold sweep on the probe (all kinds, leaks of 396; product-only 194 ru / 210 en):

| τ | 0.0 | 0.5 | 0.7 | 0.8 | 0.9 | 0.95 | 0.99 |
|---|---|---|---|---|---|---|---|
| natasha, union leaks | 62 | 62 | 62 | 99 | 100 | 135 | 191 |
| natasha, extra FP on corpora | 52 | 39 | 27 | 22 | 12 | 11 | 0 |
| spaCy sm, union leaks | 74 | 88 | 100 | 111 | 124 | 136 | 160 |
| spaCy sm, extra FP on corpora | 67 | 32 | 27 | 26 | 25 | 24 | 18 |
| spaCy md, union leaks | 65 | 96 | 110 | 120 | 125 | 133 | 154 |
| spaCy md, extra FP on corpora | 51 | 25 | 22 | 21 | 21 | 21 | 20 |

For natasha τ=0.7 is the knee: it keeps the full probe rescue and halves the corpus FP. For spaCy there is no good threshold: rescue falls steadily while FP falls only to a floor of about 20.
Below τ the hits would go to the "uncertain" review list instead of being replaced; their number is the difference between the FP rows, so a review list rather than auto-replacement is the only usable mode.

### 3c. Real documents: what NER adds that the product did not replace (AUTO or REVIEW)

| model | τ | new PERSON | new ORG | new LOC | per 1k chars |
|---|---|---|---|---|---|
| natasha (2.98M chars) | 0 | 1721 | 3583 | 2287 | 2.5 |
| natasha | 0.9 | 416 | 1358 | 1538 | 1.1 |
| natasha | 0.99 | 50 | 157 | 118 | 0.1 |
| spaCy sm (4.60M chars) | 0 | 5690 | 10003 | 6832 | 4.9 |
| spaCy md | 0 | 5780 | 12229 | 7502 | 5.5 |
| spaCy md | 0.9 | 3841 | 8577 | 4692 | 3.9 |

Hand check of 50 random new spans (25 natasha τ≥0.9 on ru, 25 md τ≥0.9 on en): **10 are person names, all public figures or citation authors; 0 private data; 40 are noise or non-personal** (countries, state names, famous organisations, cinema names, CSV country rows, wiki-markup fragments such as `{{#invoke`, ".navbar li"). 80% noise; the person names would still be something a user may or may not want hidden.
NER is clearly worse on: csv/xlsx/html/markup (en csv 5.8K to 6.9K new spans, all xlsx spans new; country and organisation names in table columns), sentence fragments (spaCy sm finds only 30/86 fragment golds, 35%), "ПОДПИСАНО"/"SSN"/"IBAN"/"WhatsApp"/"Managing Director" tagged as ORG/LOC.

### 3d. Slices (corpus gold found by NER, strict)

| type | ru natasha | en sm | en md |
|---|---|---|---|
| prose (≥12 words) | 117/144 | 84/109 | 88/109 |
| mid (6 to 11) | 142/191 | 228/317 | 244/317 |
| fragment (<6 words) | 63/80 | 30/86 | 59/86 |
| signature | 1/1 | 17/24 | 21/24 |
| table row | 1/2 | n/a | n/a |
| code/markup | 0/3 | 14/16 | 16/16 |

Most corpus FP sit in mid/fragment texts (ru: 34 + 18 of 52).

### 3e. Disagreements with the product (corpora, spans overlapping an AUTO finding)

ru: 409 overlaps; 235 same bounds (57%); 177 differ. en sm: 579 / 375 (65%) / 257; md: 622 / 413 (66%) / 242.
Typical: NER splits one full name into pieces ("Крыловым" + "Владимиром Ивановичем" against one full name), drops the trailing initial dot ("Беляеву М.Э" against "Беляеву М.Э."), labels a person as LOC/ORG, an organisation as PERSON, cuts "DOB 20.12.1995" into an ORG. NER boundaries cannot replace the product's. They can only propose candidates.

### 3f. One entity, one label (4 neutral sentences per entity, same entity)

| model | PERSON consistent / exact in all 4 | ORG | CITY |
|---|---|---|---|
| natasha | 85/120 (71%) / 80 | 19/31 | 14/24 |
| spaCy sm | 97/120 (81%) / 74 | 10/18 | 19/23 |
| spaCy md | 101/120 (84%) / 86 (72%) | 14/18 | 17/23 |

Between 16% and 29% of persons get a different span, label or none in different sentences. An NER candidate must therefore be turned into a literal entity (harvested like the product's own findings) so that every occurrence is replaced; per-sentence NER output must never feed the token map directly.

## 4. Cost

| | cold start | speed | RAM | PyInstaller (not built) |
|---|---|---|---|---|
| natasha | 0.2 to 0.3 s | 20 ms per 1k chars | ~330 MB on short texts; 1.9 GB when whole 400K-char documents are fed (chunk them) | numpy only, no torch; +~36 MB; pymorphy2/yargy not needed for NER. Low risk |
| spaCy sm | 0.6 to 0.7 s | 62 ms per 1k chars (5 s for 80K chars) | ~360 MB short; 2.2 GB on big docs | +28 MB lib +15 MB model; thinc/cymem/preshed/blis/srsly with many hidden imports and compiled extensions: highest risk |
| spaCy md | 0.4 s | 66 ms per 1k chars | ~600 MB short; 2.7 GB big docs | +54 MB model |

RAM numbers are process peak (resource.getrusage) and cumulative across models run in one process, so they are upper bounds.

## 5. The 20 most instructive examples (placeholders instead of PII)

Rescued (probe, product leaked, NER found):
1. `Свидетель [SURNAME-RU] подтвердил показания, данные ранее.` natasha PERSON 0.99, product nothing.
2. `Заявитель: [SURNAME-RU]` natasha found 59/60 of such lines.
3. `Договор подписал директор [FIRST] [PATRONYMIC] [SURNAME-RU] ...` natasha found 59/60; the product missed 8.
4. `Witness [SURNAME-EN] confirmed the earlier statement.` spaCy md 59/60; product 30/60 missed.
5. `Applicant: [SURNAME-EN]` md 44/60; product 30/60 missed.
6. `The agreement was signed by director [FIRST] [SURNAME-EN] ...` md 60/60.
7. `Born in [SMALL-TOWN-EN].` md 18/20; product 0/20 (en small towns outside the dictionary).
8. `Отправлено из [SMALL-TOWN-RU], вчера.` natasha 19/20; product leaked 6/20 (and natasha finds only 6/20 after "Родился в г.").
9. `Supplier: [ORG-EN]` and `Invoice issued by [ORG-EN] Inc.` md 12/12 (product already catches most).
10. `Regards,\n[FIRST] [SURNAME]` (ru) natasha 60/60.

Harmful or useless (corpora and real documents):
11. `ПОДПИСАНО: [SURNAME] [FIRST] [PATRONYMIC]` natasha tags `ПОДПИСАНО` ORG/LOC 0.3 to 0.6.
12. `Signed by [NAME], Managing Director.` natasha tags "Managing Director" ORG 0.63 to 0.71.
13. `WhatsApp +7 ...` `WhatsApp` ORG 0.77 to 0.85.
14. `Patient [SURNAME], [FIRST], DOB ..., SSN ...` spaCy tags `SSN` ORG 1.0.
15. `Wire the funds to IBAN ...` `IBAN` ORG 1.0; the reference `INV-xxxxx` ORG 0.53.
16. `Server [IP] is reachable via VPN.` `Server` ORG.
17. A gapminder CSV: every country row ("[COUNTRY],[ISO],[YEAR],...") gives LOC/ORG hits; more than 5000 new spans per file set.
18. Wiki citation markup: `|last1=[SURNAME] |first1=[FIRST] ...` person spans glued to markup; `{{#invoke:Cite` tagged ORG.
19. A country list in a ru PDF ("Египет 15. Индонезия 16. Ирак"): every country LOC at 0.93 to 0.99; not personal data.
20. `Based in [CITY], UK` product replaces the city; `UK` also LOC 1.0 (by-design country hit is a double count).

## 6. Caveats on the measurement

- The probe is synthetic and my own: invented syllable names, half the persons bare surnames after a cue word, contexts I wrote. It shows a real product weakness (bare surnames after a role cue) and that NER fixes most of it. It does not tell the real-world rate. Real unknown-name leak rates in customer documents are **unmeasured**.
- Real documents are public (mostly Wikipedia-like, forms, law texts) and unlabelled, so the 80% noise figure comes from a 50-span hand check on public text, not customer data.
- The spaCy confidence is a weak proxy; a proper score (a calibrated classifier on top of the beam mass plus features) was not built.
- Persons-only FP were not hand-checked separately; the 10/50 person-like spans are all that is known.

## 7. Recommendation

**(a), narrowed: integrate as a candidate source for the "uncertain" review list only, never as auto-replacement.** Evidence:

- Auto-replacement is ruled out: ~80% of new real-document spans are non-personal (3c), boundaries disagree with the product in 35 to 43% of overlaps (3e), and the same entity is labelled inconsistently in 16 to 29% of cases (3f).
- The value is real on unknown names (3b: ru leaks 194 to 62, en 210 to 65 to 74 on the probe). It is mostly PERSON; ORG/LOC add mostly noise on the corpora and real documents (ru ORG/surname-less cue contexts rescued nothing).
- Settings to test next: PERSON label only; ru natasha with τ ≥ 0.7 (knee in 3b); en spaCy **md**, not sm (better recall, fewer FP; sm collapses on fragments: 35%), without a threshold until a better confidence score exists. Chunk documents to keep RAM near 0.5 GB.
- Accepted hits must be harvested as literal entities into the product (one entity, one label), not applied as spans.
- Skip table/CSV/markup text and short code-like fragments for NER (clearly worse there).
- Suggestion for the product, cheaper than NER for the largest probe gap: treat a bare capitalised word after cue words ("Свидетель", "Заявитель", "Witness", "Applicant", "Director") as a person candidate in review (ru 60/60 and en 30/30 leaked after the cue). This does not need any model and should be tried first. Measure NER again after that fix, because it removes most of the probe gap.
- Not yet done before shipping: verify training-data licences; PyInstaller build test (spaCy is the risky one); real labelled customer-like documents to measure rescue and review-list volume (volume ~1 to 4 new person-like spans per 1k chars of public text is a lot of review work).
