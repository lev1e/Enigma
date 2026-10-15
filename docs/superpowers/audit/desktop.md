# Desktop app audit (read-only)

Scope: desktop window (`anonymizer/web/index.html`, `webapp.py`, `chat_api.py`, `chats.py`, `service.py`, `restore.py`, `vault.py`, `desktop.py`). Excludes Office add-in and the replacement-table actions (edit/merge/split/keep/hide/forget), which another auditor covers.
Method: code trace plus runtime experiments against `webapp.App` using `.venv312` (scripts were throwaway, nothing in the repo was edited). "Verified" = reproduced by running code. "Code" = read, not run (no browser/GUI session was driven). JS behaviour was never executed; every JS row is from reading `index.html`.

Legend: status = Covered / Partially / Missing / Broken / Ambiguous / Not verified. SCOPE = DESKTOP unless stated. Priority: P0 leaks data, corrupts mappings, restores wrongly, loses work, unannounced global destruction, shows unsafe file as safe, or blocks the main flow.

## Findings that need a fix first (details in the matrix)

| ID | Pri | One line |
|----|-----|----------|
| F1 | P0 | Restoring a TEXT file (.txt/.csv/.md/.json...) after "Clear vault" (or from another vault) silently puts the WRONG people in. Verified. |
| F2 | P0 | "Clear vault" confirmation does not say it also deletes ALL chats, stored originals, anonymized and restored versions. Verified: 5 chats -> 0. |
| F3 | P1 | Every restart re-creates an empty archived "ghost" chat for every job that already has a real chat; deleted chats come back. Verified. |
| F4 | P1 | If writing the chat fails, the job is "done" but the result screen has no save button at all. Verified (state=done, chat="", downloadable=True). |
| F5 | P1 | Rebuild ("Пересобрать") uses whatever the main-screen toggles say now, not the options used for the chat, and replaces the old anon file with no rollback. Code. |
| F6 | P1 | Default retention (180 days chats / 30 days restored versions) deletes work silently; UI never tells the user the clock exists. Code. |

## Matrix

Columns: intent | current path | behaviour | status | evidence | UX problem | expected | fix | test | pri.

### 1. First use / onboarding / empty states

| # | Intent | Path | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|------|-----------|--------|----------|---------|----------|-----|------|-----|
| 1.1 | Understand what to do on first launch | Open app: draft chat, empty sidebar | Draft state says "Добавьте файл, чтобы начать... обезличивается на этом компьютере... зашифрованными... добавьте файл, который вернул ИИ в этот же чат". Sidebar: "Чатов пока нет..." Drop note lists formats | Covered | index.html:1203, 387, 1127-1131 | Does not say which file goes to the AI. That comes only after the first result ("Сохранить файл для ИИ", "Что дальше" collapsed). Fine for a first run, since the label "Для ИИ" appears next to versions | Keep | None (do not add a wizard) | - | P2 |
| 1.2 | Know what stays local | Same screen | "на этом компьютере", "зашифрованными" present. No line that nothing is uploaded or that the original is kept/not kept by default | Partially | index.html:1203; `keep_originals` default True vault.py:36 | Default keeps encrypted originals; draft screen mentions only a checkbox in the chat meta | One sentence under the checkbox: "Оригинал хранится зашифрованным на этом компьютере" | Copy tweak only | - | P2 |
| 1.3 | Fresh vault, no chats, first doc -> first result | Add file -> Обезличить | Chat auto-created, named from original file stem, result opens below feed | Covered | webapp.py:213-220, 304-312; index.html:1231-1250 | Chat title = ORIGINAL file name, shown in sidebar while table values are masked by default. Local only, but weaker than the neutral-name promise | Accept (documented in docstring) | none | - | P2 |
| 1.4 | Return to an old chat | Click chat in sidebar | Opens with steps, files, versions; `openSeq` drops stale responses | Covered (code) | index.html:1157-1165 | No browser test of rapid switching | - | JS test for openSeq race (optional) | - | P2 |
| 1.5 | First run when vault could not be opened | Launch with unreadable vault.bin | Vault moved aside, notice shown. Chats are encrypted with the same device key, so unreadable chat.bin files are skipped by `listing()` with NO message | Partially | vault.py:89-102; chats.py:60-66, 100-110 | Notice talks only about files; chats vanish quietly | One-line notice when chat dirs exist but none can be read | Count unreadable dirs in `listing()`, surface in notice | unit: corrupt chat.bin -> notice | P2 |

### 2. Chat lifecycle

| # | Intent | Path | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|------|-----------|--------|----------|---------|----------|-----|------|-----|
| 2.1 | Create chat | "Новый чат" = draft; real chat made on first job. Only if the draft checkbox differs from default is an empty chat created before the job | If the job POST then fails, an empty chat stays | Partially | index.html:707-712 | Rare empty leftover | Create lazily after job accepted | Move chat creation after `post(endpoint)` succeeded or delete on failure | - | P2 |
| 2.2 | Auto-created from document | Verified | Title = file stem (or "Чат") | Covered | webapp.py:304 | - | - | - | exists | - |
| 2.3 | Failed-only job | Upload .png / broken file, press Обезличить | Verified: job state done, an empty chat titled "scan" with one failed record and a vault history entry are created | Broken (minor) | webapp.py:200-211 (`_record_job` only skips non-"done"); exp: B | Sidebar fills with dead chats from failures; vault history polluted | No chat when no file produced output | In `_write_chat` skip when all outcomes are error and no chat_id given | unit: all-error job leaves chat list unchanged | P2 |
| 2.4 | Rename | Click title, Enter/Esc | Max 200, empty reverts | Covered | chats.py:112-120; index.html:1255-1262 | - | - | - | exists | - |
| 2.5 | Many / long names | Sidebar item has `title` tooltip, `text-overflow` assumed in CSS | Not verified visually | Not verified | index.html:1135 | - | - | screenshot at 200-char title | - | P2 |
| 2.6 | Delete chat | Delete -> dialog -> "Удалить чат" | Dialog is accurate: files erased, vault labels stay, other chats and files already sent to AI unaffected. Verified chat deletion keeps restore working (restore after delete creates a new chat titled with the original name) | Covered | index.html:1262; chats.py:134-147; exp: H | Dialog does not say originals and the table view for this chat go too (it says "файлы"). Cancel path returns null, nothing deleted | Fine. Mention "в том числе оригиналы" when `keep_originals` | Copy tweak | - | P2 |
| 2.7 | Delete while a job is running | Delete handler does not call `busy()`; sidebar and "Новый чат" do | Job result then recreated in a NEW chat silently (store.get is None -> create) | Broken | index.html:1262 vs 1115; webapp.py:216-217 | Chat the user just deleted reappears with the results | Block delete while running, or refuse to recreate when `chat_id` was given and is gone | Add `if (busy()) return;` and in `_write_chat` raise when chat_id given but gone | JS/unit: stale chat_id job | P2 |
| 2.8 | Job started with a chat id that no longer exists | API `start_job` | `KeyError("Чата нет")` -> 404, user sees message | Covered | webapp.py:160-161; exp F | - | - | - | - | - |
| 2.9 | Multiple runs per chat | Add same file again | Verified: a second record for the same file is added, same neutral name, two "anonymize" steps | Partially | exp D | No "already processed here" hint; two identical `Файл2 (обезличено).txt` records | Peek says "этот файл уже обезличивался в чате X" | In `peek`, compare `vault.file_numbers`/name with chat records; show note, keep both allowed | unit: peek of known file name | P1 |
| 2.10 | Which document belongs to which chat | Step rows show anon name plus "Из файла: ..." | Covered; restore matches by anon name, then by unique token superset, else new record | Covered | webapp.py:236-247 | Two different docs with the same name share one number (`file_number(name)`), so their anon files are indistinguishable by name in the chat; restore binds to the first | Distinct anon names per content, or add a short suffix | Not now; note only | - | P2 |
| 2.11 | Current chat after restart | Always opens a new draft | Chat not reopened | Missing | index.html:1434-1438 (`startDraft()`) | "Where was I yesterday?" needs one sidebar click. No visible "last chat" | Open most recent chat or keep draft but highlight it | Use `chatList[0]` if updated < 24h; or leave as is (chat list sorted by recency) | - | P2 |
| 2.12 | History (vault.history) vs chats | Restart | See F3 | Broken | below | | | | | P1 |

**F3 detail (P1, verified).** `App.__init__` calls `chats.import_history(vault)` on every start (webapp.py:66). `import_history` marks only chats that already carry a `history_id` as known (chats.py:320-343). Chats created by normal jobs have no `history_id`, so after one restart every past job produces a second, archived, file-less chat (title = anonymized file name, e.g. `Файл1 (обезличено).txt`). Deleting that ghost, or the real chat, brings it back on the next start. The UI has no `archived` handling (0 occurrences in index.html), so ghosts look like normal chats whose files say "Версии нет на диске". Fix: tag jobs written natively with `history_id` (put `job.id` in vault history entry, record it on the chat) or run `import_history` only once, gated by a `prefs["history_imported"]` flag; hide `archived` chats behind a filter or drop the feature. Test: create job -> restart -> `listing()` length unchanged; delete archived -> restart -> still gone.

### 3. File input

| # | Intent | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|-----------|--------|----------|---------|----------|-----|------|-----|
| 3.1 | Supported formats | xlsx/docx/pptx (OOXML), pdf, TEXT_EXTENSIONS. Picker filter lists xlsx docx pptx pdf txt csv md json xml html log yaml | Covered | formats.py:335-350; desktop.py:32 | Drag/drop accepts anything and tells the reason afterwards | - | - | - | - |
| 3.2 | Unsupported (.doc, .xls, .rtf, .odt, macros, images) | Peek gives a specific "save as .docx" hint; the file is shown red and Обезличить stays disabled unless another file is ready | Covered | service.py:39-54, 256-269; index.html:660-689 | - | - | - | - | - |
| 3.3 | Corrupted / password protected | Peek: "Файл защищён паролем..." / "повреждён" | Covered | service.py:169-180, 270-279 | - | - | - | - | - |
| 3.4 | Empty file | Browser path: 400 "Файл пустой." Native picker path (`add_upload_path`) has no empty check, goes to anonymize, ends in warn "Данных для замены не найдено" | Partially | webapp.py:590, 123-128; exp C | Inconsistent between drop and picker | Same message both ways | Move empty check into `add_upload` | unit | P2 |
| 3.5 | Very large | >300 MB refused at upload (path and body); whole file read into memory; unpack bomb >1 GB refused | Covered | webapp.py:126, 464; service.py:183-197 | Memory of 300 MB x copies; no progress during upload | - | - | - | P2 |
| 3.6 | Duplicate upload in one batch | Both are processed. `Копия ...txt` gets a different number (Файл3). Same name -> same number, second gets ` (2)` suffix | Partially | exp D2; service.py:466-468 | Nothing tells the user two identical files were queued | Warn on identical name+size in the composer list | JS dedupe hint in `addEntry` | - | P2 |
| 3.7 | Folder | Separate path; result written to a mirror folder, NOT into a chat, original folder untouched | Covered | webapp.py:368-382; index.html:403-409 "Папка обрабатывается отдельно, в чат не попадает" | Folder results have no chat history, so "restore tomorrow" has no chat to find (vault-based restore still works) | Accept; do not merge folder into chats | - | - | P2 |
| 3.8 | Original vs anonymized vs already processed | Peek counts tokens already known to this vault: composer says "В файле есть коды замены (N): ... Его можно восстановить", main button flips to Восстановить, "Обезличить всё равно" stays as link | Covered | index.html:671, 694-703 | Tokens counted only if the vault knows them; a file anonymized in another vault shows 0 and gets re-anonymized | See F1 | - | - | - |
| 3.9 | Renamed copy of an already processed file | Name irrelevant; token-based detection | Covered | service.py:280-286 | - | - | - | - | - |
| 3.10 | Drag/drop of a folder in the webview | Not verified; entries without data probably fail upload and show per-file error | Not verified | index.html:633-640 | - | - | manual test on Windows | - | P2 |

### 4. Config before processing

| # | Intent | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|-----------|--------|----------|---------|----------|-----|------|-----|
| 4.1 | Standard profile and plan line | `renderPlan` writes "Будут скрыты: ... Не скрываются: ..." and title "Стандартное/Свои параметры", Reset link when not standard | Covered | index.html:741-760 | "neutral_names" off is not in either list: file names are no longer replaced wholesale but the plan line says nothing about file names | Mention "имена файлов" in the hidden list when on, in "Не скрываются: имена файлов" when off | 2-line change in `renderPlan` | page test | P1 |
| 4.2 | Dangerous silent combinations | No combination blocks anything silently except `neutral_names=false` (file name may leak a client/project the detector misses: `service._anonymized_name` falls back to detector only) and `countries=false` (stated). `strict` ON hides doubtful words (stated) | Partially | service.py:540-551 | Same as 4.1; also `numbers` replaced "числа в Excel" ok | See 4.1 | - | - | P1 |
| 4.3 | Where do toggles live | Main-screen checkboxes are initialised from prefs by `loadState()`; changing them does not persist; `openSettings()` calls `loadState()` and so silently resets any per-run choice | Ambiguous | index.html:734-760, 962-973, 987 | User changes "countries", opens Settings, returns: toggle snapped back, plan line also changes | One source: either per-run (and untouched by Settings) or persisted | Only set checkboxes from prefs when the Settings dialog saved them | JS test | P2 |
| 4.4 | Custom terms ("Всегда/Никогда скрывать") | Merged from prefs plus options; "own words (N)" appears in plan line; decisions from rerun persist (`_remember`) | Covered | service.py:293-303, 413-428 | Terms persisted from a one-off rerun become global silently (a "Решения сохранены" note is shown) | Accept; note is shown | - | - | P2 |
| 4.5 | Terminology consistency | "Обезличить", "Восстановить", "Для ИИ", "Исходный, не для ИИ", "коды замены", "метки", "соответствия", "таблица замен", "хранилище" are all used for the same Name1-style token; AI hint says "метки" | Ambiguous | index.html:671 vs 879 vs 1262; service.py:680 | Three words for one thing in one flow (коды / метки / соответствия) | One term: "коды замены" in UI, "метки" in AI hint only | Copy pass | - | P2 |
| 4.6 | Rebuild options | `btn-apply` posts `options: runOptions()` (current checkboxes) | Broken | index.html:1308; chat_api.py:50-51 | See F5 | Rebuild must reuse the options stored with the chat's last anonymize job | Persist `options` in the anonymize step; use them in `apply_chat` | unit: apply after toggle change keeps options | P1 |

### 5. Processing lifecycle

| # | Intent | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|-----------|--------|----------|---------|----------|-----|------|-----|
| 5.1 | Start / progress | Poll every 350 ms, bar and stage ("Анализ: имя", "Обезличивание: имя") | Covered | index.html:706-733; service.py:364-383 | - | - | - | - | - |
| 5.2 | Double click | Buttons disabled while `running`; API-level concurrent jobs serialise on `service.lock` | Covered (code) | index.html:682; service.py:317 | - | - | - | - | - |
| 5.3 | Cancel | No cancel anywhere (no route, no button); closing the window does not stop the daemon thread either | Missing | webapp.py routes; none | 300 MB file = long wait, no escape | A "Отмена" is NOT recommended; a progress hint is enough | Show "Это можно закрыть? Нет" line only if >20 s | - | P2 |
| 5.4 | Failure of the whole job | `job.state=failed`, message "Не удалось выполнить операцию (Type). Файл не изменён." Vault not committed | Covered | webapp.py:190-193 | Message is user language but gives no next step | Add "Повторите или выберите другой файл" (page already does when error is empty) | - | - | P2 |
| 5.5 | Partial failure | Other files complete; error files are recorded in the chat as "Не обработан"; result headline switches to "Файл готов, но его нужно проверить" | Covered | index.html:789-810; webapp.py:266-269 | The failed record stays in the chat forever (no route to remove a file; `remove_file` exists in store but not exposed) and the composer is emptied on success so retry means re-adding the file | Keep failed files in the composer after the job so Повторить is one click | `afterJob` keeps entries with status error | JS test | P2 |
| 5.6 | Retry | Via "Обезличить заново с этими словами" (rerun) | Covered | webapp.py:162-189 | Rerun is available only for jobs still in memory; after 6 h or restart: "Исходные файлы этого задания уже удалены. Загрузите файл заново." clear message | Covered | - | - | - |
| 5.7 | Switch chats during processing | Blocked with toast "Идёт обработка файла..." | Covered | index.html:1115, 1136 | Delete not blocked (2.7) | - | - | - | P2 |
| 5.8 | Restart during processing | Nothing is committed (vault commit is at the end of `anonymize`), upload is lost; next launch starts clean | Covered (code) | service.py:353-355 | Window close mid-job gives no warning | Accept | - | - | P2 |
| 5.9 | Vault committed but chat write failed | See F4 | Broken | webapp.py:200-211 | | | | | P1 |

**F4 detail (P1, verified).** `_record_job` swallows any exception and sets `job.chat=""`. The page builds the save button only when `job.chat` is truthy (`saveButtonHtml`, index.html:818-823) and `afterJob` goes to `renderResult` with no chat. The headline still reads "Готово. Файл можно загружать в ИИ." with no way to save (the `/api/download/<job>/<i>` route exists but nothing in the page uses it for chat jobs). Tokens are already committed to the vault. Fix: in `saveButtonHtml` fall back to `saveOne`/`saveAll` (already in the file) when `job.chat` is empty, and add a warn line "Не удалось записать в чат. Сохраните файл сейчас". Test: monkeypatch `_write_chat` to raise, assert a save control renders (page test) and `downloadable` stays True.

### 6. Result experience

| # | Intent | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|-----------|--------|----------|---------|----------|-----|------|-----|
| 6.1 | Which file is safe for AI | Result button says "Сохранить файл для ИИ"; versions are labelled "Для ИИ" / "Исходный, не для ИИ" / "Возвращённый"; `saveStepFiles` saves only the anon role | Covered | index.html:818-829, 1086 | "Возвращённый" carries real data but has no warning label | "Возвращённый (с настоящими данными)" | Copy | - | P2 |
| 6.2 | Unsafe file presented as safe | Headline escalates to "нужно проверить" on warnings, errors and strong suggestions; weak suggestions get their own caution. `BLOCKED` files and files that fail `check_openable` are non-downloadable | Covered | index.html:789-800; service.py:488-500 | Safe headline is shown when the detector finds no strong suggestion; unavoidable, headline is conditional wording | - | - | - | - |
| 6.3 | Primary action | One main button "Сохранить файл для ИИ…" | Covered | index.html:818-823 | When several files, one save dialog per file in a loop (`saveStepFiles`) | One folder dialog for multi-file | Use `save_all`-style folder pick for chat jobs | desktop test | P2 |
| 6.4 | Replacement counts | Per file and step ("Заменено значений", grouped counts) | Covered | index.html:775-787, 1170-1190 | - | - | - | - | - |
| 6.5 | Where is the original | Version row "Исходный, не для ИИ" appears when `keep_originals`; if not kept, the row simply has no orig entry and nothing explains why | Partially | chats.py:226-231; index.html:1184-1190 | User with originals off may think original is lost | Meta line already shows "оригиналы хранятся" only when on; add "оригиналы не хранятся" when off | Copy | - | P2 |
| 6.6 | Inspect / correct / rebuild | Table pane, then "Пересобрать" needs stored originals; without them hint tells to enable and re-add files | Covered | index.html:1273-1311; webapp.py:314-329 | Rebuild options bug (4.6); old anon file replaced with no undo | Keep prior anon blob until user saves new one, or add as new record | `apply_chat` should add a step but keep previous blob under "previous" role | unit | P1 |
| 6.7 | Save / overwrite / duplicate / error / file missing | Save uses OS "Save as" (overwrite prompt is the OS's). Folder save uses `_free_name`. Errors: "Не удалось сохранить файл. Выберите другую папку или закройте файл..." Missing job file: "Файл больше не доступен. Обработайте его заново." | Covered | desktop.py:211-294 | A user can pick the original document as the target and overwrite it with the anon file (OS prompt only) | Warn if target equals a path the user dropped (paths are known for picker uploads) | Track picked source paths in desktop bridge, refuse overwrite | desktop test | P2 |
| 6.8 | Chat version no longer on disk | "Версии нет на диске" label; open/save return "Версия файла больше не доступна." | Covered | index.html:1190; desktop.py:229-231 | - | - | - | - | - |
| 6.9 | Open original/restored file | Writes decrypted copy to `work/.open`, shredded on exit and start; no warning that a plain copy exists on disk meanwhile | Partially | webapp.py:337-361 | If the app crashes the copy persists until next start | Accept; `cleanup_open` on start exists | - | - | P2 |

### 7. Restoration tomorrow

| # | Intent | Behaviour | Status | Evidence | Problem | Expected | Fix | Test | Pri |
|---|--------|-----------|--------|----------|---------|----------|-----|------|-----|
| 7.1 | Find chat / doc | Drop the AI-returned file anywhere; with chat open it is added to that chat; from a fresh draft a new chat is created and titled with the restored original name. Verified H | Covered | webapp.py:213-247; exp H | Restore from a draft does not look for the originating chat (only Office does via `match_chat`), so the restored file lands in a new chat | Desktop should reuse `match_chat_by_tokens` when no chat is open | pass `match_chat=True` from the page for restore | unit: restore from draft lands in the matching chat | P1 |
| 7.2 | Restore after mapping edit / merge / split | Mapping lives in the vault only, so restore uses current values. Edit tracked by another auditor | Not verified (out of scope) | restore.py:106-130 | - | - | - | - | - |
| 7.3 | Restore after restart | Vault persisted; restore works (jobs/vault independent of chat). Verified A/H paths | Covered | vault.py; exp H | - | - | - | - | - |
| 7.4 | Overwrite behaviour | Each restore creates a new record/step; earlier restored version is not overwritten. Verified G: restore twice gives two records, second named by the anon upload name, not the original | Partially | webapp.py:239-261; exp G | Chat step list grows; second record has the anon name | Reuse the first record's restored role (replace) | Allow `target` where `restored` already exists | unit | P2 |
| 7.5 | Rollback of a restore | None; restore does not change vault or chat content. Only adds a version | Covered | restore.py | - | - | - | - | - |
| 7.6 | Wrong vault / cleared vault / other computer | OOXML and PDF carry a vault marker and are refused with a clear message. TEXT files carry none | Broken | service.py:628-633; formats.py (`read_vault_marker`); F1 | See F1 | Marker for text, or refuse when tokens exist but history has nothing | See F1 | see F1 | P0 |

**F1 detail (P0, verified).** Experiment: anonymize `a.txt` ("Иван Петров подписал договор." -> "Name1 подписал договор."), Clear vault, anonymize `b.txt` (new vault gives Name1 to "Мария Сидорова"), restore the first file. Result text: "Мария Сидорова подписал договор." with `status=ok` and no message. `_restore_one` only checks a marker for OOXML/PDF (service.py:628). Clear vault resets `vault_id` and counters (vault.py:184-193), so new numbering collides with old files. Same exposure for text files made on another computer or restored from an old backup. The Clear dialog claims "не восстановить", which is true only for OOXML/PDF. Fix (smallest): at anonymize time append an invisible vault-id marker to text output the same way OOXML does (zero-width encoded id, or a first/last-line comment where the format allows), and refuse or warn in `_restore_one` when a TEXT file has tokens that were issued before the current `vault_id` epoch. Cheaper interim: when `vault.history` is empty or the job id of the matching anonymize entry is newer than the first token seen in the file, add a loud warn "Метки могли быть выданы раньше очистки хранилища". Tests: clear then restore old txt must be `error`; txt from the same vault restores unchanged; backup import of the owning vault allows it.

### 8. Persistence guarantees (verified where "exp")

| Item | Survives restart? | Evidence |
|------|-------------------|----------|
| Chats (metadata, versions, originals) | Yes, encrypted with device key, until retention (180 d) / delete / vault clear / purge | chats.py; exp A2 |
| Mappings (vault) | Yes; saved at `vault.commit()` per job; unreadable vault moved aside with notice | vault.py:89-102 |
| Settings and prefs (numbers, strict, countries, neutral_names, keep_originals, retention, hide/keep terms) | Yes | vault.py:27-38 |
| Sidebar collapsed | Yes (`prefs.sidebar_collapsed`) | index.html:1106 |
| Do-not-hide / always-hide lists | Yes; survive Clear vault (exp I printed prefs) but chats and mappings they refer to do not | vault.py:184-193 |
| Doc-to-chat binding (`bound_doc`) | Yes in chat.bin; used by Office only | chats.py:122-128 |
| Per-run toggles on the main screen | No (reset from prefs); draft title and queued files: No (uploads kept 3 h in memory, lost on restart) | index.html:962-973; webapp.py:141-144 |
| "Show values" in table | No (sessionStorage), good for privacy | index.html:1312 |
| Current chat | No: always a new draft | index.html:1434-1438 |
| History / archived chats | Duplicated every restart (F3) | chats.py:320-343 |

### 9. Errors and recovery

| Scenario | Message / behaviour | Work preserved? | Retry? | Status | Evidence |
|----------|--------------------|------------------|--------|--------|----------|
| Unsupported / invalid file | Specific Russian text with "save as" hint | n/a | Yes | Covered | service.py:39-54 |
| Save failure | "Не удалось сохранить файл. Выберите другую папку или закройте файл, если он открыт." | Yes (blob stays in chat) | Yes | Covered | desktop.py:288-294 |
| Permission / missing output path | Same OSError text; native dialog usually prevents missing path | Yes | Yes | Covered | desktop.py:288 |
| Processing exception | "Не удалось обработать файл (Type). Возможно, он повреждён или защищён паролем." Generic for every exception incl. bugs | Vault untouched for whole-job failure; per-file failure still commits vault tokens issued by that file's partial work | Re-add | Partially | service.py:475-478, 353-355 |
| Corrupted vault | Moved aside with notice; chats hidden silently (1.5) | Partially | Restore backup via Settings | Partially | vault.py:89-102 |
| Corrupted/missing mapping row for token | Restore: "Не удалось восстановить метки: ..." | Yes | Yes | Covered | service.py:682-686 |
| Missing original (keep_originals off or purged) | Rebuild refuses: "Исходники в этом чате не хранятся..." | Yes | Yes | Covered | webapp.py:319-328 |
| Missing generated file | "Файл больше не доступен. Обработайте его заново." (job dir cleaned after 6 h); chat copies stay | Yes | Yes | Covered | desktop.py:211-214; service.py:228-237 |
| Stale chat binding | `KeyError("Чата нет")` message; Office dialog shows "Чат не найден" | Yes | n/a | Covered | webapp.py:160; index.html:1426-1429 |
| Chat write failure | Silent (F4) | Result unsaved | No | Broken | webapp.py:200-211 |
| Stale session link | "Откройте программу заново: адрес с ключом сеанса устарел." | Yes | Yes | Covered | webapp.py:524 |

### 10. Destructive and privacy operations

| # | Operation | Behaviour | Status | Evidence | Pri |
|---|-----------|-----------|--------|----------|-----|
| 10.1 | Reveal values | Toggle in table pane, default off, sessionStorage only; no confirm needed | Covered | index.html:1312-1333 | - |
| 10.2 | Original file access | "Открыть" (decrypted temp copy) and "Выгрузить файл"; role label "Исходный, не для ИИ" | Covered | index.html:1086, 1184 | P2 (6.9) |
| 10.3 | Delete chat | Confirm dialog with accurate scope; shreds files; vault kept | Covered | index.html:1262; chats.py:134-147 | - |
| 10.4 | Clear vault | Confirm text omits chat deletion (F2). Also resets numbering (F1) | Broken | index.html:1009; webapp.py:331-336 | P0 |
| 10.5 | Restore file | Produces real-data file; no warning not to send it to the AI | Partially | index.html:1086 | P2 |
| 10.6 | Backup export/import | Password min 6, file `.anonkeys`. Import replaces vault; chats are not part of backup | Not verified (outside scope) | webapp.py:621-631 | - |
| 10.7 | Retention purge | Runs at start: chats older than 180 d and restored versions older than 30 d deleted without any notice | Broken (disclosure) | webapp.py:65; vault.py:28-29 | P1 |

**F2 detail (P0, verified).** `index.html:1009` confirm text: "Все соответствия будут удалены. Ранее обезличенные файлы после этого не восстановить." `App.clear_vault` also calls `chats.wipe()`, which shreds every chat, stored original, anonymized and restored version. Hide/keep term lists survive. Fix: say so, with counts ("Будет удалено: N чатов, M файлов, K соответствий. Настройки сохранятся.") and require typing nothing extra; offer "Сохранить резервную копию" link first. Test: page test for text; unit test that `clear_vault` result matches the stated counts.

**F5/F6 note.** F6: the first-run screen and settings should say, once, "Чаты хранятся 180 дней, возвращённые файлы 30 дней" next to the retention control, and the chat meta line should show "удалится ДД.ММ" for chats with <14 days left. Do not add notifications.

## What should intentionally NOT be added

- No cancel button for jobs (low value, high risk of half-written vault state).
- No wizard / tour / onboarding screens; copy fixes only.
- No auto-save of the composer queue or draft title across restarts.
- No cloud, no accounts, no export of the vault together with chats.
- No automatic "safe file" scoring; keep labels "Для ИИ" and warnings.
- No merging folder jobs into chats (separate by design, noted in the UI).
- No per-chat settings dialog; store the options of the last anonymize step instead.
- No new archive concept: remove `archived` import rather than building UI for it.

## Top gaps ranked

1. F1 P0: text-file restore after Clear vault / other vault silently inserts wrong people. Add vault marker or a restore guard for TEXT; add regression test (clear -> anonymize other -> restore old txt = error).
2. F2 P0: Clear vault dialog must say chats, originals and all versions are deleted, with counts; offer backup. Test the text and counts.
3. F3 P1: `import_history` re-creates ghost chats on every start and resurrects deleted chats. Mark native chats with a history id or import once; test restart idempotence.
4. F4 P1: chat-write failure leaves a "ready" result with no save control. Fall back to direct save; add warn; test with a monkeypatched `_write_chat`.
5. 4.6/6.6 P1: rebuild uses current toggles and overwrites the old anon file. Persist options on the anonymize step; keep the previous blob.
6. F6/10.7 P1: tell the user about 180/30-day retention and what it removes.
7. 7.1 P1: restore from a draft should land in the matching chat (`match_chat`), not create a new one.
8. 2.9 P1: peek should flag "already processed in chat X" (same name or tokens), second run should not silently add an identical record.
9. 4.1/4.2 P1: plan line must mention file names when `neutral_names` is off.
10. P2 batch: failed-only jobs create ghost chats (2.3), delete not blocked while running (2.7), empty-file inconsistency (3.4), Settings resets main toggles (4.3), term consistency (4.5), single multi-file save dialog (6.3), warn when save target equals a source path (6.7), open last chat after restart (2.11), unreadable chat dirs notice (1.5).

Not verified: all JS runtime behaviour (no browser/webview session), long-name layout, folder drag/drop in a webview, backup import with chats, scanned-PDF handling, Windows-specific save dialog behaviour.
