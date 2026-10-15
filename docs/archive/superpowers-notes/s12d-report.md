# S12D report: visual and accessibility pass over the file chat screen (branch ws/s12d)

Method: local server (127.0.0.1, synthetic chat with a txt, a docx with table, an xlsx with 2 sheets), Browser pane at 1440 and 390, light and dark (data-theme), contrast computed in page JS (canvas colour resolve, alpha composited, text nodes only, disabled controls skipped, measured after transitions settled), touch targets and scrollWidth measured in JS, keyboard via real key presses. Skills used: impeccable, design-taste-frontend (web rules: no side stripes, no gradient text, no emoji, project tokens and fonts kept).

## Findings
| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | High (a11y) | `#pv-body` was `aria-live=polite`: every file load replaced a whole table or text inside a live region, so a screen reader would read the entire xlsx | Fixed: live region removed, `aria-busy` during load, one short announcement ("Показано: имя, вкладка") through the existing `#sr-status`; error and empty messages are announced too |
| 2 | Medium (a11y) | Successful AI reply was not announced (only errors and edit notes were) | Fixed: "Ответ ИИ получен." in the composer status (role=status) |
| 3 | Low (a11y) | Composer Enter / Shift+Enter behaviour not exposed | Fixed: `aria-keyshortcuts` and tooltip; behaviour itself verified (Shift+Enter newline, Enter sends, text kept on error, focus stays) |
| 4 | Low (visual) | Selected sheet tab differed from others only by a faint fill | Fixed: border uses `--text` when selected |
| 5 | Info | Desktop controls are 32-34 px high at 1440 (mouse); at 390 and `pointer: coarse` all buttons and tabs are 44 px, checkboxes are 20 px but their labels are 44 px | Not changed (existing design rule) |
| 6 | Info | xlsx merged cells still shown as a plain grid | Not fixed (from s12c) |

## Checks
| Check | Result |
|---|---|
| Contrast >= 4.5:1 (3:1 for large) on whole chat screen with panel open: 1440 light, 1440 dark, 390 light, 390 dark | PASS (0 failures once transitions end; frames taken mid theme-switch look translucent and give false lows) |
| scrollWidth = viewport at 390 (chat, panel xlsx) | PASS |
| Touch targets at 390 | PASS (see 5) |
| Tab order from header: title, Просмотр, Замены, details, file rows, composer; focus ring 2 px solid visible on each | PASS |
| Landmarks: nav "Главное меню", aside "Чаты", main, aside "Замены", aside "Просмотр файла"; panel tabs role=tab/tabpanel with aria-labelledby; message list `ol` with label | PASS |
| Composer Enter / Shift+Enter | PASS |
| Panel announcement after fix (sr-status text read back in browser) | PASS |
| No side-stripe borders, gradient text, emoji in index.html and ai-chat.js | PASS (grep, tested) |
| Reduced motion | PASS by CSS inspection and tests (global rule and `.pv` rule); not emulated in the pane |
| Escape and focus return at 390 | Not re-run (covered in s12c, code untouched) |
| Full desktop keyboard walk through the panel tabs and sheet tabs | NOT DONE (only header and file rows walked) |
| Mouse drag of resize handle, merged cells | NOT DONE |
| Tests: s12d (8) + s12c + s11a + chat_ux_page + webapp = 72 OK | PASS |

Shots (pane crops, scale 0.5): docs/archive/shots/shots-s12d/01 xlsx 390 dark (before), 02 docx 1440 light, 03 txt 1440 dark.

## Unverified
Real screen reader output (only the text placed in the live region was read back). Visual polish by eye is limited to 400x250 crops. Security behaviour untouched (CSP, sanitising, no original in the anonymized tab).
