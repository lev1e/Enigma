# S11A report: right preview panel in the file chat (branch ws/s11a)

## Adopted (structure and behaviour only, no code copied)
- Split view with a right artifact panel, opened from a file card, close button, Escape in overlay (Claude.ai Artifacts, LibreChat, LobeChat).
- Preview / source / versions tabs: "Обезличенный" / "Исходный" / "Версии" (Claude.ai, Open WebUI).
- Panel follows a new AI-edit version with a "Новая версия" marker (ChatGPT Canvas idea).
- Full-screen sheet below 900 px (all references). Details and licences: docs/superpowers/research-chat-ui.md (written from knowledge, not re-verified online).

## Built
- `anonymizer/preview.py` (new) renders to JSON data only: text with line numbers and placeholder segments, csv/tsv/xlsx tables (first 100 rows, "показаны первые N"), docx blocks (headings, paragraphs, tables), pptx slide text, pdf page as PNG (page by page, lazy), images as data URI. html/svg = escaped source text. Limits: 8 MB, 1500 lines, 24 columns, 400 blocks, 60 slides; anything else returns "none" with a Russian reason.
- Route `GET /api/chats/<id>/files/<fid>/<role>/preview[/<page>]` in chat_api.py. Placeholder segments only for anon/prev/ret; orig/restored return `local_only: true`.
- index.html: aside#pv (role=complementary, aria-label), button "Просмотр" in chat header and on every version/tree row, tabs with arrow keys, skeleton loading, Russian messages, light/dark via existing tokens, 44 px targets, reduced motion. Desktop: fifth grid column 36vw (340-640 px); opening it closes the replacements pane below 1800 px. Focus goes to the active tab on open and back to the opener on close.
- Open/closed state is stored in app prefs (`preview_open`, vault.py + webapp.py PAGE_PREFS), NOT localStorage: the existing contract test forbids localStorage because the window origin changes each launch.

## Checks
| Item | Result |
|---|---|
| tests/test_ws_s11a.py (14: each format, HTML not executed, size limit, broken file, no original in anon tab, 404 roles, panel code has no innerHTML) | PASS |
| s11a + s10a + w13a + w12b + chat_ux_page + webapp + s6e + desktop + settings_schema: 132 run | 1 failure: SelfCheck (known, no vendor/office.js) |
| Browser 1440 dark: panel, original tab banner, xlsx table, pdf paging (1 -> 2), versions list | PASS (shots 01-05) |
| 390 px overlay dark and light, no horizontal scroll (scrollWidth 375), Escape closes and focus returns to "Просмотр", 0 buttons under 44 px | PASS (shots 06-07) |
| 1920 light, remembered-open after reload | PASS (shot 08) |
| HTML file with script: shown as text, document.title unchanged, 0 script nodes | PASS |
| Anonymized tab contains no original value (browser and test) | PASS |
| Changed marker after AI edit | implemented, NOT exercised in browser (no real AI edit run) |
| 1440 light, keyboard-only walk of tabs, tooltip on chips by eye | NOT DONE |

## Limits
- Files outside the touched files: vault.py and webapp.py got a one-line pref each (needed for persistence).
- CSP is the page-wide one (the app needs unsafe-inline); the panel is safe because file content only reaches the DOM through textContent and data: images. No separate stricter CSP header per panel.
- xlsx shows the first sheet only; docx images/fields not rendered; pdf is rasterized (not selectable); text placeholders recognised by tokens.TOKEN_RE only.
- Main column is about 500 px at 1440 with the panel open (chat rows cramped); sidebar can be hidden with Ctrl+B.
- Shots are pane crops at scale 0.5; one dark narrow frame mid-animation was retaken.
