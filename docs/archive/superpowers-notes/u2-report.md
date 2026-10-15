# U2: one primary action per result row

Result row (file chat): before 6-8 visible buttons (per brief); after 3 controls: the file name (opens preview), one primary "Сохранить", one "…" menu (44x44). The menu holds Просмотр, Открыть в программе, Сохранить как… for every version (result, original; restored when present).

| Check | Status |
|---|---|
| Single primary button per row, existing save handler kept | PASS |
| Row opens preview (name button stretched over the row, click + keyboard) | PASS (390: preview panel opened) |
| "…" menu: aria-haspopup/expanded, role=menu, ArrowUp/Down/Home/End, Tab, Escape returns focus, items 44 px | PASS (1440 + 390) |
| Восстановить stays beside the anonymize button (#btn-chat-anon switches label) | PASS (unchanged, tested) |
| Actions launch -> saved file (browser run: add file, Обезличить, Сохранить = download) | PASS, 3 actions |
| Contrast >= 4.5:1, text in row and menu (canvas-resolved) | PASS: 1440 light min 5.91, 1440 dark min 6.66, 390 dark min 6.66 |
| Targets >= 44 px at 390 (name 44, Сохранить 90x44, "…" 44x44, menu items 44) | PASS |
| No horizontal overflow at 390 and 1440; menu within viewport | PASS |
| Network: only 127.0.0.1 (no external resources) | PASS |
| No aria-pressed, no new accent use | PASS (tests/test_ws_u2.py) |
| Tests: u2 u1 p2a p2b p2d p1 s10a s13a s12c s12d s11a chat_ux_page webapp w12b desktop | PASS, 227 tests; only SelfCheck fails (gitignored office.js absent in worktree, expected) |
| Fixes on resume: `outline: none` removed, class renamed .row-menu, duration token without fallback (test_desktop PageContractTests green) | PASS |
| Showing "Показать в папке" / restored version items in the browser run | NOT DONE (native bridge only / no restored file in the run) |
| Light 390 and keyboard walk through the whole page | NOT DONE (row, menu and preview walked) |

Shots: docs/archive/shots/shots-u2/ (4 crops from the first worker). Method: local server on 127.0.0.1:8793, synthetic txt, Browser pane, transitions disabled while measuring contrast.
