# S8B report (NER inference: any size, faster, identical spans)
Branch ws/s8b. Only anonymizer/ner.py inference side, tools/s8b_proof.py, tests/test_ws_s8b.py. Machine load 15-100 (unrelated processes); every before/after is back-to-back (base = `git archive` of the pre-change tree in /tmp/s8b_base) and quotes user-CPU.

## Changes
1. No size skip. MAX_TEXT 400 000 -> 50 000 000 (hard fail-soft): above it person_spans returns [] and records a visible note (`ner.take_notes()`, also logged). Same note when the model is unavailable. `eligible()` counts letters per 1 MB slice (no list of all letters; was GBs at 50 MB).
2. `_chunks` now yields (start, end, own_start, own_end). Clean cut at a sentence/line end: no overlap, as before. When no break exists in the back half of a 20 000-char window: cut at a space, next window starts OVERLAP=400 chars earlier, ownership boundary in the middle of the overlap; a span belongs to the window that owns its start, so overlap duplicates are dropped and a name on the border is seen whole. Offsets are absolute (tested at 7 border shifts). Memory: one window at a time, only the span tuple grows.
3. Speed, all bit-exact:
   - tokenise once per window (was twice: slovnet text_words + my own) and call encoder/process/decoder directly; span->token lookup by bisect (was O(spans x tokens));
   - own Viterbi `_decode` (same adds and argmax as slovnet CRF.decode, no np.indices per step);
   - forward and backward CRF passes run in one lockstep loop on a (2,k,k) stack with preallocated buffers; random-input oracle test vs the old function: max abs diff 0 (n up to 3000);
   - marginals only for windows whose decoded tags contain a PER tag;
   - windows without any capitalised Cyrillic word are skipped (`_clean` could never accept a span there);
   - window cache keyed by blake2b hash of the window text (64 entries): repeated windows/tables are free.
   Dropped/not done: sentence-level batching (changes CRF context, cannot be proven identical); windowed marginals (approximate).
4. Model: loaded once per process under a lock, lazy (import 21 MB RSS, `installed()` does not load), load 0.4 s, +306 MB max RSS on first use (numpy+natasha+navec; the "~250 MB" claim is ~300 MB). Failure -> `_model=False`, note, rules continue.

## Identity proof (tools/s8b_proof.py fp; base vs new, sha of (start,end,conf%.3f) for raw spans and person_spans)
22 fixtures, 0 mismatches: 20 real Russian docs from tests/eval/real (txt, md, tag-stripped html, csv/tsv/json/xml, two md slices; no case/), 3 MB synthetic prose (30 678 raw / 35 160 person spans), 1 MB table-like repeated lines (17 490 / 17 442). Note the base skips >400k in person_spans; the proof lifts MAX_TEXT on both sides to compare.
Caveat: the hard-cut path (no sentence break) intentionally differs from base only at the border (that is the fix); no fixture has such a window.

## Numbers
NER only, 1 MB prose, user-CPU, 3 alternating runs: base 9.4 / 9.7 / 9.1 s, new 5.2 / 5.4 / 5.9 s (-42 %). RSS 0.3-0.4 GB.
End to end 12 MB rep (tools/s7a_proof.py bench rep 12): output hashes identical (19bd6f2c..., bf0bb143..., 207829 findings); base wall 603 s / user 195.4 s (load 34); new wall 289 s / user 172.3 s (load 15); max RSS 0.52 -> 0.60 GB (< 2 GB). User-CPU saving 23 s = 42 % of NER implies NER was ~55 s (28 %) and is now ~32 s (~19 %) of the run (derived, not profiled in the same run). 12 MB at normal load is still not demonstrated; remaining NER cost = razdel tokenisation (~25 %), CNN forward (~22 %), marginals/Viterbi (~35 %).
Gate: quality_gate --only text_v1,text_v2,text_en,noise PASS (v1 678/679 fp 2, v2 111/111 fp 0, EN 798/800 fp 1, noise 0). tests: test_ws_s8b + test_ws_ner 19 OK.

## Open
- requests-s8b.md: someone must call `ner.take_notes()` per job and show the strings (detectors.py hook is S8A's).
- scan units 400k-1.5M chars now get NER; 12 MB path unaffected (400k units).
