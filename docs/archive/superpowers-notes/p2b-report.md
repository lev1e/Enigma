# P2B report (branch ws/p2b): backend done and tested

## State
- Backend complete: anonymizer/ai_docedit.py (context, prompt, patch parsing, validation, cards), anonymizer/ai_chat.py (office path in send, `_propose`, `POST /api/ai/chats/<id>/patch`, chat view `proposals`). Contract for the frontend: docs/archive/superpowers-notes/p2b-contract.md.
- tests/test_ws_p2b.py (17 tests, fake provider, synthetic files): text and design edits for pptx/docx/xlsx, apply all and subset, reject, rejected patches (stale expect, unknown label, unknown address, broken JSON, plain-text reply, echoed secret mask), selection, original source, text-file path unchanged, outbound guard, persistence.
- Targeted suites (p2a p1 s10a s13a s11a s12c s12d chat_ux_page webapp w12b llm_edits p2b): 175 tests green.

## Fixes found while testing
- The outgoing guard blocked every Office edit: Latin style/layout/font names, `RRGGBB`, `JSON-...` in the system prompt, and guillemets around slide/sheet titles looked like company names. Now: layouts and paragraph styles are sent as numbers (`макет 3`, `стиль 5`) and mapped back to names before validation (`ai_docedit.aliases/unalias`), fonts are not listed, titles are plain, prompt rewritten. The guard itself is unchanged.
- Pending proposals are now stored in the encrypted chat data (survive restart / second window), max 10 per chat.
- Edited original with no anonymized copy: the apply response `note` now carries an explicit Russian warning.
- tests/test_ws_s10a.py: the "unsupported format" sample was a docx, which is editable now; it uses a pdf.

## Known
- tests.test_desktop SelfCheck `addin_https_page` fails in this worktree only: the git-ignored anonymizer/addin_web/vendor/office.js is absent here (passes in the main checkout). Not caused by P2B.
- Not done here (P2D): selection UI, cards, announcements in the page, preview addresses. No browser verification.
- Paragraph-level text with Latin words can still trip the guard (same as for any text file); the user then sees the usual blocked message.
