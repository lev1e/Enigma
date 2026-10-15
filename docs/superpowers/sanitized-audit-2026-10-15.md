# Sanitized repository audit — 15 October 2026

Scope: read-only audit of the separate GitHub copy at its existing commit `ca1c7056416d7c0df1dcd21d210df4d0499ed146`, compared with original `main` at `bd7ebe0`. No network, package installation, tests, builds, or changes to that copy were performed by this workstream. No private source terms or customer snippets are included here.

## Findings requiring action

1. **Stale test baseline in the copy:** `tests/test_ws_p2d.py` expects 102 buttons; original main expects 104 following the add-in install/remove controls. The product HTML is identical in both repositories. Restore the current 104-control assertion and its explanation.
2. **Sanitization weakened a secret assertion:** `tests/test_text_audit.py` substitutes a synthetic API-key fixture but its negative assertion still searches for a fragment of the previous fixture. Update the assertion to test the replacement key. `tests/test_entities.py` also lost its multiword filename example; use a fictional multiword filename to retain the original coverage. A reviewable three-file patch is available to the coordinator outside both repositories.
3. **Non-neutral Office author metadata:** `docs/Enigma_instruction.docx` retains non-neutral values in `docProps/core.xml` creator and lastModifiedBy. Neither value is reproduced here. Replace both with Enigma in the sanitized copy, preserving the document content and ZIP entries. The document has 22 archive entries, no embedded media and no embedded Office objects. Its XML has no matches against the private comparison values.
4. **Unreachable Git objects:** `git rev-list --all --count` returns 1, but `git fsck --full --no-reflogs --unreachable` finds 3 unreachable commits and additional trees/blobs. The directory is therefore not a pristine one-commit object database. This does not establish that the original repository history was copied or published. Preserve a private backup outside the sanitized folder, record reachable refs, expire reflogs and prune unreachable objects locally; confirm the same reachable refs/commit and a clean fsck afterward. No reachable-history rewrite is needed. Do not publish the original repository or copy its `.git` directory.

## Verified inventory and separation

- `git ls-files`: original 907 files, sanitized 824 files; no added tracked paths. The 83 removals comprise 82 archived screenshots and the former hygiene report.
- There are 31 changed shared tracked files, concentrated in working notes, reports, fixtures and developer tools. Every tracked file under `anonymizer/` is byte-identical to original main, including AI adapters, chat pipeline, restore, OCR, Office integration and web assets. This establishes source parity, not runtime correctness.
- Sanitized reachable author/committer identity is Enigma with the configured noreply address. Local main, origin/main and the existing v2.3.0 tag are present. Remote-tracking refs are local metadata and do not prove the current remote state; no remote access was made.
- The sanitized tracked tree contains no `case/` files, device keys, vault binaries or local virtual environments. Owner home-path comparison found 0 matches, including XML archive members.
- Existing `.gitignore` excludes case data, credentials, build outputs, local environments and Office.js vendor downloads. An ignored `.DS_Store` exists locally; directory-level distribution must use tracked-content export rather than copying all files.

## Privacy checks and limits

The authorized scanner loaded values from the two explicitly allowed private JSON manifests programmatically. It neither enumerated private case contents nor printed terms/snippets. Deduplication and the required minimum length produced 37 comparison values. Tracked files and unpacked Office/XML members were scanned; the 10 values matching tracked text consist of 9 entries also in the shipped geography dictionary and 1 appearing only in public open-source author fixtures. No customer-specific match was confirmed. A common-word match is not evidence of a private-data leak; this check is also not proof against unknown names absent from the manifests.

Secret-shape matches were confined to test/evaluation fixtures and synthetic corpus generators. No matching production credential was identified. Public-source author email addresses remain in source-corpus files (including Django and Requests authors); OCR/test examples also contain synthetic email targets. These must not be described as zero personal-data occurrences. The prior cleanup intentionally redacts report addresses, while preserving the public-source evaluation inputs.

Archive inventory: 34 DOCX, 33 XLSX, 25 PPTX, 12 PDF, 11 PNG and 4 JPEG tracked files. The known malformed XLSX evaluation fixture `tests/eval/failures/poi_xlsx_9/input.xlsx` cannot be opened as a ZIP; its raw bytes were scanned, and its deliberately malformed status must remain intact. All 12 PDFs were opened for text/metadata comparison: zero private-manifest value matches and zero embedded attachments. Five PDFs contain image-only pages, so text extraction alone would not inspect their visual content.

Visual review covered the four retained JPEG corpus pages and the remaining image-only Russian PDF page. They contain public-source imagery plus generated evaluation overlays; one public specimen includes a face and identity-document layout, and the Russian scan is a historical public election notice. They are evaluation inputs, not application screenshots or private case exports. The four corresponding JPEG-as-PDF fixtures refer to the same evaluation cases. Public-source privacy/licensing obligations still apply independently of customer-data removal; retain provenance and the existing release licence decisions.

## Completion boundary

No product-code regression caused by sanitizing was found by source comparison. The concrete fixture and metadata issues above should be fixed before the coordinator's targeted sanitized-copy tests. Runtime verification, updated commits from other workstreams, final build validation and any publication remain the coordinator's responsibility. No tests were added or run in this read-only audit, and no claim about provider connectivity or real Office execution is made.

## Follow-up verification after coordinator fixes

This section supersedes the corresponding outstanding findings above. The coordinator applied the three-file fixture patch, neutralized the two DOCX author fields and synchronized the reviewed implementation fixes from original main. A second read-only privacy scan included both tracked and nonignored untracked files, rather than relying only on the committed tree.

The reusable local scanner is `/tmp/anonymizer_privacy_scan.py`; run it with the original checkout's approved Python environment. It reads only the two authorized private manifests and emits repository-relative paths and counts, with no terms, snippets or raw metadata values. It does not modify either checkout or contact a remote service.

Verified results on the updated sanitized working tree:

- 831 tracked/nonignored untracked files scanned, including the newly added source, tests and report.
- All 82 product paths under `anonymizer/` are byte-identical to the current original working tree; zero missing or extra product paths.
- Both instruction-document author fields now equal Enigma. The coordinator additionally confirmed that every other ZIP entry remained byte-identical.
- The synthetic API-key prefix occurs twice, in the fixture and its assertion; the old assertion fragment occurs zero times. The fictional multiword filename occurs twice, and the current 104-button assertion occurs once. These checks establish the patch content, not test execution.
- Private comparison remains 37 distinct values, 10 matching values: 9 in the public geography dictionary and 1 confined to public-author fixtures. No new customer-specific match was identified.
- Owner home-path matches remain zero. Secret-shape matches remain limited to synthetic evaluation inputs and generators; decompressed PDF text adds the expected synthetic-key match in one PDF fixture.
- The same intentionally malformed XLSX is the only archive/PDF parsing limitation. It was still scanned as raw bytes.

Git cleanup remains the coordinator's responsibility. Because the existing reachable root commit still contains the former DOCX author metadata, pruning unreachable objects alone would not remove that metadata from reachable history. The coordinator now plans to back up the existing sanitized `.git` directory privately outside both repositories and create a fresh single-root sanitized repository from the verified final tree, with no tags or push. This supersedes the earlier suggestion to preserve the old root while only pruning unreachable objects. Final tests, build results and verification of that new root are still pending at this audit checkpoint.

## Final coordinator verification

This section supersedes pending completion items above. The final tracked/nonignored tree contains 839 files. The authorized scanner still finds 37 comparison values, with the same 10 matching values (9 geography entries and 1 public-author fixture value); no customer-specific match was confirmed. Owner home paths: zero. Secret-shaped strings remain confined to synthetic test/evaluation fixtures and their generators. The only archive limit is the intentional malformed XLSX fixture already described. Both instruction-document author fields are Enigma.

All 82 product paths are byte-identical between the original and sanitized checkouts, with zero missing/extra paths. Targeted sanitized suite: 184 tests OK. Final full sanitized suite: 1808 tests OK in 410.705 seconds, 15 skips (13 absent private-case checks, 2 opt-in performance checks). The private regressions ran only in the original: 13 OK, one existing missing-input skip. Original E2E ran alone and last, without screenshots: first run 178/178, restart restoration OK.

All seven quality-gate sections were verified against the unchanged baseline. The first full run exposed two measurement-tool defects, not accepted regressions: shared-corpus original text used the checkout-local path, and triage mixed historical rows into the pinned sample. Both were fixed and covered by regression tests. Repeating just real/triage passed: 16 cases, 626 gold, zero leaks/refusals/crashes, restore 16/16, triage FP 28. The previously passing text/noise/images sections were not redundantly repeated. Historical text misses (RU v1 leak 1, EN leak 2) remain explicitly recorded. Seven additional problematic public PDFs all open and restore their content with zero leaks.

Final macOS artifact checks passed: strict ad hoc codesign, frozen selfcheck 8/8 including NER, Ed25519 update signature, three bundled vendor hashes and licences, Office.js plus licence, notices, model weights, hdiutil DMG checksum and SHA256SUMS. Native Office remains unverified after three -1712 timeouts. Windows artifacts and remote CI were not run or published.

The former sanitized Git directory is backed up privately outside both repositories. The final sanitized Git database has one parentless Enigma root commit, no tags, remotes or unreachable objects; original Git history remains separate and unchanged. Working trees are committed locally. No push, tag, upload, remote workflow, installation or download was performed. Runtime checks are complete; only external verification and owner release/licensing decisions remain as listed in `status-2026-10-15.md`.
