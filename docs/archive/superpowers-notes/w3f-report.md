# W3f report
Synthetic decks (python-pptx) and line batteries reproduce no 130-ORG explosion on their own; the cascade comes from
one-word company names that are ordinary words (e.g. «Рынок», «Мир», «Север»): every other form / cognate adjective was
hidden as ORG/REGION ("Другая форма известного названия").
Fixes (entities.py): `_plain_word_org` guard in `_inflected`; generic direction adjectives (Центральный/Северный/Южный/
Западный/Восточный) before офис/склад/завод/отделение/управление/дирекция no longer REGION.
Gates: v1 676/679 fp2, v2 110/110 fp0, EN 798/800 fp1, noise 0. Tests: tests/test_ws_w3f.py + ru4/w3d/w3e/orch4 OK.
Remaining: bare Title-Case region adjectives (Сибирский, Приволжский) are AUTO REGION; countries/continents are hidden
as COUNTRY/REGION by design; "LinkedIn, VK" matched as PERSON (Latin initials rule, detectors.py, not touched).
