# S6B report: image modes and warnings
- redact_text relabelled "Закрасить текст, картинку оставить (менее безопасно)"; replace stays default and first.
- formats.py OOXML: "Данные на картинках закрашены" was an info notice, now a warn (imagereplace.warn_kept_pixels): images and logos stay visible, review by eye.
- PDF: when a brand is painted and images were replaced whole (or the page has no image objects), warn imagereplace.WARN_VECTOR_LOGO and status REVIEW_REQUIRED. 3-line edit at the end of the PDF transform, no logic change.
- webapp.state(): new field image_mode_unsafe (stored pref == redact_text). Settings warning (role=status, bordered, tinted, bold lead-in) shows a "stored in your settings" sentence.
- index.html already renders warn messages loudly (Замечание.); info stays collapsed.
- Tests: tests/test_ws_s6b.py (5 tests, real pptx/docx/xlsx/pdf). Also tests.test_ws_images (21) pass.
- Browser: settings page checked at 1440 light, 1440 dark; at 390 the whole settings modal already overflows (all rows 451px wide in a 374px modal), pre-existing, not from this change.
- Unverified: PDF vector-logo warn has no test (needs OCR-readable vector logo); redact_text on pdf/png/jpg not tested for warn; 390 dark.
