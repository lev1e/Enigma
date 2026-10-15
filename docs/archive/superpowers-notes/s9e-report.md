# S9E report: UI verification and fixes (branch ws/s9e)

Method: tools/dev_server.py on :8795 plus tests/llm_fake.py as a custom offline provider (real provider not tested), Browser pane tab, dark theme at 1280x800 unless noted. Scripted file drops, real DOM clicks. Screenshots in docs/archive/shots/shots-s9e/.

| Feature | Result | Evidence |
|---|---|---|
| Single file (txt, 8 values replaced) | PASS | 01-single-file-dark-1280.jpg |
| Per-kind switch (EMAIL off in Settings, Done): contacts 2 -> 1, replaced 8 -> 7 | PASS | 02-per-kind-switch-email-off-dark.jpg |
| Restore (answer file with Name1/Phone1/Inn1, 3 values restored) | PASS | 03-restore-and-inline-ai-chat-dark.jpg |
| AI chat inline (send, streamed fake reply, "values restored locally") | PASS | 03 |
| Review list ("Программа не уверена в 2 словах", select one, "Скрыть выбранное": 2 -> 1 words, replaced 1 -> 2) | PASS | 04-review-list-hide-selected-dark.jpg |
| Hide/keep terms (hide "Сапсан-7" -> Term2; keep "Ромашка" -> no Company1) | PASS (text check; screenshot overwritten, not saved) | DOM text |
| Backup (password prompt, download anonymizer-backup.anonkeys triggered) | PASS (download intercepted, file content not inspected) | DOM |
| Updater ("Версия 2.2.0. Установлена последняя версия.") | PASS UI; real network check unverified | 06-updater-about-dark.jpg |
| Folder/project (3 txt, project chat, per-file open/save rows) | PASS (picker stubbed via /api/native/folder; native save dialogs unverified) | 07-project-folder-dark.jpg |
| File chat (attach txt + send, reply) | PASS | 08-file-chat-attach-dark.jpg |
| /ai page (test connection, send, reply) | PASS | 09-ai-page-dark-1280.jpg |
| Settings 390 px: scrollWidth == clientWidth on all 7 tabs, light theme | PASS (S6B overflow fixed) | 11-settings-390-light-no-overflow.jpg |
| Dock below 600 px height (390x480) | FAIL then FIXED | 10-dock-390x480-static-composer-dark.jpg |
| Inline links < 44 px at 390 | only settings tabs (40 px) failed: FIXED; other controls >= 44 (checkboxes 20 px sit in labels) | JS audit |
| Focus rings by eye | NOT DONE (context ran out) | global `:focus-visible` rule exists; only `.split` overrides it deliberately |
| Settings at 1920 / 2560 screenshots | NOT DONE | |
| Light theme for the feature screens | only settings@390 checked | |

## Fixed
- Python user-facing strings in ai_chat.py, llm.py, chat_pipeline.py now Russian (about 60 messages; technical identifiers kept). No test pinned the English text; ai-chat.js keeps its English-to-Russian table as a fallback (test_ws_s6e pins it).
- index.html: composer was sticky at 60% of a 480 px viewport; now static at max-height 600 px. Settings tabs 44 px at <= 720 px.
- Observed, not changed: keystore.py still raises KeyError("No such provider") (not in my files).

## Tests
Run: llm/chat/web group (ws_llm_*, chat_*, llm_edits, project_chat, addin_chat*, webapp, ws_s6e): 209 OK. test_desktop+chat_ux_page+ws_s6e+webapp: 85 run, 1 failure test_desktop SelfCheckTests.test_selfcheck_reports_every_component_and_exits_zero, which also fails without my index.html change (not caused by it; python edits were already in).

## Unverified
Focus rings by eye, 1920/2560 settings, light theme of feature screens, real provider, outbound text of an attached file (chat shows restored text), Windows WebView2. The shared Browser pane was navigated by another worker once (tab "seed"); I used my own tab.
