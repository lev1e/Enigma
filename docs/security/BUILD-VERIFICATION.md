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
