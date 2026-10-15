# D1 report: docs layout and entry docs

## Moved
- Removed the stray `-v` file (an eval JSON dump with a patient-like test line; junk, tracked).
- `HANDOFF.md` -> `docs/archive/HANDOFF-2.0.md` (no live references).
- 91 notes from `docs/superpowers/` -> `docs/archive/superpowers-notes/`: `prompt-*` and `handoff-*` (except `*-orchestrator-9`), `brief-*`, `requests-*`, `*-report.md`, `p2b-contract.md`.
- `shots-*` directories -> `docs/archive/shots/`.
- References rewritten in 36 files (notes cross-links, `tests/eval/README.md`, `docs/superpowers/worker-rules.md`).
- Stayed in place because code or docs point at them: finance-masking, ner-experiment, entity-coverage, quality-matrix, eval-failures, eval-natural-hits, finance-corpus, release-checklist.

## Added
`docs/README.md` (index), `DEVELOPMENT.md`, `CHANGELOG.md`, `README.md` restructured (no hard-coded version, features, install, licence section, stale 12 MB timing replaced with status-2026-10-14 numbers, duplicate bullet removed).

## Open points
- No `LICENSE` file; the owner must choose a licence. README says "not yet chosen; all rights reserved by the author".
- No git tag `v2.2.0`; CHANGELOG uses commit 7fd4dc4 ("Enigma 2.2.0") as the boundary. The 2.2.0 and 2.1.0 entries rest on commit titles/bodies only.
- Archived screenshots come from owner test documents; review before publishing the repository.
- README limits section is still long; ARCHITECTURE.md and SECURITY.md left to D2.
- `eval_real.py report` still writes quality-matrix/eval-failures/eval-natural-hits into `docs/superpowers/` (unchanged).
