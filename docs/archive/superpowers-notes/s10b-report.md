# S10B report: browser check of the S10A bottom composer

Method: own dev server with fake provider (seeded draft chat, anonymized txt chat), headless Chrome emulation 1440x900 and 390x844 (mobile, touch), light and dark, real keyboard for Enter / Shift+Enter via the Browser pane. Shots: docs/archive/shots/shots-s10b/ (pane crops, some 390 shots are 2x).

| Item | Result |
|---|---|
| Empty draft, 1440 / 390 | PASS (390 shot 01) |
| Chat with anonymized txt, conversation, edit row "Правка ИИ", dark + light, 1440 + 390 | PASS (shots 02-08) |
| Layout stability: composer top fixed after answer arrives (605 -> 605), growing textarea grows upward with bottom fixed (891), no content jump | PASS |
| Composer never covers content: at 390 it covered 60% of the screen (drop zone + settings sticky) | FAIL, FIXED: <=720px only the AI line is sticky, drop zone scrolls with the feed (dock 255 px of 844) |
| Bottom padding: content ends above composer, drop zone and "Обезличить" reachable by scroll | PASS |
| Focus ring on textarea visible (shot 02, 06) | PASS |
| Targets >= 44 px in composer | FAIL at 1440 (40 / 32 px), FIXED in ai-chat.js; JS audit: 0 below 44 at 1440 and 390 |
| No horizontal scroll 1440 / 390 | PASS |
| Enter sends, Shift+Enter newline | PASS |
| File attach from composer (chip appears, textarea unaffected) | PASS (simulated file input change) |
| No provider: Russian hint + link "Открыть настройки провайдера" -> /ai?chat=<id>, no chat sent | PASS |
| Old /ai route | PASS (200) |
| AI answer showed raw <<<ФАЙЛ>>> block with the whole file text | FAIL, FIXED: block replaced in display by a short note (stored text unchanged) |
| Placeholder wrapped and clipped at 390 | FIXED: "Сообщение ИИ или правка файла" |

## Tests
tests.test_ws_s10a, w13a, w12b, chat_ux_page, webapp, s6e, desktop: 107 run, 1 failure (SelfCheck, known, no vendor/office.js). No test change needed.

## Observed, not changed
- User bubble echoes the label-form file text sent to the provider (by design, shows exactly what leaves).
- Empty chat on 1440 composer takes about 45% of height (drop zone + options above the AI line).
- Attach chip is named "attachment", not the file name (names never leave the machine).
