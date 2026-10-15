# S9A report (12 MB txt speed, identical output) -- target NOT met
Branch ws/s9a. Machine load 14-56 throughout (unrelated processes); base = `git archive` of the pre-change tree in /tmp/s9a/base, runs back-to-back.

## Changes (all output-identical)
1. detectors._ner_findings.make: `inside` / `weak` lookups were a scan over all PERSON / POSSIBLE_PERSON findings per NER span (quadratic; 6 s tottime of 70 s in a cProfile of 2 MB). Now bisect over (start, original index) lists; original list order and first-match semantics kept. Local to `_ner_findings` only (S9C merge: small hunk at the top of that function plus the two lookups inside `make`).
2. en_rules.org_spans: per-line part split into pure `_org_line_spans(line)` with a bounded line cache (lines <= 400 chars, 20000 entries); rest (`_org_rest`) unchanged. Verified: org_spans hash identical on corpora v1/v2/en (+ concatenation, called twice).
3. entities.country_hits: capitalised words that cannot start any country phrase (fold / normal forms not among first elements of the phrase keys) skip the phrase probing; superset condition, so no match can be lost. country_hits hash identical on corpora.

## Identity
- tools/s7a_proof.py fp (31 fixtures incl. 12 MB big12_rep, 3 MB big3_var): 0 mismatches vs base (output sha + findings sha + count).
- tools/s6d_bench.py txt (12 MB): hash a98a2d5a... identical base/new.
- tools/s8b_proof.py fp: ner.py untouched. Base archive lacks tests/eval/real, so only prose3mb and table1mb are comparable base-vs-new (identical); the 20 real-doc fixtures ran on the new tree only.

## Numbers (12 MB, s6d_bench txt)
| | wall | user CPU | max RSS | load before/after |
|---|---|---|---|---|
| base | 195 s | 178.1 s | 0.91 GB | 55.8 / 14.5 |
| new  | 207 s | 179.5 s | 0.58 GB | 14.5 / 18.3 |
3 MB rep (s7a_proof bench), load ~28: base user 48.1 s, new 45.5 s (-5 %, noisy).
Conclusion: no measurable gain at 12 MB (user-CPU within noise). The 60 s target is NOT reached; current figure is ~180 s user CPU, ~3x off. RSS < 2 GB holds.

## Dropped / not attempted (could not prove identical or too costly)
- Skipping the whole-output verify pass: matches depend on replaced neighbouring text (S7A conclusion stands); `_rule_findings` also mutates known_ids/known_secrets.
- Two-process chunking: harvest/learn state (people index, entities, known ids) flows chunk to chunk; not provably identical.
- NER chunk memo/skip: S8B already skips windows without capitalised Cyrillic words and caches windows; remainder is tokenisation/CNN/CRF.
- Raw regex cost is only ~1.0 s per 400 KB chunk (measured per rule: top rules EN_NAME label rules ~0.1 s each); the cost is spread across many small per-match and per-token Python passes (explicit_spans ~11 s/2 MB, _unknown_names 3 s, _siblings 2.5 s), none with a single provable shortcut.
Tests: unittest test_ws_s7a, test_ws_ner, test_ws_s8b, test_ws_s8a, test_ws_en2/3/4, test_ws_detect_en, test_round4_countries_names, test_round3_orgs_geo: 131 OK.
