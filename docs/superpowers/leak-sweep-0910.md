# Leak sweep 09.10

Method: build a real input file, run `Service.anonymize`, unzip/read the real output file and grep every part for each original sensitive value, then `Service.restore` and compare with the input. Tests: `tests/test_ws_leak2.py` (7 tests). Probe scripts were scratch (not committed).

## Fixed this session (verified on real output files)

| Gap | Fix | Evidence |
|---|---|---|
| xlsx numeric cells under INN/Passport/SNILS/Card headers leaked (cell stored as number, `<v>`) | `formats.force_numeric_ids` (called from `learn_package`): numeric cell under an ID header or right of an ID label (`INN | 6547100017`) becomes text for the detector | `NumericXlsx`, `LabelBesideNumber` |
| Excel date serial under "Дата рождения" leaked (`31120`) | same function, only cells with a date style | `NumericXlsx` |
| Restore returned those cells as text, not numbers | invisible U+2060 mark appended to the token text in the anonymized cell; `restore._strip_numeric_marks/_renumber` turns the cell back into `<v>` number. Text-typed digit cells stay text (no mark) | restore equality: value, data_type, number_format identical |
| html table: bare passport/DOB/INN under `<th>` leaked (6 of 6) | `colctx.grids_from_html/learn_html`, hooked in `transform_text_file` | `TableText.test_html_table_header_context` |
| comma csv: INN right after a date (`14.03.1985,770708389312`) leaked (thousand-separator glue) | `colctx.learn_ids` also registers the exact literal in `known_values` | `TableText.test_comma_csv...` |
| `20.10.1974 года рождения` date not detected (found in real-style synthetic contracts, all formats) | new BIRTH_DATE rule in `detectors.py` | `LabelBesideNumber` |
| csv "Month D, YYYY" | already safe when quoted (verified); unquoted comma splits the cell, inherent to csv | probe |

## Per-format matrix (probe: name, INN, passport, DOB, phone, email, city in one file; table variant with header context)

Legend: leaks = original values found in any part of the output (0 = none); restore = restored file equals input (cell/paragraph units for office, text for text formats).

| Format | anonymize leaks | restore equality | metadata | archive parts | temp copies | notes |
|---|---|---|---|---|---|---|
| txt | 0 | equal | n/a | n/a | job `out/` shredded on TTL (hunt2) | |
| md | 0 | equal | n/a | n/a | same | `_Name1_` emphasis restore still open |
| csv | 0 (comma and `;` variants) | equal | n/a | n/a | same | header-context ok |
| html | 0 (prose and `<table>`) | equal in probe; 6/17 unequal reported earlier NOT re-run | n/a | n/a | same | see Remaining |
| json | 0 | equal | n/a | n/a | same | |
| xml | 1 leak: bare INN in `<inn>770708389312</inn>` (element name is not used as a label) | equal | n/a | n/a | same | OPEN |
| rtf | not supported (BLOCKED, error) | n/a | n/a | n/a | n/a | odf also unsupported |
| docx | 0 incl. author metadata | equal | author scrubbed | thumbnails, printerSettings dropped | same | glossary/ffData/sdt not re-verified |
| pptx | 0 | equal | scrubbed | same | same | `tags`, comment authors not re-verified |
| xlsx | 0 incl. numeric ID cells and date serials | equal (type, value, number format) | creator scrubbed | | same | externalLinks/connections/pivot/VML not re-verified |
| pdf | 0 in text, metadata | text probe compared unequal (whitespace/hyphen in my naive compare; tests/test_ws_pdf* cover it) | metadata cleaned | n/a | same | `pdf_en_hiros` not re-run |
| images (png/jpg) | covered by `tests/test_ws_images.py`, not re-run | exact original bytes | EXIF stripped | n/a | same | |

## Real xlsx vs synthetic (separate tables; leaked = distinct strings from the vault entity store that still appear anywhere in the output zip; token-shaped names `Name1` excluded)

Real files (Apache POI test corpus, `tests/eval/real/poi_xlsx_*`; no personal data, so little to detect):

| file | kind | leaked values | restore equal | note |
|---|---|---|---|---|
| 123233_charts.xlsx | real | 0 | True | charts |
| 54399.xlsx | real | 0 real values (4 hits are `Microsoft`/`Complete`/ContentType id: non-personal vocabulary) | True | |
| 58896.xlsx | real | 0 | True | |
| InlineString.xlsx | real | 0 | True | status attention |
| clusterfuzz ...4828727001088000.xlsx | real (corrupt fuzz sample) | n/a | n/a | refused (error), by design |

Synthetic (`tests/eval/real/_cases/syn_*_xlsx`, run after the fixes above; before the fixes: contract_ru 6 leaks, invoice_ru 5 leaks):

| file | kind | leaked values after fixes | restore equal | note |
|---|---|---|---|---|
| syn_contract_ru_xlsx | synthetic | 0 | False only for secrets | `API key`/`password` become `Secret1`, irreversible by design |
| syn_invoice_ru_xlsx | synthetic | 0 | False only for secrets | same |
| syn_invoice_en_xlsx | synthetic | 0 | False only for secrets | same |
| syn_resume_en_xlsx | synthetic | 0 | False only for secrets | same |

Not done: building extra Excel-saved workbooks (merged cells, tables, charts, hidden sheets, conditional formats) via `tools/fetch_real_corpus.py`; needs Excel/network download approval, not available autonomously here.

## Remaining (not done in this session)

- xml: bare identifier inside an element named `inn`/`passport` (use element/attribute name as label like csv header).
- OOXML parts (not re-verified, still listed in audit-0810-formats.md): xlsx externalLinks, connections, pivot refreshedBy, numFmt, autoFilter, VML alt/textpath; cached formula strings; docx glossary docPart, ffData, sdt placeholder; pptx tags; comment authors; embedded xlsx/docx inside containers; ZWSP-split names; SmartArt false warning.
- Restore equality: html (6/17 unequal in eval), md `gh_requests_hist`, markdown `_Name1_` emphasis (TOKEN_RE excludes `_`), `pdf_en_hiros`.
- Unquoted csv `Month D, YYYY` (comma splits the field).
- Phone numbers stored as numbers under a "Телефон" header are covered only by the 79xxxxxxxxx shape (`_sensitive_number`).
- Finance branch also edits xlsx in `formats.py`: my xlsx edits are confined to `force_numeric_ids`, `_text_into_numeric_cells`, `_column_number` and one call in `learn_package`; restore edits to `_strip_numeric_marks/_renumber` and one call in `restore_ooxml`.
