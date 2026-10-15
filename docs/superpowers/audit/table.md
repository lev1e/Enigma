# Audit: replacement table and rule/mapping correction lifecycle

Read-only audit. Method: traced `chat_api.py::_edit_entity/_undo`, `vault.py`, `chats.py::table`, `service.py` (`settings_for`, `rerun`, `_remember`, `apply_chat` in `webapp.py`), `index.html` (`entityAct`, `renderTable`, `renderApply`, `anonymizeExtras`, Settings), `taskpane.js` (table is a read-only list: `loadTable`, `pending_edits` flag only). Behaviours marked (run) were confirmed with small scripts through `tests/helpers.Env` using `.venv312`.

## Scope model (what each editable action really changes)

| Action (UI label) | Real scope | Touches current safe file? | Touches old files / restore | UI says scope? |
|---|---|---|---|---|
| Изменить значение (`edit_value`) | Vault entity variant: restore value only. Never changes detection. Applies to every chat and every old file with that code, and to every FUTURE restore. Already-restored files untouched. (run: restore gave the edited value, re-anonymize still emits Name1) | No | Yes, all restores | Yes, dialog text is accurate (`index.html:1389`) |
| Объединить (`merge`) | Vault-wide: future anonymizations of the source value emit target code. Source tokens stay restorable (vmap). Source entity restricted to same kind, non-secret. | No, until rebuild | Old files restore as before | Yes ("во всех чатах", "новые файлы") `:1395` |
| Выделить в отдельный код (`split`) | Vault-wide pin kind+spelling -> new code, future files only | No, until rebuild | Old files unchanged | Yes `:1402` |
| Не скрывать / Скрывать снова (`keep`/`hide`) | GLOBAL permanent list in prefs (`keep_terms`/`hide_terms`), all chats, all future docs, forever, matched by fold() (case-insensitive) on the WORD, not on the occurrence. Also visible/editable in Settings. | No, until rebuild | Old files restore as before | Note after the action says "в новых файлах, во всех чатах" `:1404`; the button label itself does not, and the "Settings" side effect is not mentioned |
| Удалить код (`forget`) | GLOBAL erase of the entity's spellings and pins, all chats. Number stays taken. Not a rebuild-requiring edit. | No (code stays in file) | All files with this code can no longer be restored (they report "no value") | Yes, danger dialog, "во всех чатах", "Отменить нельзя" `:1399` |
| Скрыть ещё слова -> checkbox suggestion | Writes `hide` into prefs (global, via `_remember`) AND re-runs the job | Replaces the file in the chat | - | Yes ("Решения сохранены ... Список: Настройки") |
| Скрыть ещё слова -> typed words | This job only (options.hide_terms), NOT in prefs (run: `prefs['hide_terms']==[]`). Persist only indirectly: the TERM entity is seeded from the vault into later runs (`service.py:309`). Not listed in Settings, cannot be removed | Yes (rerun) | - | NO: the block never says typed words are not remembered; checked suggestions are |
| Settings lists | Global, no chat step, no rebuild button | No | - | Settings text only |

No action is "this occurrence" or "this document". Occurrence/document scope does not exist in the backend (only global prefs + vault). See D.

## Matrix

Legend: Cov=Covered, Part=Partially, Miss=Missing, Brk=Broken, Amb=Ambiguous, NV=Not verified.

### A. Missed sensitive data (add word after processing, rebuild, optionally future, from table)
- Intent: "this word leaked into the safe file, hide it now".
- Current path: (1) result block right after the job: "Скрыть ещё слова" textarea or suggestion checkbox -> "Обезличить заново" (`index.html:904,937`, `/api/rerun`, needs the job still in memory `service.py:396`); (2) Settings -> "всегда скрывать" textarea, save, then manually re-add file (no rebuild control there).
- Behavior: path 1 works only in the live result view. Re-open the chat later, or restart: block gone, `/api/rerun` KeyError "Исходные файлы этого задания уже удалены". The table pane has NO way to add a word, and the only "hide" button is "Скрывать снова" for a variant previously kept. Typed words are not stored in prefs (run). Settings change adds no chat step so the "правок, не применённых" banner never appears (`pendingEdits` counts only edit steps `:1273`).
- Scope: typed word = job + vault TERM knowledge; suggestion = global. Status: Part. Priority: P1.
- UX problem: the most common correction (word leaked) is unreachable from the table and from a reopened chat; stale state after Settings edits invisible.
- Expected: "Скрыть слово..." in table pane header and from a selection-free input; one dialog: word, scope choices (this chat's files / always), then rebuild offered inline.
- Fix (reuse): new action `hide_new` in `_edit_entity` calling `vault.add_term("hide_terms", term)` (already exists) + record edit step `hide` so `pendingEdits`/`chat_summary` count it + existing `/apply`. Settings save should add a pending step to chats (or compare prefs hash to the chat's last-anonymize hash).
- Test: chat route test: add term via entities endpoint, assert pending_edits==1, apply, assert word absent in anon blob and Settings list shows it.

### B. Manual new mapping (value -> chosen code)
- Intent: map a specific string to a new/own code. Current: none. Only hide-term which creates `TermN` (kind TERM) with auto number. Status: Miss. Priority: P2.
- Expected: not needed beyond "hide word"; a user-chosen code is not required and would break the numbering invariant. Do not add (see Not-to-add).

### C. Add alias to existing entity (nickname/abbreviation -> Name3)
- Current: merge works only between two existing codes of the SAME kind both present in this chat's table (`chat_api.py:115-120`, `vault.merge` kind check). A typed alias becomes a new TERM entity; TERM cannot be merged into PERSON/ORG (kind mismatch ValueError). Result: alias gets its own code, cannot be unified. Status: Miss (alias of a word the detector did not see). P1.
- Expected: "Это тот же объект, что Name3" for a typed word.
- Fix (reuse): in `merge`, allow source kind TERM -> any target (the TERM has no detection semantics of its own) OR add `vault.add_alias(base, text)` = `entity["spellings"].append` + pin `pins[kind\0text]=base` (pins already route future detection: `token_for` pinned logic). Test: alias "Ванька" -> Name1, rebuild, both restore to same person.

### D. False positive ("Не скрывать")
- Meaningful scopes: (a) always/global (exists, via keep_terms, whole-word case-insensitive), (b) this chat's files only (rebuild with a per-run override; backend has `overrides`/`user_overrides` in `anonymize`, `rerun`, but no chat-scoped persistence). "This occurrence" and "this document" are NOT meaningful: detector decides per word via folded keys; a per-occurrence mask would desync with the restore table.
- Current: one scope, global, permanent, stated only in the after-action note. Part. P1.
- UX problem: user wanting "not here" cannot choose; keeps accumulate in Settings silently. Click affects the word everywhere (e.g. keep a surname that also is a real person elsewhere). Table button has aria-label only with token.
- Fix: two-choice dialog "Только пересобрать этот чат" (use `overrides={word:'keep'}` in apply options; `_remember` already skipped when not passed) vs "Всегда" (current). Show affected count of files in the chat.
- Test: keep with scope=chat does not alter `prefs['keep_terms']` and still unmasks on rebuild.

### E. Edit mapping ("Изменить значение")
- Changes: restore value only, vault-wide, all chats, all old files with that code, all future restores; does not change the current safe file or detection; already restored files do not change; undoable once (note). Dialog text states exactly this. Cov. (run confirmed). Residual: undo only in the transient note.
- Ambiguity: edited value hides original in search? `renderTable` search matches both value and original (fine). CSV exports the edited value only, original lost. P2.

### F. Merge
- Affects: vault-wide, future anonymizations, restore of old tokens fine (tests `test_merge_keeps_old_tokens_restorable...`). Current safe file/other chats' safe files still have the old codes -> table now shows them under the target row (describe resolves `_final`), so table and file diverge until rebuild. Files in OTHER chats are never flagged stale (pending is per chat steps). Pending flag set for this chat only. Status: Part. P1.
- UX: dialog says "Новые файлы получат выбранный код"; OK. Cross-chat staleness not shown.
- Test: merge in chat A, chat B list shows pending/stale indicator (needs per-chat "built before edit N" marker, e.g. vault edit counter vs chat file build counter).

### G. Split
- Same as F. Only available when a code has >=2 spellings; the choice is by spelling index, not occurrence. Test coverage exists (vault_edits, chat_routes). Part (no cross-chat stale indicator). P2.

### H. Delete ("Удалить код")
- Real: erases vault values + pins for that entity, all chats, irreversibly; code stays in all files; those files can no longer restore it (they report no value). Dialog states this plainly. NOT local. Warning: explicit, with danger style. Cov (warning).
- Surprise (run): next anonymization of the same person re-creates spellings under the SAME code (`by_key` kept, `token_for` re-appends spelling). "Удалить" therefore does not stop the value being hidden again or stored again; restore starts working for files again. Amb. P2.
- Missing: "remove from this chat/doc only" - not meaningful (codes are vault-wide). Better wording: "Стереть значение из хранилища", warning that the old files can no longer be restored. P2.

### I. Hide again after "Не скрывать" ("Скрывать снова")
- Calls `add_term("hide_terms", term)` which removes from keep_terms (mutually exclusive), global, needs rebuild (counted by `pendingEdits` incl. undo). Status: Cov. Risk: if the same word is also a standalone entity, see L (hide-over-existing).

### J. Undo/redo
- Undo exists for edit, merge, split, keep, hide (`UNDOABLE`), stateless server (client carries the descriptor). Only ONE level, only from the transient `#pane-note` (`lastUndo`, cleared by the next action or by closing/reopening the pane `setPane`); no redo; undo is also logged as a step and counts to pending. `forget` is irreversible and warned beforehand. A split undo merges the new code back (new code number stays consumed, cosmetic). Status: Part. P2.
- Fix: persist the last N undo descriptors in the chat step (`add_step` already stores action/base; add the undo dict) and offer "Отменить" in the chat feed step. Redo: do not add.

### K. Rebuild semantics (does the AI-safe file still match the table?)
- keep/hide/merge/split: do NOT touch the existing safe file. Banner "Правок, ещё не применённых к файлам: N" appears (`renderApply`, `taskpane.js:568` for Office) only when the pane is open; tab/pane closed = no indicator in the chat feed? (feed steps show "Правка", not stale). Stale state IS visible in one place only.
- P0 ENGINE FINDINGS:
  1. Partial rebuild silently clears the stale state: `apply_chat` (`webapp.py` ~line 337) only rebuilds files that have an `orig` blob; files without are skipped with no error if at least one has it; the job then adds a new `anonymize` step and `pendingEdits` resets to 0 (`index.html:1275`). Remaining files keep the old mapping with no warning. Status: Brk. P0 (a stale file presented as safe, now flagged clean). Hit when `keep_originals` was turned on after some files were added (`btn-keep-on`).
  2. Hide over existing entity creates a duplicate entity and can unmask other forms (run): doc "Иван Петров ... Позвонить Петрову" -> Name1 / Name1_2. After `add_term("hide_terms","Иван Петров")` the rebuild gives `Term1 ... Позвонить Петрову` (surname form now in clear text, Name1 not detected any more). Reachable through suggestion/typed words or Settings or "Скрывать снова". Status: Brk. P0 (leak). Fix: in `register`/`add_term` path, when a hide term equals an existing vault entity spelling, reuse that entity key (seed already has it) instead of a new TERM; add a regression test (the exact doc above).
  3. Settings hide/keep edits do not mark any chat stale. P1.
- Also: a rebuild uses `runOptions()` with `hide_terms: []` (`index.html:735`), typed-only words survive only via vault TERM seeding; after Удалить код / retention purge / vault clear they silently disappear on rebuild. P1. Fix: persist typed words to `hide_terms` (`_remember` already does it for overrides) or tell the user.

### L. Duplicates/conflicts
- Same value twice: see K2 (hide over existing makes a second entity; (run) hide "ромашка" over ORG gives both Company1 and Term2 in vault; output uses Term2).
- Alias attached elsewhere: merge refused across kinds (C).
- Code collision: counters per stem, safe. Case: hide/keep matched with fold(); (run) "ромашка" matched "Ромашка". Morphology: handled by the recognizer for TERM (run: Сириусом -> Term2_2). Abbreviations/whitespace: NV.
- Keep applied to phones: (run) keep "+7 912 345-67-89" removed Phone1, so keep is a universal global switch, not only for names. Fine but non-obvious. P2.
- Contradictory entries: add_term keeps them mutually exclusive (test exists); Settings textareas allow both lists with the same word, then "keep" wins in recognizer (`self.keep`). NV for hide+keep tie. P2.

### M. Large table (163+ rows)
- Search exists (code, original, value; masked values still searchable = confirms presence; acceptable). Grouped by kind with counts. Each toggle/search re-renders all rows via innerHTML; focus restored by `focusRow`. No sort, no filter by kind/edited/kept/merged, no "expand all", no keyboard shortcut for search (focus moved on open), no row count of files per variant. Part. P2.
- Fix: kind chips + "изменённые/объединённые" filter reusing `r.merged`, `v.edited`, `v.kept` already in `describe`.

### N. Export/import and privacy
- CSV export of the table (`index.html:1411`): Код;Вид;Значение;Файлов, always with real or edited values, hint text "В таблице настоящие данные: не загружайте её в ИИ." sits beside the button; no confirm dialog; export works even with values hidden on screen (reveal state ignored). Hidden state does not protect the export. Cov (warning text), P2 (add confirm; name file explicitly "не для ИИ").
- Reveal toggle persisted in `sessionStorage` across chats; rows masked by default; Office table has server-side `reveal` flag. Cov.
- Import of rules: none (only vault backup/restore with password). Not needed (see below). Backup includes prefs. NV: backup merge conflict policy for hide/keep lists (prefs are not merged by `import_backup` when vault non-empty). P2.

## Top gaps ranked (concrete fixes reusing backend)

1. P0: Hide-over-existing-entity leaks other forms. Fix in `entities.py` register / `Vault.add_term`: reuse the existing entity key if the hide term matches a registered spelling; cover with a regression test using the doc in K2.
2. P0: Partial rebuild marks everything applied. Fix `apply_chat`/`_record_job`: if some files lack `orig`, rebuild those, and keep the pending/stale marker for the rest (add a per-file `stale` flag, or refuse with the current ValueError unless all have originals), and warn in the note which files were NOT updated.
3. P1: No "add missed word" in the table or reopened chat; typed words not persistent or listed. Add `hide_new` action using `vault.add_term` + step + existing `/apply`; persist typed words to `hide_terms` so Settings lists them.
4. P1: Settings edits and cross-chat effects produce no stale indicator. Add a vault `rules_version` counter incremented on `merge/split/add_term/remove_term/set_prefs(hide|keep)`, store it in each chat file record at build time; show "устарел" per file and per chat.
5. P1: Scope choice for "Не скрывать" (chat-only vs always) using existing `overrides` path in rerun; show affected file count.
6. P1: Alias: allow TERM -> any-kind merge or `add_alias` via pins.
7. P2: Make the last undo durable (store descriptor in the edit step, show in feed); wording of "Удалить код" (re-created on next anonymization; old files lose restore).
8. P2: Table filters (kind, edited, kept, merged) and CSV confirm.

## Intentionally NOT to add
- Per-occurrence or per-document masking in the table (breaks the vault-wide code invariant and restore).
- User-chosen custom codes (breaks numbering, collision risk).
- Redo and multi-level history beyond persisting the last undo.
- Auto-rebuild on every edit (rebuild is slow, replaces versions; keep explicit button but make staleness unmissable).
- Rules import/export separate from vault backup.
- Revealing values in the Office task pane list beyond the existing server flag.
