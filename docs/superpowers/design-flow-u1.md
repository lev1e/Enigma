# U1: anonymizer first, AI second (flow audit and target)

Owner feedback: "Why are there anonymization AND adding files AND a search bar there? We are first of all an ANONYMIZER."

## Audit (before; real page, local server, synthetic doc, Browser pane; counts = visible interactive controls, closed details excluded)
| State | Visible controls | AI-related among them |
|---|---|---|
| Empty, AI not configured | 21: side toggle, profile, new chat, **search field**, chat title, "О чате", 3 example prompts, "Выбрать файл", "Изменить, что скрывать", "Обезличить", AI "+" , AI textarea, AI send | 6 (examples, +, textarea, send; plus AI wording in the drop note) |
| File added, AI configured | 16 (+ model picker) | 5: examples x3, "+", textarea, send, model picker |
| Result ready, AI configured | the same + file row buttons | AI bar identical to the empty state |
| AI not configured, result | as row 1 | the AI bar and examples shown although no provider exists |

Problems: (1) the AI composer, examples and model picker show before any result and even without a provider; (2) after the first file the add zone becomes a second text row "Добавить ответ ИИ или ещё файл" next to the AI "+" that also attaches files: three ways to add a file; (3) the search field is always on screen for a list of 1-2 chats; (4) the drop note talks about AI.
Actions to first saved result today: open app, choose/drop file, Обезличить, Сохранить = 3 after the app opens, 4 counting the open; the screen offers 20+ other things meanwhile.

## Target flow (adopted)
1. Empty: one drop zone "Перетащите файлы сюда или выберите", drop anywhere in the window (already wired: window drop handler). No AI element in the DOM-visible tree.
2. With files: list/status/result, Сохранить, Просмотр; the add zone shrinks to one "+" ("Добавить файлы"); no second add row.
3. AI progressive: a provider is configured and enabled (existing `GET /api/ai/providers`: `items` with `saved`/`local`, `enabled`) AND the chat has at least one anonymized result -> a calm bar "Спросить ИИ" with input + send + one "Параметры" button (4 visible). Under "Параметры": model, files with source choice (Исходный/Обезличенный), attach, show request, clear, AI on/off, provider settings. File chips only with more than one file; selection chip and proposals only when elements are selected or proposals exist. Examples and "Чем помочь" block are removed from the page. Not configured: nothing, the entry is "Провайдер и ключ" under settings.
4. Search hidden; Ctrl/Cmd+K opens it, only when the history has more than 3 chats (icon on the narrow rail follows the same rule). Sidebar = list.
5. Восстановить stays next to Обезличить, same size.
6. One primary action per screen (Обезличить, then Сохранить); the rest is secondary/menu.

## Deviations
- "Параметры" is the former "+" menu (same keyboard model, items kept) rather than a second disclosure, to avoid two overlapping menus; the model select lives inside it.
- No backend flag added: the existing providers endpoint already says whether AI is configured; the bar simply reads it.
- The drop note no longer mentions AI; the restore hint wording stays about "обезличенный файл".

## Success metrics (verified in u1-report.md)
Clicks to first saved result <= 3 after the app is open; AI elements visible at rest <= 4 and 0 without a provider; one add-files control after the first file; search hidden by default; 1440 light / 390 dark: contrast >= 4.5, targets >= 44 px at 390, no overflow, network 127.0.0.1 only.
