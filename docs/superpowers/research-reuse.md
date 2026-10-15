# S11B research: reusable components for chat UI + right preview panel

Checked 2026-10-14 against the npm registry, jsDelivr and GitHub API. Nothing downloaded into the repo. Sizes are minified bytes; SHA-256 values were computed by me from the CDN files (upstream publishes none, so verify against the npm tarball integrity at vendoring time). All runtime vendored under `anonymizer/web/vendor/`, no CDN, no network calls; load via local `<script>`/`import` only. Do not use the old `/xlsx` npm 0.18.5 (see SheetJS).

## Shortlist (TAKE = recommend, SKIP = not worth it)

| Component | Ver | SPDX | Verdict | What / size | Replaces | Notes |
|---|---|---|---|---|---|---|
| **pdf.js** `mozilla/pdf.js` (npm `pdfjs-dist`) | 6.4.299 | Apache-2.0 | TAKE | `build/pdf.min.mjs` 458,904 B + `build/pdf.worker.min.mjs` 1,264,342 B (~1.7 MB; plus `cmaps/` + `standard_fonts/` only if scanned/CJK PDFs are needed: skip for RU/EN) | any current PDF iframe/`<embed>` | Canvas render, `isEvalSupported:false`, no scripting, no network. Set `workerSrc` to local file. Cyrillic text layer fine (font embedded in PDF; non-embedded fonts fall back to system). Risk: low-medium (ESM worker + CSP `worker-src 'self'`). |
| **docx-preview** `VolodymyrBaydalka/docxjs` | 0.4.1 | Apache-2.0 | TAKE | `dist/docx-preview.min.js` 75,527 B + **jszip** 3.10.2 `dist/jszip.min.js` 97,781 B (use under MIT, dual MIT/GPL-3) | hand-made docx text extraction | High-fidelity layout, Cyrillic OK, offline. Renders into a node: feed through nothing but our own container, disable `renderAltChunks`, no scripts executed; still wrap in sandboxed shadow root/iframe. Small, single maintainer: medium risk. |
| mammoth.js | 1.13.0 | BSD-2-Clause | SKIP (fallback) | `mammoth.browser.min.js` 405,060 B | n/a | Semantic HTML, drops layout, 5x bigger than docx-preview. Keep as fallback only if docx-preview fails on a corpus. |
| **SheetJS CE** `SheetJS/sheetjs` | **0.20.3** (cdn.sheetjs.com, NOT npm) | Apache-2.0 (LICENSE 11,355 B) | TAKE | `xlsx.mini.min.js` 279,523 B (reads xlsx/xls/csv, enough) | none today / ad hoc table preview | npm `xlsx` is frozen at 0.18.5 and has known CVEs (prototype pollution CVE-2023-30533, ReDoS CVE-2024-22363); fixed only in 0.20.x from SheetJS CDN tarball. Vendor the tarball file, not a runtime fetch. Use `sheet_to_html` through DOMPurify or build the table with `textContent`. Treat files as hostile input (parse in a Worker, size cap). Medium risk. |
| exceljs / read-excel-file | 4.4.0 / 9.3.12 | MIT | SKIP | 21.8 MB / 2.7 MB unpacked, Node-oriented | n/a | Bigger, no gain for read-only. |
| **PapaParse** | 5.7.0 | MIT | TAKE (optional) | `papaparse.min.js` 18,874 B | csv parsing | Only if csv must be streamed/typed; SheetJS can also read csv. Low risk. |
| **marked** | 18.1.1 | MIT | TAKE | `lib/marked.umd.js` 47,956 B | custom md renderer | Small, fast, no deps. Output is NOT sanitised: always pipe through DOMPurify. Alt markdown-it 14.1.0 (MIT, `dist/markdown-it.min.js` 123,618 B): SKIP. |
| **DOMPurify** | 3.4.17 | MPL-2.0 OR Apache-2.0 (choose Apache-2.0) | TAKE (mandatory) | `dist/purify.min.js` 29,828 B | ad hoc escaping | Sanitise every HTML we inject (md, xlsx html, docx fallback). Config: `FORBID_TAGS:[style,form]`, `ALLOWED_URI_REGEXP` no `http(s)`, `FORBID_ATTR:[srcset]` to stop remote image loads (privacy). Low risk. |
| **highlight.js** | 11.12.0 (npm); prebuilt bundle 11.11.1 from `highlightjs/cdn-release` 127,496 B | BSD-3-Clause | TAKE | custom build with ~10 langs (json, xml, md, yaml, py, js, sql, ini, diff, plaintext) ~35-50 KB, or ship the 127 KB common bundle + one theme CSS | plain `<pre>` | Escapes input, no network. Cyrillic in code is just text. Prism 1.30.0 (MIT, 58,240 B core): SKIP, hljs autodetect is better. Low risk. |
| **Split.js** | 1.6.5 | MIT | TAKE | `dist/split.min.js` 6,769 B | custom drag-resize panel | Dependency-free, gutter styling ours. Remember keyboard resize and ARIA on gutter ourselves. Low risk. |

## Chat UI projects (logic/ideas only)

- **Open WebUI**: "Open WebUI License" (BSD-3-based, since 0.6.6 adds a branding clause: may not remove or alter name, logo or identifiers except for <=50 users in 30 days or by written permission). Not on the OSI list, custom licence: **REJECT, do not copy any code**; looking at behaviour as inspiration is fine, but write our own.
- **LobeChat/LobeHub**: "LobeHub Community License" = Apache-2.0 plus commercial-use conditions (derivative works need a commercial licence). **REJECT**.
- **LibreChat** (MIT, `danny-avila/LibreChat`): Artifacts side panel (React, Sandpack-based, heavy). Idea only: panel opens on tool/file reference, tabs for code/preview. **SKIP code** (React + CDN-style sandbox, no value for a vanilla UI).
- **assistant-ui** (MIT, 0.15.28): React primitives (composer, thread, auto-scroll). **SKIP**: React only, 2.8 MB, we are vanilla.
- **Chatbot UI** (MIT, `mckaywrigley/chatbot-ui`): Next.js + Supabase; **SKIP**, nothing small to lift.
- **Vercel ai-chatbot** (Apache-2.0 per LICENSE text; GitHub shows NOASSERTION): its Artifacts panel (resizable right pane, version history, "document" kinds) is the closest model. **IDEAS ONLY**: React/Next, cloud-bound. If any file is ever copied, keep Apache notice.

## Approve this download list (all go into `anonymizer/web/vendor/`)

| File | Source URL | Bytes | SHA-256 |
|---|---|---|---|
| pdf.min.mjs | cdn.jsdelivr.net/npm/pdfjs-dist@6.4.299/build/pdf.min.mjs | 458,904 | 57456c8e0c81e46be31174b499ef77f2b9f5ee46d04412ba627320a36755d4c2 |
| pdf.worker.min.mjs | .../pdfjs-dist@6.4.299/build/pdf.worker.min.mjs | 1,264,342 | 9536359f1b8367850d485731ca1d5e45c159a7b7a0912325e539937aa21ceb18 |
| docx-preview.min.js | .../docx-preview@0.4.1/dist/docx-preview.min.js | 75,527 | c4a133c65a112799e35b143c572dfff9e923a3bf39b5fd3b07a06aa0f8f530c2 |
| jszip.min.js | .../jszip@3.10.2/dist/jszip.min.js | 97,781 | 7f839b2d4688b845c105ebf5d2f9803075f91ea0fe72bdaac176c3a04dd3d2c1 |
| xlsx.mini.min.js | cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.mini.min.js | 279,523 | 0cb353f830d7288385492c83d277b058ddeac664ca51cf1393aa1fd3e2b70939 |
| marked.umd.js | .../marked@18.1.1/lib/marked.umd.js | 47,956 | b82b9334406d8bdd16b6236c08de1cb65b2a859873ca9503d9cc0b292ca3c12a |
| purify.min.js | .../dompurify@3.4.17/dist/purify.min.js | 29,828 | cd37898f9782adf54820c413191b5691803f0f137c799d6edcfd38523b4c2c31 |
| highlight.min.js | cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.11.1/build/highlight.min.js | 127,496 | c4a399dd6f488bc97a3546e3476747b3e714c99c57b9473154c6fb8d259b9381 |
| split.min.js | .../split.js@1.6.5/dist/split.min.js | 6,769 | c32bd277fed98cd8a04033d4eef37201d9b50886189b4bb4d099d133feaf16dc |
| papaparse.min.js (optional) | .../papaparse@5.7.0/papaparse.min.js | 18,874 | 4d5d2d6e3282b66aafaa5e6de8ca3ae06f8d3440111ae99c6a30f6c00cfac33e |

Total about 2.4 MB (2.4 MB incl. optional). Plus one highlight.js theme CSS (a few KB, from the same repo).
SheetJS LICENSE (sha256 4d2a38ac35cda06a555c84074a819d413339cd3691b822cae50f8f322fe01f64) at cdn.sheetjs.com/xlsx-0.20.3/package/LICENSE.
Process notes: fetch once on a dev machine, verify against npm `dist.integrity` (jsDelivr npm files equal tarball contents), commit with a `vendor/MANIFEST.json`, add a test that fails if the web UI references any `http(s)://` script/style URL, and set CSP `default-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self'`.

Licence files to ship: Apache-2.0 text (pdf.js, docx-preview, SheetJS, DOMPurify) with each project's NOTICE/copyright line; MIT texts (jszip, marked, split.js, papaparse); BSD-3-Clause (highlight.js). Use the exact `LICENSE` file from each upstream tag in `THIRD_PARTY/licenses/<name>.txt`.

## Proposed THIRD_PARTY notice text

```
Anonymizer bundles the following third-party software. It runs fully offline;
none of these components contact any network.

pdf.js 6.4.299 (c) Mozilla and contributors - Apache License 2.0
docx-preview 0.4.1 (c) Volodymyr Baydalka - Apache License 2.0
SheetJS Community Edition 0.20.3 (c) SheetJS LLC - Apache License 2.0
DOMPurify 3.4.17 (c) Cure53 and contributors - Apache License 2.0 (dual MPL-2.0)
JSZip 3.10.2 (c) Stuart Knightley and contributors - MIT License (dual MIT/GPL-3.0, MIT elected)
marked 18.1.1 (c) MarkedJS contributors - MIT License
Split.js 1.6.5 (c) Nathan Cahill - MIT License
PapaParse 5.7.0 (c) Matthew Holt - MIT License
highlight.js 11.11.1 (c) Ivan Sagalaev and contributors - BSD 3-Clause License

Full licence texts are in THIRD_PARTY/licenses/. Open WebUI and LobeChat code is not used.
```

## Recommendation summary

Take: pdf.js, docx-preview(+jszip), SheetJS CE 0.20.3 mini, marked, DOMPurify, highlight.js, Split.js, (PapaParse optional). Skip: mammoth, markdown-it, Prism, exceljs, assistant-ui, Chatbot UI, LibreChat code. Reject: Open WebUI, LobeChat. Use Vercel ai-chatbot and LibreChat only as UX references for the artifacts-style panel. Open question for owner: confirm the copyright holder names above against each upstream LICENSE when vendoring (I did not read every file).
