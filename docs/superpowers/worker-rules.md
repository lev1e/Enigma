# Worker rules (all workstreams)
- Read first: docs/archive/superpowers-notes/prompt-orchestrator.md sections 1, 1b, 6; docs/superpowers/queue.md; status-2026-10-12.md; ARCHITECTURE.md, SECURITY.md; your workstream text in prompt-orchestrator.md section 4.
- Python: `.venv312/bin/python` by absolute path of the MAIN checkout's venv (<repo>/Downloads/Anonymizer-1.0.0-Windows-build-kit 2/.venv312/bin/python). Never write into .venv312/bin.
- Work only in your own worktree and branch; edit only files you own; new tests go in your own new test file. If you need a change in a file you do not own, write it to docs/superpowers/requests-<ws>.md and continue.
- Run TARGETED tests only (your test file plus the tests of modules you touched). Do NOT run the full suite, tools/e2e_window.py, or full eval_real runs unless your brief says so; the orchestrator runs integration. Machine is shared: at most `--jobs 2`.
- `case/` is private customer data: never read into docs/tests, never commit, never send anywhere.
- No downloads or package installs. If you need one, stop and report name, source, size, licence.
- Fail closed everywhere. Every claim carries a number from a named tool on a named corpus. Never write "100%" except for a literal gate result.
- Commit on your branch with clear messages. Final report (short): branch, commit hashes, files changed, tests added, before/after numbers, unverified items, open requests to other workstreams. Append a status line to docs/superpowers/queue.md notes in your own worktree only (orchestrator merges).
