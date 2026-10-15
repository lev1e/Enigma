# Format audit 08.10 (4 adversarial agents) — confirmed failures backlog

Repro scripts lived in the session scratchpad (scratchpad/{ooxml,pdf,text,restore,addin,rt}) and may be gone; every item below was reproduced at HEAD 70bea6b. Fix order: leak > corruption > restore > FP. Corpus generator/evaluator for the text area (442 sentences, 689 spans; recall 93.5%, precision 97.7%) was in scratchpad/text (make_corpus.py, eval.py) — regenerate into tests/eval/ when needed.


---
Confirmed failures on PDF hard cases, ranked leak, then corruption, then restore, then false positive. Each was run on this repo's PDF path (`Env().anonymize` and `restore`), using only invented identities.

All repro scripts are in `S=/private/tmp/claude-501/-Users-USER-Downloads-Anonymizer-1-0-0-Windows-build-kit-2/7ce29159-bd26-4d60-b01d-4a4a30e07415/scratchpad/pdf/`. Run any of them with `/private/tmp/py <script>`. `h.py` is the shared helper, and `t*.py` are the repros named below.

## Confirmed failures

1. **LEAK, rotated or sideways scans.** A scan image rotated 90° or 180° is not OCR'd. In `t12.py` the INN and the patronymic stay readable in the pixels. The file is still returned with status ok and the message "recognized (6 words) and checked". The 90° case was also re-OCR'd independently: "Сергеевич" is still readable. The 270° case was not visually checked.
   - `ocr.py:274` (`ocr_page_words`) runs one orientation only. The verify step in `formats.py` ~2065 uses the same engine, so it cannot see what the first pass missed.
2. **LEAK, surnames in a separate table column.** With columns Фамилия | Имя | Отчество, all 3 of 3 surnames stay readable (`t23.py`). First names and patronymics are replaced. Status is ok with no warning. The single-cell "Воронцов Артём Сергеевич" layout passes.
   - The cause is lone-surname detection in `detectors.py`: no column-header context is used.
3. **LEAK, unreadable page text exported with "nothing found".** Two cases: text converted to vector outlines (`t7.py`) and fonts without ToUnicode (`t22.py`, extraction gives garbage). Both return the file with the PII fully visible. The only message is "Данных для замены не найдено", status attention.
   - There is no check in `transform_pdf` (~1990-2000) for pages that have visible content but no readable text.
4. **LEAK, XFA datasets and catalog actions.** XFA `datasets` streams (full form XML) remain: name and email leak (`t25.py`). The catalog `/OpenAction` URI (`mailto:…?subject=INN`) and the catalog `/URI /Base` also remain. None of these are reached by the scrubbers in `formats.py` 1814-1945.
5. **LEAK, choice-field options, field names and widget JS.** Combobox and listbox `/Opt` values leak email, name and phone even when those values are on the page and already known (`t14.py`, `t4.py`). The widget field name `/T` is not scrubbed. A widget `/AA` JavaScript with an email is not scrubbed. `_scrub_pdf_extras` handles only `field_value`.
6. **LEAK, tagged-PDF text.** StructTree `/Alt` and `/ActualText` stay in the file (`t14.py`). Part of the Alt text is stored as UTF-8 hex, so `pdf_probe` misses it.
7. **LEAK, image and page metadata.**
   - JPEG EXIF inside embedded images is kept: an email and an INN in the EXIF fields were still in the output (`t16.py`).
   - XMP `/Metadata` streams on pages and images are kept: name and email leak. `del_xml_metadata` only removes the catalog XMP.
   - PNG text chunks are dropped. They are re-encoded by fitz.
8. **LEAK (low), letter-spaced text.** Text with 3pt gaps between characters (`t8.py`, gap=3) makes the full name stay readable. The message is again "nothing found".
9. **LEAK (low, niche), RTL text glued to the next word.** Hebrew or Arabic text before a Cyrillic surname puts the space before the RTL run (`t10.py`). The line view becomes `םולשВоронцов`, and the surname is not replaced.
10. **LEAK, detection hole (not PDF-specific, confirmed on .txt).** "Jean-Paul Martin" and "Contact: Jean-Paul Martin, CEO." are not detected. "Mr. Jean-Paul Martin" becomes "Name1 Martin", so the surname stays. Repro is inline in this session; the PDF version is in `t28.py`.
11. **CORRUPTION, vector backgrounds and lines deleted.** Redaction uses `PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED` (`formats.py` ~2022). A coloured banner behind a name is removed (`t18.py`, drawings 4→7). A red bar behind white text is removed, so the white token becomes invisible on white. A strike-through or signature line is removed. There is no warning.
12. **CORRUPTION (low), hidden layers become visible.** `_pdf_open_layers` deletes `/OCProperties`, so hidden OCG layers render in the output (`t19.py`: 0 dark pixels before, 193 after). A draft note that contained no PII is now visible, with no notice.
13. **RESTORE, restored PDF is visually broken** (`t6.py`; renders in `rest.png` and `anon.png`). Restore draws the original text in the `china-s` CJK font, at 3-8pt, inside the placeholder box (`restore.py:371-381, 447-451`). The restored page shows letter-spaced text, overlap with neighbouring text, and tiny names. Extracted text also puts the values at the end of the stream, out of order.
14. **RESTORE, hyphens in restored values are silently lost.**
   - MuPDF extracts `-` as U+00AD for some fonts. `normalize.py:12,132` strips U+00AD, so the vault stores `severinvest.ru` (`t27.py`).
   - Restore therefore returns a different email address ("severinvest.ru" instead of "sever-invest.ru"), "5551234" instead of "555-12-34", and "АльфаБанк".
   - With a normal ASCII hyphen (`t28.py`) the round trip is exact. I can't tell how common U+00AD is in real PDFs.
15. **RESTORE, scan text is not restored and nothing says so.** Restoring an anonymized scan PDF leaves the drawn tokens in the pixels. Restore returns no message, and the image is not byte-identical (`t24.py`). `restore_pdf` has no image store.
16. **FP (low).** The public 8-800 hotline number becomes Phone1 (`t17.py`).

Known-gap overlaps I hit again (no separate repro): an INN without the "ИНН" label leaks in table cells (`t18.py`, `t23.py`) and in white or tiny text. The handoff lists this.

## Passed

- **Extra leak check:** a raw-bytes search of every decoded object plus a zlib scan of the whole file (so old revisions would show up) found nothing in these cases.
- **Page content, no leak:**
  - Two-column layout.
  - Hidden OCG text.
  - Render mode 3 over scans.
  - Text under a black rectangle.
  - Text under an opaque image.
  - Tiny and white text carrying emails.
  - Text outside the CropBox.
  - Text clipped to 1pt.
  - Page rotation plus CropBox.
  - Character-by-character positioned text at gaps up to 1.5pt (the 3pt gap fails, see item 8).
  - `fi`-ligature name plus email.
- **Annotations and forms, no leak:**
  - FreeText, Text, Highlight and Stamp annotations.
  - Reply annotations with `/RC`.
  - Text, label and checkbox widgets.
  - Widget `/TU`, `/DV` and `/TM`.
  - Links with `mailto:` and Launch actions.
  - JS on a link annotation and SubmitForm URLs.
- **Document structure, no leak:**
  - Info, XMP (catalog level), page labels, outlines, named destinations and the Names tree.
  - Optional-content layer names, PieceInfo, and `/Thumb`.
  - Document-level OpenAction JS.
  - Embedded files (dropped with a warning) and incremental-update leftovers (full rewrite removes them).
- **Encryption and signatures:**
  - Owner-password-only PDFs (AES256 and RC4) open and are anonymized.
  - User-password PDFs are rejected with a clear message.
  - Signed and signature-field PDFs return no output.
- **Embedded images:** OCR of embedded text images passes for upright RGB, JPEG, CMYK, gray, 1-bit, RGBA with SMask, transparent background and low-resolution variants. An independent app-OCR check of the output found no name, INN or email.
- **Corrupt and bad input:** a truncated file, a bad xref, a damaged stream, zero bytes, header-only and not-a-PDF inputs give a clean error or a safe result, with no crash.
- **Restore fidelity:** a 200-page round trip restored all 200 emails. A 14400pt page works. A 100% harmless numeric and date page was unchanged except for items 16 and the by-design city and public-person names. Per-column and per-line token consistency held.
- **Not tested:** JBIG2 and inline images (not generated), Windows OCR, and Tesseract with Russian (only `eng` is installed). Also not available here: reportlab, pikepdf and LibreOffice.

## Performance

- 200 pages of text, 2.4 MB input: 25.4 s to anonymize, 11.9 s to restore, peak RSS about 505 MB.
- A 9000×9000 scan page: 2.5 s but about 2.45 GB peak RSS.

---
## Text formats and detector quality: audit results

Nothing under the repo was edited. I ran everything against a `git archive` snapshot of HEAD 70bea6b, kept in `…/scratchpad/head`.

Another agent has an uncommitted `anonymizer/detectors.py` diff in the live tree. Items it already fixes are marked **[WT-fixed]**. Re-verify and commit that diff.

Scratch root `S` = `/private/tmp/claude-501/-Users-USER-Downloads-Anonymizer-1-0-0-Windows-build-kit-2/7ce29159-bd26-4d60-b01d-4a4a30e07415/scratchpad/text`. Repro scripts live in `S/repros/`. Run each from a repo root with `.venv-mac/bin/python`.

Datasets:
- `S/corpus_v1.jsonl`: 442 sentences, 689 sensitive spans, 137 harmless look-alike spans.
- `S/corpus_v1_persongrid.jsonl`: 1260 name mentions.
- Generators: `make_corpus.py` and `make_grid.py`. Evaluator: `eval.py`.

## Confirmed failures, ranked

All were reproduced at HEAD. The WT-fixed ones were re-run on the live tree.

**Leaks and silent unsafe export**

1. **UTF-16 without BOM, and UTF-32, are exported unchanged.**
   - The file is read as UTF-8 with NUL bytes, nothing is found, and the output equals the input. Only a "nothing found" warning appears.
   - Cause: `util.py:62-74` `sniff_encoding` and `formats.py:498-504` `transform_text_file`.
   - Repro: `repros/repro_encoding.py`.
2. **KOI8-R and CP866 text is decoded as cp1251.** Names such as Смирнов and Иванов go undetected and the file is exported as OK. Cause: `util.py:68`. Same repro.
3. **HTML and XML character references are never decoded.**
   - `&nbsp;`, `&#1057;…` and `&#x421;…` hide names completely.
   - Names split by `<br>`, `<b>`/`<i>` or `<span>` leak.
   - `smirnov&#64;romashka.ru` leaves the local part readable.
   - There is no markup awareness in `transform_text_file`.
   - Repro: `repros/repro_html_entities.py` (6 of 6 cases leak).
4. **JSON with `\uXXXX`-escaped Cyrillic leaks fully.** `json.dumps` with the default `ensure_ascii=True` is enough: the name and `ООО «Ромашка»` stay readable after parsing while the phone and email are replaced. Repro: `repros/repro_json_xml_keys.py`.
5. **CSV and TSV with separate Фамилия, Имя and Отчество columns leak the surname.**
   - Output looks like `Смирнов,Name1`.
   - `"Смирнов, Алексей"` leaks entirely and `"Иванов, Пётр"` becomes `Name1, Пётр`.
   - Multi-line cells leak too: `Смирнов\nName1`.
   - Repro: `repros/repro_csv_columns.py`.
6. **Secrets in logs and config.**
   - 5 of 12 lines leak at HEAD:
     - `DB_PASSWORD=…` and `MYSQL_ROOT_PASSWORD: …`
     - `AWS_SECRET_ACCESS_KEY=…`
     - `X-Auth-Token: …`
     - the URL userinfo password in `http://u:p4ssw0rd@host`
     - `/home/smirnov/…` paths
   - Cause: `detectors.py:182` anchors password keys with `\b`, and `_` is a word character, so `DB_PASSWORD` never matches.
   - Repro: `repros/repro_log_secrets.py`. `user=asmirnov` is **[WT-fixed]**.
7. **Detector gaps on the 689-span corpus.** These are **[WT-fixed]** in the uncommitted diff:
   - IPv6 (4 of 4 missed)
   - spaced OMS (3 of 3)
   - passport "серия 4512 № 345678" (2 of 2)
   - crypto wallets (3 of 3)
   - `Логин:` and `user=` (2 of 2)
   - lowercase plates
   - an ISO date of birth covered only as `1990`, leaving month and day readable
   - "Пароль от почты — x"
8. **Unlabelled INN** (checksum-valid 10 or 12 digits): 7 of 10 are not replaced.
   - **[WT]** downgrades them to REVIEW only, so they stay readable unless a user confirms.
   - The 10-digit ones starting with 8, 3 of 6 unlabelled and even 5 labelled `ИНН 8065…`, are typed PHONE (`detectors.py:117/122`). They are hidden, but with the wrong token type.
9. **Person misses in two-word forms.**
   - Female given names that are also common words (Вера, Надежда, Роза, Любовь, and Алла in the dative) leave the given name readable, and the surname gets REVIEW only. Example: `Гусевой Веры`.
   - `Романа Ильина`, `Гусеву Пётру` and the rare `Любим` are REVIEW or missed.
   - Other misses:
     - `MARIA SMITH`
     - `J. Whitfield`
     - `Smith, John`
     - `Hans Müller` (REVIEW only)
     - `Оглы Рашид Эльдар` (partial)
     - nicknames
   - The grid shows 46 of 1260 mentions missed (3.7%), all in two-word forms.
10. **Markdown and hyphenation.** Emphasis markers break the name match and the surname stays readable: `**Смирнов** *Алексей* `Петрович`` becomes `**Смирнов** *Name1``. A hyphen-wrapped `Смир-\nнов` leaks. Repro: `repros/repro_md_markup.py`.

**Corruption**

11. **Minified JSON becomes invalid.**
    - `{"status":"Paid","type":"Invoice"}` becomes `…"type":"Company2`, losing the closing `"}`.
    - `["Alpha","Beta","Gamma"]` gives `"Company2,"b":…`.
    - Cause: `entities.py:631` `_siblings` ("Рядом в перечне") builds a span that includes `"}`.
    - Repro: `repros/repro_json_overredaction.py`.
12. **CSV and TSV columns collapse.**
    - Delimiters sit inside the name span, so TSV rows go from 3 columns to 1 and CSV rows from 3 to 2.
    - `;` is swallowed in `Алексей;Петрович`.
    - The cause is name tokenization joining across `, ; \t` (name passes around `detectors.py:1107`; I did not isolate the exact line).
    - Same repro as 5.
13. **Keys and structure are renamed.**
    - JSON key `ФИО` becomes `Company1` and `Смирнов` becomes `Name1_2`.
    - XML `<Смирнов>` becomes `<Name1_2>`, and `id="Смирнов"` is replaced.
    - INI `[Смирнов]` becomes `[Name1]`.
    - Restore is byte-identical, but the anonymized file's schema is wrong.
    - Same repro as 4.
14. **Token look-alike identifiers.** CSV headers and JSON keys `name1`, `phone1`, `phone2`, `city1`, `company1`, `ip6` become `TermN`. Repro: `repros/repro_token_lookalike_keys.py`.
15. **Quoted CSV cell misclassified.** `"Смирнов А.П.","ИНН 7707083893"` gives `"Company1.","Company2"`. The person is learned as an ORG, the dot is left behind, and the INN cell is swallowed into an ORG. Cause: `entities.py:519` (quoted capitalised string).

**Restore**

16. **Label rule eats whitespace, so the original is lost.**
    - Input `Тел +7 (913) 555-12-34 Смирнов Алексей Петрович` becomes `Тел Phone1Name1`, and restore cannot split the glued tokens.
    - Cause: `detectors.py:126`, where `((?:\+?\d[\s()\-]*){7,15})` absorbs the trailing whitespace.
    - It fires for any `Тел`, `Моб` or `факс` label followed by a space and more text.
    - Repro: `repros/repro_phone_label_swallows_space.py`.
17. **cp1251 files restore as UTF-8.**
    - When the anonymized output is pure ASCII, restore re-sniffs it as UTF-8, so `<meta charset=windows-1251>` HTML and XML come back as UTF-8 bytes.
    - Cause: `util.py:68-74` together with `restore.py:171-179`. The source encoding is not recorded.
    - Same repro as 1.

**False positives and performance**

18. **Quoted strings are treated as ORG.**
    - A PII-free catalog loses about 85–95% of its strings: JSON 51 of 56 strings, CSV with `QUOTE_ALL` 53 of 63, XML attributes 32 of 40, quoted YAML 22 of 24.
    - Unquoted CSV is untouched (0 of 63).
    - Cause: `entities.py:87` (`QUOTED` regex) and `entities.py:503-520` (`_quoted`).
    - Same repro as 11.
19. **Other false positives from the corpus.**
    - Version and section numbers read as IPv4 (`2.10.3.1`, `1.2.3.4`).
    - Code `8517130000` read as PHONE.
    - `Client:` read as ORG.
    - `report_final_v2` read as FILE and `WordPress` read as PROJECT.
    - `Площадь Победы` read as ADDRESS.
    - `РФ`, `Российской Федерации` and `Банк России` are replaced as COUNTRY. This may be policy.
20. **Quadratic time and memory on large logs.**
    - 4k, 8k and 16k lines (0.5, 1.0 and 2.0 MB) take 6.7 s, 19 s and 59 s, with RSS at 214 MB, 308 MB and 598 MB.
    - Hot spots: `detectors.py:1179-1218` `_complete_list_names` (90M generator iterations for 6k lines) and `entities.py:1037` `suggest_hits` (41M).
    - At this rate the 300 MB upload limit is unreachable.

## Quality matrix (corpus v1)

| Run | Full recall | Leakage | Precision |
|---|---|---|---|
| HEAD | 644 of 689 (93.5%) | 45 (6.5%) | 97.7% (15 false positives) |
| Working tree | 96.1% | 3.9% | 97.8% |

- **Categories at 100% (HEAD):** PHONE 70/70, EMAIL 57/57, CARD 39/39 (Luhn), BANK_ACCOUNT 13/13, BIK, CONTRACT, DRIVER_LICENSE, KPP, OGRN, SNILS.
- **Below 100% (HEAD):** PERSON 235/249 (94%), ORG 60/62, CITY 43/44, ADDRESS 7/9, INN 53/60.
- **Name declension grid:**
  - Overall 1208 of 1260 (95.9%).
  - The `ФИО`, `Фамилия И.О.` and `И.О. Фамилия` styles: 756 of 756.
  - The two-word styles: 458 of 504 (90.9%).
- **Prose precision:** 50 harmless business, legal, ALL-CAPS and English lines gave 0 false positives on business phrases. The 18 auto-replacements were policy cases: countries, cities, public figures, brands and a street.
- **Text formats that passed:**
  - CSV with quoted separators, BOM, CRLF, cp1251 and UTF-16 with BOM: byte-identical restore.
  - TSV, INI values and YAML values.
  - HTML: 12 of 12 placements with no leak and identical restore. These cover mailto, tel, meta, title, alt, script, style, comment, data-*, input, textarea, pre and ld+json.
  - Markdown: frontmatter, links, reference links, footnotes, tables, code fences and images (8 of 8), and headings.
  - XML: attributes, CDATA and `&amp;`/`&lt;` stay well-formed.
  - Pretty JSON with ASCII PII stays valid.
  - Mixed-encoding files are blocked with an error (safe).

Scripts not listed above, in `S/`: `d9.py` (HTML placements), `d11.py` (encodings), `d18.py` (markdown), `perf.py` and `prof.py` (performance), `harmless.py` (prose false-positive probe). All except `harmless.py` import the repo via `sys.path`; run them from a repo root.

---
SCRATCH=/private/tmp/claude-501/-Users-USER-Downloads-Anonymizer-1-0-0-Windows-build-kit-2/7ce29159-bd26-4d60-b01d-4a4a30e07415/scratchpad/ooxml

I found 24 confirmed failures across DOCX, XLSX and PPTX. All use synthetic identities, nothing under the repo was edited, and every item was re-run. Run a script with `cd $SCRATCH && <repo>/.venv-mac/bin/python <script>`. The helpers `lib.py`, `dx.py` and `ctx.py` live in `$SCRATCH`. Scripts marked `known` take the argument `known`, which adds a body paragraph so the name is already known to the detector. All `formats.py` line numbers are hypotheses, not confirmed root causes.

## Confirmed failures, ranked (leak > corruption > restore > false positive)

**LEAK (the export reports status ok or attention, and the original is still readable)**

1. **A label in a neighbouring table cell is ignored.** With a header cell "ИНН" and a valid 10-digit INN in the next cell, the INN stays readable. The same happens with passport "4509 123456", OGRN, КПП, БИК, a birth date, and a 10-digit phone.
   - Repro: `dt.py` (DOCX tables) and `xl12.py` (XLSX). In `xl12.py`, 14 of 36 test rows leak, including every INN variant, numeric or text.
   - Cause: detectors only see the label inside the same text segment (detectors INN/PASSPORT rules). Table and sheet cell context is not passed to them.
2. **Unprocessed non-XML parts are copied raw with no warning.**
   - A DOCX `altChunk` .html part (`dx1.py altchunk_html`) leaves a name and phone fully readable. Status is ok and there are no messages.
   - Unknown related parts such as `word/extra/notes.xml` and `readme.txt` leak the same way (`dx4.py known`).
   - A zip entry named `../../evil.txt` is also carried through (`rb.py`).
   - Cause: `formats.py:1413` only parses `.xml` and `.rels` parts. Other text parts are neither processed nor flagged.
3. **XLSX connections and external links are not anonymized.**
   - `xl/connections.xml` keeps the connection string (server, user, **password**) and the SQL command.
   - `xl/externalLinks/externalLink1.xml` keeps cached cell text and sheetNames, including a full ФИО and a company.
   - `pivotCacheDefinition` keeps `refreshedBy="Лебедев Тимофей"`.
   - The only signal is the generic message "После обработки остались критические совпадения".
   - Repro: `xl7.py`. Cause: these attributes and `<v>` text are not in `NAMED_ELEMENT_ATTRS` or `TEXT_TAGS` (formats.py:43-82).
4. **XLSX structure text leaks.** Repro: `xl1.py`, `xl17.py`.
   - Number format codes in `styles.xml` keep `0 "руб. Норд-Импульс"` and `[Red]0.00" Лебедев"`.
   - `cellStyle name="Стиль Лебедев"` is not changed.
   - autoFilter `<filter val="Белов Илья Романович"/>` and `customFilter val="*Мираж*"` are not changed.
5. **VML and WordArt text in DOCX leaks.** Repro: `dx1.py known`.
   - `v:shape alt=` and `o:title=` keep names, including in headers.
   - `v:textpath string="КОНФИДЕНЦИАЛЬНО ООО Звезда Громов"` (watermark) is not changed.
   - DrawingML `descr` is handled; VML is not.
6. **More DOCX attributes leak.** Repro: `dx1.py known`, `dx6.py known`.
   - `w:sdt` `listItem displayText/value` keeps a full ФИО.
   - Form-field `ffData` (name, helpText, statusText, default) leaks.
   - `settings.xml` `w:docVars` keeps "ООО Звезда, Громов Святослав".
   - `tblCaption` and `tblDescription` (table alt text) leak.
   - `styles.xml` style names ("Стиль Звезда Громов") leak.
   - The glossary docPart name leaks.
7. **PPTX leaks.** Repro: `pp2.py`, `pp6.py`.
   - `a:hlinkClick tooltip="Написать Яковлеву"` is not changed.
   - `custShow name="Показ для Яковлева"` is not changed.
   - `ppt/tags/tag*.xml` `val="Вектор-Пром, Яковлев Артём"` is not changed. This is deliberate: `tag/val` is excluded for ppt at formats.py:89-95.
8. **A lone patronymic survives when the full name is known.**
   - It leaks when it sits alone in a table cell (surname and name cells became Name1_2 and Name1_3).
   - It leaks in a chart `strCache` (`dx4.py known`).
   - It leaks when it ends one tracked-change fragment (`t_tc.py`): "Директор Name1_2 Леонидович".
   - Repro: `dx1.py known` (lone_patronymic_cell), `t_tc.py`.
   - Cause: sibling `w:ins`, `w:del`, `w:moveFrom` and `w:moveTo` text is concatenated with no boundary, so a name that ends one fragment merges with the next word.
9. **Birth date variants leak.** Repro: `bd.py`.
   - "Дата рождения директора: 14.03.1985" stays.
   - "14.03.1985 г.р." stays.
   - "Born: March 14, 1985" stays.
   - A real date cell in XLSX (with the header "Дата рождения") stays.
10. **Domain or email glued to following Cyrillic text.** Repro: `glue.py`.
    - `www.zvezda-nsk.ruКонтакты` leaks completely.
    - `x@zvezda-nsk.ru.Тел:` becomes `email3@example.com: 5`, so "Тел" is eaten.
    - Cause: the Cyrillic IDN TLD rule in entities `DOMAIN` and `EMAIL_DOMAIN`.
11. **Numeric cells are skipped.** Repro: `xl12.py`.
    - A 9-digit phone "9132223344" stays.
    - A 20-digit account stored as a number stays (`4.07e+19`).
12. **Image file names leak.** `word/media/Громов_подпись.png` keeps its part name and the rels `Target`. Repro: `dx4.py known` (image_name).
13. **An INN split by `<w:tab/>` leaks.** Repro: `dx2.py` (inn_split_cells). The only message is "Данных для замены не найдено".
14. **Partial company name remains.** For «Сириус-Трейд», bare "Сириус" stays in a drawing group name and a data-validation list (`xl9.py`). Low severity.

**CORRUPTION (the anonymized file is broken or inconsistent)**

15. **XLSX formulas are rewritten as prose.** Function names and string literals are replaced by tokens. Repro: `xl4.py`, `xl6.py`, `xl15.py`.
    - `=IF(ISNUMBER(SEARCH("ИП",A2)),1,0)` becomes `Company1(Company2(Company3("Company4",A2)),1,0)`.
    - `=LEFT("ООО",3)` becomes `Company1("Company2",3)`.
    - `=CONCATENATE("ИНН ","1")` becomes `Company2("Company3 ","1")`.
    - `=INDIRECT("Москва!B2")` becomes `Company1("Company2")`, and in the same file `=Москва!B2` becomes just `Company2`.
    - Excel shows #NAME?. Cause: `"f"` is in `TEXT_TAGS` (formats.py:44), so formulas go through the prose detector.
16. **A U+200B appears in formulas but not in the definition.** Repro: `xl18.py`.
    - Formulas use `План_\u200bName1_2` and `Тбл_\u200bName1_2[Сумма]`.
    - The `definedName` and table name are `План_Name1_2` and `Тбл_Name1_2`.
    - Every formula referencing a renamed named range or table breaks. Restore is exact.
17. **Sheet rename not propagated.** Repro: `xl13.py`, `xl3.py`.
    - Internal hyperlink `location="Москва!A1"` and `'Лебедев Т.А.'!A1` keep the old name. This leaks and breaks the link (`LINK_ATTRS` handling at formats.py:1132 only covers URL-like values).
    - A chart value ref `'Москва'!$B$2:$B$3` is not renamed, while the title and category refs are.
18. **Sheet name over Excel's 31-character limit.** Repro: `xl11.py`. "Ли Вэй - сверка расчётов по пос" (31 characters) becomes "Name1_2 - сверка расчётов по пос" (32 characters), which makes Excel offer to repair the file. This affects short surnames.
19. **Word REF, PAGEREF and anchor targets drift from the renamed bookmark.** Repro: `bm.py`.
    - Bookmark `Name1_3` has `REF Name1_2`.
    - `Company1_раздел` has `REF Company1\u200b_раздел`.
    - Cross-references break in Word.
20. **Word IF field instruction is mangled.** Repro: `fp1.py`. ` IF "{ MERGEFIELD Пол }" = "М" …` becomes ` IF "{ MERGEFIELD Name1" …`, which breaks the field.
21. **Text lost in tracked changes.** Repro: `t_tc.py`. An email ending a `w:ins` and `Удалено…` starting the next `w:del` are matched as one email. The word "Удалено" disappears from the anonymized file, and restore writes it into the `w:ins` run (corrupts the restored document).

**RESTORE fidelity**

22. **Restore changes formatting boundaries.** Repro: `fm.py`. The original runs were bold "Орлов" and italic " Пётр Иванович". After restore the whole name is bold and an empty italic run remains. The same happens with split runs in DOCX and PPTX.
23. **Restore moves or drops control elements inside an entity.** Repro: `dx3.py`.
    - `Лебедев<noBreakHyphen/>Крамской` restores as "ЛебедевКрамской …" with the hyphen moved to the end.
    - A `<w:tab/>` inside the entity is dropped at anonymize time, and restore writes a space.
    - A `<w:br/>` inside an entity is handled correctly.

**False positive or spurious warning**

24. **Restore of any PPTX or DOCX with SmartArt shows a false warning.** Repro: `pp2.py`. The message "Не удалось восстановить метки: Data1 (2)" comes from the part name `data1.xml` in rels and `[Content_Types].xml`, which looks like the token `Data1`. Restore reports "attention" for a clean round trip.

## What passed

| Area | Result |
|---|---|
| DOCX body | Name split mid-word across runs (10 runs), merged and vertically merged table cells, even/odd/first-page header and footer. No leaks. |
| DOCX text flow | nbsp, `w:br`, `w:softHyphen`, `proofErr`, `smartTag`, a hyperlink in the middle of a name, `w:ins` in the middle of a name, a field inside a name, caps, genitive, initials, Latin names, card, passport and СНИЛС. No leaks. |
| DOCX structure | Footnotes, endnotes, comments with replies, `commentsExtended`, `people.xml`, tracked changes (author attributes), docProps core/app/custom, customXml, header/footer textboxes (body text), TOC, HYPERLINK and MERGEFIELD, hyperlink Targets in rels (URL, mailto, `file:///`), math, hidden (`vanish`) text. No leaks. |
| DOCX phones | 19 phone formats in running text, all replaced and restored exactly. |
| DOCX embedded content | Embedded docx via altChunk, SmartArt data, chart with embedded xlsx. Processed. OLE .bin objects are removed with a notice. |
| XLSX | Defined names, data-validation lists, conditional-format expressions and `containsText`, legacy and threaded comments, persons, headers/footers, table columns kept consistent with header cells, hidden and veryHidden sheets and rows, rich-text cells, drawing textboxes and groups, x14 sparklines (kept), 30+ sheet-name variants with no duplicate names, formula cached values. |
| PPTX | Notes, groups, tables, chart category/series caches plus the embedded xlsx (restored exactly), master and layout text, slide and modern comment authors, `authors.xml`, sections, hidden slide, alt text, SmartArt, chart `userShapes`, `app.xml` TitlesOfParts. `pptx_A` had zero leaks. |
| Restore | Text of all fixtures except the cases listed above restores equal to the original. |
| Hostile inputs | XXE (error), billion-laughs entities (error, 0.0 s), truncated part (flagged), UTF-16 and BOM parts, namespace-prefix variants, OLE-as-docx, empty and encrypted files (all give clear errors). |
| Performance | XLSX 5000×5 in 6.0 s with zero leaks and an exact 5000-row restore (1.4 s). DOCX with 3000 paragraphs in 4.4 s (restore 0.5 s), exact. PPTX with 120 slides in 0.5 s with zero leaks. |

Counts for the leak scans: `xl12.py` = 14 of 36 rows leaked, `dx1.py known` = 10 of 19 leaked.

---
CONFIRMED FAILURES (area: restore/fidelity/add-in). Each was reproduced by running it. Repro scripts are in `/private/tmp/claude-501/-Users-USER-Downloads-Anonymizer-1-0-0-Windows-build-kit-2/7ce29159-bd26-4d60-b01d-4a4a30e07415/scratchpad/` (called `$S` below). Run them from the repo root with `.venv-mac/bin/python`. Nothing in the repo was edited.

**LEAKS (ranked)**

1. **Column header context is ignored for identifiers.**
   - In xlsx, csv and docx tables, the INN under an "ИНН" header (as string or int), a passport under "Паспорт", and a card number under "Карта" stay unanonymized. The job status is `ok`.
   - A known INN also leaks on its second bare occurrence: `ИНН 7707083893 … контрагент 7707083893` gives `Inn1 … 7707083893`.
   - Repro: `$S/rt/t7.py`, `t8.py`, `t9.py`.
   - Cause: only person columns use header context (`detectors.py:615`, `formats._person_column_values`). The identifier rules need a label inside the same string, and a value already known to the vault is not replaced when it appears without a label.
2. **"Фамилия, Имя Отчество" leaks the surname.**
   - `Иванова, Мария Сергеевна` becomes `Иванова, Name1`. The same happens in txt and xlsx, for example `Петров, Name2`.
   - Repro: `$S/rt/nm1.py`. Root cause is in the person rules in `detectors.py`.
3. **CSV doubled-quote company names leak.**
   - `"ООО ""Ромашка"""` becomes `"Company1 ""Ромашка"""`. The legal form "ООО" is tokenised as a company and the real name stays readable. Status is `ok`.
   - Repro: `$S/rt/csv1.py`. Related code: `entities.py` `_legal_quoted` / `_quoted` (line 483).
4. **xlsx autoFilter values leak.**
   - `<filter val="Смирнов Алексей Петрович"/>` and `<customFilter val="Смирнов*"/>` in sheet XML survive. Status is `ok`.
   - Repro: `$S/addin/h6.py`, `h5.py`. Probable cause: the sheet XML scan covers only the tags listed in `TEXT_TAGS` / `IDENTIFIER_ATTRS` (`formats.py:43-52`) and does not look at `val` attributes.
5. **Unreadable encodings pass through unchanged.**
   - UTF-16LE/BE without BOM, UTF-32, JSON with `\uXXXX` escapes, HTML numeric entities, URL-encoding and base64 all leave the file byte-identical.
   - The status is `attention` with the message "Данных для замены не найдено", and `downloadable` is True.
   - Repro: `$S/rt/u16.py`. Related code: `util.sniff_encoding` (`util.py:62`). The file should be refused, not returned.
6. **Other hidden parts are not scrubbed (status `ok`, no warning).**
   - xlsx: `workbook.xml` `definedName@comment`, `xl/connections.xml`, `xl/externalLinks/externalLink1.xml`, `xl/slicers`, `xl/queryTables`.
   - docx: `word/settings.xml` `w:docVar`, `w:permStart w:ed="<name>"`, `w:placeholder/docPart`.
   - pptx: `ppt/tags/tag1.xml`, `p:custShow@name`.
   - Repro: `$S/addin/h2.py`, `h5.py`, `h6.py`.
   - `verify_document` also misses leftover `docVars` in the add-in re-read check (`$S/addin/vd.py`: `ok=True`).
7. **API key `sk-live-AbCdEfGhIjKl-nOpQrStUvWx` is not detected.** The input was `API key sk-live-…`, and the key stays in the output. A `ghp_…` token in the same file was caught. Repro: `$S/rt/s1.py`.
8. **The add-in token is handed out without authentication.**
   - `GET /addin/taskpane.html` and `GET /addin/chat?chat=aaaaaa` need no token and return it (`addin.py:675-698`, substitution at line 698).
   - With that token, `/api/addin/backups` and `/api/addin/backup/<id>` return the plaintext original document. I confirmed the whole chain.
   - Risk is local users or processes on a shared machine. Browsers are blocked by the Host check and same-origin rules.
   - Repro: `$S/addin/s2.py`.
9. **Plaintext originals stay on disk during the session.**
   - `work/<job>/in/0/<name>` holds the unencrypted input. `Service.cleanup` runs only at construction (`service.py:242-251`), and `taskpane.js` never calls `/api/addin/forget`.
   - This also applies when `retain_secrets_for_restore` is off, where secrets are meant to be "удаляются безвозвратно".
   - Repro: `$S/addin/p1.py`, `$S/rt/s1.py`.
10. **Retention leaves original file names in the vault.** After `retention_days` expires, entities are purged but `vault.file_names` still holds `Договор_Ромашка_Смирнов.txt` (`vault.py:165-176`). Repro: `$S/rt/ret1.py`.

**CORRUPTION**

11. **Excel formulas are broken.** `=IF(A1>0,"Директор ООО Ромашка","нет")` becomes `=Company2(A1>0,"Company3","нет")`. The function name is replaced and Excel will show `#NAME?`. Restore is still exact. `f` is in `TEXT_TAGS` (`formats.py:44`) and formulas go through the plain-text detector. Repro: `$S/rt/f2.py`.
12. **CSV quoted fields lose the opening quote.**
    - `"Иванова, Мария Сергеевна",ООО «Лютик»,200` becomes `Name2, Name3",ООО «Company2»,200`, which parses as 4 columns instead of 3.
    - A whole-cell quoted person is also tokenised as a company: `"Иванова Мария Сергеевна"` becomes `"Company1"`.
    - Repro: `$S/rt/csv3.py`, `csv2.py`.
13. **Contract number swallows the sentence period.** `Договор №45/2026. Подпись.` becomes `Договор №Contract1 Подпись.` The vault stores `45/2026.` as the spelling. The regex group at `detectors.py:167` includes `.`. Repro: `$S/rt/k1.py`.
14. **Phone after the label "Тел" swallows the following space.** `Тел 89135551234 и ok` gives `Phone1и ok`, and the vault spelling is `'89135551234 '`. If a model fixes the spacing, restore gives a double space. Cause: `detectors.py:126` (`\s` inside the group). Repro: `$S/rt/t10.py`.

**RESTORE / FIDELITY**

15. **Vault edits are silently lost on rerun.** `edit_value` and `merge` made after a job disappear when `rerun` is called. `service.py:443-444` calls `vault.rollback(snapshot)` and `_commit_counter` is only bumped by anonymize commits. Repro: `$S/rt/rr1.py`.
16. **Stale chat overrides survive a rerun.** After `chats.set_settings(c, {"countries": None, "hide_terms": []})`, the rerun still keeps "Германии" and hides "плану", while a fresh run gives `Country1`. Cause: `merged = {**old.options, **options}` in `service.rerun`, where `old.options` already holds the chat-merged values. Repro: `$S/addin/a1.py`.
17. **Markdown underscore emphasis is never restored, with no warning.**
    - `_Name1_` stays `_Name1_`. It failed in 21 of 21 token kinds, and the same applies to `отчёт_Name1`, `иName1` and a zero-width space inside the token.
    - Cause: the `(?<![A-Za-z0-9_Ѐ-ӿ])` lookbehind in `TOKEN_RE` (`tokens.py:113`). The leftover check uses the same regex, so it is blind to these.
    - Repro: `$S/rt/m2.py`.
18. **Cross-vault restore is not refused for files without a marker.**
    - A `.csv` anonymized in vault A and restored in vault B returns B's people (`Кузнецов Борис Игоревич`) with status `ok` and no messages.
    - txt, md, docx, xlsx, pptx and pdf are refused correctly. A `.txt` whose marker was stripped by a model would restore the same wrong way.
    - Repro: `$S/rt/t12.py`.
19. **Invented tokens that collide with the vault restore other people's data.** A model-added `Name3` restores to a person from a different file. The only message is an `info` line ("относятся к нескольким исходным файлам"). The stray-source warning needs a 20:1 ratio (`service.py:816-835`). Repro: `$S/rt/w1.py`.
20. **A person's initials in parentheses are typed as a company.**
    - `Директор Смирнов Алексей Петрович (Смирнов А.П.), ООО «Ромашка»` becomes `Name1 (Company1.), ООО «Company2»`.
    - Without the trailing `ООО «…»` the same text is typed correctly as a person. Cause: `_abbreviations`, `entities.py:634-653`.
    - Repro: `$S/rt/k1.py`.
21. **Wrong message after `vault.forget`.** The restore warning says "Секретные данные (пароли, ключи) удаляются безвозвратно" for ordinary forgotten people. Low severity.
22. **Russian endings on tokens produce garbled text, with a warning.** `Name1у` gives `Смирнов Алексей Петровичему`. An email token with an ending (`email1@example.comу`) is restored with no warning at all.

**FALSE BLOCKS / UNSAFE EXPORT**

23. **Fail-closed false block on a PDF with a contract title on line 1.** `Договор поставки №45/2026` followed by any other line gives BLOCKED ("Остались значения: 1"). The drawn token ends up after the other lines in reading order, so `№ Просто` is re-detected as a contract number (`formats.py:2071-2081`). It is safe but blocks a very common layout. Repro: `$S/rt/pdf5.py`.
24. **A `.docx` containing `vbaProject.bin` is returned byte-identical.** The message is "Автоматическая обработка отключена: VBA", status `attention`, `downloadable=True`. Repro: `$S/addin/h3.py`. The file-extension check refuses real `.xlsm`, `.docm` and `.pptm`.
25. **Numbers mode skips text-stored numbers.** `"1 250 000,50"` and `"12,5%"` in text cells stay unchanged, as do numeric constants inside formulas. Repro: `$S/rt/n1.py`. The numeric-cell round trip itself is exact.

**PASSED**

| Area | Result |
|---|---|
| Round trip, identity (txt, md, csv, tsv) | Byte-exact in 5 encodings (utf-8, BOM, cp1251, koi8-r, cp866, utf-16 with BOM) and in CRLF, LF and CR variants. |
| LLM-edit simulation, 21 token kinds × 30 mutations | Exact in 25 of 30 mutations. These are bold, `*italic*`, code, brackets, quotes, `.,`, links, `'s`, `-го`, table pipe, JSON, `Клиент:` prefix, `/`, lowercase, uppercase, `\_`, trailing year, `name1` and similar. |
| Same simulation, failing mutations | `_x_` is 0/21 silent (item 17). `Name 1` and NBSP restore 0/21 but the warning appears. Letter-glued and inflected forms are 20/21, and the single failure is the email token. |
| Rich docx, xlsx, pptx (`leak_probe` builders) | Zero leaks. Restore is part-by-part identical, except the thumbnail removed by design. |
| docx tokens split across runs, header and footer | Restored correctly. |
| Cross-format consistency | Same person gives `Name1`, same INN gives `Inn1`, same company gives `Company1`, across txt, docx, xlsx, pptx and pdf. |
| Legal-form spelling variants | ООО, ЗАО, АО and ИП merge into one `Company1` entity; the legal form stays outside the token and restore is exact. |
| Vault edits | merge, edit_value, split and forget work on restore of old and new files (except item 15). |
| `retain_secrets_for_restore` | Round trip works when on. Nothing readable appears in `vault.bin`. |
| xlsx formula strings, sheet names, defined names | Restored exactly. Sheet names over 31 characters are truncated with a warning. |
| Add-in concurrency | 8 simultaneous jobs in one chat: all `done`, one `Name1`, no duplicates. |
| Add-in error paths | Corrupt, truncated and empty files, and XML entity bombs, give clean errors or refusals. XXE is not exploited. A 600 MB unpacked zip is processed in 2 s with a result. Huge or negative Content-Length, unsafe chunked bodies, path traversal and a wrong Host header are all refused. |
| `verify_document` | Flags leftover customXml, people.xml, comments, header, and a surname or inflected form left in the body. |
| Harmless text, 20 sentences | 18 unchanged. The two changes are by design (a city, an example email). |
| Performance | docx with 3000 paragraphs: anonymize 3.1 s, restore 0.4 s. xlsx with 20,000 cells: 6.2 s and 1.3 s, restore exact. |

**Not testable here:** real Office behaviour (`insertFileFromBase64`, leftover masters and custom XML in the open document), Windows OCR, and whether the rare PDF hyphen loss (a soft-hyphen font artifact in my own test PDF) happens in real PDFs. I dropped that last one.