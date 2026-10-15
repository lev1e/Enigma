# U1 report: anonymizer first, AI second (branch ws/u1)

Design and audit: docs/superpowers/design-flow-u1.md. Method: local server on 127.0.0.1 (harness outside the repo), synthetic txt, fake provider, Browser pane.

## Before / after (visible interactive controls, closed details excluded)
| State | Before | After |
|---|---|---|
| Empty, AI not configured | 21 (3 example prompts, AI "+", textarea, send, search field, ...) | 8 (side toggle, profile, new chat, title, "О чате", "Выбрать файлы", "Изменить, что скрывать", Обезличить); 0 AI, search hidden |
| File added, AI configured | 16 (AI: examples x3, +, textarea, send, model picker = 7) | 9 (file x, Выбрать файлы, ...); 0 AI before a result |
| Result ready, AI configured | AI bar always shown, 7 AI controls | AI bar 3 visible (Параметры, input, send); chips 0 with 1 file |
| Result, AI not configured | AI bar still shown | none |

## Changes
- ai-chat.js: bar and dock hidden unless provider saved/local AND enabled AND >=1 anonymized file (`sync()`); empty-state greeting and examples never shown; file chips only when >1 file; model picker, hint, files/version, attach, show request, clear, AI switch, provider settings all in one "Параметры" menu (the former "+" button, sliders icon); placeholder "Спросить ИИ про эти файлы" ("Спросить ИИ" on phones).
- index.html: drop zone "Перетащите файлы сюда или выберите", after the first file one "+" ("Добавить файлы", 44 px) and no second row; drop note has no AI wording; chat search hidden by default, Ctrl/Cmd+K opens it only when the list has more than 3 chats (rail icon follows the same rule), closes on blur when empty.
- No backend change (existing /api/ai/providers gives saved/local/enabled).
- Tests: tests/test_ws_u1.py (11 static page checks); tests/test_ws_s13a.py placeholder assertions updated (deliberate rename). Security assertions untouched.

## Checks
| Check | Result |
|---|---|
| Targeted suites (p2a p2b p2d p1 s10a s13a s12c s12d s11a s11c chat_ux_page webapp w12b desktop + u1) | PASS (225 + 11 run; only desktop SelfCheck fails: gitignored office.js, allowed) |
| PageContract tests (accent count, no aria-pressed) | PASS |
| Clicks to first saved result: choose/drop file, Обезличить, Сохранить | 3 (Сохранить path not clicked end to end; steps 1-2 run in the browser) PARTIAL |
| AI visible at rest <= 4 | PASS (3); 0 without provider |
| Search hidden at rest; Ctrl+K no-op with 1 chat, opens and focuses with 4 chats | PASS |
| Keyboard: Shift+Tab from input to Параметры, Enter opens menu on first item, Escape closes, focus back | PASS |
| 390 dark: contrast (24 text nodes, min 5.23, none <4.5), all buttons/selects/summaries >= 44 px, scrollWidth 390, origins only 127.0.0.1 | PASS |
| 1440 light contrast, 1440 overflow | NOT DONE (same tokens as s13a; pane small) |
| Model picker select inside the menu with keyboard (Tab, arrows) | NOT DONE (Escape handled in code) |
| Screenshots | 1 pane crop in docs/archive/shots/shots-u1/ (menu captured mid-fade); others NOT DONE |

## Open
- The result card in the feed still carries 6-8 row buttons (Показать/Открыть/Сохранить как per file, "Сохранить файл для ИИ", "Скопировать подсказку", "Скрыть ещё слова", "таблицу замен"): rule 6 (one primary action, rest in "...") is NOT DONE for the result area.
- "Выбрать папку" and the answer-folder button remain as before when a folder is pickable.
- Drop anywhere in window relied on the existing window drop handler (not re-tested by an actual drag).
