# S12C report: vendor cleanup, preview resize handle, browser verification (branch ws/s12c)

## Removed (unused, per orchestrator decision: no pdf.js / docx-preview / SheetJS integration)
pdf.min.mjs, pdf.worker.min.mjs, docx-preview.min.js, jszip.min.js, xlsx.mini.min.js, split.min.js and licences pdfjs, docx-preview, jszip, sheetjs, split. MANIFEST.json and THIRD_PARTY_NOTICES.md now list only marked, DOMPurify, highlight.js (all three are loaded by `index.html` and used by the preview panel). JS removed: 2,182,846 bytes; licence texts about 66 KB. Remaining vendored JS: 205,280 bytes. No reference to a removed file remains in index.html, ai.html, Anonymizer.spec, webapp.py, preview.py (tests guard this). Historic reports (s11c-report.md, research-reuse.md) still describe the earlier download; they are history, not a shipping claim.

## Added / fixed
- Preview panel resize handle `#split-pv`: role=separator, aria-orientation vertical, aria-controls pv, aria-valuenow/min/max/text, focusable; Left/Right 16 px (Shift 64), Home/End, Enter and double click reset; no Split.js. The existing handle code for sidebar and table pane was generalised to three handles; width is saved in a new pref `preview_width` (vault.py, webapp.py validation 340-640, like the other two). Hidden below 900 px and when the panel is closed.
- Fix (found in browser): on the narrow full-window overlay Tab walked into the page behind the panel and Escape did nothing there. Now the rest of the shell is `inert` while the overlay is open (`pvBackdrop`).
- Fix: focus ring of panel tabs and sheet tabs was clipped by the scroll container (only side bars visible); outline-offset -3px.
- Fix: table headers in the panel broke inside words at 390 px ("Сумм/а", "Менедже/р"); `overflow-wrap: break-word`.
- Tests: tests/test_ws_s12c.py (10: manifest equals script tags and files, licences, notices, removed names not referenced, handle markup, pref, three panel fixes); tests/test_ws_s11c.py adjusted (3 files). Run: s12c, s11c, s11a, chat_ux_page, webapp = 72 OK.

## Checks (synthetic docs only, local server on 127.0.0.1, fake provider)
| Check | Result |
|---|---|
| 1440 light: xlsx, docx (shots 01, 02) | PASS |
| 1440 dark: json, md, pdf (03-05) | PASS |
| 390 dark pdf, 390 light xlsx, scrollWidth 390 = viewport, no panel button under 44 px | PASS (06, 07) |
| 390 dark with xlsx after the fixes | NOT DONE (checked dark pdf before fixes, light xlsx after) |
| docx: heading, paragraph chips, table | PASS |
| pdf: image page 1 of 2, pager | PASS |
| xlsx with merged cells (A1:C1, A5:A6): 3 sheet tabs, renders, no error | PASS, but merges shown as a plain grid (content in first cell, no colspan/rowspan): not fixed |
| md: h1, 0 script, 0 a[href], link dotted | PASS |
| json: 19 hljs spans, placeholders kept | PASS |
| Keyboard at 390: Tab pv tab -> body -> sheet tab -> Close; arrows move/select sheet tabs, Home goes first; Escape closes and focus returns to "Просмотр" | PASS after the inert fix (FAIL before: focus escaped to page behind) |
| Resize handle by keyboard at 1440: 3x Left = +48 px, Home 340, End max, Right -16, double click = default, pref saved (534) | PASS |
| Network: all requests 127.0.0.1 only (list read, 170 entries) | PASS |
| New-version marker after AI edit via fake provider (UI composer): "Новая версия" chip, new file "правка ИИ 2" opened in panel | PASS (08) |
| Resize handle by mouse drag | NOT DONE |
| 1440 light/dark full keyboard walk of the desktop panel (only 390 overlay walked) | NOT DONE |

## Unverified
- Screenshots are 400x250 pane crops (the Browser pane is small), taken at scale 0.5. A frame taken right after a panel open can catch the 300 ms-ish sheet animation (translucent); retaken frames were clean.
- Merged cells, drag resize, desktop focus-ring look by eye.
