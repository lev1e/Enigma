# S10A report: persistent AI composer in the file chat (branch ws/s10a)

## Done
- Top-right "ИИ-чат" button removed from the file-chat page; /ai route and ai.html unchanged.
- The AI message line (ai-chat.js dock) is now always mounted, last inside `.composer` below the drop zone, sticky to the bottom of the scroll pane, in empty drafts too. Enter sends, Shift+Enter newline, attach file kept. Conversation renders above in the page; history persisted as before (ai.bin, label form).
- Send in a draft with a configured provider creates the chat (`ensureAiChat`); with no provider, no chat is created and a Russian hint with link "Открыть настройки провайдера" (/ai) is shown. Sending turns the per-chat AI flag on.
- Server (`anonymizer/ai_chat.py`): `send` accepts `with_files`: anonymized text of the chat's files (label form, invisible marks stripped, max 3, never file names) goes through the existing prepare/guard path; outbound check stays mandatory and re-runs before sending.
- Edit by instruction (regex on verbs such as "поправь", "исправь", "перепиши" or `edit: true`): model must return the full file between `<<<ФАЙЛ>>>`/`<<<КОНЕЦ>>>`; text is restored locally and stored as a NEW file record "<name> (правка ИИ N)" with anon + restored blobs, step kind `ai_edit` ("Правка ИИ") rendered as a version row with Открыть/Сохранить like other versions. Original and earlier versions untouched.
- Fail closed: no block, unknown/removed/damaged labels, or non-text formats (docx/xlsx/pptx/pdf) give no version and a plain Russian note; the text answer stays in the conversation.
- SECURITY.md sentence updated (text formats only, fake provider only).
- tests/test_ws_w13a.py updated deliberately (button gone, composer after drop zone).

## Checks
| Item | Result |
|---|---|
| tests.test_ws_s10a (6) + w13a + w12b + chat_ux_page + webapp + s6e: 65 tests | PASS |
| Outbound leak in s10a tests (names, email, phone absent from every provider request) | 0 leaks |
| Edit creates new version, original kept, values restored locally | PASS (test) |
| Damaged labels / docx edit refused with note | PASS (test) |
| Browser screenshots (empty, file, conversation, edit row, 390 px, dark), focus ring, 44 px targets, layout jump at 390/1440 | NOT DONE (worker context limit) |
| test_desktop, test_ws_s9*, test_addin_chat | NOT RUN |

## Limits
- Real provider and real browser layout unverified; sticky dock inside a 70dvh scroll pane not eyeballed.
- Edit target is always the latest file with an anon blob; no per-file choice by name in the message.
- Text-format check goes by file extension. The owner screenshot was not present in the worktree.
