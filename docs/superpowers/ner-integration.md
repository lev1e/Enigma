# NER candidates (W7): integration notes

Module `anonymizer/ner.py`, setting `ner_candidates` (default OFF), hook in `detectors._scan_one` (4 lines after `_unknown_names`).
Implements section 7 of `ner-experiment.md` (branch exp/ner).

## Behaviour
- natasha (slovnet NER, ru only). PERSON spans only, forward-backward posterior >= 0.7 (min over the span's tokens).
- Output is always `POSSIBLE_PERSON` / `Decision.REVIEW`. Never AUTO, never a replacement. Existing higher-priority findings win in `_resolve`.
- Skipped: text < 12 chars, < 50% Cyrillic letters, table-like (tabs, `;`-rows), markup, short code-like fragments.
- Span filter: 1 to 4 words, every word capitalised Cyrillic (or an initial), so country lists and glued markup are dropped.
- Chunking: 20 000 chars per model call. Small texts (< 4000 chars) are cached (LRU 256).
- Accepted spans become literals: every whole-word occurrence of the string in the scanned text is a candidate.
- If natasha cannot be imported or fails to load: `available()` is False, feature is silently off, no exception. The module is imported lazily only when the setting is on, so selfcheck is unaffected.

## Measurement (this worktree, venv312, natasha 1.6.0)
| Set | Metric | OFF | ON |
|---|---|---|---|
| text_corpus_v1 (442) | AUTO set changed / AUTO soft leaks / review items | - / 3 / 11 | 0 items changed / 3 / 13 |
| text_corpus_v2 (139) | same | - / 1 / 8 | 0 / 1 / 8 |
| text_corpus_en (512) | same | - / 2 / 0 | 0 / 2 / 0 (feature is ru-only) |
| Novelty probe, 300 ru person sentences (tests/test_ws_ner.py::probe_units, synthetic) | not AUTO-covered / not flagged at all / review items | 128 / 66 / 80 | 128 / 29 / 117 |

Reading: no increase in leaks (AUTO findings are byte-identical), +2 review items over 581 corpus sentences, probe: unflagged names 66 -> 29 for +37 review items (all inside the probe). AUTO leaks are by design unchanged: the benefit is that a human sees the name.
Not measured: review-list volume on real customer-like documents (tests/eval/real is not present in this worktree; tools/eval_real.py was not run). The report's raw figure was 1.1 to 2.5 new person-like spans per 1k chars of public text before the filters above; the filters reduce it by an unknown amount. Because of this the default stays OFF.

## Draft paragraph for README
> **Optional name finder (Russian).** If the optional `natasha` package is installed, the setting "Искать незнакомые имена нейросетью" asks a small local model (no internet, about 2 MB of weights plus word vectors) for surnames that are not in the built-in directories. Such names are only added to the review list; nothing is replaced without your decision. Off by default.

## Draft paragraph for SECURITY.md
> The optional NER model runs fully offline in the same process; text is not sent anywhere. It only proposes candidates for review and cannot weaken replacement: the set of automatic findings is identical with the setting on or off. Model quality is statistical: it misses names in table rows and mislabels some organisations; it must not be treated as a guarantee.

## Licences (UNVERIFIED)
Package licences from metadata: natasha, slovnet, navec MIT. The licence of the training data (news corpus used for the NER weights and the navec embeddings) was NOT verified. Check before shipping the weights inside the installer.

## Build risk
`Anonymizer.spec` collects natasha, slovnet and navec with `collect_all` (data files `natasha/data/model/*.tar` and navec embeddings, about 36 MB) when natasha is importable. Not built on Windows or macOS here. natasha also pulls pymorphy2 (next to the existing pymorphy3) and razdel/yargy; numpy 2.x was installed into .venv312 by this task, so the PyInstaller bundle size grows and numpy compatibility with PyMuPDF/openpyxl in the frozen app is unchecked. If the data files are missing in the frozen app the feature turns itself off (no crash).
