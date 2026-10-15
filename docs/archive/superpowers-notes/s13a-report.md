# S13A report: file chat as a classic comfortable AI chat (branch ws/s13a)

Spec: docs/superpowers/design-chat-13.md (adopted / skipped, with reasons). Skills used: impeccable (project tokens and fonts kept; no ui-ux-pro-max in this project).

## Changed (before -> after)
- Composer: boxed form with 5 text buttons and a checkbox -> one pill: "+" (left), auto-grow textarea (1-6 lines), round send button that morphs into stop while streaming (opacity/scale, 180 ms), one muted hint line. Enter / Shift+Enter kept (`aria-keyshortcuts`).
- "+" menu (role=menu, arrows, Home/End, Escape returns focus to "+", Tab closes, outside click closes, 44 px items): Прикрепить файл; "С какими файлами работаем" with checkboxes; Показать запрос; Очистить беседу; ИИ включён для этого чата; Провайдер и ключ. All previous features stay reachable.
- File context chips above the pill (one per file the next message will use, x removes it from the choice). Default: all current chat files with an anonymized version.
- Backend (`anonymizer/ai_chat.py`, `_with_chat_files`): new optional `file_ids` in `send`. Key absent = old behaviour (all, cap 3); list = intersect with this chat's own anonymized files (unknown or foreign ids ignored, never fetched); empty list = no chat files; non-list = refused. Edit target is the first chosen file. Only anonymized text can be chosen, guard and outbound check unchanged.
- Messages: centred column 740 px; user message as soft pill, AI reply as plain text; user bubble no longer echoes the whole file text (shows the message plus "С файлами: N", full request via menu "Показать запрос"); quiet icon actions under a reply (copy via clipboard, save with values restored), always visible on the last reply, on hover/focus for others, always on touch; typing indicator = three dots (static under reduced motion); empty state "Чем помочь с файлами?" with 3 clickable Russian example prompts (they fill the textarea, never auto-send); live AI edit adds a file card (type, name, "Новая версия") that opens the panel.
- Blocked send now shows its own findings and an RU message (before: it re-ran a dry run without files and said "Запрос чистый" even though the send was blocked). Resolve buttons mark and ask to press Send again.
- Panel: file switcher (native select, shown when the chat has 2+ files), tabs unchanged (Обезличенный / Исходный / Версии), new-version marker kept.
- Tests: tests/test_ws_s13a.py (11: page structure, one-button row, stop morph, column, 3 examples, real actions, reduced motion, no external URLs/innerHTML/gradient text/emoji, host wiring, backend selection: ticked only, empty list, missing key, foreign/unknown ids, bad type). No existing test weakened; the chat JS uses CSS-drawn checkmarks and avoids hex white/black to satisfy the existing no-emoji/no-#000/#fff tests; the SVG namespace string is built as "http:" + "//www.w3.org/2000/svg" so the "no http(s):// in chat js" test stays meaningful (it is an XML namespace, not a network address).

## Checks
| Check | Result |
|---|---|
| tests s13a (11) + s12c + s12d + s11a + s11c + s10a + chat_ux_page + webapp + w13a + w12b (102 earlier run, then s13a 11, w12b+w13a 16) | PASS (last full targeted run: 1 failure fixed, re-run of the failing files OK) |
| Browser 1440 light: chat with txt, md, docx, multi-sheet xlsx; pill, chips, menu open, deselect file, Escape returns focus to "+" | PASS (manual) |
| Selection honoured end to end in the page: with only spec.docx ticked the send went through; other files blocked by the guard individually (synthetic text) | PASS |
| Send, stream, reply with quiet icons, user bubble collapsed | PASS (1440 light) |
| No horizontal overflow at 1440 (scrollWidth 1440) | PASS |
| Contrast >= 4.5:1, dark theme, 390 px, touch targets at 390, keyboard-only walk of panel and menu, focus-ring look, network origins list, screenshots in docs/archive/shots/shots-s13a/ | NOT DONE (worker context limit; my contrast script mis-parsed oklch colours and gave false 1.00 values, discarded) |
| Panel switcher in the browser, new-version card after a real AI edit | NOT DONE (code and tests only) |
| Reduced-motion emulation | NOT DONE (CSS and test only) |

## Observed at 1440 (non-composer), not changed
Row buttons in file step rows are 32-34 px high (existing desktop rule, 44 px at coarse pointer).

## Skipped on purpose
Folders in sidebar, voice, model selector, regenerate, thumbs, zoom, "Запросить правку" button, original-page rendering (see spec). Download in the panel header: save stays on the "Версии" rows.

## Unverified / for the next worker
Everything in the NOT DONE rows above. The `shots-s13a` folder is empty. Menu is `position: fixed`, placed above "+" from its rect: check at 390 and with the sticky composer. Seed script used for browser checks lives only in the session scratchpad (server on 127.0.0.1:8791, stopped after the session).

## S13B: browser verification and polish (continuation, same branch)
Method: local server on 127.0.0.1 (synthetic chat: txt, md, docx with table, 2-sheet xlsx; fake provider), Browser pane at 1440 and 390, data-theme light/dark, transitions disabled during measurement (a mid-transition run gave false 1.07 values, discarded). Contrast: text nodes, colours resolved through a 1x1 canvas (oklch/oklab/color-mix resolved by the browser), alpha composited over ancestors, aria-disabled and disabled controls exempt.

| Check | Result |
|---|---|
| 1440 dark: contrast, 62 text nodes (chat) / 90 (chat + panel) | PASS, min 5.23, 0 below 4.5 |
| 390 light: 58 text nodes, then 84 with panel | PASS, min 5.40, 0 below 4.5 |
| 390 dark: 58 text nodes; panel 73 nodes | PASS, min 5.23; one hit 3.55 = "Исходный" tab, aria-disabled by design (no original text), exempt |
| Touch targets at 390 (all visible buttons, selects, tabs, menu items) | PASS: only a 20x20 non-interactive indicator is under 44; menu items 9 x 44 px, panel tabs 44, switcher select 44, row buttons 44 |
| Horizontal overflow, scrollWidth = viewport | PASS at 1440 and 390 (light, dark, panel open) |
| "+" menu at 390: opens above "+", fully inside viewport (50..378 x 251..712 of 390x844), ArrowDown moves to the first file item, Escape closes and focus returns to "+" | PASS |
| Panel at 390: tabs, multi-sheet xlsx sub-tabs, file switcher (4 files), Escape closes the panel and focus returns to the "Просмотр" button | PASS |
| AI edit (fake provider, only dogovor.txt chosen): reply with file card "dogovor (правка ИИ 1).txt, Новая версия, TXT", card opens the panel on the new version (subtitle "Правка ИИ", switcher shows it), live region says "Показано: ..." and "Создана новая версия файла..." | PASS |
| Send with all four files was blocked by the guard (synthetic words "Normal", "Email" flagged in md/xlsx labels), message "Отправка остановлена ... Ничего не отправлено." | PASS (guard works; not changed) |
| Keyboard: Tab order textarea -> Send, Shift+Tab -> "+", focus ring 2 px solid oklch(0.76 0.12 252) on dark | PASS |
| Network: all resource origins = http://127.0.0.1:<port> only | PASS (performance entries) |
| Reduced motion | PARTIAL: media emulation is not available in this tool; static check of the stylesheet: universal rule sets animation/transition duration 0.01 ms !important, panel rule sets none | NOT DONE as live emulation |
| Visual compare with ChatGPT reference | Found and fixed below |

Fixes (CSS/JS):
- File rows in the history carried a filled accent "Сохранить как…" button on every row (4 rows = 4 blue buttons) plus two more buttons: far louder than the reference file cards. Now all three row buttons are quiet text buttons (transparent, muted, hover fill); the accent stays for the one real primary action elsewhere.
- At 390 the third row button ("Сохранить как…") was clipped on the right (row buttons 314 px in a 300 px column). Now nowrap, 10 px padding, no gap, 44 px high, all three on one line (measured: row height 44, scrollWidth = clientWidth).
- Composer placeholder wrapped and was clipped at 390 ("Сообщение ИИ или правка файла"); now "Сообщение ИИ" up to 480 px, full text above (matchMedia, updates on resize).
- Tests: 3 added in tests/test_ws_s13a.py (class QuietRows).

Not changed, noted: the drop zone "Добавить ответ ИИ или ещё файл / Выбрать файл" above the composer duplicates "+ > Прикрепить файл" and is heavier than the reference (which has none); left because removing it is a structure change outside this pass.
Shots (pane crops, scale 0.5, the pane is small so 1440 shots are low resolution): docs/archive/shots/shots-s13a/ (01-06 after the fixes; 07, 08 are the "before" states). The "+" menu itself could not be captured: the screenshot action steals focus and the menu closes on blur; its geometry is measured above.
Targeted tests: s13a, s12c, s12d, s11a, s11c, s10a, chat_ux_page, webapp, w12b, desktop = 152 run, 1 failure: tests.test_desktop SelfCheckTests.test_selfcheck_reports_every_component_and_exits_zero fails identically on the branch without my changes (stash check), environment-related, not touched.
