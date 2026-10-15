# Requests from W7 (NER candidates)

- Settings UI (static/JS, if the screen is not generated from `settings_schema.OPTIONS`): the new option `ner_candidates` is in the schema (section general, advanced). Confirm the screen renders it.
- Optional, for the integrator: ner.py only sees the text of one `scan()` call. Document-wide harvesting (an accepted name found in one paragraph flagged in every other paragraph) needs a hook in `Detector.harvest` to feed accepted NER literals into the entity index with a REVIEW-only flag. Not done to stay inside the thin-hook limit.
- README.md / SECURITY.md: paste the draft paragraphs from `docs/superpowers/ner-integration.md`.
- requirements-build.txt / build_windows.ps1: decide whether natasha (about 36 MB plus numpy 2.x) is installed in the release build.
- `numpy 2.5.4` was pulled into `.venv312` by `pip install natasha==1.6.0`; the orchestrator should re-run the integration suite.
