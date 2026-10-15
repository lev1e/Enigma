
## 12.10 (W1 part 3): requests for W3 (detector) and the eval owner

1. EVAL FALSE POSITIVES, not detector misses (checked: product output contains 0 copies of the full injected name in both cases).
   - `gh_cpython_acks` (txt): needle for `Grace R. Lindqvist` is the surname `lindqvist` alone (`tools/eval_real.py needles`). The CPython acknowledgements list has real people `Björn Lindqvist` and `Per Lindqvist` (lines 1163-1164), so the needle matches genuine text. Proposed fix: for PERSON gold values, require the first name or the full name nearby, or exclude surname-only needles that occur in the unmodified base corpus.
   - `wd_en_actors_csv` (csv): needle for `Elena C. Haverford` is `haverford` (with Cyrillic look-alikes); the Wikidata rows contain the Welsh town `Haverfordwest`. Same fix.
2. DETECTOR GAPS ON OCR TEXT (W3): on OCR text of scanned pages the rules miss
   - `attn Marcus R Haverford` (OCR drops the period after the initial; `detector.scan` finds `Marcus R. Haverford` with the period, nothing without it);
   - `token = sk live_705871Z081428808XW` (OCR damage: space instead of `_`, `0` for `q`); `API key: sk live 550863Zq18247646X` also found nothing.
   W1 covers both on the image/scan path with its own rules (`_label_value_hits`, per-layer detection), but plain detector rules would be cleaner: allow optional period after a one-letter initial, and allow `sk[ _]live` plus `0/q` and `O/0` confusion after a secret label.
3. OCR coverage (ocr.py, mine): `cm_jpg_ru_023_aspdf` INN `391780587105` and the `sk_live_550863Zq18247646Xw` key in the bottom text strip are read by none of our OCR layers on the INPUT; they only become readable after we paint around them. The product now re-reads the output, finds them and refuses (fail closed) instead of shipping.

## 12.10 (W1 part 4): the 3 non-image leaks (diagnosed, detector/colctx files are W3's)
Files: `syn_minutes_ru_csv`, `syn_mail_ru_log`, `syn_invoice_ru_csv` (eval_real `--only`, plain-text path, no OCR). Leaked by `tools/eval_real.py` needles: 2 individual INN (12 digits, valid checksum, checked) and 1 passport per file:
- csv minutes: INN `907788854000`, `711545784791`, passport `7767 681576`; log: INN `332658166951`, `681230958485`, passport `9529 145774`; csv invoice: INN `458277305514`, `454889623869`, passport `4898 519757`.
- Where: a table block inside a text file (some lines of free text, then the header row `ФИО,Телефон,E-mail,ИНН,Паспорт,СНИЛС,Адрес`, tab-separated in the log, with a timestamp prefix). In the output the row reads `Name3_2,Phone2,email1@example.com,711545784791,7767 681576,Snils1,...`: name, phone, email and SNILS are replaced, the INN column and (in some rows) the 4+6 passport column are not.
- Layer that missed: not the sentence rules. `Detector.scan` on the sentence form (`... (7767 681576), СНИЛС ... и ИНН 711545784791 приложить`) returns PASSPORT 0.97 and INN_PERSON 0.97 AUTO. On the header+row text it finds PHONE, EMAIL, SNILS and the `89 81 147514` passport, but no INN for `907788854000` even with the header line in the same text. So the bare 12-digit value under an `ИНН` column header has no column context (colctx does not apply because the header is not line 1 of a clean CSV), and a bare `NNNN NNNNNN` passport is found only some of the time.
- Proposed fix (W3 / colctx): apply column context to header-led blocks in the middle of a text file and to timestamp-prefixed TSV rows; treat a 12-digit number with a valid INN checksum under an `ИНН` header as INN_PERSON AUTO; keep the 4+6 passport rule for columns headed `Паспорт`.
- Product behaviour today: the output carries the warning «После обработки в файле остались данные, похожие на исходные» (not blocking).
