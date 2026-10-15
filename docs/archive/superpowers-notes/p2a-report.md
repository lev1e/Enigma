# P2A report: Office edit engine (branch ws/p2a)

Files: anonymizer/docedit.py (public API), docedit_core.py (zip/XML package, limits, label guard), docedit_pptx.py, docedit_docx.py, docedit_xlsx.py; tests/test_ws_p2a.py.

## API
- `outline(data, name, opts=None, *, text=None|"stub", selected=None, neighbours=1) -> dict` containers (slides / body+headers+footers / sheets) with elements: addr, kind, role, text, fp, style, geom (pptx, pt), editable, flags, label for non-editable. `selected` returns a budget slice (selected + neighbours, other containers summary only).
- `apply_patch(data, name, patch, opts=None) -> (new_bytes, report)`; raises `PatchRejected(code, text, op_index, at)` (`.report()`), nothing partial. Patch is a dict or JSON string `{"v":1,"ops":[...]}`.
- `diff_summary(old, new, patch, name) -> {"items":[{text: "... было «..» -> стало «..»"}], "preview_hint":{"addresses","containers"}}`.
- `Opts`: max_ops 200, max_growth 0.30 (+ growth_floor 40 chars/op), max_text, max_total_insert, safe_fonts, known_labels, limits for size/width.

## Addresses (slide, h, f, t, 1-based; p, r, c 0-based)
pptx `s3.sh2.p1`, group child `s3.sh7/sh2.p0`, table `s3.sh9.r1.c2.p0`, notes `s3.notes.p0`; docx `p12`, `t2`, `t2.r1.c3.p0`, `h1.p0`, `f1.p0`; xlsx `Sheet1!B4`.

## Ops
| op | pptx | docx | xlsx |
|---|---|---|---|
| replace_text (expect fp) | yes | yes | text cells |
| insert_paragraph / delete (paragraph; pptx also text shape) | yes | yes | no |
| comment (report only) | yes | yes | yes |
| set_style (font from doc/theme, size, bold, italic, colour, alignment, spacing) | yes | yes | no |
| move_shape / resize_shape / align / set_layout | yes | no | no |
| col_width | table | table | column(s) |
| paragraph_style | no | yes | no |
| set_cell value/formula | no | no | yes (formula string, calcChain dropped, fullCalcOnLoad) |
| number_format | no | no | yes |

Rejections (whole patch): unknown address/op/keys, stale fp, label removed/unknown/loose, growth, size, text too long, control chars, out of bounds, font not allowed, unknown layout/style, non-editable, too many ops, duplicate address, last paragraph, reopen failure.

## Decisions
- replace_text keeps the first run's rPr and drops the other runs (deterministic, no merging of mixed formatting); runs with images/footnotes in docx are kept.
- Labels: every label of the old text must stay, new ones must already exist in the file (or opts.known_labels); delete is the only way to drop them.
- Non-editable: images, charts, SmartArt, OLE, video, WordArt, connectors, fields, tracked changes, equations, content controls, shared/array formulas.

## Not done
Real docx/pptx/xlsx comments (kept in report only), distribute, set_theme_color, apply_style_to_all, xlsx cell_style/conditional formats, header/footer tables, docx table style, finance-record/numeric-mark xlsx rules, charts. Not verified in real Office. Large sheets: cell neighbours in outline budget are by list order, not row window.
