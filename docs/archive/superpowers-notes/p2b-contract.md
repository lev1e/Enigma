# P2B API contract (AI editing of docx / pptx / xlsx)

All paths are under `/api/ai/chats/<chat_id>`. JSON in, JSON out. Errors use the usual convention (`{"error": "<русский текст>"}`, 4xx).

## 1. Send (existing endpoint `POST .../send`, new optional fields)

```json
{ "text": "Сделай заголовок крупнее",
  "file_ids": ["<file id>"],
  "sources": { "<file id>": "original" },
  "edit": true,
  "selected": ["s2.sh1.p0", "s2.sh3"],
  "selected_file": "<file id>" }
```
- `edit` (bool, optional): force edit mode. Without it the backend guesses from the text (verbs; design words like "шрифт", "цвет", "выровняй" on an Office file also mean edit, unless the text has "?").
- `sources[<id>] == "original"`: edit the ORIGINAL version of that file (the AI sees real text, secrets stay masked as "[секрет удалён]"; the usual `needs_confirm_originals` / `confirm_originals: true` flow applies). Absent: the anonymized version (labels like `Name1`).
- `selected`: list of element addresses (max 20, as shown in the preview/outline: `s3` slide, `s3.sh2` shape, `s3.sh2.p1` paragraph; docx `p4`, `t1.r2.c1`...; xlsx `Лист1!B2`, `Лист1!B2:C5`). Narrows what the model sees to these elements plus neighbours. `selected_file`: the file id the addresses belong to (that file becomes the edit target).
- Response is unchanged (`{"run": "<id>", "editing": true, "note": "...", "mode": "anonymized"|"original", ...}`).

## 2. Run events: `edit` in the `done` event

SSE `GET /api/ai/runs/<run>/events` ends with `done`; the polling view `GET /api/ai/runs/<run>` has the same `edit` field.

```json
{ "length": 812, "error": "", "report": null, "usage": null,
  "edit": {
    "applied": false,
    "note": "Предложено правок: 2. Ничего не изменено, пока вы не нажмёте «Применить».",
    "proposal": {
      "id": "Xk3_9aQz",
      "file": "<file id the patch is based on>",
      "source": "anonymized",
      "note": "кратко, что сделано (от ИИ)",
      "hint": "Падеж меток проверьте вручную.",
      "done": [],
      "items": [
        { "index": 0, "op": "replace_text", "at": "s1.sh0.p0", "comment": false,
          "text": "Слайд 1: заголовок", "was": "Отчёт за квартал", "now": "Итоги квартала" },
        { "index": 1, "op": "set_style", "at": "s1.sh0.p0", "comment": false,
          "text": "Слайд 1: шрифт 44 pt", "was": "32", "now": "44" },
        { "index": 2, "op": "comment", "at": "s2.sh1", "comment": true,
          "text": "Комментарий: заголовок длинный", "was": null, "now": null } ] } } }
```
- `edit.applied` is always `false` for Office files (nothing is written until Apply). No `proposal` key = no cards: show `edit.note` (Russian reason, e.g. "Правка не применена: ... Файл остался прежним.", or "ИИ не предложил правок..."). `edit.code` may carry a machine code.
- `items[].text` is the Russian card line; `was`/`now` are short strings or null (null for non-text ops, show `text` only). `comment: true` items are notes: shown, but not applicable (no checkbox).
- `index` is the stable id of a card; pass it back in `ops`.
- Text files (txt/md/csv/...) keep the old shape: `edit = {"applied": true, "file": ..., "name": ..., "note": ...}`, no `proposal`.

## 3. Apply / reject: `POST .../patch`

```json
{ "id": "Xk3_9aQz", "action": "apply", "ops": "all" }
{ "id": "Xk3_9aQz", "action": "apply", "ops": [0, 2] }
{ "id": "Xk3_9aQz", "action": "reject" }
{ "id": "Xk3_9aQz", "action": "reject", "ops": [1] }
```
Responses (HTTP 200 unless the id is unknown: 404 `{"error": "Предложение правок не найдено или уже закрыто"}`):
```json
{ "ok": true, "file": "<new file id>", "name": "Отчёт (правка ИИ 1).pptx", "source": "anonymized",
  "left": [1], "hint": "...", "note": "Создана версия «...». Исходный файл и прежние версии сохранены." }
{ "ok": false, "reason": "Правка не применена: ... (операция 2, s1.sh0.p0). Файл остался прежним.", "code": "stale", "left": [0, 1] }
{ "ok": true, "left": [] }              // full reject
```
- `left`: indices still pending (writable and neither applied nor rejected). When empty, the proposal is closed. After a partial apply the remaining cards stay valid only if still applicable: re-checked on the next apply (a stale one returns `ok:false` + `reason`, nothing changes).
- Apply always creates a NEW file record (version) in the same chat; the original and earlier versions stay. The new record appears in the chat file list (`GET .../` -> history/files) with name `<stem> (правка ИИ N).<ext>`; refresh the file list after `ok:true`.
- If the base was the ORIGINAL and the new version could not be anonymized, `ok:true` still holds and `note` contains an explicit Russian warning (`"... Обезличенной копии нет: ..."`); the version then has only original/restored roles.

## 4. Chat view `GET .../` -> `proposals`

`proposals`: array of the same `proposal` objects (section 2), pending ones only (survive reload / second window / restart). Render them on opening the chat; same `patch` endpoint.

## 5. Preview addresses
Element addresses are those of `anonymizer/docedit.py` (`outline`). The frontend sends them back verbatim in `selected`.
