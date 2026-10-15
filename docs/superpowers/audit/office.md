# Office add-in audit (Word / Excel / PowerPoint)

Method: static trace of `anonymizer/addin.py`, `addin_web/taskpane.{html,js,css}`, `addin_install.py`, `helper.py`, `tools/fake_office.js`, `tools/dev_addin_server.py`, tests. `python -m unittest tests.test_addin tests.test_addin_chat tests.test_helper` ran: 59 OK (server side only). No real Office was touched or connected. Everything about real Office.js behaviour is **Not verified** unless stated; `fake_office.js` is a simulator written by the same author and proves the panel logic, not Office.

Paths: A=`anonymizer/addin.py`, J=`anonymizer/addin_web/taskpane.js`, H=`.../taskpane.html`, W=`anonymizer/webapp.py`, I=`anonymizer/addin_install.py`, D=`anonymizer/web/index.html` (desktop UI).

Status legend: Covered / Partially / Missing / Broken / Ambiguous / NV (Not verified, needs real Office).

## 1. Office.js API used per host (differences)

| | Word | Excel | PowerPoint |
|---|---|---|---|
| Read file | `getFileAsync(Compressed)` 4 MB slices, 90 s timeout (J:61-85) | same | same |
| Replace content | `doc.insertFileFromBase64(Replace)` if WordApiDesktop 1.1, else `body.insertFileFromBase64` (J:164-170); headers/footers rewritten per section (J:131-149) | requires ExcelApi 1.13, deletes all workbook names, `insertWorksheetsFromBase64` at End, deletes old sheets, renames, restores visibility and names (J:184-240) | `insertSlidesFromBase64(KeepSourceFormatting)` then delete old slides one by one (J:174-183). No `isSetSupported` guard |
| Properties | `document.properties` + `customProperties` (J:99-129) | `workbook.properties` + `.custom` | `presentation.properties` (PowerPointApi 1.7, not checked) |
| Tracked changes | server refuses docx with `w:ins/del/moveFrom/moveTo` (A:120-135); optional `acceptAll` button (WordApi 1.4) | n/a | n/a |
| Not covered | footnote/endnote/text-box formatting fidelity, content controls, fields, doc-level protection: NV | pivots, charts, tables, validation, external links, macros (`.xlsm` refused by suffix), co-authoring: NV | old slide masters/layouts survive (KeepSourceFormatting adds new ones), sections, notes pages, custom shows: NV |
| Min requirement in manifest | none (only `SharedRuntime` if `shared`, I:28-42) | none | none |

Unsupported/degraded: Word header/footer with images or relationships falls back to plain text silently (A:240, J:143); `.doc/.xls/.ppt/.docm/.xlsm/.pptm/.xlsb` refused (A:357); files over 100 MB refused client side (J:427), 300 MB server side (A:361).

## 2. Scenario matrix

Columns: intent | current path | current behavior | SCOPE | status | evidence | UX problem | expected | fix | regression test | pri.

### 2.1 Core flow

| # | Intent | Path | Behavior | SCOPE | Status | Evidence | UX problem | Expected | Fix | Test | Pri |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Open untouched doc | `Office.onReady` -> `connect()` -> `refreshState()` | Reads binding (doc property, then settings, then localStorage), asks server for chat state; none -> "Документ не обезличен" + lead + buttons | W/X/P | Covered (logic) / NV (real Office) | J:540-550, 680-705 | none | - | - | existing fake_office run | - |
| 2 | Anonymize | `run("anonymize")` read -> POST -> job -> (review) -> unchanged check -> apply -> re-read -> verify | Full pipeline with encrypted backup first, tracked-changes refusal, concurrent-edit check, post-verify | W/X/P | Covered server side; Office apply NV | J:411-456, 482-511; A:353-385 | Excel/PPT apply failure leaves doc half-changed (see 12, 13) | - | - | - | - |
| 3 | Plan summary | `renderPlan()` | "Будут скрыты: ... Не скрываются: ..." from checkboxes; same wording as desktop | W/X/P | Partially | J:296-305 vs D:752 | In Word/PowerPoint the line still says "числа в Excel" (hidden/not hidden). Panel has no "Стандартное обезличивание / Свои параметры" title and no "Вернуть стандартные параметры" reset that desktop has (D:390,405,750). Panel plan line lacks "и номера документов" tail of desktop line (D:391) | Same words and a standard/custom indicator; omit Excel-only item outside Excel | Share one string source; hide "числа в Excel" when HOST != Excel | unit on `renderPlan` per HOST | P2 |
| 4 | Advanced settings | `<details id="more">` checkboxes | Per-run only: values come from vault prefs once (`dataset.set`), never written back, never persisted between panel loads, not synced if desktop prefs change while panel open. `opt-auto` is stored in localStorage only | W/X/P | Partially | J:662-665, 688-689; A:347-351 | Desktop pref change not reflected; a user who changes a box in the panel expects "remembered" but panel reopens with desktop prefs; `neutral_names` returned by `/info` but never shown/used | State clearly "только для этого запуска" or persist | Add one line "Действует на эту обработку" | fake_office: change prefs, reload | P2 |
| 5 | Repeated anonymization | `go-anon` hidden while state=anonymized (J:574); after rollback or restored state `go-anon` shown | Re-anonymize with `X-Chat: chatId \|\| lastChat`; same-name record in chat is replaced, not duplicated (A:378-381) | W/X/P | Covered | J:430, A:378-383, test_addin_chat:48 | Re-anonymizing an already anonymized doc is not offered (must roll back first, losing later edits, see 9). Desktop-side mapping edits are not applied to the open doc (see 17) | A "Обезличить заново" for anonymized state with the unchanged-check, so desktop edits can be applied without rollback | Add only if rebuild path (17) is built | - | P1 (tied to 17) |
| 6 | Review before replace | `renderReview` when auto-apply off, suggestions exist, or status attention | Lists strong suggestions; "Скрыть отмеченное" -> `/rerun` | W/X/P | Covered | J:342-361, 444-447 | Rerun reuses `last.job`; if job purged -> "Задание уже удалено" (A:389), clear | - | - | test_addin:246 | - |
| 7 | Restore | `run("restore")` with `X-Chat: chatId` | Restores whole open doc; backup of the anonymized doc saved; unknown tokens shown as chips | W/X/P | Covered | J:430, 381 | Doc now holds real data; panel says "Данные возвращены" with a green-ish state but no warning that the doc must not be shared (desktop wording?). NV | One neutral hint "В документе снова настоящие данные" | add hint in `renderFinal` restore | - | P2 |
| 8 | Result honesty: success shown when file is not clean | `renderFinal`: `clean = !problems.length && !brokenParts.length`; `warns` (leftover properties) and `propertyLimit` (Office refused to change author/title/company) do NOT make it unclean | Title "Документ обезличен." plus an amber note. Author, company, title, comments property may still hold real values; custom-properties wipe errors are swallowed (J:127) | W/X/P | **Broken** | J:109, 119-128, 363-379; A:319-323 | **Unsafe file presented as safe.** Heading green/neutral, "Документ заново прочитан и сверен" ok-line even when the file still carries the real author/company | If properties could not be cleared or verify found them: heading "Документ обезличен, но в свойствах файла остались данные" as error level | Treat `properties` warning and `propertyLimit` as not clean; show the heading as incomplete | test on `renderFinal` with `warnings` / `failedNames` | **P0** |
| 9 | Rollback ("Откатить к исходному") | `go-rollback` -> `rollback(chat.backup)` | Replaces the whole doc with the stored original **without** the unchanged check and **without** confirmation (only the "Дополнительно" list has a two-click arm, J:649-653). Anything typed after anonymizing is lost | W/X/P | **Broken** | J:692-695, 513-534; A:434-441 | **Lose work**: one click overwrites later edits; Office Ctrl+Z may not work (own hint J:383) | Run `unchanged`-style comparison against the anonymized result; if changed, warn and require confirm | Reuse `/unchanged` against result bytes; add confirm step like backups list | rollback after edit test with fake_office | **P0** |
| 10 | Rollback uses chat-level backup, not doc-level | `chat.addin_backup` = latest anonymize backup of the *chat* (A:427-428) | If two documents are bound to one chat (copy / same doc in two files, see 14-15), "Откатить" on doc B writes doc A's original into B | W/X/P | **Broken** | A:427-441, J:693-694 | **Destructive wrong-document overwrite** | Backup must be checked against this document (backup name and a hash/token set of the current doc) | Store backup per (chat, doc id) and compare name+tokens before rollback; refuse on mismatch | two bindings, one chat, rollback B | **P0** |
| 11 | Undo restore | `rollback(last.backup, true)` only while the panel session has `last`; after reload: hint to list in "Дополнительно" | Works with in-session copy; otherwise instructs to use list | W/X/P | Partially | J:576-579, 693 | Two paths, one hidden in a fold | - | - | - | P2 |

### 2.2 Per-host apply and failure

| # | Intent | Path | Behavior | SCOPE | Status | Evidence | UX problem | Expected | Fix | Test | Pri |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 12 | Excel replace fails midway | `applyExcel` | Names are deleted and synced before sheets are inserted. If insert fails, message "Документ не изменён" (J:199) is false (names gone). If an old sheet cannot be deleted, both old (real data) and new sheets remain; text offers rollback (J:210) | X | Partially | J:192-199, 205-210 | Doc state misreported; old sheets with real data remain in book until rollback | Say "Книга изменена" and offer rollback; verify (`/verify`) is skipped on throw, so leftover sheets are not checked | Throw with explicit touched flag; run verify on failure | fake_office: delete fails | P1 |
| 13 | PowerPoint replace fails midway | `applyPowerPoint` | Inserts new slides then deletes old ones in one `run`; failure after insert leaves both decks (real data in old slides). No API-set check, raw Office error shown | P | Partially | J:174-183 | Same as 12; no min-version guard | Guard `PowerPointApi 1.2`, report "в презентации и старые, и новые слайды" | as 12 | - | P1 |
| 14 | PowerPoint masters/layouts | `KeepSourceFormatting` | Adds new master(s); old masters/layouts stay. Real values in old layouts/notes possible. Server leak check includes "образцы слайдов" text (A:318) only if Office text extraction sees them | P | NV | J:178; A:317-318 | Possible residual real data in masters | Verify must read masters of the *re-read* file; warn on leftovers | NV on real PowerPoint | needs real Office | P1 (NV) |
| 15 | Word track-changes mode on failure | `applyWord` sets mode Off, restores at end | If insert throws, mode stays Off | W | Broken (minor) | J:155-171 | User's Track Changes silently disabled | try/finally restore | try/finally | fake_office throw | P2 |
| 16 | Word header/footer with images | `applyHeadersFooters` | Falls back to plain text without telling the user | W | Partially | A:240, J:140-143 | Silent formatting loss in header/footer | Add warning "Колонтитул восстановлен без оформления" | push to `failed`/notes | unit | P2 |
| 17 | Verification of Word/Excel/PPT result | `/verify` | Compares words (lost text, leaked values), sheet names, slide count, header and comment counts. Passes only text-level equality: images, charts, formatting, formulas are not compared | W/X/P | Partially | A:294-334 | "сверен с результатом" could be read as full fidelity | Wording "текст и структура сверены" | copy only | - | P2 |

### 2.3 Chat linking, open chat, save/close/reopen, binding

| # | Intent | Path | Behavior | SCOPE | Status | Evidence | UX problem | Expected | Fix | Test | Pri |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 18 | Open linked chat in desktop app | "Открыть чат" -> `displayDialogAsync` of `/addin/chat?chat=`; fallback `/api/addin/open-app` sets `app.open_chat` and focuses window | Dialog if DialogApi 1.1; otherwise app focus; helper spawns window if none (`tab_request`) | W/X/P | Covered (server), dialog NV | J:622-639, A:680-690, W:296 | Fallback text "Окно чата в Office недоступно..." fine. `open_chat` is single-slot: second request overwrites the first | - | - | test_addin_chat:183 | P2 |
| 19 | Binding doc to chat | Custom property `Anonymizer.Chat`, then `document.settings`, then localStorage keyed by hash of URL | Order: property, settings, local. Survives rename and move (property travels in file). localStorage key is the URL, so rename/move loses only the last fallback | W/X/P | Covered / NV | J:241-280 | See 10, 20, 21 | - | - | - | - |
| 20 | Copy of an anonymized document | Property copied with the file | Both files point to same chat; panel shows "Обезличен ... чат «X»"; rollback uses the chat's latest backup (10) | W/X/P | Broken | J:254-266; A:427-441 | Wrong-document rollback (P0 via 10); copy shows a state that was valid only for the original | Detect that the copy diverges: compare tokens/name; offer "Это копия: привязать как новый документ" | add per-doc id in the bound property (chat id + backup id) | copy test | P0 (via 10) / P1 |
| 21 | Same doc opened twice | Same property; two panels, no coordination | Both can run operations; `unchanged` check protects only against edits in the same file instance, not the other window's replace | W/X/P | Ambiguous | J:482-495 | Two windows can anonymize/restore the same file concurrently | Lock per chat on server (reject second running job with a clear message) | server-side "job in progress for chat" | NV | P2 |
| 22 | Binding from marks | "Определить по метке" -> `/match` unique-best overlap | Binds only when unambiguous; reasonable | W/X/P | Covered | A:443-457, J:605-615 | Message when none/ambiguous merges both cases | Separate wording | - | test_addin_chat:123 | P2 |
| 23 | Stale binding (chat deleted in desktop) | `refreshState` clears binding if `found=false` | Works; but `docState=null` on any error (helper down) means no state shown, no message | W/X/P | Covered / Partially | J:545-548 | helper down -> blank state without hint | Show "Состояние неизвестно: нет связи" | note() | - | P2 |
| 24 | Save / close / reopen / app restart | Binding in file; backups server-side 7 days, 20 items; token file persists; `chat.addin_backup` persists | After reopen state restored from doc property. Backups expire (7 days/20 items): `has_backup` false -> no rollback button, no explanation | W/X/P | Partially | A:40-41, 96-109, 439; J:577 | After 7 days there is silently no rollback; user may expect it | Show "Копия оригинала удалена (срок 7 дней)" when state anonymized and no backup | text in `renderState` | test purge then doc-state | P1 |
| 25 | Original data at rest and in Office history | Backup stores the real original encrypted with device key; Office/OneDrive version history and AutoRecover store originals too | UI says copies stored 7 days (H:72). Does not warn that cloud version history / AutoSave keeps the original data | W/X/P | Missing | H:72-78, J:383 | Real data remains outside the tool's control | One-line warning when the doc path is cloud/AutoSave: NV | add hint | - | P1 |
| 26 | Property `Anonymizer.Chat` in shared file | Written into custom props of the anonymized doc | Anonymized file carries the chat id when sent out (low sensitivity, opaque id) | W/X/P | Partially | J:267-275 | Minor metadata trace | Mention or strip on export | - | - | P2 |

### 2.4 Errors, offline, tokens

| # | Intent | Path | Behavior | SCOPE | Status | Evidence | UX problem | Expected | Fix | Test | Pri |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | Helper not running before panel loads | Pane URL is the helper's HTTPS page itself | Panel never loads (Office shows its own load error); offline screen only possible after load. Autostart exists (launchd / HKCU Run) | W/X/P | NV | I:54-132; H:19-23 | User sees Office error, not a hint | Document in install/README; NV | - | - | P2 |
| 28 | Helper dies mid-run | `api()` fetch error -> "Нет связи с программой Anonymizer" | Before apply: doc untouched (ok). **After apply** (during verify): same message under "Не получилось." while the document has already been replaced; rollback also needs helper | W/X/P | Ambiguous | J:31-35, 482-505 | **Doc replaced but UI says failed / not saying doc changed** | Distinguish "заменено, проверка не выполнена" | Wrap verify step separately: after `touched`, message "Документ заменён, проверку выполнить не удалось" | fake_office: kill after apply | P1 |
| 29 | Token problems | Token embedded at page load; token file persists | Any 403 (token regenerated, wrong origin) is shown as "Нет связи... Запустите программу" (connect swallows all errors) | W/X/P | Ambiguous | J:657-677, 31-44 | Misleading text; fix is "reopen the panel" | Show "Панель устарела, закройте и откройте её снова" on 403 | map 403 | test 403 -> message | P2 |
| 30 | Token exposure to other local OS users | `GET /addin/taskpane.html` and `/addin/chat?chat=` need only a valid Host; token injected into HTML | Any local account/process that can reach 127.0.0.1:47831 reads the token, then every API (backup listing/downloads, results, doc-state, chat table with `reveal`). Same-user processes are equal anyway; other users on a shared Windows/Mac host are not. NV: CORS headers of `Handler._send` not checked, browsers from foreign origins are blocked by Origin/Sec-Fetch checks on API | W/X/P | Partially | A:561-568, 623-635 | Local privilege boundary only on single-user machines | Serve token only over a request carrying a per-launch secret in the page URL, or bind by OS user | NV; design decision | multi-user test | P1 |
| 31 | Office API failure | Exceptions bubble to `renderError` | Raw Office message shown; rollback offered only if `touched` | W/X/P | Partially | J:507-510 | Raw English text possible | Wrap with Russian lead | - | - | P2 |
| 32 | Unsupported version | Excel only checks 1.13 and states reason; Word falls back silently to body replace (header/section loss); PPT no check | Word old versions: body replace only | W/X/P | Partially | J:164-170, 185 | Silent downgrade | Warn when doc-level replace unavailable | - | - | P2 |

### 2.5 Layout, keyboard, a11y

| # | Intent | Path | Behavior | SCOPE | Status | Evidence | UX problem | Expected | Fix | Test | Pri |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 33 | Narrow panel | `@media (max-width:340px)`, single-column grid, `overflow-wrap:anywhere` | Layout designed for narrow; real Office pane widths/zoom NV | W/X/P | NV (static OK) | CSS:28, 115-116 | - | - | screenshot at 320 px via dev server | - | P2 |
| 34 | Keyboard / screen reader | Buttons native, focus moved to `#result` on completion, progress `role=progressbar`, live regions on state and busy | Good. Gaps: busy state re-renders without moving focus (button that had focus disappears); `renderState` shuffles button order via `insertBefore`, which moves DOM and focus order; no Escape/close handling for the review list; step marks "+", "!" as text for AT | W/X/P | Partially | J:307, 585, 309-312 | Focus lost when `show()` hides the clicked button | Move focus to `#busy` heading on start | - | a11y test | P2 |
| 35 | Ribbon commands | `Office.actions.associate("anonymizeCommand")` defined in JS | Manifest declares only `ShowTaskpane`; no `ExecuteFunction` -> commands are dead code | W/X/P | Ambiguous | J:707-720; host_block.xml.tmpl:23-26 | Possible confusion in docs | Remove or wire | - | - | P2 |

### 2.6 Mapping edits in the desktop and consistency

| # | Intent | Path | Behavior | SCOPE | Status | Evidence | UX problem | Expected | Fix | Test | Pri |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 36 | Desktop table edit afterward | Desktop "Обезличить заново с правками" updates chat files; `chat_summary.pending_edits` counts keep/hide/merge/split | Panel shows note "В таблице замен есть правки... Откройте чат, чтобы пересобрать файлы" and the open Office document is **not** updated: no path pulls the rebuilt file into the document. Only route is rollback then re-anonymize, which loses edits made after (9) | W/X/P | Missing / Partially | A:279-294 (W), J:568, H:31 | Panel and desktop can disagree: panel says "Обезличен" with old replacements. Pending counter ignores "undo" (desktop D:1273-1277 counts undo of rebuild actions) so numbers differ | A single button "Применить пересборку к документу" using the chat's rebuilt file with the unchanged-check and verify, or say plainly that the open document keeps the old replacements | Add only this one action, reusing `applyAndVerify` with the chat's current anon blob | unit: edit in chat then apply in panel | P1 |
| 37 | Table in panel | `chat-table` masks values server side; `secret` rows show "хранится только в программе" | Good; but `?reveal=1` is accepted by API for any token holder (A:585) with no UI | W/X/P | Partially | A:459-473, 585 | Unused reveal endpoint widens exposure | Remove or gate | drop reveal | test | P2 |

### 2.7 Terminology vs desktop

| Term | Desktop | Panel | Verdict |
|---|---|---|---|
| Plan line | "Будут скрыты: ... Не скрываются: ..." (D:752) | same (J:303) | Matches (Excel-only item leak noted in 3) |
| Standard profile | "Стандартное обезличивание", "Свои параметры обезличивания", "Вернуть стандартные параметры" (D:390,750,405) | absent | Missing |
| Options | "Скрывается всегда", "Включено по умолчанию", "Может скрыть лишнее" groups; "Скрывать страны", "Заменять числа в Excel", "Скрывать и сомнительные слова" | same three labels, no groups, plus panel-only "Заменять сразу, если нет сомнительных мест" | Partially matches |
| Originals | "Хранить оригиналы в этом чате / в новых чатах" (D:371,465) | "Копии документов до замены ... 7 дней" | Different concept and wording: a panel copy lives 7 days regardless of the desktop setting (A:418-421); users may think originals are not kept |
| Rebuild | "Обезличить заново с правками" | "пересобрать файлы" | Different verbs |
| Restore | "Вернуть данные" | "Вернуть данные" | Matches |
| Rollback | n/a | "Откатить к исходному" / "Откатить к виду до возврата" / "Вернуть" (backups list) | Three verbs for related actions; "Вернуть" in the list means rollback while "Вернуть данные" means restore. Ambiguous |

## 3. P0 list (unsafe / loss / destructive)

1. #8 Result shown as success while real author/company/title may remain in file properties (J:363-379).
2. #9 Rollback overwrites the document without unchanged-check or confirmation; later edits lost.
3. #10/#20 Rollback uses chat-level backup: copied/shared binding can write another document's original into this one.
Candidates held at P1: #12/#13 half-applied Excel/PowerPoint (real-data old sheets/slides remain until rollback), #28 verify skipped when helper dies after apply, #30 token page readable by other local users, #25 cloud history.

## 4. Not verified (needs real Office)

Every `Office.context` / `Word.run` / `Excel.run` / `PowerPoint.run` behaviour: replace fidelity (footnotes, text boxes, charts, pivots, masters), `insertFileFromBase64` option effects, WordApiDesktop fallback, property writes per version, DialogApi availability, binding persistence in settings, undo stack, ribbon/manifest load, pane width, helper-down pane load, co-authoring/AutoSave/OneDrive history, Mac vs Windows differences.

## Top gaps ranked

1. Rollback has no unchanged-check/confirmation (#9).
2. Rollback not tied to this document (#10, #20).
3. Success displayed with leftover properties (#8).
4. Open document cannot be refreshed after desktop mapping edits; no honest "document keeps old replacements" (#36, #5).
5. Half-applied Excel/PPT and post-apply helper loss reported ambiguously (#12, #13, #28).
6. Silent expiry of rollback copy at 7 days (#24); cloud history not warned (#25).
7. Local token disclosure on shared machines (#30).
8. Terminology drift (standard profile, originals, three rollback verbs).

## Intentionally not to add

No cloud/online mode, no bulk/folder processing inside Office (already pointed to desktop), no live sync with the desktop table, no editing of mappings in the panel, no new settings storage in the panel, no `.doc/.xls/.ppt/macro` support, no auto-accept of tracked changes without a click, no automatic Ctrl+Z emulation, no per-element undo. Fix only the three P0s and the single rebuild-apply action.
