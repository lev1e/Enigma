# P2D report (branch ws/p2d, forked from ws/p2b, merged with the P2C contract commit)

## Works (tested)
- preview.py: docx paragraphs and table cells, pptx slides and paragraphs (incl. table cells), xlsx cells carry the docedit address (taken from docedit.outline, same scheme the backend uses). Old fields kept; any outline failure = no addresses, preview as before. Tests: tests/test_ws_p2d.py (10 tests) plus s13a, s12c, s12d, s11a, chat_ux_page, webapp, p1 all green (108 tests before the last small test edit).
- Panel selection (index.html): click or Enter/Space toggles, role=button + aria-pressed, roving tabindex with Arrow/Home/End, outline via --accent, max 20, Escape clears (before closing the panel), cleared on file/chat switch. No new static buttons (button count in markup unchanged).
- Chip (ai-chat.js): one removable chip "Выделено: ..." with count; sent as `selected` + `selected_file`; cleared after send; Escape in the textarea clears it.
- Cards (ai-chat.js): under the AI message from `d.proposals` (survive reload): было / стало, per-card Применить/Отклонить, "Применить все" + "Отклонить" when 2+ pending, comments as quiet notes, rejected patch note shown as a quiet line; after apply POST /patch, new-version card, onEdit opens the new version with "Новая версия" and highlights changed addresses when `hint` is an array. Status line (role=status) announces. Motion 180 ms opacity/transform, off under reduced motion.
- Browser pane (1440 light), real server + fake provider: preview showed 12 pickable elements on the 3-slide pptx; mouse click and keyboard (ArrowDown x9, Enter, Space) selected elements; chip appeared with correct label.

## Not done / unverified
- Send -> cards -> apply -> new version was NOT seen end to end: every edit send on my synthetic pptx was blocked by the leak guard (see docs/archive/superpowers-notes/requests-p2d.md: layout/font names and "Org3"-like words in the outline context are flagged). Cards, apply, announcements, "Новая версия" are code-reviewed only.
- docx and xlsx panels not checked in the browser; 390 dark, contrast, 44 px targets, overflow, network-only-127.0.0.1 not measured; no shots in docs/superpowers/shots-p2d/ (empty).
- Selection chip sits among file chips (not a separate row). Other ticked files are still sent with the message (backend decides the target by selected_file).
