# Requests from S7A
- ner.py (owner?): `_raw_spans` runs slovnet per 400-char-ish chunk with no cache above 4000 chars; ~26 % of the 12 MB run. Options that keep output identical: memoise `_raw_spans` per chunk text (helps repeated lines only), batch several chunks per `tagger.infer` call, or skip chunks with no capitalised/Cyrillic-name-like token that `_clean` could ever accept.
- entities.py: explicit_spans (~17 % cum): `_known_hits`, `_geo_intros`, `country_hits`, `_gazetteer_hits` each rescan the whole chunk; a shared lowercase/word index per chunk would cut it.
- detectors EN_NAME_RULES 0/1/9/11: label alternation is tried at every word boundary; anchoring on the separator `[:\-–—]` first would be exact but restructures the rules (S7C territory).
