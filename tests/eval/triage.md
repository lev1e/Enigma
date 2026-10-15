## Eval run 08.10 (300 cases: 229 real-document copies incl. 60 real docx/xlsx/pptx, 48 synthetic complex documents, 19 adversarial) - what is 10/10 and what is not

Every document carries ~31 (EN) to ~44 (RU) injected values (people, orgs, addresses, ids, cards, secrets, contacts). End-to-end recall over 8836 injected values:
**~71 %** overall, but it splits sharply by language: **Russian ~97 %** (PERSON 6/399 leaked, ORG 3/237, ADDRESS 10/237, PHONE/EMAIL/CARD/ACCOUNT/BIK 0), **English ~25 %** (PERSON 638/855, ORG 476/513,
ADDRESS 512/513, SSN 325/342, BIRTHDATE 283/342, PASSPORT 140/342).

10/10 (zero leaks in every format): CARD, ACCOUNT, BIK, IBAN (valid checksum), EMAIL (2 leaks, both PDF), PHONE (9, html/pdf), IP, OGRN, SNILS, PLATE, SECRET (15 of 502, csv/json/tsv/pdf).
Not 10/10: PERSON, ORG, ADDRESS (English almost entirely), SSN (no detector), BIRTHDATE, PASSPORT (English bare numbers), KPP (bare KPP), INN (bare INN in txt/csv/xlsx/docx/log).
Formats: the detector gaps are identical in txt/csv/docx/xlsx/pptx/pdf, so no Office format has a format-specific leak in this run; docx/xlsx/pptx recall is 56 % only because the weighted EN share is high.
Restore: exact for docx/xlsx/pptx/csv/tsv/log/yaml/ini and images; broken for PDF (see 3), XML/JSON after a secret (see 4).
Timing: median 0.1 s for Office/text, 8 s PDF, 7 s image; worst gov_fw9 PDF 250 s, adv_huge_txt (12 MB) 255 s; peak RSS 3.3 GB (cm_pdf_en_037).

### Top-15 defects (owner: D detectors, P PDF/OCR, O OOXML, S security-service)

| # | defect | repro ids | owner |
|---|---|---|---|
| 1 | XML output is NOT well-formed when a secret line is replaced: the secret rule swallows the closing tag and the next list number ("password: X</para><para>14. The Court" -> "Secret2 The Court"); the product reports status attention only | all 7 xml files with a secret fail ParseError: `syn_minutes_en_xml`, `syn_minutes_ru_xml`, `gh_lang_pom`, `gh_io_pom`, `gh_codec_pom`, `wd_ru_writers_xml`, `wd_en_scientists_xml` (JSON/XML restore content-equal 0 of 14) | D |
| 2 | English person names leak almost completely: "Applicant: Grace T. Okonkwo", table cells "Oliver E. Haverford", "Haverford, Oliver" (only partly), signature "Yuki D. Underhill" | `txt_en_lincoln`, `syn_invoice_en_tsv`, `off_docx_poi_footnotes` | D |
| 3 | PDF restore leaves placeholders in the file (564 tokens in 67 of 92 PDFs: Name3, Card1, Company6, Address5...) and splits words; only 18 of 92 PDFs restore to the original text | `syn_contract_ru_pdf`, `pdf_ru_ukaz1843`, `gov_fw4` | P |
| 4 | Secret rule corrupts neighbours: version numbers treated as passwords (`"pbkdf2-password": "1.2.1"` -> `"Secret1"`), label dropped and following text glued | `gh_pkg_json`, `gh_lodash_pkg` | D |
| 5 | US SSN ("SSN 437-86-6666", in tables, in running text) not detected at all (327 of 344) | `txt_en_lincoln`, every `*_en_*` case | D |
| 6 | English organisations (Redwood Ferris Logistics, Blue Harbor Capital) and US/UK street addresses ("2270 Fenwick Street, Portland") not detected (ORG 476/513, ADDRESS 512/513) | `txt_en_lincoln`, `off_docx_pydocx_test` | D |
| 7 | Birth dates leak in ~64 % (US "10/07/1968", "October 2, 1985"; RU 39/158 with "дата рождения" variants) | `txt_en_lincoln`, `syn_contract_ru_json` | D |
| 8 | Bare English passport numbers ("passport no. 340899782", "B97369255") and bare Russian KPP (67/158) and bare INN (34/320, txt/csv/xlsx/docx/log) leak | `syn_invoice_en_tsv`, `csv_en_gapminder` | D |
| 9 | Over-redaction: 1738 replacements in one Wikipedia page, 1420 in a decree, `wikidata.org/entity/Q...` URLs and adjective forms ("российских", "германском") replaced | `html_ru_putin`, `pdf_ru_pp1300`, `wd_en_scientists_xml` | D |
| 10 | HTML restore not equal in 6 of 17 pages (markup fragments replaced as entities) | `html_ru_putin`, `html_en_musk`, `html_ru_moscow` | D |
| 11 | Images and scanned PDFs: 18 of 28 images and 4 PDFs refused ("данные остались читаемыми после закраски" / signed / "Остались значения"); 72 of 248 values leak in the 8 jpg that were produced; TIFF and WebP unsupported | `cm_jpg_ru_019`, `img_ru_ao1926`, `gov_sc_opinion1`, `syn_minutes_ru_tiff_scan` | P |
| 12 | Signed-PDF refusal on fillable/signed samples is a hard block without a path to continue | `cm_pdf_en_027`, `cm_pdf_ru_001` | P |
| 13 | xlsx pivot tables: refused as "numbers not anonymised" (64 values); corrupt POI sample correctly refused | `off_xlsx_calamine_pivots`, `poi_xlsx_9` | O |
| 14 | Performance: 12 MB txt 255 s / 1.4 GB, IRS fw9 PDF 250 s, peak RSS 3.3 GB on one PDF | `adv_huge_txt`, `gov_fw9`, `cm_pdf_en_037` | D / P |
| 15 | Nested archives: PII in an embedded docx part and in a 4-level zip inside xlsx is handled (0 leaks), zip bomb and malformed inputs refused cleanly (no crash, no hang) - no defect, kept as regression | `adv_nested_docx`, `adv_nested_zip4_xlsx`, `adv_zipbomb_docx` | S |

Measurement artifacts fixed in the tools (not product defects): restore compare now ignores the by-design irreversible removal of secrets (`syn_contract_ru_docx`, `syn_mail_en_html` were False only because of that);
the generated IBAN now has a valid ISO-13616 checksum (the product rightly ignores invalid IBANs: 169 of 172 "leaks" were an artifact); XML well-formedness is now checked on the output.

## Natural-hit triage (entities replaced that were not injected; rule-based by `tools/eval_triage.py`, hand-checked on the printed samples)

Rule table (counts regenerated by `python tools/eval_triage.py`): 5330 unique natural replacements: TP 41 %, TP? 43 % (single capitalised words, public figures in encyclopaedic text, macro-regions),
FP 16 % (sentence fragments tagged ORG, adjective forms tagged COUNTRY, `wikidata.org/entity/...` DOMAIN, FILE `image`, TERM `data1`).
By kind: CITY/ADDRESS/USERNAME/EMAIL ~100 % TP; PERSON 3 % FP; COUNTRY 16 % FP (adjectives); ORG 17 % FP; DOMAIN 46 % FP (public URLs); FILE/TERM 100 % FP.
Verdict: names/contacts are precise; ORG and DOMAIN detection over-fires on prose and public URLs (defect 9).
