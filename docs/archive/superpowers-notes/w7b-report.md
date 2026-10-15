# W7b: natasha NER, measurement, integration, decision

Labels: [M] measured here, [S] static reading, [U] unverified. Corpus: committed public documents in tests/eval/real (manifest `real_manifest.json`); no case/ data. Tool: `tools/ner_measure.py` (normal Service path, `ner_candidates` False vs True). Raw results were in /tmp (not committed).

## 1. Measurements (37 Russian documents: txt, md, html, text-layer PDF; 20.3 MB) [M]
Ran with the first version of the module (all NER hits as REVIEW), natasha 1.6.0, numpy 2.5.4, Python 3.12, macOS.

| Metric | Value |
|---|---|
| Extra REVIEW suggestions per 1,000 chars (distinct strings, reason "NER") | mean 0.066, median 0.0, p90 0.142, max 1.15 (txt_ru_pushkin, 89 strings in 77 KB) |
| Documents with no NER extras | 23 of 37 |
| Total extras / occurrences | 394 distinct strings / 1,787 occurrences |
| Precision of extras (random 100, judged by eye: person name or not) | about 75 % (25 non-names: adjectives, titles, common nouns, "Что", "См", "Оп") |
| Precision of full-name-shaped extras (36 of the 100) | 33/36 = 92 %; after the new filters (role words, initials-only, lone words) about 97 % |
| Recall gain on injected gold (dense synthetic persons, 210 values) | 0: the rules already cover 198/210 with NER off and the same 198 with NER on; NER found no gold name the rules missed |
| Real names the rules did not flag (non-injected) | about 70 of the 100 sampled strings were real people (historical and news figures: "Джо Байден", "Эммануэль Гриншпан", "Макс Фасмер"); this is the actual benefit |
| Run time | +0.18 s per 100 KB on average over 20 MB; html_ru_tver (1.6 MB) 6.6 s to 19.1 s (+0.77 s per 100 KB) |
| Memory | RSS 528 MB to 778 MB after model load and use: about +250 MB |
| First-call model load | 0.31 s (weights 29 MB, from package data) |
| English | NER does nothing: `eligible()` needs 50 % Cyrillic letters. text_en gate with the feature ON is unchanged (798/800, fp 1); unit test `test_english_untouched`. A 12-document EN comparison run was started but had not finished when this was written [U] |

Note: AUTO leaks on the injected gold are unchanged either way (NER never reduces protection; AUTO findings from rules always win in `_resolve`).

## 2. Licences and training data [M for metadata, U for data]
- natasha 1.6.0, slovnet 0.6.0, navec 0.10.0: `License: MIT`, MIT classifier and LICENSE file in each dist-info (copyright 2016 Natasha contributors). razdel, yargy, ipymarkup, pymorphy2 are separate packages; not re-checked here [U].
- Training data per package metadata (offline): `slovnet_ner_news_v1` "trained on news articles"; `navec_news_v1_1B_250K_300d_100q` built from news corpora (lenta, ria, taiga_fontanka, buriy_news, buriy_webhose, ods_gazeta, ods_interfax). Package metadata states no licence for those corpora or for the model weights separately. Whether news-corpus copyright restricts redistributing derived weights is NOT verified [U]. The software licence (MIT) is verified; the training-data licence is not. Owner to confirm before public release (checklist G12).
- Models are a statistical model: it misses names in tables and mislabels some common words; kept as a second opinion only.

## 3. Packaging [S], not built
- Finding: `Anonymizer.spec` listed `numpy` in `excludes`, while natasha/slovnet need numpy. In a frozen build the model would silently fail to load and the feature would be off. Fixed: numpy is excluded only when natasha is absent.
- Spec now adds: `collect_all` for natasha, slovnet, navec (already there) and hidden imports numpy, pymorphy2, razdel, yargy, ipymarkup, intervaltree, dawg_python. `pymorphy2_dicts_ru` (14 MB) is not needed by the NER path and is not collected.
- Data in the bundle: natasha/data/model/*.tar (NER 2.4 MB; morph and syntax 5.2 MB unused), natasha/data/emb/navec_news...tar 26.6 MB, name dictionaries.
- Estimated growth (disk, unmeasured): natasha 36 MB, numpy about 34 MB, rest under 2 MB: about +60...70 MB in the app folder, +25...35 MB in the installer. Optional saving: exclude the unused morph and syntax tars (about 5 MB) with a datas filter.
- Release checklist: new gate G12 (frozen app must report the feature available; the log line "NER (natasha) недоступен" must be absent). Not run: no Windows build here.

## 4. What changed in code
- `anonymizer/ner.py`: `decide()` classifies each accepted span. Full-name shaped (two or more name words, or initials plus a surname; first word not a role/title; every word at least 3 letters; no labels like Name1) with posterior at least `AUTO_CONF = 0.9` becomes AUTO (category POSSIBLE_PERSON, reason "Полное имя по модели NER", replaced as Name N). Lone words stay REVIEW; generic words, stop words, adjective endings with hyphen compounds, label-like tokens are dropped. `MAX_TEXT = 400000` characters per call; longer texts are skipped. If natasha or its weights are missing, one warning is logged (`anonymizer.ner`) and the rules continue alone; model load happens once under a lock; no network access.
- `anonymizer/detectors.py`: only the hook lambda (now receives an `auto` flag).
- `Anonymizer.spec`, `docs/superpowers/release-checklist.md`, `tests/test_ws_w7b.py`, `tools/ner_measure.py`.
- ORG/LOC from NER are not used: not measured, and PER is the only gap the rules have.

## 5. Gates [M]
- `tools/quality_gate.py --only text_v1,text_v2,text_en,noise` with the feature ON and the new classification: text_v1 678/679 fp 2 (baseline 676), text_v2 110/110 fp 0, text_en 798/800 fp 1, noise 0 replaced. PASS.
- Unit: test_ws_w7b, test_ws_ner, test_ws_ru4, test_ws_w3d, test_ws_w3e, test_orch4 (50 tests), settings tests (28): OK. Full suite not run (as instructed).
- `eval_real` on the Russian txt/md/html cases (14 docs, --jobs 2), OFF vs ON:
  leaked injected values identical in every case (html_ru_putin 5, html_ru_tver 1, md_ru_gazprom 1, txt_ru_moscow 1, others 0); restore equal unchanged (html_ru_putin restore False both before and after). Extra replaced entities with ON: html_ru_cheb +63 replacements, txt_ru_pushkin +27, txt_ru_putin +40, txt_ru_gazprom +5, txt_ru_moscow +8, txt_ru_sber +7, other html and md unchanged (markup is skipped by `eligible`). New replaced strings seen: Анжелика Варум, Риэ Кугимия, Лев Хасис (true persons), Крокодил Гена (cartoon character, arguable), Чебурахать (a false positive: a verb). No RU docx exists in the committed corpus (docx samples are English).

## 6. Decision
Default ON for Russian text, with the existing toggle (Settings > "Искать незнакомые имена нейросетью (русский)"). Reasons: licences of the packages are MIT; AUTO only for full-name shaped hits at 0.9 or more (about 97 % precision on the sample); zero effect on leaks, gates not worse (v1 better by 2); English untouched; fail-soft when the model is missing; the cost is time (+0.2 to 0.8 s per 100 KB of Russian prose) and about +250 MB RAM once the model loads. The reason it was off (unknown review volume) is answered: median 0 extra suggestions per 1,000 chars, p90 0.14.
Caveats the owner must accept: (1) training-data licence not verified, check before public release; (2) the recall gain on injected gold is 0, the gain is on real names outside the directories; (3) residual AUTO false positives exist at low rate (e.g. a verb); (4) the frozen build was never run (G12).
UI: show the toggle in Settings (exists), add a note in the file result when the model is unavailable ("правила работают, нейросеть имён недоступна") and in the review list show reason "Имя по модели NER" for lone names. The UI note is not implemented here (outside ownership).
To revert: flip `ner_candidates` back to False in models.py and settings_schema.py (one commit).
