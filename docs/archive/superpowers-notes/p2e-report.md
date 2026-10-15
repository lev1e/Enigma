# P2E report: page-contract fixes and end-to-end check of AI editing (branch ws/p2e)

Method: real server on 127.0.0.1 (harness outside the repo), fake provider returning valid JSON patches, synthetic 3-slide pptx, docx (with table), xlsx. Browser pane at 1440 light and 390 dark. Selection driven by real mouse click and keyboard (arrows, Space), sends by the composer.

## Fixes
- index.html: selectable preview elements use role="checkbox" + aria-checked (no aria-pressed); selected state = text-colour 2 px outline on --select, focus ring = --text outline; no accent and no shadow (accent count back under the limit, shadows stay floating-only). tests/test_ws_p2d.py updated. The two PageContract tests pass unchanged.
- ai_chat._body_text: pptx slideLayouts/slideMasters/notesMasters placeholder text ("Click to edit Master...") is no longer sent. It produced 172 leak-guard false positives, so any stock pptx was blocked (P2D request 1). Test added.
- ai-chat.js: the raw ```json patch block no longer shows in the AI reply (cards replace it). Test added.
- docedit.diff_summary: design cards read "оформление текста: размер 28, жирный да" / "ширина колонки: ширина 40" instead of JSON. Test added.

## Results
| Check | Result |
|---|---|
| Two PageContract tests (accent count, no aria-pressed) | PASS |
| pptx (3 slides): click + keyboard selection (Arrow, Space), chip "Выделено: ...", send, 2 cards было (struck) / стало | PASS |
| Apply one card, apply all: new file "deck (правка ИИ N).pptx", "Новая версия" marker, original deck.pptx and earlier versions kept, panel shows new text | PASS |
| Reject: "Правки отклонены. Файл не менялся." | PASS |
| Rejected patch (unknown address): Russian reason "Правка не применена: Неизвестный адрес элемента (операция 1, s99.sh9.p9). Файл остался прежним." | PASS |
| docx: select paragraph, 2 cards, apply all, new version "memo (правка ИИ 1).docx" | PASS |
| xlsx: select cell, 2 cards, apply all, new version; design request (col_width) card + apply | PASS |
| Design-only request on pptx (set_style) | NOT DONE in browser (xlsx design done; set_style covered by test_ws_p2b) |
| 1440 light contrast >= 4.5 (oklch via canvas): was/now/labels 5.9, text 16.6, buttons 13.9, selected element 13.4, outline vs surface about 4.9 | PASS |
| 390 dark contrast: cards 6.7 to 13.4, buttons 11.3 | PASS |
| 390 targets >= 44 px: preview elements 44, chip remove buttons 44x44, card buttons, send, plus | PASS (chip body itself is 34 px high, not interactive) |
| No horizontal overflow at 1440 and 390 | PASS |
| Network: only 127.0.0.1 | PASS |
| Keyboard-only walk: composer, chips, Выбрать файл, message actions, card buttons reachable in order, 2 px focus outline everywhere; panel: Arrow/Space | PASS |
| Targeted suites (225 tests: chat_ux_page, desktop, webapp, p1, p2a, p2b, p2d, s10a, s11a, s11c, s12c, s12d, s13a, w12b) | PASS except desktop SelfCheck (gitignored office.js missing in worktree; allowed) |

## Open / notes
- Leak guard still flags capitalised synthetic Russian words in plain (non-edit) sends of the deck as POSSIBLE_ENTITY (6 hits); the harness used lower-case text. Real users get "Разрешить один раз".
- With all chat files ticked, an edit send still attaches the other files' text, so a hit in an unrelated file blocks the edit; untick them (x) as in the test.
- At 390 the preview overlay hides the cards; the user closes it (selection chip stays) and sees them. Cards show struck-through "было" without a text label (стало has one); screen-reader text for "было" not added.
- Shots: docs/archive/shots/shots-p2e/ (4 pane crops at scale 0.5; 1440 pane crops are small because the pane renders at reduced size).
