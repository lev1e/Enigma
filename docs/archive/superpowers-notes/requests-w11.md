# Requests from W11 (entity coverage) to W3 (detector) and W1 (images/OCR)
Measure with `python tools/eval_entities.py` (prints AUTO/PART/REV/MISS per kind and carrier) and `tools/eval_text.py` for regressions. Details and numbers: `docs/superpowers/entity-coverage.md`.

W3:
1. ORG-ru: quoted legal forms (`ООО «Ромашка Логистик»`) end PARTIAL in 5 of 6 carriers; also the known v2 gate failure "Техноград". Target: probe ORG-ru AUTO >= 5/6, text_corpus_v2 gate PASS.
2. BIRTH_DATE: table cell (ru miss, en REVIEW only) and the form "14 марта 1987 года рождения" (AUTO 1/6). Target AUTO >= 5/6 for both.
3. Roles that identify a person ("главный бухгалтер Петрова А. В.", "Chief Financial Officer Anna Whitfield") and signature lines ("_____ / Сидоров И. И. /"): name caught, role/initials left. Treat role + name as one span. Target 0/6 -> 5/6 AUTO.
4. CONTRACT-ru in table/header/filename (2/6); BIK bare in prose/table (4/6); ADDRESS-ru partial (2/6).
5. NATIONAL_ID-en: UK NI number (`QQ 12 34 56 C`) missed in 5 of 6 carriers.
6. New label-gated rules, cheap with low FP: VIN (17 chars, no I/O/Q, check digit), IMEI (Luhn, 15 digits), MAC, GPS decimal pairs, SWIFT/BIC, medical record number, NHS number, ICD code after a diagnosis label. Each measured 1/6 or 0/6 today.
7. URL carrier: known kinds 16/34; decide whether query-string values are scanned (probe artefact partly: spaces are %20).
8. Owner decision needed before work: DE Steuer-ID, US licence, KZ IIN, UA RNTRC, salary.

W1: none from this audit (probe is text only). Image alt text and metadata carriers are not measured; that needs the format-level eval_real cases.
