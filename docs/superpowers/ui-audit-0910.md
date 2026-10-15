# UI audit 09.10 (1440, 1920, 900, 760; light and dark)

Method: `audit.py` driver (scratchpad, not committed) subclasses `tools/shots_window.py` Shots, drives the real WKWebView window with synthetic docx, and for every screen takes a PNG and runs an in-page check (text contrast with alpha compositing, target size under 32px, off-screen and horizontal overflow, unlabeled controls, document overflow). About 150 checks. Screenshots: `/private/tmp/claude-501/-Users-USER-Downloads-Anonymizer-1-0-0-Windows-build-kit-2/7bd155dc-0b2e-4f16-a9eb-031e036445b4/scratchpad/shots` (before, 1440), `.../shots2` (after, 900/760/1920), `.../shots3`.

Screens covered: empty chat, plan options, profile menu, rail search, error toast, lost-connection overlay, result, replacements pane (hide/back tabs, reveal, add word), merge picker, import dialog, ask dialog, per-chat options dialog, settings (7 sections, search with hit and no hit, preset row, locked rows, image_brand_policy, theme row), chat view.

| # | Defect | Before | After |
|---|--------|--------|-------|
| 1 | Escape/close of Settings opened from the profile menu left focus on BODY (keyboard user loses place) | `focus_after: BODY` | focus returns to profile button (`btn-profile`) |
| 2 | Settings search placeholder clipped ("Поиск по настройка") at 184px | clipped, `1440-dark-20-set-general.png` | shorter placeholder "Поиск настроек"; aria-label kept |
| 3 | Preset row: select, Apply, Save stacked as ragged column | misaligned | row wraps, controls left-aligned in one flow (`760-light-20-set-general.png`) |
| 4 | Long code (`email1@example.com`) overran the value field in the replacements pane (`hoverflow span.tok 134>84`) | text under the input | wraps inside its 84px column |
| 5 | Targets 28px (chat row menu), 30px (small buttons), 21px summaries | below 32px | row menu 32px, `--ctl-sm` 32px, `summary` min-height 32px |

Remaining / not changed:
- Contrast below 4.5 only on disabled controls (Обезличить, Скрыть выбранные (0), Готово when nothing changed): WCAG-exempt, kept as the disabled affordance.
- Inline text links (`Скопировать подсказку`, `таблицу замен`, `Что именно скрывается`) are 19px tall: inline in sentences, not enlarged. Splitter handles are 8px wide (drag/keyboard separators).
- Native selects render 20px tall in the dialogs by WebKit styling; width/legibility fine.
- `button.switch` 42>36 reported scrollWidth overflow: visual only, no clipping seen.
- Reduced motion: `closeDialog_` and details animation already honor `prefers-reduced-motion`; not re-tested visually.
- Not exercised: Tab-trap cycling (native modal dialog handles it), per-dialog Escape focus return was tested for Settings only; picker/import/ask/chat-options opened from persistent buttons use the native dialog focus restore.

## Final pass (second round)

Method: new scratch driver (not committed) over `tools/shots_window.py`: 17 scenes per size and theme (empty, plan options, profile menu, rail search, error toast, lost-connection, result, replacements pane with and without reveal, merge picker, import, ask danger and password error, per-chat options, 7 settings sections, settings search hit and miss) at 1440, 1920, 900 and 760 px, light and dark, with an in-page check (alpha-composited contrast, off-screen and clipped text, targets under 24px, unlabeled controls, document overflow). A second script drove each dialog through its `cancel` handler (what Escape triggers) and read `document.activeElement`. The add-in panel (`tools/dev_addin_server.py`, 340px viewport) was checked in ready, busy, error, partial-failure, offline and rollback-confirm states.

Screenshots (outside git): before `/private/tmp/enigma-s/shots/before` (1440), after `/private/tmp/enigma-s/shots/after` (1440, 1920, 900, 760; names `<width>-<theme>-<NN>-<scene>.png`). `/private/tmp/enigma-s` is a symlink to the session scratchpad.

| # | Defect | Before | After |
|---|--------|--------|-------|
| 6 | Settings closed by Esc, the X or a click on the backdrop silently discarded edited fields | edits lost, no prompt | when "Готово" is enabled (dirty), a danger confirm "Закрыть без сохранения?" opens with focus on the safe button; cancel returns to settings |
| 7 | Error toast "Закрыть" was 53x19 | 19px target | 32px target |
| 8 | Native selects in settings and dialogs 20px tall (preset, theme, retention, image policy) | 20px | min-height 32px |
| 9 | Lost-connection overlay was not modal: the app behind stayed reachable with Tab | focus could leave the overlay | `#shell` and `#settings` become inert while it is shown (reconnect reloads the page) |

Verified OK, no change needed: Escape closes every dialog and focus returns to the opener (settings to the profile button, ask to its opener, import to `btn-pane-import`, picker to `btn-pane-add`, profile menu to `btn-profile`); dialogs open with focus inside (ask danger on Cancel, import on Apply, picker on search); no contrast failures except disabled controls; no horizontal overflow or clipped text at 760-1920; add-in panel at 340px has no overflow, contrast or label issues, and the rollback confirm focuses the safe button.

Remaining: per-chat option selects inside collapsed groups still report 20px (not visible until a group is opened); the 409/stale-document path in the add-in was checked through its rendered states, not against a live Word document.
