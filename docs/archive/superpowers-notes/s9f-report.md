# S9F report: focus, settings widths, light theme, tap targets

Method: tools/dev_server.py :8796, Browser pane own tab, real Tab key for focus modality, JS audits. Shots: docs/archive/shots/shots-s9f/. Screenshots show the pane crop, not the full emulated viewport.

| Item | Result | Evidence |
|---|---|---|
| 1 Focus rings, light and dark (header link, settings tab, toggle, confirm dialog button, review checkbox) | PASS by eye; computed: every focusable control gets solid 2px outline, offset 2px, --focus contrast vs bg/surface/field/hover/select 3.5-4.3 (light), 6.4-8.8 (dark) | 01-focus-header-link-light.jpg, 02-focus-settings-tab-dark-1280.jpg, 03-focus-toggle-dark-zoom.png, 09-modal-confirm-focus-light.jpg, 12-focus-review-checkbox-light-zoom.png |
| 2 Settings modal 1920 / 2560, dark and light | PASS layout (820x640 centred, no overflow). FAIL then FIXED: search field rendered dark in light theme | 04-settings-1920-dark.jpg, 05-settings-2560-dark.jpg, 06-settings-2560-light-search-fixed.jpg, 08-hide-keep-terms-light-1920.jpg |
| 3 Light theme main screen, result, review list | PASS | 07-main-empty-light-1920.jpg, 10-result-light-1920.jpg, 11-review-list-light-1920.jpg |
| 4 Hide/keep terms shot | PASS (shot retaken, light 1920) | 08-hide-keep-terms-light-1920.jpg |
| 4 Backup produces a file | PASS: POST /api/backup/export -> 200, 3641 bytes, magic "ANONBACK" (fetched via API, no native dialog; import not exercised) | JS fetch result |
| 5 Targets < 44 px | 390 wide: FAIL then FIXED (#extra-terms 40, a "Провайдер и ключ" 20, settings selects 32 and search 40); after fix 0 below 44 on result screen and all 7 settings tabs, scrollWidth == clientWidth. 1440 wide: inline button.link 20 px FIXED via ::after hit area 44 px, no layout change | 13-settings-390-targets-44.jpg, 14-review-list-1440-link-hit-areas.jpg |

## Fixes
- index.html: `color-scheme` now follows data-theme (light/dark); before, light theme on a dark OS gave UA-dark form controls. `input[type=search]` styled like other fields.
- index.html: `button.link::after` 44 px hit area; #extra-terms and settings select/search 44 px at <= 720 px or coarse pointer.
- ai-chat.js: `.aic-head a` 44 px hit area by padding/negative margin.

## Not fixed / observed
- Desktop 1440: ghost buttons (#link-ai 34 px), summaries 32 px, selects 32 px stay under 44 px (mouse UI, not inline links; left as is).
- Transitional frame after opening a result showed the "add AI answer" block dark for a moment in light theme (settled light in later shots); not investigated.
- Settings tab "Поиск настроек" input has aria-label; not otherwise changed.

## Tests
unittest tests.test_desktop, test_chat_ux_page, test_webapp, test_ws_s6e: 85 run, 1 failure (SelfCheckTests, known, no vendor/office.js).
