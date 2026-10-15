handoff:v1
task: final frontend design + motion pass (desktop window done in part, Office panel NOT done)
base: 28b4948 -> this pass part 1 (see git log)

## Done in part 1 (anonymizer/web/index.html, tests, tools)
- New token system (OKLCH neutral cool palette, one blue accent, semantic ok/warn/error), radii 4/6/8, type scale 12/13/14/16/20, controls 34px, motion tokens (--dur-1/2/3 = .12/.18/.24s, one ease-out).
- Flattened: composer is ONE frame (files + picker + plan + button); warnings/suggestions/notices are flat rows; sentence-case micro headings; ghost "Новый чат"; danger buttons; status dot (ok/warn/error).
- Sidebar: grid column transition (--side-w), content widens 760->960, visibility hides it from Tab; <=720px it is an overlay drawer with scrim + Esc. Pane: grid column transition (--pane-w), inert when closed (JS var `paneOpen` replaces `#pane.hidden`; tools/e2e_window.py updated).
- Motion: details height animation (WAAPI, JS), dialog open/close, toast in/out, new steps only (animateFrom), result/notice rise; global prefers-reduced-motion block; JS honours reduceMotion().
- Tests: tests/test_desktop.py motion/shadow contract rewritten; test_chat_ux_page updated. 696 unit tests green.
- tools/shots_window.py: native-window screenshots (light/dark, wide/mid/min/short). Window in background freezes CSS transitions, so snap() disables them for static shots.

## NOT done / to verify next session
1. Re-run `tools/shots_window.py /tmp/x` and LOOK at: wide/min/short light+dark, drawer at 520px, composer pinned to bottom (page is flex column, composer margin-top:auto), `.ver` grid alignment, settings dialog focus (h2 focus, no ring on summary), result state (needs a screenshot after processing), options expanded, long chat list.
2. Run real-window E2E AFTER these changes: `.venv-mac/bin/python tools/e2e_window.py` (expect 122/122; it was last run before the redesign).
3. Office panel visual pass (anonymizer/addin_web/taskpane.css/.html/.js): port tokens, flatten frames, same buttons/radii/motion; plan summary already exists. Real Word/Excel/PowerPoint are installed on this Mac but connecting the add-in changes system trust (certificate): needs the owner's explicit OK; otherwise verify in browser via tools/dev_addin_server.py + tools/fake_office.js and say so.
4. Keyboard-only pass (Tab/Shift+Tab/Enter/Space/Esc/Cmd+B, focus after dialog close/delete), table pane at narrow width, long values.
5. Not yet checked in live UI: motion actually playing (getAnimations / computed transition), reduced-motion emulation, sidebar open/close transition feel, drawer on narrow native window.
6. Then final report to owner (commit hash, problems removed, palette, border reductions, motion system, screens checked, test results, Office status, what is not verified). Do not claim 10/10 before steps 1-5.

## ADDED REQUIREMENT (owner, after part 1): spatial stability / no layout shift or jank
Audit EVERY screen by clicking through repeatedly (not only tests). Nothing may jump, resize, reflow or move unexpectedly on:
button clicks, open/close panels, expand/collapse sections, open/close dialogs, switching chats, sidebar show/hide,
processing start/finish, results appearing, replacements pane open/close, dismissing toasts/errors.
Either an element stays exactly in place, or it moves through ONE coordinated smooth transition (no "jump then animate").
Look for and fix:
- vertical/horizontal content jumps; buttons moving after state change; header height changes;
- containers suddenly resizing; scrollbar appearing/disappearing shifting layout (consider `scrollbar-gutter: stable` on scroll containers/body);
- text wrapping that moves neighbouring controls; panels pushing unrelated content abruptly;
- dialogs shifting the background (scrollbar lock); loading state with different size than loaded state;
- result block causing page reflow (reserve space or animate height); focus/hover/active changing size
  (borders must not appear on hover/focus and change size: use constant 1px transparent borders or outline);
- icon/label swaps changing button width (e.g. "Скрыть значения"/"Показать значения", "Обезличить"/"Обезличить всё равно", Подключить/Подключить заново: give min-width);
- sidebar collapse repositioning; async content (chat list, state load, plan line text: "Загрузка" placeholder with reserved height) moving things.
Known suspects already seen: plan-line renders empty until /api/state arrives (composer height changes); `.chat-title` input vs draft; feed re-render on refreshChat; result block insertion above composer; flash/notice insertion above feed; sidebar flash before saved collapsed state arrives; `#progress-chat` show/hide; `.files` list growing the composer (composer is sticky/bottom-pinned); `.drop-note` hide/show; toast; scrollbar in `.pane`.
Method: measure with JS (getBoundingClientRect of anchors before/after each action, PerformanceObserver 'layout-shift' entries / CLS), then verify visually in native window (tools/shots_window.py) and fix. Add regression tests for static guarantees (e.g. constant border widths, min-widths, scrollbar-gutter).

## Part 2 (this session)
- Re-ran tools/shots_window.py: light/dark wide, mid, min, short, drawer, options expanded all look coherent (viewed chat, drawer, options).
- Real-window E2E after redesign: 122/122. Unit tests: 697 green.
- Layout stability fixes: `scrollbar-gutter: stable` on html; plan-line has a hidden placeholder (reserves height before /api/state); min-width on #btn-reveal, #btn-chat-anon, #btn-addin-install. Regression test test_layout_stays_put_on_state_changes.
- Measured in browser (1280x800): sidebar toggle keeps composer y and button y unchanged; no layout-shift entries recorded. Caveat: the in-app browser tab is `document.hidden`, so animation mid-states are frozen and not measured.
- STILL NOT DONE: items 3 (Office panel pass), 4 (keyboard-only pass), 5 (motion actually playing / reduced-motion emulation), result-state screenshot after processing, CLS check for result block / flash / toast / chat switching. No 10/10 claim yet.

## Part 3: click-through of chats and table (tools/usability_window.py, native window)
Run: `.venv-mac/bin/python tools/usability_window.py /tmp/u` (4 files processed, 4 chats switched twice, table opened/revealed/expanded/edited/searched/closed; prints which anchors moved per action).
Found and fixed:
- Edit note in the table pane was inserted above the list and pushed every row down ~85px -> now sticky at the pane bottom (after #table-body), bordered.
- "Показать значения" removed the hint and shifted the list up 48px -> hint stays, text swaps, min-height 3lh.
- Focus fell to BODY after editing a value: ask() resolved before the dialog finished its 120ms close, then <dialog> restored focus to the replaced button. closeDialog_ now takes a callback; ask() resolves after close. Focus returns to the row.
- Row action links wrapped with 12px row gap -> 4px row gap.
Verified OK: switching chats (2 rounds x 4) moves nothing; opening table re-centres main column (intended); reveal, edit, search no shift; narrow table fine. Unit 697 green, E2E 122/122.
Seen, not changed: starting processing shrinks the composer (file row leaves) and the title narrows when "Замены" appears (draft -> chat); the page scrolls to bottom when a result is taller than the window (header scrolls away); sticky note covers part of one row until dismissed/undone.
Still open: items 3 (Office panel), 4 (keyboard pass), 5 (motion playing/reduced motion).

## Part 4: scenario-coverage audit and fixes
Audit matrices: docs/superpowers/audit/{table,desktop,office,keyboard}.md. Fixed: hide-over-existing-entity leak, partial rebuild marking everything applied (stale flag, not_updated), text-file vault marker (invisible tag chars on .txt/.md; csv unguarded), one-time history import, chat-write-failure fallback, rebuild uses stored options + keeps previous version, add-missed-word from table (hide_new), restore lands in matching chat, clear-vault warning, keyboard/focus/a11y P1s, retention hints, contrast tokens, sticky error toasts, Office: partial-success heading, rollback confirmation + per-document fingerprint, honest half-applied/helper-lost messages, rollback expiry/cloud-history hint.
Results: unit 745 green, real-window E2E 124/124 (dark-theme check made deterministic).
NOT verified: real Word/Excel/PowerPoint behaviour, VoiceOver, Windows WebView2, motion feel. Open: stale indicator after Settings/cross-chat edits (rules_version), alias add, token-in-HTML on shared machines, csv marker, old ghost chats cleanup, ghost chat for failed-only jobs, 'already processed' hint, tool outputs in /tmp.

## Part 5: resizable panels + chat row menu
Sidebar/pane drag handles (role=separator, keys, double-click reset, prefs sidebar_width/pane_width), sidebar row "⋯" menu (rename/delete, right-click, ContextMenu, Shift+F10, Delete key), delete confirm states exact scope. Archive intentionally not added. Unit all green, E2E 154/154.
Not verified: real mouse/trackpad drag, Windows WebView2, 721-1100px with pane open, one-frame width flash before /api/state.
Next session: keyboard-only pass with real keys, Office panel visual pass in browser fake, remaining P1s from docs/superpowers/audit/*.md (stale indicator rules_version, alias add, csv marker, ghost-chat cleanup, 'already processed' hint).
