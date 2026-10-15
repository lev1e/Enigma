# Entity and language coverage audit (W11, read-only)

Tool: `tools/eval_entities.py` (probe: 59 invented values, RU and EN, each embedded in 6 carriers: prose, table row under a header, `Label: value` header line, URL query, file name, code comment = 354 cells). Result per cell: AUTO (replaced), PARTIAL/REVIEW (flagged, not fully auto-replaced), MISS. Measured 13.10 on branch ws/w6b, detector from main 935a9e6.
Not measured here: metadata fields, image alt text, hidden text, comments inside OOXML (the probe feeds plain text to `Detector.scan`; format carriers are covered by `tools/eval_real.py`). Carrier "url" values are percent-encoded for spaces, so some url misses are partly a probe artefact; treat the url column as a lower bound.

## 1. Existing kinds, synthetic labelled corpora (`tools/eval_text.py`)
| corpus | gold | full | miss | recall | precision | per-kind gate |
|---|---|---|---|---|---|---|
| text_corpus_v1 (RU) | 679 | 676 | 3 | .996 | .997 | ALL PASS |
| text_corpus_v2 (RU) | 110 | 109 | 1 | .991 | 1.000 | FAIL ORG ("Техноград") |
| text_corpus_en | 800 | 798 | 2 | .998 | .999 | ALL PASS |

## 2. Existing kinds, probe (23 kinds, 204 cells: 164 AUTO = 80 %)
By carrier, known kinds only: prose 30/34, table 26/34, header 31/34, url 16/34, filename 30/34, comment 31/34.
Weak known kinds (AUTO cells out of 6 or 12): ORG-ru 0/6 (all PARTIAL, the «» quotes / legal form leave remnants), CONTRACT-ru 2/6 (misses in table, header, url, filename), ADDRESS-ru 2/6 (3 PARTIAL), NATIONAL_ID-en 7/12 (SSN ok, UK NI number missed in all carriers except one), BIK-ru 4/6 (prose, table), BIRTH_DATE 4/6 in both languages (table, url; en table is REVIEW only), PHONE-en 4/6 (url, filename).
Solid (6/6 or 12/12): INN, OGRN, KPP, BANK_ACCOUNT, EMAIL, DOMAIN, IP_ADDRESS, USERNAME, SECRET-en, PERSON-ru.

## 3. Candidate kinds not in `tokens.KINDS` (35 value types, 174 cells: 66 AUTO = 38 %)
Detected already by luck of other rules: API keys (AWS, GitHub) 6/6, crypto wallets BTC/ETH 6/6, US EIN 6/6, IBAN 5/6, JWT 5/6, ISO birth date 5/6, RU phone with leading 8 4/6, signature "/s/ Name" 4/6.
Not detected (AUTO of 6): VIN 1/6 (EN and RU, only the filename carrier), GPS coordinates 1/6, MAC address 0/6 (one PARTIAL), IMEI 1/6, UK NHS number 1/6, DE Steuer-ID 1/6, US driver licence 1/6, SWIFT/BIC 1/6, KZ IIN 1/6, UA RNTRC 1/6, medical record number 1/6, ICD diagnosis 1/6, extension/fax 0/6, salary 0/6, RU birth date in words ("14 марта 1987 года рождения") 1/6, role titles that identify a person ("главный бухгалтер Петрова А. В.", "Chief Financial Officer Anna Whitfield") 0/6 AUTO with 12/12 PARTIAL (the name is caught, the title and the rest are not), RU signature line ("_____ / Сидоров И. И. /") 0/6 AUTO, 6/6 PARTIAL.

## 4. Ranked gaps (realistic exposure x fix cost)
1. ORG-ru partial cover (quoted legal forms): leaves the company name readable in 5 of 6 carriers; known v2 gate failure. W3.
2. Birth dates: table-cell and "in words" forms (en table REVIEW only, ru table miss, words 1/6). Direct personal data. W3.
3. Person-identifying roles and signature lines: name is caught but title/initials stay; a chief accountant or CFO is identifiable from the title alone. W3 (rule: role word + surname/initials span as one entity).
4. CONTRACT-ru numbers in table/header/filename (2/6). W3 (colctx).
5. UK NI / other national ids (NATIONAL_ID-en 7/12): NI number not recognised in any carrier. W3.
6. Medical: MRN, NHS number, ICD diagnosis (1/6 each). Health data is special-category. W3 (new kind PII subtype, labelled rules).
7. VIN (1/6), IMEI (1/6), MAC (0/6), GPS (1/6): device and vehicle identifiers with checksums or fixed shapes; cheap, low false positives. W3.
8. ADDRESS-ru full form with "г., ул., д., кв." leaves 3 of 6 partial; BIK bare in prose/table (2/6). W3.
9. SWIFT, DE Steuer-ID, US licence, KZ IIN, UA RNTRC: only with a label in front (label-gated rules, as for INN). Exposure depends on customer base; ask the owner (see section 5).
10. Salary/extension: low priority; salary needs the owner's policy decision (is compensation personal data for this product).
11. URL carrier: known kinds 16/34 (47 %) in query strings; W1/W3 decision whether URL parameters are scanned as a text carrier.

## 5. Languages beyond RU/EN (effort only, nothing implemented)
UK (Ukrainian): mostly the same Cyrillic rules; names/morphology need a pymorphy3 Ukrainian dictionary (separate package, licence/size check, owner approval) plus RNTRC/EDRPOU/passport formats: medium. KZ: IIN/BIN rules are 12-digit checksum, cheap; names are Russian-script mixed with Kazakh letters (ә, ғ, қ, ң, ө, ұ, ү, һ, і) which the tokenizer must accept: small to medium. Others (DE/FR/ES...): per-country id formats plus a name model; not a rule-only job, treat as W7/NER territory. Needs the owner's decision.

## 6. Handoff
Tasks written to `docs/archive/superpowers-notes/requests-w11.md` for W3/W1. Re-run `python tools/eval_entities.py` after each W3 merge; the cell counts above are the baseline.
