# Prompt for the parallel chat B: NER experiment (measure only, no product changes)

Paste everything below the line into a fresh chat. Chat A is working on English leaks and images in the same repo at the same time, so this chat must not edit product code.

---

You are running a measurement experiment for Anonymizer (Python 3.12, offline, reversible document anonymizer; repo root = current dir, branch `main`). Another chat is editing `anonymizer/*` right now. **You must not edit anything under `anonymizer/`, `tests/` (existing files), or `tools/` (existing files).** Work in your own git worktree off `main` (`git worktree add ../anonymizer-ner-exp -b exp/ner`) and add only NEW files: `tools/ner_experiment.py`, `docs/superpowers/ner-experiment.md`. Use `.venv312/bin/python` by absolute path for the product; NEVER write wrapper scripts into `.venv312/bin` or homebrew python. The `case/` folder is private customer data: never read it into an external tool, never copy it into corpora or docs.

## Question to answer

Would a local, offline NER model used as a second detector on top of the existing rules close a meaningful share of the remaining leaks, at an acceptable false-positive cost? Answer with numbers, not opinions.

Hypothesis (unproven): NER helps on unknown surnames/organisations/places that the rules and dictionaries miss, and does nothing for structured ids, PDF structure or images. Check this hypothesis; do not assume it.

## Candidates (install in a throwaway venv OUTSIDE the repo, not in `.venv312`)

- Russian: `natasha` (Slovnet NER; the models are bundled in the pip package `slovnet`/`navec`).
- English: `spacy` with `en_core_web_sm` and `en_core_web_md` (and `lg` if size allows).
- Optional, only if the first two give a clear signal: one multilingual transformer NER (e.g. an XLM-RoBERTa token-classification checkpoint) for both languages.
- Before downloading anything, **ask me for approval**: list each package/model, source, size, licence. Do not download without a clear yes. After approval, record versions and licences in the report. Run all candidates fully offline after install.

## Method

1. Data (read-only): `tests/eval/text_corpus_v1.jsonl`, `_v2.jsonl`, `_en.jsonl` (labelled spans), the text of the real-document cases listed in `tests/eval/real_manifest.json` that are text-extractable (use the product's own extraction helpers read-only, or `pdftotext`), and `tests/eval/real_results.json` plus `docs/superpowers/en-eval-0910.md` for the list of currently leaked values.
2. Baseline: product detector alone = `tools/eval_text.py` logic (import `Env` from `tests.helpers`, call the detector read-only). Per kind: gold, found, leaked, FP.
3. For each NER model, run on the same texts. Map labels PER/PERSON → PERSON, ORG → ORG, LOC/GPE → CITY/REGION/COUNTRY (coarse). Ignore everything the models cannot know (ids, phones, cards).
4. Compute, per language and per kind:
   - **Rescued leaks**: gold spans the product missed that NER found (the number that matters).
   - **Extra FP**: NER spans that are not gold and the product did not already replace (the cost). Hand-check a sample of 50 to separate real PII from noise.
   - **Disagreements**: spans where NER and product overlap but differ in boundaries or category.
   - Slice by text type: running prose, table cells / short fragments, signatures, headers, code/markup. State where NER is clearly worse.
5. Union simulation: product ∪ NER high-confidence → what would leakage and FP be if NER hits above a confidence threshold are auto-replaced and the rest go to the "uncertain" review list. Sweep the threshold, plot/print the trade-off.
6. Cost: model size on disk, cold start, per-document time, RAM; PyInstaller impact (just size and obvious hidden-import risks; do not build). Licences.
7. Also check that NER does not break the product's core invariant "one entity, one label": run the same entity twice in different sentences and report how often NER gives inconsistent spans.

## Deliverable

`docs/superpowers/ner-experiment.md` with: versions and licences; one table baseline vs each model vs union (rescued, extra FP, net, per language and per kind); the text-type slices; cost table; the 20 most instructive examples (rescued and harmful) with PII replaced by placeholders; and a recommendation in one of three forms: (a) integrate as candidate source into "uncertain" with threshold X, (b) integrate for language Y only, (c) do not integrate, with the reasons. State plainly what is measured and what is not (synthetic vs real, sample sizes). Do not claim a gain that only appears on the synthetic corpora.

## Rules

- Measurement only. If you think a product change is needed, write it as a suggestion in the report.
- No network use except the approved installs.
- Do not touch the shared venvs. Do not leave large model files inside the repo or commit them; commit only the new tool and the report on branch `exp/ner`.
- Finish with a short summary: what you ran, the key numbers, the recommendation, and what remains unmeasured.
