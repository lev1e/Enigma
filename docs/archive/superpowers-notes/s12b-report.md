# S12B report: gh_curl_thanks restore=False

Branch ws/s12b. Fix commit: see `git log` (one commit, "Restore: digit before a token-shaped literal ...").

## Root cause
The input (public curl "thanks" txt, dense-injected, 59.5 KB) contains the literal `n0name321 on github`. The relaxed second pass
of `Restorer.matches` (anonymizer/restore.py, RELAXED_TOKEN_RE, lookbehind only `[A-Za-z]`) read `name321` inside it as the placeholder
`Name321`. In this document the vault holds 321+ names, so the lookup succeeded and the literal became a stranger's name
(`n0Chris Carlmar on github`). The strict pass already refuses a digit before a token; the relaxed pass did not.
Only other diff: password/token lines (Secret1/Secret2), removed irreversibly by design (harness masks them).
Leak count was 0 throughout; this is a restore fidelity bug, not a privacy one.

## Bisect (frozen input, restore diff on non-secret lines; probe run in a temporary worktree, removed afterwards)
| rev | date | non-secret diff lines |
|---|---|---|
| cb79e68~1 | 2026-10-08 | 0 (good) |
| cb79e68 "Restore: tolerant second pass" | 2026-10-08 | 2 (first bad) |
| 03e8e25, a9e4db3, b5bd5fd, fdb3fe5, 63e9b00, a0f039a, 1470b17 | 10-08..10-14 | 2 (bad) |

Verdict: regression introduced by cb79e68 (parent is good, direct child bad). The b5bd5fd guards (leading zero, filename context) did not cover a digit before the stem.

## Fix
In `_resolve` (relaxed branch): if the char before the match is a digit, return None, unless the digits end a neighbouring token
(`Inn1Name1` glued tokens still restore; checked with INNER_TOKEN_RE on the preceding 40 chars).

## Tests
tests/test_ws_s12b.py (no private data): digit-glued literals (`n0name1`, `x9Name1`, `0name1`) stay unchanged; `_Name1_`, `a_Name1_b`, `вName1` still restore.
Run: test_ws_s12b + test_ws_restore2 + test_ws_finance_restore + test_tokens + test_chat_tokens: all OK. The test fails without the fix (verified via stash).

## Before / after (tools/eval_real.py run --only gh_curl_thanks)
Before: leaked=0 opens=True restore=False. After: leaked=0 opens=True restore=True. tests/eval/real_results.json restored via git checkout.
Not run: full eval_real, full unit suite (orchestrator integration).
