# Design spec S13A: file chat as a classic comfortable AI chat

Sources: four ChatGPT screenshots from the owner (sidebar, centred column, file card, quiet reply icons, pill composer, right tab-like preview panel). Project tokens, fonts and security guarantees stay; no new libraries.

## Audit of the current file chat (before)
- Composer is a boxed form: checkbox "ИИ включён для этого чата", link "Провайдер и ключ", then up to five text buttons (Прикрепить файл, Показать запрос, Очистить беседу, Остановить, Отправить). Loud, hides the main action in a row of equals.
- Messages are left/right bubbles up to 72ch, no hover actions, a full-width text button "Сохранить ответ с возвратом значений" under every AI reply. Typing is the plain text "ИИ отвечает…".
- Empty state is two sentences without anything to click.
- Which files the AI sees is implicit (latest 3 anonymized files); the user cannot choose, and the composer does not say.
- Panel header: file name as a heading plus a "Закрыть" text button; no way to switch file without going back to the chat.
- Motion: only message fade-in; send and stop are two different buttons, no morph.

## Adopt (from the references) and why
- Pill composer, "+" on the left, round send on the right, one quiet hint line: one obvious main action, the rest out of sight.
- Context chips inside the composer: the owner wants per-message file choice; chips show it at a glance, "+" menu lists chat files with checkboxes.
- Centred column 740 px, generous leading: readable at 1440 and 390.
- Quiet hover/focus icons under an AI reply (copy, save with values restored): the save button stays reachable but stops shouting.
- File result as compact card (type icon, name, kind, state) opening the panel; this is what the existing "Просмотр" row buttons already do, now with a card look in the AI message when a reply created a version.
- Panel as a tab: file switcher on top, compact tabs (Обезличенный / Исходный / Версии), close.
- Soft typing dots, send-to-stop morph, skeleton in panel: feedback with 150-250 ms transform/opacity, off under prefers-reduced-motion.
- Empty state with three clickable examples in Russian.

## Deliberately skip
- Folders/projects in the sidebar, voice input, model/effort selector, regenerate, thumbs, share: not features of this offline tool, or they would be dead buttons.
- "Запросить правку" button in the panel: editing is already a chat message ("поправь ..."); a second entry point would be a duplicate.
- Zoom in panel: previews are structured data, not a page render; browser zoom works.
- Rendering the file as the original page (real Office layout): needs a renderer; out of scope, would risk the sanitising guarantees.
- "Показать запрос" and "Очистить беседу" are not removed: moved into a "..." menu in the composer row (one button, three items: show request, clear chat, provider settings). The per-chat "ИИ включён" checkbox becomes a menu item with state, send still enables AI automatically.

## File selection rule
Default: all current chat files that have an anonymized version (backend still caps at 3 and the size limit). The composer sends `file_ids`; the server intersects with the chat's own files (unknown ids ignored), an empty list means no files. Original and restored versions are never selectable: only anonymized text can leave.

## Tokens and motion
Existing `--s*`, `--r-*`, `--field`, `--line`, `--muted`, `--dur-2`, `--ease`. Durations 150-250 ms, transform and opacity only, ease-out, no bounce. Hover icons are visible (not hover-only) on touch and on keyboard focus.
