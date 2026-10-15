# S7D report: settings audit (branch ws/s7d)
Test: tests/test_ws_s7d.py, 25 tests, OK (6 s). Related: test_settings_schema, test_webapp, test_ws_ner, test_ws_categories, test_chat_settings: 61 OK.

## Per-option table
read = read in product code; UI = rendered from schema in Settings (search matches label+hint+example; verified in browser); effect = flipped via Env(**prefs), observable change asserted.

| option | read | UI | effect test | verdict |
|---|---|---|---|---|
| theme | index.html (UI only) | yes | wiring only (no engine effect by design) | ok |
| strict | service/formats/entities | yes | output differs, Term1 appears | ok; leak found, see requests-s7d.md #1 |
| learn_names | detectors | yes | output differs | ok |
| ner_candidates | detectors | yes + availability note + privacy line (new) | findings with "NER" reason vanish when off | ok, improved |
| business_confidential | detectors | yes | line hidden when on | hint was wrong (promised "цены, скидки", rule covers выручка/себестоимость/маржа/KPI/бонус/зарплата): relabelled |
| neutral_names | service | yes | out_name differs | ok |
| hide_kind_* x22 (PERSON..IP_ADDRESS incl. DEVICE_ID, MEDICAL_ID, COMPENSATION, countries) | disabled_kinds | yes (groups, per-kind) | each kind: hidden when on, visible when off | ok (PII wiring only: no stable sample) |
| protected kinds (SECRET, CARD, ...) | PROTECTED_KINDS | locked rows | cannot be disabled, test asserts | ok |
| hide_terms / keep_terms | service/detectors | yes (words screen) | next job, no restart | ok; see requests #2 |
| numbers | service/formats | yes | B1 changes in xlsx | ok |
| finance_numbers | formats | yes | amount changes | ok |
| finance_scale_per_sheet, finance_text_amounts, finance_on_formula_conflict | formats | yes | read-in-code + covered by test_ws_finance | ok |
| scrub_metadata | formats | yes | docx core author gone/kept | ok |
| inspect_embedded | formats | yes | read + warnings not fewer when on (weak) | ok, weak effect test |
| image_mode | imagereplace/webapp | yes, warning | media differs replace vs redact_text | ok |
| ocr_images, image_brand_policy | formats | yes | resolved into Settings; pixel effect covered by test_ws_images/img2 | ok |
| keep_originals, retention_days, restored_retention_days | webapp/vault/chats | yes | persist + reset test | ok |
| retain_secrets_for_restore | formats/detectors | yes | persist test | ok |
Persistence: all options survive Env.reopen and reset to defaults (test_options_persist_after_reopen_and_reset). Chat scope rejects global-only options.

## Fixes
- Removed dead field Settings.anonymize_filenames (never read; neutral_names is the real switch).
- ner: added ner.installed() (cheap, no model load); /api state now has ner_available; Settings shows a note when the model is missing and one line that it runs locally.
- business_confidential label/example corrected to what the rule matches.

## UI reachability (browser, dev_server, worktree)
Settings open, search filters to the NER row, 0 controls under 24 px. Present in index.html and API: single file, folder pickers (chat/answer), restore, AI chat inline + /ai link, review list ("Возможно, нужно скрыть ещё", extra terms), hide/keep terms, backup export/import, Office add-in install, updater check, stage text, per-kind groups, chat override + reset. Screenshot: docs/archive/shots/shots-s7d/settings-ner-search.jpg.
Unverified: end-to-end clicks of each feature (not run), 44px target audit only spot-checked, AI chat settings not part of settings_schema (kept in keystore/ai_chat, tests test_ws_llm_*).
