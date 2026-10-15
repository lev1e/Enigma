# Requests from W3d
- entities.py / geo_data.py owner: country adjectives ("российский", "китайские") are hidden as COUNTRY by design (settings hint says so); if over-redaction is unwanted, add an option or exempt the owner's own country adjective. Not changed here (not owned).
- entities.py: CITY inside a public URL (https://ru.wikipedia.org/wiki/Москва) is replaced, which breaks the link. Suggest skipping geo hits inside URLs of PUBLIC_SITE_SUFFIXES (detectors.py).
- W6 corpus v2: item v2_person-0016 contains "1975 г.р." unlabeled; a bare birth year with "г.р." is real personal data. Label it BIRTH_DATE, then W3 can add the bare "NNNN г.р." rule (dropped here to keep the v2 BIRTH_DATE precision gate).
