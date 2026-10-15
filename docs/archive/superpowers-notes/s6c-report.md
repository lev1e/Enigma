# S6C report
Gate (tools/quality_gate.py, fast steps) before -> after: v1 678/679 fp 2 -> same; v2 110/110 fp 0 -> 111/111 fp 0 (one corpus label added, see 5); EN 798/800 fp 1 -> same; noise 0 replaced -> 0.
1. Countries/continents: behaviour kept (COUNTRY/REGION and country adjectives hidden). geo_data.py docstring corrected. No over-hide measured on a named corpus (noise corpus 0 replaced), so no behaviour change.
2. "LinkedIn, VK": social networks added to _NOT_SURNAME and COMMON_SOFTWARE; the initials-then-surname branch also checks _NOT_SURNAME. "J. Smith" still found.
3. Quoted generic phrases: geo_data.GENERIC_BUSINESS_PHRASES; skipped only when kind is PROJECT in entities._quoted. «Альбатрос» still PROJECT.
4. Bare "Сибирский регион": kept as REGION (safe); no measured over-hide, gates unchanged.
5. BIRTH_DATE year-only rule ("1975 г.р.", "1975 года рождения"). Corpus fix: tests/eval/text_corpus_v2.jsonl item v2_person-0016 now labels "1975" BIRTH_DATE (not real/). v2 gold 110 -> 111, baseline.json not updated (orchestrator decision).
6. New kinds DEVICE_ID (Device), MEDICAL_ID (Medical), COMPENSATION (Pay) in tokens.py + KIND_GROUPS (advanced rows) + W3e rules re-categorised. tests/test_ws_w3e.py expectations moved from PII to new categories (file not mine; edit is mechanical).
7. OMS: "№" trimmed out of the span (the normaliser turns it into "No", which shifted the mapped span).
8. transform_ooxml macro/signature: BLOCKED, no copy, output_path "", Russian message. Service still gives MACRO_REFUSAL / "не был изменён"; nested OOXML handled (BLOCKED raises NestedBlocked).
9. Detector.ner_unavailable set when ner_candidates on, text eligible (Russian), ner.available() False; service._pass adds one info message NER_UNAVAILABLE_NOTE to the first file outcome. Option text extended. NER thresholds untouched.
Tests: tests/test_ws_s6c.py (15). Also green: w3e, w3f, w9, categories, settings_schema, tokens, entities, ooxml2, round3/4, detect, detector, service (318 tests).
Unverified: web UI rendering of the new kind rows; frozen-build behaviour of the note; real_results not run.
