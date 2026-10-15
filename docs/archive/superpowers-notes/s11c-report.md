# S11C report: vendored libraries and preview panel integration (branch ws/s11c)

## Vendoring
9 files from the approved list downloaded once (curl), committed in `anonymizer/web/vendor/` (whole `anonymizer/web` is already in the PyInstaller `datas`, so they ship). All byte sizes and SHA-256 match the research table. For the 6 npm packages the registry tarball integrity (sha512) was recomputed and each vendored file is byte-identical to the tarball copy; SheetJS from cdn.sheetjs.com, its LICENSE sha256 matches. PapaParse skipped. Only one theme CSS was approved, so no highlight.js theme is shipped: token colours are styled with the app's own CSS variables. Licences in `vendor/licenses/`, `vendor/MANIFEST.json`, `THIRD_PARTY_NOTICES.md` (holders taken from the real LICENSE files / file headers). Added file bytes: 2,390,750 (9 JS) + licence texts. Served by a new `/vendor/<name>` route (session cookie required, strict name regex, `.js/.mjs` as text/javascript, others 404).

## Per library
| Library | Integrated | Why |
|---|---|---|
| DOMPurify | Yes | Only route for markup into the panel (forbids img, iframe, form, style, svg, href, src, srcset, target). |
| marked | Yes | `.md` rendered; placeholders re-chipped through private-use sentinels; raw `<script>`/`<img onerror>` stripped; links lose href (dotted, not clickable). |
| highlight.js | Yes | json/xml/html/svg/yaml/ini/sql in the text view, per line, so line numbers and chips stay; falls back to plain text on error. `.log`/`.txt` not highlighted (no gain). |
| SheetJS | No, better done server-side | Browser would need raw file bytes (new endpoint), loses placeholder marks and parses hostile files in the page. Instead `preview.py` now returns all sheets (first 12, 100 rows each) and the UI shows sheet tabs (arrow keys). Merged cells: shown as plain grid (not exercised beyond file creation). |
| docx-preview + jszip | No | Needs raw bytes endpoint; chips would have to be reconstructed in a rendered layout tree. Current server-side docx blocks keep chips and stay safe. Follow-up: `/raw` endpoint for the anonymized copy plus text-node chipping. |
| pdf.js | No | Same raw-bytes requirement; canvas pages would show placeholders as pixels either way. Gain would be zoom and selectable text only. Files stay vendored; test guards workerSrc/isEvalSupported if integrated later. |
| Split.js | No | Shell is a 5-column CSS grid with a pref-remembered width; Split.js sizes sibling flex/width elements, so it would require restructuring the shell. Left for a layout task. |

## Checks
| Item | Result |
|---|---|
| tests/test_ws_s11c.py (9: hashes/sizes, no unlisted code, no fetch targets, page local-only, MIME, auth, traversal, xlsx sheets, DOMPurify-only) | PASS |
| s11a, s10a, w13a, w12b, chat_ux_page, webapp, s6e, desktop (130 run) | 1 failure: SelfCheck (known, no office vendor in worktree) |
| Vendored JS absolute URLs | 130+ found, all XML namespaces or licence comments; no `fetch/XMLHttpRequest/import` to http(s) |
| Browser: md with script, img onerror, external link: chips 3, 0 script/img/a[href], title unchanged | PASS |
| Browser: json 18 and yaml 8 hljs spans, chips kept | PASS |
| Browser: xlsx 3 sheets, tab 2 shows 100 of 151 rows | PASS |
| Browser 390 light: no horizontal scroll (390/390) | PASS |
| Network: all requests to 127.0.0.1 only (evil.example image never requested) | PASS |
| 1440 light, dark at 390, keyboard walk of sheet tabs by hand, docx/pdf in browser | NOT DONE |

Shots in `docs/archive/shots/shots-s11c/` (3, pane crops at scale 0.5).
