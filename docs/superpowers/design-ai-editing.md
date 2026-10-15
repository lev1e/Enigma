# Design spec S14: model choice, trust tiers and AI editing of Office documents

Status: proposal for owner and security-service review. No product code in this change. Baseline: branch main at S13 (pill composer, per-message file choice, preview panel, text-file AI edit as a new version).

Goal: the built-in chat works like an ordinary AI chat; the user can switch model (internal Tedorra/Qwen, GPT, Claude, others); the model can really edit pptx (first), docx, xlsx, anonymized or not, with element selection, comments, suggestions and version history; the screen stays minimal; the company security service can review and own the rollout.

## 0. What exists today (verified in the code)

| Fact | Where | Consequence for this spec |
|---|---|---|
| Providers: `anthropic`, `openai`, `gemini`, `openrouter`, `custom`; stdlib `urllib`, no retry, no redirects, https required for non-local hosts, key only in a header, `scrub()` on errors | `llm.py` | Tedorra fits `custom` (OpenAI-compatible). Transport rules stay; we add a host allow-list and a tier. |
| Outbound guard: scans every outgoing part against all vault originals and the detector; definite hits can never be allowed; scan failure blocks | `guard.py` | Stays always on for external. Gets a second, narrower mode for internal (section 1). |
| Three locks: AI on in settings, AI on for the chat, guard pass. History is stored only in label form in `ai.bin`; log has time, provider, model, size, labels, no text | `ai_chat.py`, SECURITY.md | Extended, not replaced. |
| Text-file AI edit: model returns the whole file between `<<<ФАЙЛ>>>`/`<<<КОНЕЦ>>>`, labels checked by `Restorer` (unknown/removed/loose labels = refuse), result stored as a new file record "<name> (правка ИИ N)", step kind `ai_edit`, original kept | `ai_chat._apply_edit` | Same safety shape reused. For docx/xlsx/pptx edit is refused today ("Править файл .docx прямо в чате пока нельзя"). |
| Chat sends only anonymized text of chat files (max 3 files, label form); original and restored versions are never selectable | `_with_chat_files`, design-chat-13 | Rule kept for external providers. |
| Preview: `preview.py` returns JSON, pptx = text per shape only, docx = blocks, xlsx = first sheet rows; page builds DOM with `textContent` | `preview.py` | No addresses yet; must be extended with stable element ids. |
| OOXML is parsed with lxml part by part (`parse_part`), structural snapshot (slides, charts, comments, media, embeddings, macros, signatures) compared before/after, restore walks XML text nodes with `Restorer`, xlsx numeric cells carry a mark and finance workbooks have a stored record | `formats.py`, `restore.py` | Edit engine reuses the same parser, the same before/after snapshot check and the same restore path. |

## 1. Trust model

### 1.1 Tiers and who decides

| Tier | Meaning | Example | Data allowed to leave |
|---|---|---|---|
| `internal` | Endpoint inside the company perimeter, owned by the company, contractually no retention outside | Tedorra (Qwen) | Anonymized text always. Originals only if policy allows and the user opts in per chat (1.3). |
| `external` | Anything else | GPT, Claude, Gemini, OpenRouter | Anonymized text only, outbound guard always on, no exceptions. |
| `local` | Loopback only (existing `is_local`) | Test fake, local Ollama | Treated as `external` unless policy lists it as internal. Loopback is not a trust claim. |

The tier is never a user setting. It comes only from an admin policy file (1.5). A provider the user adds in the page that is not matched by the policy is `external`, whatever its URL looks like. A policy match requires exact scheme + host + port; a path or redirect never upgrades a tier.

### 1.2 Default is closed

No policy file: all providers `external`, originals never sent, AI off until the user turns it on (as today). A malformed or unsigned policy (when signature is required) behaves like no policy and the page says "Политика безопасности не загружена: работают только обезличенные данные и внешние модели ограничены." A policy change takes effect at the next request; running requests finish under the old policy.

### 1.3 Rules per request

| Case | Rule |
|---|---|
| External provider | Only label-form text. Guard `full` mode (vault originals + detector). Blocked = nothing sent, nothing stored, findings listed without values. |
| Internal provider, anonymized data | Same as external, including guard `full`. Default for everything. Internal is not an excuse to skip masking: it keeps the model blind to real values and keeps restore exact. |
| Internal provider, originals (optional, phase P5, off by default) | Needs all three: policy `internal.send_originals = "per_chat_optin"`, the user ticks "Работать с исходным текстом" in this chat, provider host is in the policy allow-list. Guard runs in `secrets_only` mode: passwords, keys, tokens, connection strings are still blocked; names, numbers, organisations pass. Chat shows a persistent badge "Исходные данные уходят во внутреннюю модель". |
| Secrets (passwords, keys, tokens) | Never leave in any mode. Existing behaviour. |
| Files | Per message the user picks files (S13). For external and for internal-anonymized only the anonymized version is selectable. Original/restored versions appear in the menu only in internal-originals mode. A message mixes files only within one mode; mixing is refused with a message (scenario 2). |

### 1.4 Switching model mid-conversation

History is stored as label-form messages tagged with the mode they were sent in (`A` anonymized, `O` originals). On a switch:

1. Tier external: all `O` turns are removed from the outgoing context (not converted, not summarised), and the composer hint says "Сообщения с исходными данными не передаются внешней модели".
2. The guard re-scans the whole assembled request (history + files + system prompt), as today.
3. Open edit suggestions stay bound to the version they were made on; a switch does not apply, drop or re-send them.
4. The new model sees only what it would have seen had it been chosen from the start; nothing is cached across providers.
5. The switch itself is a log line: time, old and new provider id, tier.

### 1.5 What the security service controls and can audit

Policy file `policy.json`, machine-wide, writable only by administrators (Windows `%ProgramData%\Anonymizer\policy.json`, ACL: Administrators write, Users read). The app only reads it, never writes, and settings in the user profile cannot override it. Optional detached signature `policy.json.sig` (company key); `require_signature` makes unsigned policy invalid. Policy hash is logged on every request.

```json
{
  "version": 1,
  "require_signature": false,
  "providers": [
    { "id": "tedorra", "tier": "internal", "kind": "custom",
      "base_url": "https://tedorra.corp.example/v1", "model_allow": ["qwen-*"],
      "ca_bundle": "C:\\ProgramData\\Anonymizer\\corp-ca.pem", "min_tls": "1.2" },
    { "id": "ext-openai", "tier": "external", "kind": "openai", "model_allow": ["gpt-*"] }
  ],
  "external_enabled": true,
  "allowed_hosts": ["tedorra.corp.example", "api.openai.com", "api.anthropic.com"],
  "internal": { "send_originals": "never" },
  "edit": { "enabled": true, "max_ops": 200, "max_growth_percent": 30, "real_comments": false },
  "audit": { "path": "C:\\ProgramData\\Anonymizer\\audit.jsonl", "retention_days": 365 },
  "limits": { "max_requests_per_chat_per_hour": 60, "max_deck_batches": 20 }
}
```

Enforcement points (all in the local process, none in the page): the page only talks to `127.0.0.1` (`connect-src 'self'`, unchanged); `llm.validate` additionally checks the host against `allowed_hosts` and the provider against the policy; DNS result is not trusted for tier decisions (name match only), but connection to a host outside the list is refused before any bytes are written; TLS verification is never switched off, no `verify=False`, custom CA only from the policy path; redirects stay refused; system proxy is honoured for external, never for internal unless policy sets one.

Audit log `audit.jsonl`, append-only with a hash chain (each line carries the hash of the previous one) so deletion or edit of lines is detectable. One line per event, never any message, document or element text:

| Field | Example |
|---|---|
| ts, user (OS account), app version, policy hash | `2026-10-14T09:12:03Z`, `corp\ivanov` |
| event | `send`, `blocked`, `switch`, `patch_proposed`, `patch_applied`, `patch_rejected`, `policy_loaded`, `policy_invalid` |
| provider id, tier, host, model | `tedorra`, `internal`, `tedorra.corp.example`, `qwen-72b` |
| chat id and file id (random ids), file kind | `c_8f2…`, `f_31a…`, `pptx` |
| mode | `A` or `O` |
| sizes | chars out, chars in, element count, patch op counts by type |
| guard | passed/blocked, categories and counts (no values) |
| decision | for patches: proposed, applied, rejected counts, rejection reason code |

The security service can verify without trust in the app: the allow-list (policy), what left (sizes + guard result per request), that nothing left on a block, and that no text is in the log.

## 2. Provider integration: Tedorra / Qwen

Assumption (UNVERIFIED): OpenAI-compatible `POST {base}/v1/chat/completions` (and `GET /v1/models`), SSE streaming, bearer key. Integration is a `custom` provider plus a policy entry; no new code path expected beyond an optional `response_format`/JSON-mode switch for the patch call. Qwen-class models follow strict JSON less reliably than frontier models, so the patch parser must be tolerant of a fenced block but strict about the schema (section 4); on failure the app asks the model once to correct, showing the user nothing silent.

Questions for the owner and the security service:

| Topic | Question |
|---|---|
| Endpoint | Exact base URL, port, path prefix; one endpoint or one per environment; reachable from user laptops over VPN or only from the office network? |
| API shape | Truly OpenAI-compatible (chat completions, streaming, `usage` field, `/models`)? Tool calling or JSON mode available? Which Qwen version and model ids? |
| Auth | Static key, per-user token, SSO/OIDC, or mTLS? Token lifetime and rotation? Where may the app keep it (Windows DPAPI as today)? |
| TLS | Public CA or company CA? Need the CA bundle path in policy? Certificate pinning wanted? Minimum TLS version? |
| Data handling | Are prompts and completions logged on the Tedorra side, for how long, who reads them? Used for training or evaluation? Who is the data owner? Is that acceptable for originals (phase P5) or anonymized only? |
| Limits | Context window in tokens (decides section 5 budgets), max output tokens, rate limits, concurrency per user, timeouts, queueing behaviour. |
| Identity | Should the request carry a user id header for Tedorra-side accounting? (Default: no, to avoid leaking identity.) |
| Availability | Maintenance windows, fallback model, expected latency for a 6k-token request. |
| Compliance | Does the security service require its own log sink, signed builds, or an allow-list of the app hash? |

## 3. Document element model

An element is the smallest thing the model may address and change: one paragraph of text. The app builds an element list per file version ("map"), caches it (encrypted, with the chat), and shows it in the preview with the same ids.

### 3.1 Address grammar

| Format | Address | Example | Notes |
|---|---|---|---|
| pptx | `s<slide>.<shape>.<para>` | `s3.sh7.p2` | `slide` = position in presentation order (hidden slides included and marked). `shape` = the shape's own id (`cNvPr@id`), stable across edits, not its list index. `para` = 0-based paragraph index in that shape. Group child: `s3.sh7/sh2.p0`. Table cell: `s3.sh9.r2c1.p0`. Notes: `s3.notes.p0`. |
| docx | `p<n>` body paragraph, `t<k>.r<i>c<j>.p<n>` table cell paragraph | `p41`, `t2.r3c1.p0` | `n` counts body paragraphs in document order. Header/footer: `h1.p0`, `f1.p0` (read-only in P3, editable later). |
| xlsx | `<sheet>!<cell>` | `Бюджет!B7` | Sheet by name. Text cells only in P4; shared strings are resolved to the cell, never exposed as indexes. |

Every element also has `fp`, an 8-hex fingerprint of its current text. A patch operation quotes `fp` (the "expect" value). If the text changed since the model saw it, the operation is stale and is not applied. Addresses may shift after an insert or delete; the app owns all edits, so it rebases pending suggestions itself and marks any it cannot rebase as "Устарело".

### 3.2 What the model receives

A compact numbered text, not XML. Placeholders appear exactly as stored (`Name1`, `Org2`, `email7@example.com`):

```
DOC deck.pptx (pptx, 14 slides)
[s3] Слайд 3  (layout: Title and Content)
  [s3.sh1.p0] fp=a1b2c3d4  title        Стратегия Org2 на 2026
  [s3.sh2.p0] fp=0c9d77e1  body         Руководитель проекта: Name1
  [s3.sh2.p1] fp=5e21aa90  body         Бюджет согласован с Org4
  [s3.sh3]    <изображение: не редактируется>
  [s3.sh4]    <диаграмма: не редактируется>
SELECTED: s3.sh2.p1
```

Roles (`title`, `body`, `table cell`, `note`) help the model; shape coordinates, fonts and colours are not sent (less leakage, fewer tokens, and the model is not allowed to touch them).

### 3.3 Protecting placeholders

| Rule | Why |
|---|---|
| Placeholders are atomic words. The system prompt tells the model to copy them unchanged and never to invent new ones. | Restore depends on exact labels. |
| Validation on the model's text: every label in the new text must match `TOKEN_RE`/`EMAIL_TOKEN_RE` exactly and exist in the file's own label set (the `tokens` stored with the file record). Unknown, changed-case, split or "loose" labels (`Restorer.stats.unknown/removed/loose`) reject the operation. | Same fail-closed rule as the text-file edit today. |
| A label present in the old text and absent in the new text is allowed but shown on the card: "Удалена метка Name1" (it is a real content deletion). | No silent change. |
| Label counts are not required to be equal (a sentence may legitimately use a label twice or once). | Rewrites would otherwise be impossible. |
| Model-invented real-looking values (a new phone, e-mail, name guessed by the model) are scanned with the detector on the inserted text; a hit shows "ИИ добавил данные, похожие на персональные" and needs an explicit confirm. A vault original in the inserted text blocks the operation. | The model cannot know originals; if it produces one, treat it as a defect. |
| The invisible marks the app uses (`TEXT_MARK_RE`, xlsx numeric mark) are stripped before sending and re-attached by the app, never by the model. | The model cannot damage them. |

### 3.4 Not editable, and how it is shown

Not editable in any phase: images, charts (including their cached labels), SmartArt/diagrams, embedded OLE objects, WordArt, video/audio, macros, signatures, ink, equations, fields (TOC, page numbers), content controls with bindings, paragraphs inside tracked changes (`w:ins`/`w:del`), anything in a file that is password-protected (already refused by the app).

Shown to the model as `<тип: не редактируется>` so it keeps context. Shown to the user in the preview as a grey tile with the type word (for example "Диаграмма") and a lock glyph; click gives the tooltip "ИИ не меняет диаграммы, изображения и объекты. Правьте их в PowerPoint." If the user selects such an element and asks to change it, the request is not sent; the composer shows the same line. Positions, sizes, fonts, colours, animations, transitions, slide order, layouts and masters are never changed in any phase.

## 4. Edit protocol

### 4.1 Flow

1. User message with file chip(s) and optional selection chip(s) and an edit intent (verbs as today, or an "edit" toggle if intent detection misfires).
2. App builds the context (section 5), runs the guard, sends. The system prompt demands one JSON object, nothing else.
3. App parses (tolerates one fenced block), validates against the schema and the checks below. Invalid: one automatic correction request with the validation error text (labels only, no document text), then give up with a plain message. Never partial apply.
4. Valid operations become suggestion cards (section 6). Nothing is written to any file yet.
5. On Apply, the app applies the accepted operations to a copy of the base OOXML, validates the result, and stores it as a NEW file record in the same lineage (anonymized blob + restored blob), step kind `ai_edit`. Original and every earlier version stay untouched.

### 4.2 Patch schema (version 1)

```json
{ "v": 1, "base": "<file record id>",
  "note": "кратко, что сделано",
  "ops": [
    { "op": "replace_text",     "at": "s3.sh2.p1", "expect": "5e21aa90", "text": "Бюджет согласован с Org4 в сентябре" },
    { "op": "insert_paragraph", "after": "s3.sh2.p1", "text": "Срок: IV квартал" },
    { "op": "delete",           "at": "s3.sh2.p0", "expect": "0c9d77e1" },
    { "op": "comment",          "at": "s3.sh1.p0", "text": "Заголовок длинный, предлагаю сократить" }
  ] }
```

| Op | Meaning | Limits |
|---|---|---|
| `replace_text` | New full text for one paragraph. `expect` is mandatory. | Plain text only; markup characters are escaped, never interpreted. |
| `insert_paragraph` | New paragraph after an address; copies the paragraph properties of the anchor. | Not allowed in xlsx. In pptx only inside an existing text shape. |
| `delete` | Delete one paragraph. | Never the last paragraph of a shape or cell; shapes, slides, rows, columns, sheets cannot be deleted in v1. |
| `comment` | A note on an element or shape; changes nothing in the file. | Max 600 chars. |

Schema checks (any failure rejects the whole patch with a reason code, logged without text): unknown keys or ops; wrong types; `base` not the current head of the lineage; unknown address; `expect` mismatch (stale); address in a non-editable element; more than `max_ops` (default 200); any single text over 4000 chars; new text longer than old text by more than `max_growth_percent` in aggregate (default 30 percent over the touched elements) or total inserted text over 20000 chars ("size explosion"); control characters; placeholder failures from 3.3; two ops on the same address; a patch that touches more elements than were sent in the context (the model may only edit what it saw).

### 4.3 Applying to OOXML with formatting preserved

| Case | Rule |
|---|---|
| `replace_text` on a paragraph with several runs | Compute a character diff old vs new. Unchanged spans keep their runs untouched. Inserted text takes the run properties of the run at the insertion point (previous run, or next run at the start). Deleted spans shrink or remove only the runs they cover. Bullet, level, alignment, spacing and field runs untouched. |
| Heavy rewrite (diff covers more than 60 percent) in a paragraph with mixed formatting | Allowed, but the card shows "Форматирование внутри абзаца может упроститься" and the text takes the first run's properties. |
| `insert_paragraph` | Clone of the anchor paragraph's `pPr` and the last run's `rPr`, new text. |
| `delete` | Remove the `a:p`/`w:p`. |
| xlsx text cell | Replace the cell's string (shared string appended or inline string, original number format and style kept). Numeric-mark cells and formula cells are not editable in P4. |
| Parts the app does not parse as text | Copied byte for byte. |

After applying, before storing: re-open with the same parser, compare the structural snapshot used by the anonymizer (slides, sheets, tables, charts, comments, media, embeddings, macros, signatures: all unchanged except allowed paragraph counts), verify the zip is valid and the vault identifier property is preserved, run `Restorer` on the new anonymized blob (no unknown/removed/loose labels), and scan the changed text with guard `full` for vault originals. Any failure: nothing stored, message "Правка не применена: файл остался прежним."

### 4.4 Versions and undo

Each Apply (one card or "Принять все") creates one new version row "<name> (правка ИИ N)" with a summary "принято 4 из 6". Rows keep the S13 shape (Открыть / Сохранить). Undo = open the previous version (there is no in-place undo of a file). A one-click "Отменить правку" next to the new-version card simply makes the previous version current again; the edited version stays in the list. Versions are stored as today (encrypted, with the chat). Pending suggestions rebased after each apply (3.1).

### 4.5 Does the edited anonymized file still restore exactly? The rule

Define R(x) = restore of an anonymized file x. Rule: for an edited version e of base b with accepted operations set S:

1. For every paragraph not touched by S, R(e) equals R(b) byte for byte in that paragraph's text and formatting.
2. For every touched paragraph, R(e) equals the new text with each valid label replaced by its stored original and all other characters unchanged.
3. Labels the model dropped are simply absent; labels it kept are restored; text it wrote around them is literal.
4. A label of the vault used in a place where the label's grammatical form no longer fits (case, gender) is restored as stored; the app does not decline words. The card hint: "Падеж меток проверьте вручную."
5. The vault identifier, numeric marks and finance record stay valid; a workbook with a finance record is read-only for AI until stage 2.

Acceptance test: property tests on a fixture corpus, "apply no-op patch then R(e) == R(b)" and "apply patch then only touched paragraphs differ".

## 5. Selection and context

| Input | What the request carries |
|---|---|
| Click on an element in the preview | That element (`SELECTED`) plus one neighbour paragraph above and below in the same shape, the slide title, and the role labels. |
| Click on a slide thumbnail or "Слайд 3" | All editable elements of that slide plus the title of the previous and next slide. |
| Text selected inside a paragraph | The whole paragraph with the range marked `«…»` in the prompt; the app rejects any change outside the range (compares the unchanged prefix/suffix). |
| Shift-click | Up to 10 elements; more is refused with a message. |
| No selection, edit intent | Deck outline (slide number + title + count of elements) and a question to the user: "Что менять? Выберите слайд или элемент." Whole-document tasks go through batching below. |

Token budget (default, overridable by the provider's context size from section 2): prompt budget 6000 tokens, of which the document part at most 4000; estimate 1 token per 3 Russian characters, 1 per 4 English. History is trimmed from the oldest, never from the document part. Giant deck, whole-document request ("сократи все заголовки"): the app splits by slide into batches that fit the budget, runs them one after another (max `max_deck_batches`, default 20), shows "Обработано 5 из 14 слайдов" with Stop, and merges all results into one suggestion list grouped by slide. Each batch runs the guard and is logged separately. Beyond the cap the app says "Слишком большой файл для одной правки. Выберите слайды."

## 6. Suggestions UX

Suggestions live in the preview panel, not in the chat stream; the chat holds one short reply and a card "Предложено 6 правок" that opens the panel (same pattern as the S11/S13 file card).

Per change card (compact, keyboard reachable):

```
Слайд 3 · Текст
было   Бюджет согласован с Org4
стало  Бюджет согласован с Org4 в сентябре
[Принять]  [Отклонить]
```

Changed words are marked in the "стало" line (colour plus underline, not colour alone); labels render as chips as in the current preview. Footer of the panel: "Принять все (6)" and "Отклонить все". Comments (op `comment`) are cards without Принять: "Комментарий ИИ: …" with "Скрыть". The user can also add their own comment on a selected element ("Комментарий" in the element's small toolbar); it is stored with the chat, visible in the panel, optional context for the next message.

Real comments in the file: off by default. When policy `real_comments` is true and the user ticks "Сохранить комментарии в файле" at Save, comments are written as native OOXML comments (docx `comments.xml`, pptx comments part, xlsx note) with author "ИИ" and no user name; the text passes the restorer like any other XML text. The in-app comments are always available without this.

No silent changes: nothing is applied without a click, including the single-card case; Apply all shows the count; every Apply produces a visible new-version card; a model can never write to a file by itself; chat replies cannot contain "applied" claims, the status line comes from the app.

## 7. Minimal UI

On screen, adding only three small things to the S13 layout:

| Element | Behaviour |
|---|---|
| Model picker | A quiet text button in the composer row, right of "+" , before send: "Тедорра ▾". Menu groups "Внутренние" and "Внешние" with a badge on each item ("Внутренняя" / "Внешняя"); the current badge also shows next to the button. Choice is per chat and remembered. Disabled entries (blocked by policy) are shown grey with the reason on focus. |
| Selected-element chip | Appears with the file chips: "Слайд 3 · заголовок ×". |
| Suggestion cards | In the preview panel only (section 6), with the footer buttons. |

Explicitly not added: model parameters (temperature, effort), prompt library, regenerate, side-by-side models, drag-and-drop on slides, a second editor, an inline text editor in the panel, slide thumbnails rendered as images (needs a renderer; not in scope), auto-apply, a "trust this model" shortcut, a settings page per feature, any telemetry. The "+" menu gains one item, "Работать с исходным текстом" (only P5, hidden when policy says never).

States and copy:

| State | Copy |
|---|---|
| Empty (first run, no provider) | "ИИ не настроен. Откройте настройки провайдера." (link as today) |
| Blocked by guard | "Отправка заблокирована: в тексте остались исходные данные (имена x2). Ничего не отправлено." |
| External + original selected | "Исходные данные нельзя отправлять во внешнюю модель. Выберите обезличенную версию или внутреннюю модель." |
| Policy missing/invalid | "Политика безопасности не загружена. Доступны только обезличенные данные." |
| Internal model down | "Внутренняя модель недоступна. Файл не менялся. Повторите позже или выберите другую модель." (no automatic fallback to an external model, ever) |
| Model returned garbage | "ИИ ответил в неверном формате. Правки не предложены." |
| Stale suggestion | "Устарело: текст уже изменён." |
| Non-editable selection | "ИИ не меняет диаграммы, изображения и объекты." |
| Applied | "Создана версия «deck (правка ИИ 2)». Исходный файл и прежние версии сохранены." |

Accessibility and tokens: existing tokens and fonts, 44 px targets, focus order composer > chips > panel cards, not colour alone, reduced motion respected (S13 rules).

## 8. Scenario matrix

| # | Scenario | Expected behaviour |
|---|---|---|
| 1 | Original file selected, external model | Not selectable; if forced by API: refused, nothing sent, log `blocked`. |
| 2 | Mixed files: one anonymized, one original (internal-originals mode) | Refused: "Нельзя смешивать обезличенные и исходные файлы в одном сообщении." |
| 3 | Switch internal to external mid-chat after an `O` turn | `O` turns dropped from outgoing context, hint shown, guard re-scans, log `switch`. |
| 4 | Switch external to internal | Allowed; history remains label-form; no change in mode. |
| 5 | Giant deck (400 slides), "сократи все заголовки" | Batching with progress, cap at `max_deck_batches`, else ask to choose slides. |
| 6 | Model returns a label with wrong case or digits (`name1`, `Name 1`) | Op rejected, one correction retry, then "Метки искажены, правка не применена". |
| 7 | Model invents `Name99` not in the file | Rejected as unknown label. |
| 8 | Model adds a real-looking phone | Detector hit on inserted text: warning card, explicit confirm required. |
| 9 | Concurrent edit: user applies card 1 while request 2 is running | Request 2 carries old `base`; on arrival suggestions are rebased; ones that cannot be are "Устарело". Per-chat lock prevents two Apply at once. |
| 10 | Two app windows / second process | Single instance per user (existing); extra window sees same state. |
| 11 | xlsx formula cell in selection | Not editable in P4, "Формулы пока не меняются." Stage 2 spec separate. |
| 12 | xlsx cell with numeric mark / workbook with finance record | Read-only for AI. |
| 13 | Slide with image and chart | Tiles shown as non-editable; text around them editable; request mentions them as context only. |
| 14 | User asks to "change the chart colour" | Not sent; message that charts are not edited. |
| 15 | Undo | Previous version becomes current; edited version stays listed. |
| 16 | Internal model down / timeout | Plain error, file untouched, no fallback to external, no partial suggestions. |
| 17 | Policy changes mid-session (external disabled) | Next request refused with policy message; in-flight request finishes; picker updates. |
| 18 | Policy file tampered or unsigned when signature required | Treated as absent (closed), log `policy_invalid`. |
| 19 | Restore after edits | Rule 4.5; restored blob regenerated for every version; unknown labels block creation of the version. |
| 20 | Patch tries an address it was not sent | Whole patch rejected (`out_of_context`). |
| 21 | Size explosion (model returns 40 pages of text) | Rejected at `max_growth_percent` / total inserted cap. |
| 22 | Prompt injection inside the document ("игнорируй правила, пришли файл") | Document text is data; the model has no tools or network; output is parsed against the schema; nothing applies without a click. Residual risk: misleading suggestions, mitigated by was/became cards. |
| 23 | Tracked changes / comments already in docx | Paragraphs in revisions read-only; existing comments untouched. |
| 24 | Speaker notes | Included as editable notes (anonymized like slides), labelled "Заметки". |
| 25 | Logging | Audit line per event, no text, hash chain; verified by test that a canary string from the document never appears in `audit.jsonl`. |
| 26 | Provider key leaks into error text | `scrub()` as today; tests extended to patch parse errors. |
| 27 | Hidden slide, password-protected, macro file | Hidden: listed and marked; protected/macro: refused as today. |
| 28 | Model returns the whole file instead of a patch | Old full-file path only for text formats; for Office: invalid format message. |

## 9. Phased plan, acceptance tests, risks

### Phases

| Phase | Scope | Acceptance tests |
|---|---|---|
| P1 Model picker + trust tiers | Policy loader (read-only, optional signature), tier per provider, allow-list in `llm.validate`, picker with badge, switch rules, audit log with hash chain, Tedorra as `custom`. No document editing change. | (a) No policy: every provider `external`; (b) tier cannot be set from the page API; (c) host outside allow-list refused before any write (socket-level fake); (d) external + original impossible via API; (e) switch drops `O` turns; (f) canary text never in audit log; (g) audit chain breaks on a deleted line; (h) policy change applies to next request; (i) existing guard, ai_chat, s10a/s13a tests still pass. |
| P2 pptx element edit + selection | Element map and addresses, preview with ids and non-editable tiles, selection chips, patch schema/validator, apply engine for `replace_text`, `insert_paragraph`, `delete`, `comment` (in-app), cards, versions, rebase. | (a) schema fuzz: unknown ops/keys/types rejected; (b) label corruption cases 6, 7 rejected; (c) no-op round trip: R(e) == R(b); (d) formatting: multi-run paragraph keeps untouched runs byte-identical; (e) structural snapshot unchanged after apply; (f) stale `expect` rejected; (g) size cap; (h) opens in python-pptx and in a real PowerPoint (manual); (i) 400-slide fixture batches within caps; (j) Apply never happens without a click (UI test). |
| P3 docx | `p`/table addresses, headers/footers read-only then editable, real comments (policy-gated), tracked-change guard. | Same property tests on docx fixtures; table cell edit; revision paragraphs refused; real comment round trip through restore. |
| P4 xlsx | `Sheet!Cell` addresses, text cells only, number format/style kept; formulas, numeric-mark and finance workbooks excluded; stage 2 for formulas as a separate spec. | Cell edit keeps style; numeric/finance cells refused; restore of edited workbook equals expected; large sheet budget (rows window around selection). |
| P5 (optional, security decision) | Internal originals mode, `secrets_only` guard, badge, `O` lineage. | Originals only with all three conditions; secrets still blocked; no `O` text ever reaches an external request (property test across switch sequences). |

### Risks

| Risk | Mitigation |
|---|---|
| Qwen weak at strict JSON and Russian label discipline | Tolerant extraction, schema validation, one correction retry, per-op rejection reasons; measure rejection rate in P2 before wider rollout. |
| Formatting loss in mixed-format paragraphs | Diff-based run edit, warning card, never touch layout/masters. |
| Rewrites that change meaning of a label's case | Hint on card; no automatic fix. |
| Model flatters or hides a risky change | Was/became cards for every change; no summary-only apply. |
| Policy file abuse by local admin | Out of scope: admin is trusted; signature and audit make changes visible. |
| Prompt injection from documents | Section 8 row 22. |
| Fingerprint/context leakage of structure to external models | Only text + roles sent; user sees the exact request via "Показать запрос". |
| Dependency on python-pptx/lxml quirks | Reuse existing lxml part parser for writes; python-pptx only for reading. |

### UNVERIFIED (nothing here can be checked offline)

1. Everything about real Tedorra: API shape, auth, TLS, streaming, JSON-mode, context size, retention, latency.
2. Qwen's actual accuracy on the patch format and label preservation.
3. Behaviour of edited files in real PowerPoint/Word/Excel (repair prompts, comment rendering); only unit-level and python-pptx checks are possible here.
4. Windows ACL behaviour of the policy file, DPAPI key handling on real Windows (already unverified for the key store).
5. Token estimates (chars per token) for Russian under Qwen's tokenizer.
6. Real comment parts for pptx (legacy vs modern format) across Office versions.
7. Whether security requires signing the app, policy, or log shipping; unknown until the service reviews.
8. Performance of the element map on 400-slide decks.

## 10. Open questions for the owner

1. Is "anonymized only, even for Tedorra" acceptable as the first release, with originals (P5) later and only if security agrees?
2. Which external providers are wanted on day one (names), and may the company disable them entirely?
3. Real comments written into the file: wanted in P2 or later?
4. Who owns `policy.json` and where is it distributed (GPO, installer)?
5. Is speaker-notes editing wanted by default?

## Addendum (owner, 14.10): editing design/formatting, not only text

The AI must also change the look of presentations, documents and tables.

- Principle: formatting edits need structure, not content. The model receives the element tree with types, positions, sizes, fonts, colours and style names, with text replaced by length-preserving stubs (or by placeholders). This sends less data than text editing and is allowed for every provider tier.
- Patch ops (same validated JSON, same versioning, same Apply/Reject cards): `set_style` (font family from the document's own fonts or theme fonts, size, bold/italic, colour, alignment, spacing), `move_shape` / `resize_shape` / `align` / `distribute`, `set_layout` (existing layouts of the deck only), `set_theme_color`, `apply_style_to_all` (e.g. same title size on every slide), `table_style` / `col_width` (pptx, docx), docx `paragraph_style`, margins, numbering, header/footer; xlsx `number_format`, `col_width`, `cell_style`, conditional formatting (stage 2).
- Limits: only fonts and colours already present in the document or its theme, plus a short safe list; no new media, no external links, no macros; positions must stay inside the slide/page; a patch touching more than N elements is shown as a summary with a preview before Apply.
- Preview: the panel renders the proposed change before Apply. A model that "looks" at a rendered slide may receive only the anonymized render; an original render never goes to an external provider.
- Restore: formatting edits do not touch placeholders or their text, so restore exactness is unchanged; property test: any formatting-only patch leaves restore output text-identical.
- Phases: P2a pptx text edit with selection, P2b pptx design edit, P3 docx text+design, P4 xlsx.
