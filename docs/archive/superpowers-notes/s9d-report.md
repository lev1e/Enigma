# S9D report: Office add-in pane design pass
Branch ws/s9d. Files: anonymizer/addin_web/{taskpane.css,taskpane.html,taskpane.js}, tests/test_addin_design_s9d.py, docs/archive/superpowers-notes/requests-s9d.md.

## Changed
- taskpane.css: old beige/terracotta hex palette and serif headings removed. The :root, dark `prefers-color-scheme` and `[data-theme="dark"]` token blocks are copied verbatim from anonymizer/web/index.html (OKLCH cool palette, one blue accent). Pill buttons, flat tinted rows instead of bordered cards, 44px controls, all text >= 14px, `scrollbar-gutter: stable`, reduced-motion respected. No side stripes, no gradient text.
- Alerts shown before a run (loaded from `/api/state`): name-model note (ner_available false; wording from the main app) and "Менее безопасный режим" image warning (image_mode_unsafe, wording identical to Settings in the main app, warn-tinted full border).
- Kept-pixels warning: the backend text (imagereplace.warn_kept_pixels) arrives as a job warn message and is shown in the result. Info-level job messages (the natasha unavailable note, NER skip notes) were previously dropped by the pane; they are now shown as muted rows. The title "Есть замечания" still counts only warn/error.
- Settings link: two buttons ("Изменить в настройках программы", "Все настройки в программе") POST `/api/addin/open-app` with `settings:true`. The add-in server serves no settings page (main app is another server), so this currently focuses the main window and the pane says where Settings is. See requests-s9d.md.

## Measured (Chrome devtools emulation, fake_office + dev_addin_server, synthetic docx)
- 320/380/420 px: scrollWidth == clientWidth (no horizontal scroll); no interactive element under 44px high; no text under 14px (checked by script); result state at 320 also clean.
## Screenshots (docs/archive/shots/shots-s9d/)
pane-320-light, pane-320-dark, pane-380-light, pane-380-dark, pane-420-light, pane-420-dark (ready state with name-model note and image warning), pane-320-light-result (after anonymize).
## Tests
tests/test_addin_design_s9d.py (5) + existing add-in tests: 106 OK (unittest).
## UNVERIFIED
Real Word/Excel/PowerPoint on Windows/Mac (task pane chrome, WebView2/Edge vs WKWebView rendering, Office light/dark theme interplay, real side-panel width); the settings link opening the settings dialog (needs addin.py change); kept-pixels warning with a real image document (text path verified in code only); focus-ring look under keyboard navigation (CSS rule present, not screenshotted); narrow dark result state.
