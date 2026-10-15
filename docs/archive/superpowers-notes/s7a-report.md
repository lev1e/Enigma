# S7A report (12 MB txt speed, identical output)
Branch ws/s7a. Machine load 17-150 during all runs (unrelated system processes); wall time is unreliable, so every comparison is back-to-back base vs worktree in one script (tools/s7a_proof.py bench; /tmp copy of the pre-change tree = "base") and quotes user-CPU too.

## Proof harness
tools/s7a_proof.py `fp OUT.json`: for 31 fixtures records sha256 of the anonymized text (invisible tag stripped) and of the finding list (category,start,end,decision), plus finding count:
20 files (tests/eval/noise + tests/eval/en_corpus/clean; tests/eval/real and case/ not read), corpus v1/v2/en as one txt each, 6 corpus snippets, `big12_rep` (12 MB, corpus v1 repeated; same output hash 19bd6f2c as s6d), `big3_var` (3 MB, v1+v2+en texts with digits randomised: no repeated lines).
Baseline (pre-change) fingerprints: /tmp/s7a/fp_base.json. After each step: `FPCMP IDENTICAL 31` required, otherwise the change is dropped.

## Optimisations (each verified: `FPCMP IDENTICAL 31`, all 31 fixtures incl. the 12 MB txt, output sha 19bd6f2c157797d7, findings sha bf0bb143f7a30682, 207829 findings)
1. normalize fast path (normalize._normalize_fast). Text whose only needs are whitespace runs, single characters with a context-free NFKC form (e.g. "No" sign, ligatures, full-width), dashes and mixed-script words skips the per-character Python walk; the offset map is built from the few edits (array.extend over ranges); homoglyph unification only on word runs that hold both scripts; dashes only at dash positions. Falls back to the old walk on combining marks, invisible chars, or if the substituted text is not NFKC-stable. Micro-bench (one 400 KB chunk, min of 5, base vs worktree back-to-back): normalize 0.18 s -> 0.056 s (3.2x). Verified against the old walk on 300k random strings (text and every to_original(s,e)) and as test in tests/test_ws_s7a.py.
2. fold(): lru_cache (safe, tiny gain).
3. rulefilter (anonymizer/rulefilter.py + 6 lines in detectors._rule_findings): required literals of each regex rule come from the parsed pattern; a rule whose literals are absent from the casefolded chunk is not run. 107 of 129 rules get a filter; 0 violations on 4066 corpus pieces x 129 rules, re.I equivalence checked for every code point (U+0131 dotless i found and handled). Gain depends on how keyword-dense the text is: 76 % of rule x piece pairs skipped on corpus pieces, but only ~7 % rule time on the dense 12 MB fixture (rules 1.02 s -> 0.95 s per 400 KB chunk).
4. TRIED AND DROPPED: org_spans per-line noun prefilter (regex of 119 nouns was 4x slower than the loop it guarded). Reverted.

## Results (load 22-35, wall unreliable; same-script back-to-back)
12 MB rep fixture, load ~22: base wall 400 s / user 221.6 s; worktree wall 328 s / user 202.1 s (user -9 %, wall -18 %). RSS 1.0 GB both (<2 GB). 3 MB var fixture: output identical, user 53 s vs 48-52 s (noisy).
Sparse 100-page PDF (tools/s6d_bench.py pdf): 3.1 s at load 24, hash unchanged (b722fcf6...). Target <= 30 s met.
Quality gate (tools/quality_gate.py --only text_v1,text_v2,text_en,noise): PASS; v1 678/679 fp 2, v2 111/111 fp 0, EN 798/800 fp 1, noise 0.
Target 12 MB <= 60 s at normal load: NOT demonstrated. At the s6d-era normal-load figure of 94 s the saving above projects to roughly 80-85 s; no normal-load run was possible (load never below 17).

## Where the rest of the time is (cProfile, 3 MB rep, tottime/cumtime of 88 s) -- needs files I do not own
- ner.person_spans/_raw_spans (slovnet inference): 22.7 s cum (26 %). Chunks are inferred one by one; no cache for text >= 4000 chars.
- _rule_findings regex scanning: 15 s (17 %); scan + the whole-output verify() pass (~2.6 s/MB of rule regex per pass). Four EN_NAME PERSON keyword rules alone are 0.7 s/MB; they start with a ~150-alternative case-insensitive label group at every word boundary, and an exact speed-up needs a restructure of those rules (detection semantics: out of scope).
- entities.explicit_spans 14.8 s cum (_known_hits, _geo_intros, country_hits, _gazetteer_hits).
- _residuals/verify second full scan: not skipped; matches in the output depend on neighbouring replaced text, so skipping cannot be proven identical.
Requests: docs/archive/superpowers-notes/requests-s7a.md.
