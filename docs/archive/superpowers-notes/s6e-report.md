# S6E report: UI pass (index.html, ai.html, ai-chat.js)

Method: tools/dev_server.py on port 8791, Browser pane, fake slow SSE provider (127.0.0.1:8792, custom kind), 3 txt files uploaded, widths 375/390/1440/1920/2560, light and dark, injected audit (horizontal overflow, text contrast >= 4.5, touch targets at <= 480 px).

## Fixed
- Settings modal at 390: `.set-sec` grid had an auto track, rows stretched to 451 px in a 372 px body. Now `minmax(0,1fr)` plus wrapping rows (`.srow`, select full width) at <= 720 px. After fix: scrollWidth = clientWidth on all 7 tabs at 390.
- Settings group header at phone width: count text ("5 из 5 + 5 защищено") no longer squeezes the title (wraps under it).
- Touch targets: 44 px for .btn, .btn.sm, icon-btn, rail buttons, chat title input, summary, link buttons at <= 720 px / coarse pointer (index.html, ai.html, ai-chat.js). Audit at 375/390: only inline text links (117x20) remain.
- AI composer on phones: actions in a 2-column grid; dock about 41% of 844 px instead of 60%.
- AI chat showed English server errors ("AI is switched off...", "Stopped", provider errors): mapped to Russian in ai-chat.js (RU table).
- Chip padding 2px moved onto the 4pt scale.

## Checked OK
- Multi-file job stage text is Russian ("Подготовка", "Файл 1 из 3: Изучаю имена и названия", "Готово"); 3 txt files finish in under 4 s so only one intermediate stage was observable.
- Inline AI chat: send, SSE streaming (40 chunks), Stop (status after stop, send re-enabled), attach row, sticky dock with both composers, last message stays above dock (scroll-padding via --composer-h).
- Settings: image-mode select shows warning (role=status) when "Закрасить текст"; natasha toggle ("Искать незнакомые имена нейросетью") present; DEVICE_ID, MEDICAL_ID, COMPENSATION rows present inside group "Личные документы".
- Contrast: 0 failing text nodes (non-disabled) at 375, 390, 1440, 1920, 2560, light and dark (chat view); /ai at 390 dark and 1440 light. No horizontal page overflow anywhere.
- Console: only errors caused by my harness (403 from calls without X-Requested-With, one TypeError from setting no upload mode, one 400 for the expected "AI off" send). None from normal use.

## Requests (Python owner, not changed)
- ai_chat.py / llm.py / chat_pipeline.py return English user-facing strings ("AI is switched off in the settings", "Stopped", "No provider is set up", ...). UI maps the known ones; better to localise at source.
- Focus ring: global :focus-visible rule exists; my programmatic focus() probe could not confirm rendering per element, so keyboard focus was not verified by eye.

## Not done / unverified
- Disabled primary button ("Обезличить") has 2.94:1 contrast (exempt as disabled, left).
- Dock at heights below 600 px not tested. Settings modal at 1920/2560 only measured via the page audit, not screenshotted.

## Screenshots (docs/archive/shots/shots-s6e/)
01-chat-1440-dark.jpg, 02-settings-image-mode-390-dark.jpg, 03-chat-ai-390-dark.jpg

Test: tests/test_ws_s6e.py (3 static checks, passing).
