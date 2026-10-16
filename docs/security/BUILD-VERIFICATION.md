# Native build verification

The owner authorized publishing the remediation branch and native Windows verification through GitHub Actions with unit tests and installer smoke checks enabled. Existing release assets and tags are not replaced by these verification runs.

## Build preflight

The original packaging-version test incorrectly rejected the pinned Tesseract dependency version. It now masks only the explicit four-part `choco install tesseract --version=` argument; added negative cases prove stale application versions remain rejected even on the same line. The dependency remains pinned. All 23 targeted packaging and security tests passed locally on Python 3.12.15.

Windows builds use `publish=false` and `run_tests=true`; results are recorded after completion. Local macOS arm64 builds use the existing release build and frozen-selfcheck functions, including native helper compilation, ad hoc code signing and signature verification. No release-version bump or replacement of existing v2.3.0 artifacts is part of build verification.

## OCR correction discovered by cross-platform verification

Prior Linux CI exposed a genuine Tesseract rotated-scan redaction defect, independently reproduced locally using valid Russian/English models and TSV configuration: internal vertical-text recognition returned word rectangles without direction metadata, while the application interpreted them as horizontal. This could leave a patronymic visible in rotated-image and rotated-page output. Tesseract internal vertical detection is now disabled; the application's existing four-orientation passes still recognize rotated content with matching coordinate transforms. The existing image-270/page-90 confidentiality tests reproduce the failure before the change and pass afterward. A regression checks both Tesseract providers retain TSV words/coordinates and request the explicit-rotation configuration.

A separate existing logo consistency test assumed bilingual OCR must read a rendered Latin `Company1` as ASCII; Tesseract reads the correct visible label as Cyrillic lookalikes (`Сотрапу1`). The test now wraps the real renderer, requires a company token to actually be drawn, verifies the exact full token in the text document, checks image bytes changed, and OCR-checks that both original brand words are absent. Rendering is not stubbed and confidentiality assertions are retained. This strengthens exact identity compared with the former stem-only comparison. The forced-Tesseract logo test passed.

The first Windows/PR workflow attempts were canceled when this runtime correction became ready; they do not count as successful verification. Fresh builds and full tests run against the corrected commit. macOS artifacts are rebuilt for source equivalence.

### Complete Tesseract orientation verification

Expanded tests exposed a remaining inverted-sideways case after disabling implicit vertical detection. The final TSV reader also defers tall lines containing multi-character words to the existing explicit rotation passes; it retains narrow single-character fields and ordinary horizontal lines. This prevents directionless words from suppressing correctly transformed words. Automatic page segmentation and column handling remain enabled.

Verified locally with Tesseract 5.5.1, official Russian/English fast models plus the installed TSV configuration, DejaVu fixture fonts and forced selection of Tesseract before importing tests:

- Positive control: 12 source words recognized, all expected sensitive values present, proper 270-degree direction and per-character boxes. Empty OCR output cannot count as a pass.
- All `RotatedScans`, `PdfOcr`, `OfficeImageOcr`, and `TesseractDirections` cases: **14 tests passed** in 56.585 seconds, including rotated-image/page confidentiality, explicit-orientation assertions and exact recovery.
- Corrected logo consistency test with forced Tesseract: **passed**.
- Native Apple Vision `test_pdf_ocr` plus logo regression: **17 tests passed**; additional native rotated checks: **9 passed**.
- A preliminary custom-language setup without `configs/tsv` produced empty parsed words; its results were discarded and are not evidence. All stated forced-provider results use valid TSV output and the positive control.

The intermediate workflow attempts are superseded by verification on the final corrected commit.

### Short and minority rotated text: final recovery hardening

A final review reproduced a regression in the first tall-line guard: a short sideways email such as `a@enigma.ru` could be filtered while the normal 20-character / 35%-of-best orientation thresholds prevented recovery. That intermediate revision is not the final implementation, even though its workflows passed.

Deferred word boxes now travel with each recognition result, without shared mutable provider state. When such boxes exist, nonempty orientation probes receive full recognition even below the ordinary page thresholds, with stronger orientations merged first. A spatial index checks that deferred regions have geometric coverage in recovered words; an unresolved region raises `OcrUnavailable`, and the image pipeline refuses output. Normal pages retain their previous thresholds and behavior.

Final targeted results on this implementation:

- **18 forced-Tesseract tests passed** (129.873 s), including all rotated-scan/PDF/Office-image cases, narrow-field preservation, short/minority email recovery, strongest-orientation precedence, and unresolved-region refusal.
- **36 native-provider tests passed** (146.179 s): complete PDF OCR, logo policy and rotated-scan suites.
- Real short-field comparison with the original runtime confirmed correct recognition of `a@enigma.ru` and `Пароль: abcD9!xy` at both 90 and 270 degrees, with proper direction metadata.
- A service-level regression requires an unresolved vertical region to produce no output image; no privacy assertion or rendering operation is disabled.

Final full tests and native builds are rerun on the corresponding committed source before publication to main.

## Final native macOS verification

Runtime and build source: `628ba4d09af143488298d00059585a80aee56d12`. The OCR source SHA-256 was checked before and after the build: `434515f18068dd15496d7fc9a9f20636b1d499059d40b60c5d5ee4726ad298ff`.

The Apple Silicon app was built with Python 3.12.15 / PyInstaller 6.15.0. Ad hoc signing and `codesign --verify --deep --strict` passed. All eight frozen selfchecks passed twice, including the bundled NER model, server/page, HTTPS add-in, helper/window client and anonymization/recovery. ZIP integrity and DMG checksum verification passed.

| Local artifact | Bytes | SHA-256 |
|---|---:|---|
| `Anonymizer-2.3.0-arm64.zip` | 100064266 | `ccb64e86b8f150a5eaa6860e0e677f3809f2c63c142e38fe8379158b3d769293` |
| `Anonymizer-2.3.0-arm64.dmg` | 107973152 | `1cd0f599fa83782712c435bdfa2791cb1267eee1c67d54b6ecf50ad4f76a265f` |

Artifacts and `SHA256SUMS.txt` are in the ignored local directory `dist/verified-macos/`. Existing release tags/assets are preserved. Real Microsoft Office interaction, Developer ID signing and Apple notarization were not exercised.

## Final Windows and Linux verification records

Both workflows execute the same runtime/build/test source commit `628ba4d09af143488298d00059585a80aee56d12`:

- [Windows native build, full tests, frozen selfcheck and installer smoke](https://github.com/lev1e/Enigma/actions/runs/38919667287), dispatched with `publish=false` and `run_tests=true`.
- [Linux full unit suite and text/noise baseline quality gate](https://github.com/lev1e/Enigma/actions/runs/38919673911).

Both final workflows completed successfully. Windows ran 1,829 tests in 1945.032 seconds with 24 platform/data skips, no failures or errors. Linux ran 1,829 tests in 2175.078 seconds with 22 platform/data skips, no failures or errors; all four text/noise quality gates passed against the unchanged baseline. Earlier successful builds on `afaae46` are superseded by these final-source checks. Documentation-only follow-up commits do not change the verified runtime, tests, dependencies, workflow or packaging inputs.

## Final complete local suite

The complete final-source discovery ran **1,829 tests: 1,826 passed, 3 existing skips, 0 failures, 0 errors**. Exact test-ID multiset parity was checked against standard unittest discovery; all 154 modules/cases are accounted for. The private `case/` fixtures were temporarily linked from the supplied build kit and are not copied or committed. The link is removed after verification.

| Local group | Tests run | Result | Seconds |
|---|---:|---|---:|
| 1 | 472 | passed | 833.375 |
| 2 | 443 | passed, 3 existing skips | 1083.543 |
| 3 | 457 | passed | 1407.737 |
| 4 | 457 | passed | 592.211 |

The skips are the two opt-in heavy-performance cases and one unavailable original private fixture. No test or baseline was weakened or bypassed. Logs are `/tmp/enigma-release-full-shard-{1,2,3,4}.log`; inventory is `/tmp/enigma-release-full-summary.json`. Host disk pressure slowed local verification but did not produce a failed test.

## Verified Windows artifacts

The native Windows build passed the portable frozen selfcheck and the installed-program smoke/selfcheck, including the NER model. The installer-produced executable hash matched the portable build. The workflow uploaded [Anonymizer-Windows](https://github.com/lev1e/Enigma/actions/runs/38919667287/artifacts/12055823299), containing the portable executable, installer and `SHA256SUMS.txt` (209,749,129-byte artifact archive; archive SHA-256 `a25054237e3a601d1770e5d775fe32e42156d096a2a18bb41acde0e3c1365faa`).

| Built file | SHA-256 |
|---|---|
| `Anonymizer.exe` | `d8dc0b6a8ba77358008048c2fc9218bb0400fc6110b2788d8170571ef768a157` |
| `Anonymizer-Setup-2.3.0.exe` | `9e589e1bf4f7228a6750974e944ae176166da0d8dc50184f6955d752d7b30ec2` |

## Publication outcome

The verified runtime/build/test source is commit `628ba4d09af143488298d00059585a80aee56d12`. The final follow-up changes only these security documents; runtime, tests, dependencies, workflows and packaging inputs are unchanged. All original 60 report entries remain individually accounted for. Publication uses [PR #1](https://github.com/lev1e/Enigma/pull/1), preserving commit history and existing release assets.
