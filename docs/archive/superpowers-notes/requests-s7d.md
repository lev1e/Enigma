# Requests from S7D to S7C (detectors/entities)
1. strict=True: in "Компания Альфа-Групп и Ромашка ... Альфа-Групп отгрузила товар" the first occurrence becomes Term1 but the sentence-initial second "Альфа-Групп" stays visible (observed via tests/test_ws_s7d.py sample). Same entity must be hidden everywhere once any occurrence is hidden.
2. keep_terms=["Иванов"] does not un-hide the surname inside the full name "Иван Иванов" (full name stays Name1; only the full string in keep_terms keeps it). Decide if intended; the UI hint says "слова, ошибочно принятые за имена".
