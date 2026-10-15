"use strict";
/* Панель Anonymizer внутри Word, Excel и PowerPoint.
   Порядок для каждой операции: прочитать открытый файл, отправить его программе на этом компьютере (127.0.0.1),
   получить результат, заменить им содержимое документа, заново прочитать документ и сверить с ожидаемым.
   Копия исходного файла перед заменой хранится в программе (зашифрованной), её можно вернуть кнопкой «Откатить». */

const $ = (s, r = document) => r.querySelector(s);
const TOKEN = $('meta[name="addin-token"]').content;
const EXT = {Word: "docx", Excel: "xlsx", PowerPoint: "pptx"};
const SLICE = 4 * 1024 * 1024;
const MAX_BYTES = 100 * 1024 * 1024;
let HOST = null;
let busy = false;
let last = null;                       // последняя операция: нужна для повторного прохода и отката
let chatId = "";                       // чат, к которому привязан открытый документ
let lastChat = "";                     // чат последней операции в этой сессии: после отката повтор пополняет его же
let docState = null;                   // ответ /api/addin/doc-state для chatId
let dialog = null;
let backupDays = 7;                    // срок хранения копии оригинала: приходит из программы (/info)
let undoneRestore = "";                // чат, документ которого откатили к виду до возврата (пока открыта панель)
const BIND = "Anonymizer.Chat";

const dbg = msg => { try { fetch("/api/addin/debug", {method: "POST", body: String(msg), headers: {"X-Requested-With": "anonymizer", "X-Addin-Token": TOKEN}}); } catch (e) { /* отладка не должна ломать работу */ } };
const esc = v => { const d = document.createElement("div"); d.textContent = v == null ? "" : String(v); return d.innerHTML; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const store = {
  get(k, d) { try { const v = localStorage.getItem("anon." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("anon." + k, JSON.stringify(v)); } catch (e) { /* хранилище недоступно: не страшно */ } },
};

/* ---------- связь с программой ---------- */
async function api(path, opts = {}) {
  const headers = {"X-Requested-With": "anonymizer", "X-Addin-Token": TOKEN, ...(opts.headers || {})};
  let r;
  try { r = await fetch(path, {...opts, headers, cache: "no-store"}); }
  catch (e) { throw new Error("Нет связи с программой Anonymizer. Запустите её и повторите."); }
  const type = r.headers.get("Content-Type") || "";
  if (type.includes("json")) {
    const data = await r.json();
    if (!r.ok) { const err = new Error(data.error || "Ошибка " + r.status + "."); err.code = data.code; err.count = data.count; err.status = r.status; throw err; }
    return data;
  }
  if (!r.ok) throw new Error("Ошибка " + r.status + ".");
  return r;
}
/* Отпечаток документа: сервер по нему отличает «тот же документ» от изменённого пользователем после обработки. */
async function sha256Hex(bytes) {
  try {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch (e) { return ""; }                                     // без crypto.subtle (http) проверку делает «unchanged»
}
const postJson = (path, body) => api(path, {method: "POST", body: JSON.stringify(body), headers: {"Content-Type": "application/json"}});

/* ---------- чтение и запись документа ---------- */
function documentName() {
  let name = "";
  try { name = decodeURIComponent((Office.context.document.url || "").split(/[\\/]/).pop().split("?")[0]); } catch (e) { /* без имени */ }
  const ext = "." + EXT[HOST];
  if (!name) return "document" + ext;
  return name.toLowerCase().endsWith(ext) ? name : name.replace(/\.[^.]*$/, "") + ext;
}
/* Office иногда не отвечает на чтение файла (документ занят, идёт сохранение): ждать вечно нельзя. */
function withTimeout(promise, ms, message) {
  let timer;
  const limit = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
  return Promise.race([promise, limit]).finally(() => clearTimeout(timer));
}
const getFile = () => withTimeout(readFile(), 90000, "Office не отдал документ за 90 секунд. Подождите и повторите.");
function readFile() {
  return new Promise((resolve, reject) => {
    Office.context.document.getFileAsync(Office.FileType.Compressed, {sliceSize: SLICE}, res => {
      if (res.status !== Office.AsyncResultStatus.Succeeded) return reject(new Error("Не удалось прочитать документ: " + res.error.message));
      const file = res.value, parts = new Array(file.sliceCount);
      const fail = msg => { file.closeAsync(); reject(new Error("Не удалось прочитать документ: " + msg)); };
      const next = i => {
        if (i >= file.sliceCount) {
          file.closeAsync();
          let total = 0; parts.forEach(p => total += p.length);
          const out = new Uint8Array(total); let at = 0;
          parts.forEach(p => { out.set(p, at); at += p.length; });
          return resolve(out);
        }
        file.getSliceAsync(i, s => {
          if (s.status !== Office.AsyncResultStatus.Succeeded) return fail(s.error.message);
          parts[i] = Uint8Array.from(s.value.data);
          next(i + 1);
        });
      };
      next(0);
    });
  });
}
function toBase64(bytes) {
  let out = "";
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(out);
}
const supported = (set, v) => { try { return Office.context.requirements.isSetSupported(set, v); } catch (e) { return false; } };

/* Исправления ищет программа по самому файлу (надёжнее, чем API Word, которого нет в части версий). Принять их кнопкой
   можно, если API есть; иначе нужно сделать это самому на вкладке «Рецензирование». */
async function wordAcceptAll() {
  await Word.run(async ctx => { ctx.document.body.getTrackedChanges().acceptAll(); await ctx.sync(); });
}
/* Свойства файла (автор, название, компания) Office при вставке не переносит: их нужно записать отдельно. */
async function applyProperties(host, structure) {
  const wanted = (structure && structure.props) || {}, custom = (structure && structure.custom) || [];
  const keys = ["author", "title", "subject", "keywords", "comments", "category", "manager", "company"];
  const failures = [];
  const api = host === "Word" ? Word : host === "Excel" ? Excel : PowerPoint;
  const root = ctx => host === "Word" ? ctx.document.properties : host === "Excel" ? ctx.workbook.properties : ctx.presentation.properties;
  try {
    await api.run(async ctx => {
      const target = root(ctx);
      for (const key of keys) {
        try { target[key] = wanted[key] || ""; await ctx.sync(); } catch (e) { /* поле недоступно: проверка ниже скажет об этом */ }
      }
      target.load(keys.join(","));
      await ctx.sync();
      for (const key of keys) {
        let have = ""; try { have = target[key] || ""; } catch (e) { continue; }
        if (have !== (wanted[key] || "")) failures.push("свойство «" + key + "»");
      }
    });
  } catch (e) { failures.push("свойства файла"); }
  try {
    await api.run(async ctx => {
      const props = root(ctx);
      const bag = host === "Excel" ? props.custom : props.customProperties;
      bag.deleteAll();
      for (const item of custom) bag.add(item.name, item.value);
      await ctx.sync();
    });
  } catch (e) {
    // Старые пользовательские свойства могли остаться; если результату свои свойства нужны, это неполный итог.
    if (custom.length) failures.push("пользовательские свойства");
  }
  return failures;
}
/* Колонтитулы по разделам: вставка файла заменяет тело документа, но не колонтитулы. */
async function applyHeadersFooters(parts) {
  const failed = [];
  await Word.run(async ctx => {
    const sections = ctx.document.sections; sections.load("items"); await ctx.sync();
    for (const item of parts) {
      const section = sections.items[item.section];
      if (!section) { failed.push("колонтитул раздела " + (item.section + 1)); continue; }
      const body = item.kind === "header" ? section.getHeader(item.type) : section.getFooter(item.type);
      try {
        if (!item.docx) throw new Error("text");
        body.insertFileFromBase64(item.docx, "Replace"); await ctx.sync();
      } catch (e) {
        try { body.clear(); body.insertText(item.text || "", "Start"); await ctx.sync(); }
        catch (e2) { failed.push("колонтитул раздела " + (item.section + 1)); }
      }
    }
  });
  return failed;
}
async function applyWord(b64) {
  await Word.run(async ctx => {
    const doc = ctx.document;
    let previous = "Off";
    if (supported("WordApi", "1.4")) {
      doc.load("changeTrackingMode"); await ctx.sync();
      previous = doc.changeTrackingMode;
      // Замена при включённых исправлениях оставила бы прежний текст внутри самих исправлений.
      if (previous !== "Off") { doc.changeTrackingMode = "Off"; await ctx.sync(); }
    }
    const options = {importTheme: true, importStyles: true, importParagraphSpacing: true, importPageColor: true,
      importChangeTrackingMode: true, importCustomProperties: true, importCustomXmlParts: true, importDifferentOddEvenPages: true};
    let done = false;
    // Документ целиком (колонтитулы, разделы, водяные знаки) умеют заменять новые версии Word; тело — только содержимое.
    if (supported("WordApiDesktop", "1.1")) {
      try { doc.insertFileFromBase64(b64, "Replace", options); await ctx.sync(); done = true; } catch (e) { done = false; }
    }
    if (!done) {
      try { doc.body.insertFileFromBase64(b64, "Replace", options); await ctx.sync(); }
      catch (e) { doc.body.insertFileFromBase64(b64, "Replace"); await ctx.sync(); }
    }
    if (previous !== "Off") { doc.changeTrackingMode = previous; await ctx.sync(); }
  });
}
/* Ошибка замены с указанием, в каком состоянии остался документ: untouched (не тронут) или partial (изменён частично). */
function applyError(message, state, cause) { const err = new Error(message); err.docState = state; err.cause = cause; return err; }
const reason = e => e && e.message ? e.message : String(e);
async function applyPowerPoint(b64) {
  if (!supported("PowerPointApi", "1.2")) throw applyError("Эта версия PowerPoint не умеет заменять слайды целиком. Документ не изменён.", "untouched");
  let stage = "start";
  try {
    await PowerPoint.run(async ctx => {
      const slides = ctx.presentation.slides; slides.load("items/id"); await ctx.sync();
      const oldIds = slides.items.map(s => s.id);
      ctx.presentation.insertSlidesFromBase64(b64, {formatting: "KeepSourceFormatting"});
      await ctx.sync();
      stage = "inserted";
      for (const id of oldIds) ctx.presentation.slides.getItem(id).delete();
      await ctx.sync();
    });
  } catch (e) {
    if (e && e.docState) throw e;
    if (stage === "start") throw applyError("Не удалось заменить слайды (" + reason(e) + "). Скорее всего, презентация не изменена, но проверьте её.", "unknown", e);
    throw applyError("В презентацию уже добавлены новые слайды, а прежние (с настоящими данными) удалить не удалось: " + reason(e) + ". Сейчас в ней и те, и другие.", "partial", e);
  }
}
async function applyExcel(b64, structure) {
  if (!supported("ExcelApi", "1.13")) throw applyError("Эта версия Excel не умеет заменять листы целиком (нужен Excel 2021 или Microsoft 365). Книга не изменена.", "untouched");
  const failedNames = [];
  let stage = "start";
  try { await applyExcelRun(b64, structure, failedNames, s => { stage = s; }); }
  catch (e) {
    if (e && e.docState) throw e;
    if (stage === "names") throw applyError("Имена книги уже удалены, а листы из результата вставить не удалось: " + reason(e) + ". Листы остались прежними, с настоящими данными.", "partial", e);
    if (stage === "inserted") throw applyError("В книгу уже вставлены новые листы, но прежние (с настоящими данными) убрать не удалось: " + reason(e) + ". Сейчас в ней и те, и другие.", "partial", e);
    throw applyError("Не удалось заменить листы (" + reason(e) + "). Скорее всего, книга не изменена, но проверьте её.", "unknown", e);
  }
  return failedNames;
}
async function applyExcelRun(b64, structure, failedNames, mark) {
  await Excel.run(async ctx => {
    const wb = ctx.workbook, sheets = wb.worksheets;
    sheets.load("items/id,items/name,items/visibility"); wb.names.load("items/name"); await ctx.sync();
    const oldSheets = sheets.items.map(s => ({id: s.id, name: s.name, visibility: s.visibility}));
    // Имена книги ссылаются на старые листы и сами могут содержать данные: Excel переносит их вместе с новыми листами.
    wb.names.items.forEach(n => n.delete());
    await ctx.sync();
    mark("names");
    wb.insertWorksheetsFromBase64(b64, {positionType: "End"});
    await ctx.sync();
    mark("inserted");
    sheets.load("items/id,items/name"); await ctx.sync();
    const oldIds = oldSheets.map(s => s.id);
    const fresh = sheets.items.filter(s => !oldIds.includes(s.id));
    if (!fresh.length) { mark("names"); throw new Error("Excel не вставил листы из результата"); }
    // Скрытые и «очень скрытые» листы Excel удалять не даёт: сначала они делаются видимыми.
    for (const old of oldSheets) {
      if (old.visibility !== "Visible") { try { sheets.getItem(old.id).visibility = "Visible"; } catch (e) { /* проверим при удалении */ } }
    }
    await ctx.sync();
    const stuck = [];
    for (const old of oldSheets) {
      try { sheets.getItem(old.id).delete(); await ctx.sync(); }
      catch (e) { stuck.push(old.name + (e && e.message ? " (" + e.message + ")" : "")); }
    }
    if (stuck.length) throw new Error("не удалось убрать прежние листы: " + stuck.join(", "));
    const want = (structure && structure.sheets) || [];
    if (want.length === fresh.length) {
      fresh.forEach((sheet, i) => { if (sheet.name !== want[i].name) sheet.name = want[i].name; });
      await ctx.sync();
      // Видимость листов как в результате (скрытые остаются скрытыми). Последний видимый лист скрыть нельзя.
      for (let i = want.length - 1; i >= 0; i--) {
        const state = want[i].state;
        if (state && state !== "visible") {
          try { fresh[i].visibility = state === "veryHidden" ? "VeryHidden" : "Hidden"; await ctx.sync(); } catch (e) { failedNames.push("видимость листа " + want[i].name); }
        }
      }
    }
    for (const item of (structure && structure.names) || []) {
      // Excel переносит имена книги вместе с листами; недостающие (например, на формулы) создаются здесь.
      const present = wb.names.getItemOrNullObject(item.name); await ctx.sync();
      if (!present.isNullObject) continue;
      // Имя на диапазон создаётся по объекту диапазона, остальное (формулы, константы) — по тексту формулы.
      const m = /^(?:'((?:[^']|'')+)'|([^!']+))!(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)$/.exec(item.ref || "");
      let added = false, why = "";
      for (const attempt of m ? ["range", "formula"] : ["formula"]) {
        try {
          const target = attempt === "range" ? wb.worksheets.getItem((m[1] || m[2]).replace(/''/g, "'")).getRange(m[3]) : "=" + item.ref;
          wb.names.add(item.name, target); await ctx.sync(); added = true; break;
        } catch (e) { why = e && e.message ? e.message : String(e); }
      }
      if (!added) failedNames.push(item.name + " (" + why + ")");
    }
  });
}
/* ---------- привязка документа к чату ----------
   Идентификатор чата хранится в документе в трёх местах: свойство файла, настройки add-in и память панели. Любое
   может не сработать (версия Office, документ без имени): тогда берётся следующее. */
const propBag = (ctx, host) => host === "Word" ? ctx.document.properties.customProperties
  : host === "Excel" ? ctx.workbook.properties.custom : ctx.presentation.properties.customProperties;
const hostApi = host => host === "Word" ? Word : host === "Excel" ? Excel : PowerPoint;
function docKey() {
  let url = ""; try { url = Office.context.document.url || ""; } catch (e) { /* без адреса */ }
  if (!url) return "";
  let h = 5381; for (let i = 0; i < url.length; i++) h = ((h << 5) + h + url.charCodeAt(i)) >>> 0;
  return "chat." + h.toString(36);
}
const validId = v => typeof v === "string" && /^[a-z0-9]{6,20}$/.test(v);
async function readBinding() {
  try {
    let value = "";
    await hostApi(HOST).run(async ctx => {
      const item = propBag(ctx, HOST).getItemOrNullObject(BIND); item.load("value"); await ctx.sync();
      if (!item.isNullObject) value = item.value;
    });
    if (validId(value)) return value;
  } catch (e) { /* свойств нет или API недоступен */ }
  try { const v = Office.context.document.settings.get(BIND); if (validId(v)) return v; } catch (e) { /* нет настроек */ }
  const key = docKey(); const v = key ? store.get(key, "") : "";
  return validId(v) ? v : "";
}
async function writeBinding(id) {
  if (!validId(id)) return;
  try { await hostApi(HOST).run(async ctx => { propBag(ctx, HOST).add(BIND, id); await ctx.sync(); }); } catch (e) { /* не записалось: есть запасные места */ }
  try {
    const settings = Office.context.document.settings; settings.set(BIND, id);
    await new Promise(r => settings.saveAsync(() => r()));
  } catch (e) { /* то же */ }
  const key = docKey(); if (key) store.set(key, id);
}
async function clearBinding() {
  try { await hostApi(HOST).run(async ctx => { const item = propBag(ctx, HOST).getItemOrNullObject(BIND); await ctx.sync(); if (!item.isNullObject) { item.delete(); await ctx.sync(); } }); } catch (e) { /* ничего */ }
  try { const settings = Office.context.document.settings; settings.remove(BIND); await new Promise(r => settings.saveAsync(() => r())); } catch (e) { /* ничего */ }
  const key = docKey(); if (key) store.set(key, "");
}
async function applyToDocument(b64, structure) {
  let extra = [];
  if (HOST === "Word") { await applyWord(b64); extra = await applyHeadersFooters((structure && structure.parts) || []); }
  else if (HOST === "PowerPoint") await applyPowerPoint(b64);
  else extra = await applyExcel(b64, structure);
  const failed = await applyProperties(HOST, structure);
  if (chatId) await writeBinding(chatId);       // после applyProperties: оно стирает пользовательские свойства
  return [...(extra || []), ...failed];
}

/* ---------- экран ---------- */
const STEPS = {anonymize: ["Чтение документа", "Обезличивание", "Замена в документе", "Проверка"],
               restore: ["Чтение документа", "Восстановление", "Замена в документе", "Проверка"]};
function show(...ids) { for (const id of ["offline", "ready", "busy", "result"]) $("#" + id).hidden = !ids.includes(id); $("#more").hidden = !ids.includes("ready") && !ids.includes("result"); $("#plan-line").hidden = $("#more").hidden; }
/* Та же сводка, что в окне программы: что скрывается при текущих параметрах. */
function renderPlan() {
  const o = {numbers: $("#opt-numbers").checked, strict: $("#opt-strict").checked, countries: $("#opt-countries").checked};
  const hidden = ["ФИО", "компании", "проекты", "города и адреса", "контакты", "реквизиты"];
  if (o.countries) hidden.push("страны");
  if (o.numbers) hidden.push("числа в Excel");
  if (o.strict) hidden.push("сомнительные слова");
  const left = [!o.countries && "страны", !o.numbers && "числа в Excel", !o.strict && "сомнительные слова"].filter(Boolean);
  $("#plan-line").textContent = `Будут скрыты: ${hidden.join(", ")}.` + (left.length ? ` Не скрываются: ${left.join(", ")}.` : "");
}
for (const key of ["numbers", "strict", "countries"]) $("#opt-" + key).addEventListener("change", () => { touchedOpts[key] = true; renderPlan(); });
/* Итог читает экранный диктор: фокус переходит на блок результата, а не остаётся на кнопке, которая исчезла. */
function focusResult() { const el = $("#result"); if (!el.hidden) { el.tabIndex = -1; try { el.focus({preventScroll: false}); } catch (e) { /* ничего */ } } }
function drawSteps(kind, now, failed) {
  $("#steps").innerHTML = STEPS[kind].map((t, i) => {
    const cls = failed && i === now ? "fail" : i < now ? "done" : i === now ? "now" : "";
    const mark = failed && i === now ? "!" : i < now ? "+" : i === now ? "&gt;" : "";
    return `<li class="${cls}"><span class="mark">${mark}</span><span>${esc(t)}</span></li>`;
  }).join("");
  const pct = Math.round(((now + (failed ? 0 : .4)) / STEPS[kind].length) * 100);
  $("#bar").style.width = pct + "%"; $("#bar-box").setAttribute("aria-valuenow", String(pct));
  $("#bar-box").setAttribute("aria-valuetext", failed ? "Шаг не выполнен: " + STEPS[kind][now] : "Шаг " + (now + 1) + " из " + STEPS[kind].length + ": " + STEPS[kind][now]);
}
function setBusy(on) {
  busy = on;
  for (const id of ["go-anon", "go-rest", "retry", "go-rollback", "open-chat", "open-chat-edit", "match-link", "open-app", "btn-rerun", "rb-go", "rb-cancel"]) { const el = $("#" + id); if (el) el.disabled = on; }
}
// <options-core>
/* Запуск шлёт только то, что человек изменил в панели. Остальное сервер решает сам: запуск > чат > общие настройки > умолчание.
   Если слать все галочки, настройки чата (и новые пункты схемы: категории hide_*, scrub_metadata…) перестают действовать. */
const PANEL_OPTS = ["numbers", "strict", "countries"];
function pickOptions(values, baseline, touched) {
  const out = {};
  for (const key of PANEL_OPTS) if (touched[key] && values[key] !== undefined && !!values[key] !== !!baseline[key]) out[key] = !!values[key];
  return out;
}
// </options-core>
let globalPrefs = {}, touchedOpts = {};
/* То, что панель показывает по умолчанию: общие настройки, поверх них переопределения чата, к которому привязан документ. */
function baselineOptions() {
  const mine = docState && docState.found && docState.chat && docState.chat.settings ? docState.chat.settings : {};
  return {...globalPrefs, ...mine};
}
function syncToggles() {
  const base = baselineOptions();
  for (const key of PANEL_OPTS) { const el = $("#opt-" + key); if (el && !touchedOpts[key]) el.checked = !!base[key]; }
  renderPlan();
}
function options() {
  const values = {};
  for (const key of PANEL_OPTS) values[key] = $("#opt-" + key).checked;
  return pickOptions(values, baselineOptions(), touchedOpts);
}
const noteList = items => `<ul class="notes">${items.map(i => `<li class="${i.level}">${esc(i.text)}</li>`).join("")}</ul>`;
const headline = (text, error) => `<p class="status${error ? " error" : ""}">${esc(text)}</p>`;

function summaryText(job) {
  const parts = (job.result.summary || []).map(s => `${s.label}: ${s.count}`);
  return parts.join(", ");
}
function messagesOf(job) {
  return (job.files[0] ? job.files[0].messages : []).map(m => ({level: m.level === "error" ? "error" : m.level === "warn" ? "warn" : "info", text: m.text}));
}

function renderUnchanged(title, job, extra) {
  show("result", "ready");
  $("#result").innerHTML = headline(title, true) + `<p class="sub">Документ не изменён.</p>` + noteList([...messagesOf(job), ...(extra || [])]);
  focusResult();
}

function renderReview(job) {
  const suggestions = job.result.suggestions || [];
  const rows = suggestions.map((s, i) => `<label><input type="checkbox" data-sug="${i}"><span><b>${esc(s.text)}</b>${s.count > 1 ? " ×" + s.count : ""}<div class="ctx">${esc(s.reason)}. …${esc((s.context || "").slice(0, 100))}…</div></span></label>`).join("");
  show("result", "ready");
  $("#result").innerHTML = headline("Нужно проверить перед заменой.") +
    `<p class="sub">Найдено значений для замены: ${job.result.total || 0}. Документ ещё не изменён.</p>` +
    noteList(messagesOf(job)) +
    (suggestions.length ? `<div><h2 class="sec">Возможно, нужно скрыть ещё</h2><div class="sug">${rows}</div></div>` : "") +
    `<div class="actions">` +
    (suggestions.length ? `<button class="btn" id="btn-rerun">Скрыть отмеченное и подготовить заново</button>` : "") +
    `<button class="btn main" id="btn-apply">Заменить в документе</button></div>`;
  focusResult();
  $("#btn-apply").onclick = () => applyAndVerify(job);
  const rerun = $("#btn-rerun");
  if (rerun) rerun.onclick = () => {
    const overrides = {};
    document.querySelectorAll("[data-sug]").forEach(box => { if (box.checked) overrides[suggestions[+box.dataset.sug].text] = "hide"; });
    run("anonymize", overrides);
  };
}

const PROPERTY_LABELS = {author: "автор", title: "название", subject: "тема", keywords: "ключевые слова", comments: "комментарии",
  category: "категория", manager: "руководитель", company: "организация"};
/* Что осталось в свойствах файла: то, что Office не дал изменить, и то, что нашла сверка. Пусто, если всё чисто. */
function propertyLeftovers(limits, warnings) {
  const names = [];
  for (const item of limits) {
    const m = /«(.+)»/.exec(item);
    names.push(m ? (PROPERTY_LABELS[m[1]] || m[1]) : item);
  }
  if (!names.length && warnings.some(w => w.code === "properties")) names.push("имя автора или другие сведения");
  return [...new Set(names)];
}
function renderFinal(kind, job, verify, failedNames) {
  const problems = (verify && verify.problems || []).map(p => ({level: "error", text: p.text}));
  const notes = (verify && verify.notes || []).map(t => ({level: "info", text: t}));
  const warns = (verify && verify.warnings || []).map(p => ({level: "warn", text: p.text}));
  const extra = [];
  // Свойства файла Office иногда менять не даёт: это ограничение версии, а не расхождение в документе.
  const propertyLimit = (failedNames || []).filter(n => n.indexOf("свойств") >= 0);
  const brokenParts = (failedNames || []).filter(n => n.indexOf("свойств") < 0);
  if (brokenParts.length) extra.push({level: "warn", text: "Не удалось воссоздать: " + brokenParts.join(", ") + "."});
  // Автор, организация и название файла остаются в файле, даже если текст заменён: итог неполный, а не чистый.
  const leftovers = propertyLeftovers(propertyLimit, (verify && verify.warnings) || []);
  if (leftovers.length) extra.push({level: "error", text: "В свойствах файла остались данные: " + leftovers.join(", ") + ". Следующий шаг: очистите их вручную (Файл, Сведения) или обработайте файл в программе Anonymizer."});
  const partial = !!leftovers.length;
  const clean = !problems.length && !brokenParts.length && !partial;
  const attention = messagesOf(job);   // и «info»: заметка об недоступной модели имён должна быть видна
  const verb = kind === "anonymize" ? "Документ обезличен." : "Данные возвращены.";
  const title = clean ? (attention.some(m => m.level !== "info") ? verb + " Есть замечания." : verb)
    : partial && !problems.length && !brokenParts.length ? (kind === "anonymize" ? "Документ обезличен не полностью." : "Данные возвращены не полностью.")
    : "Документ заменён, но есть расхождения.";
  const counts = kind === "anonymize" ? `Заменено значений: ${job.result.total || 0}. ${summaryText(job)}` : `Восстановлено значений: ${job.result.restored || 0}.`;
  let html = headline(title, !clean) + `<p class="sub">${esc(counts)}</p>`;
  html += noteList([...problems, ...extra, ...warns, ...attention, ...(clean ? [{level: "ok", text: "Документ заново прочитан и сверен с результатом."}] : []), ...notes]);
  const unknown = Object.keys(job.result.unknown || {});
  if (kind === "restore" && unknown.length) html += `<div><h2 class="sec">Метки, которых нет в хранилище</h2><div class="chips">${unknown.slice(0, 12).map(u => `<span class="chip">${esc(u)}</span>`).join("")}</div></div>`;
  if (!job.chat) html += `<div class="actions"><button class="btn" id="btn-rollback">Откатить к исходному</button></div>`;
  html += `<p class="hint">Отмена в Office (Ctrl+Z) после такой замены может не сработать: используйте «Откатить».</p>`;
  show("result", "ready");
  $("#result").innerHTML = html;
  const rb = $("#btn-rollback"); if (rb) rb.onclick = () => rollback(last && last.backup);
  focusResult();
}

function renderError(error, canRollback) {
  show("result", "ready");
  let html = headline("Не получилось.", true) + `<p class="sub">${esc(error.message || error)}</p>`;
  if (canRollback) html += `<div class="actions"><button class="btn" id="btn-rollback">Откатить к исходному</button></div>`;
  $("#result").innerHTML = html;
  const b = $("#btn-rollback"); if (b) b.onclick = () => rollback(last && last.backup, false, true);
  focusResult();
}

/* Ошибка после того, как замена началась: честно говорит, что с документом, и что делать. */
function renderApplyFailure(e) {
  const docState = e && e.docState || "unknown";
  show("result", "ready");
  const title = docState === "untouched" ? "Не получилось." : docState === "partial" ? "Документ изменён частично." : "Документ мог измениться.";
  const lead = docState === "untouched" ? "" : docState === "partial" ? "Часть документа уже заменена, часть нет. Откатите документ к исходному или повторите обезличивание."
    : "Замена не завершилась, и состояние документа неизвестно. Проверьте его, откатите к исходному или повторите обезличивание.";
  let html = headline(title, true) + `<p class="sub">${esc(e.message || e)}</p>` + (lead ? `<p class="hint">${esc(lead)}</p>` : "");
  if (docState !== "untouched") html += `<div class="actions"><button class="btn" id="btn-rollback">Откатить к исходному</button></div>`;
  $("#result").innerHTML = html;
  const b = $("#btn-rollback"); if (b) b.onclick = () => rollback(last && last.backup, false, true);
  focusResult();
}
/* Связь с программой пропала после замены: документ уже другой, проверить результат не удалось. */
function renderVerifyFailure(e, pending) {
  show("result", "ready");
  $("#result").innerHTML = headline("Документ уже заменён, но проверить результат не удалось.", true) +
    `<p class="sub">${esc(e.message || e)}</p>` +
    `<p class="hint">Замена выполнена. Повторите проверку, когда связь с программой появится, или откатите документ к исходному.</p>` +
    `<div class="actions"><button class="btn main" id="btn-reverify">Повторить проверку</button><button class="btn" id="btn-rollback">Откатить к исходному</button></div>`;
  $("#btn-reverify").onclick = () => reverify(pending);
  $("#btn-rollback").onclick = () => rollback(last && last.backup, false, true);
  focusResult();
}
async function reverify(pending) {
  if (busy) return;
  setBusy(true); show("busy"); drawSteps(pending.kind, 3);
  try {
    const reread = await getFile();
    const verify = await api("/api/addin/verify/" + pending.job.id, {method: "POST", body: reread, headers: {"Content-Type": "application/octet-stream"}});
    renderFinal(pending.kind, pending.job, verify, pending.failedNames);
    loadBackups();
    await refreshState();
  } catch (e) { renderVerifyFailure(e, pending); }
  finally { setBusy(false); }
}

/* ---------- операции ---------- */
async function waitJob(id) {
  const until = Date.now() + 20 * 60 * 1000;
  for (;;) {
    if (Date.now() > until) throw new Error("Обработка идёт слишком долго. Документ не изменён: повторите или обработайте файл в программе.");
    await sleep(450);
    const job = await api("/api/addin/jobs/" + id);
    if (job.state === "done" || job.state === "failed") return job;
    $("#bar").style.width = Math.round((.25 + job.percent * .25) * 100) + "%";
  }
}

async function run(kind, overrides) {
  dbg("run " + kind + " busy=" + busy);
  if (busy) return;
  undoneRestore = "";
  setBusy(true);
  let step = 0;
  show("busy");
  try {
    drawSteps(kind, 0);
    let started;
    if (overrides) {
      const digest = await sha256Hex(await getFile());
      started = await postJson("/api/addin/rerun", {job: last.job, options: options(), overrides, ...(digest ? {digest} : {})});
    } else {
      dbg("reading file");
      const bytes = await getFile();
      dbg("file read " + bytes.length);
      if (bytes.length > MAX_BYTES) throw new Error("Документ больше 100 МБ: Office не позволяет заменить его целиком. Обработайте файл в программе Anonymizer.");
      started = await api("/api/addin/" + kind, {method: "POST", body: bytes, headers: {
        "X-Filename": encodeURIComponent(documentName()), "Content-Type": "application/octet-stream",
        "X-Options": encodeURIComponent(JSON.stringify(options())), ...(((kind === "anonymize" ? chatId || lastChat : chatId)) ? {"X-Chat": kind === "anonymize" ? chatId || lastChat : chatId} : {})}});
    }
    step = 1; drawSteps(kind, 1);
    dbg("job started " + started.job);
    const job = await waitJob(started.job);
    dbg("job state " + job.state);
    if (job.state === "failed") throw new Error(job.error || "Не удалось обработать документ.");
    last = {job: job.id, backup: started.backup, kind, structure: job.structure, data: job};
    const file = job.files[0];
    if (!file || !file.downloadable) return renderUnchanged(kind === "anonymize" ? "Документ не обезличен." : "Данные не возвращены.", job);
    if (!file.total && !(job.result.numbers && job.result.numbers.replaced)) {
      const text = kind === "anonymize" ? "Данных для замены не найдено." : "В документе не найдено меток для восстановления.";
      return renderUnchanged(text, job);
    }
    if (kind === "anonymize" && (!$("#opt-auto").checked || (job.result.suggestions || []).length || file.status === "attention")) {
      setBusy(false);
      return renderReview(job);
    }
    setBusy(false);
    await applyAndVerify(job);
  } catch (e) {
    setBusy(false);
    if (e.code === "tracked_changes") return renderTracked(e.count, kind);
    show("busy"); drawSteps(kind, step, true);
    renderError(e, false);
  } finally { setBusy(false); }
}

function renderTracked(count, kind) {
  show("result", "ready");
  $("#result").innerHTML = headline("В документе есть исправления.") +
    `<p class="sub">Исправлений: ${count}. Они хранят прежний текст, поэтому его не удалось бы убрать из документа. Примите их или отклоните, затем повторите.</p>` +
    `<div class="actions"><button class="btn main" id="btn-accept">Принять все исправления и продолжить</button></div><p class="hint" id="accept-note"></p>`;
  $("#btn-accept").onclick = async () => {
    try { await wordAcceptAll(); } catch (e) {
      $("#accept-note").textContent = "В этой версии Word кнопка недоступна: примите исправления на вкладке «Рецензирование» (Принять, Все исправления) и нажмите «Обезличить документ» снова.";
      return;
    }
    run(kind);
  };
}

function renderChanged(kind, check) {
  show("result", "ready");
  $("#result").innerHTML = headline("Документ изменился во время обработки.") +
    `<p class="sub">Замена затёрла бы ваши правки (изменено слов: ${check.changed}). Документ не тронут.</p>` +
    `<div class="actions"><button class="btn main" id="btn-again">Повторить с текущей версией</button>` +
    `<button class="btn" id="btn-force">Всё равно заменить</button></div>`;
  $("#btn-again").onclick = () => run(kind);
  $("#btn-force").onclick = () => applyAndVerify(last.data, true);
}

async function applyAndVerify(job, force) {
  if (busy) return;
  setBusy(true);
  const kind = last.kind;
  let step = 2, touched = false, pending = null;
  show("busy");
  try {
    drawSteps(kind, 2);
    if (!force) {
      // Пока шла обработка, документ могли править: замена затёрла бы эти правки.
      const now = await getFile();
      const post = {method: "POST", body: now, headers: {"Content-Type": "application/octet-stream"}};
      let check;
      try { check = await api("/api/addin/unchanged/" + job.id + "?strict=1", post); }
      catch (e) {
        if (e.status !== 409) throw e;                            // документ изменён: подробности для диалога берём без strict
        check = await api("/api/addin/unchanged/" + job.id, post);
        check.same = false;
      }
      if (!check.same) { setBusy(false); return renderChanged(kind, check); }
    }
    const result = await api("/api/addin/result/" + job.id);
    const bytes = new Uint8Array(await result.arrayBuffer());
    touched = true;
    if (job.chat) { chatId = job.chat; lastChat = job.chat; }
    const failedNames = await applyToDocument(toBase64(bytes), job.structure || last.structure) || [];
    pending = {kind, job, failedNames};
    step = 3; drawSteps(kind, 3);
    const reread = await getFile();
    const verify = await api("/api/addin/verify/" + job.id, {method: "POST", body: reread, headers: {"Content-Type": "application/octet-stream"}});
    pending = null;
    renderFinal(kind, job, verify, failedNames);
    loadBackups();
    await refreshState();
  } catch (e) {
    if (pending) return renderVerifyFailure(e, pending);       // замена выполнена, не прошла только проверка
    if (touched) return renderApplyFailure(e);
    show("busy"); drawSteps(kind, step, true);
    renderError(e, false);
  } finally { setBusy(false); }
}

const RB = {
  other: ["Откат не выполнен.", "Открытый документ не совпадает с тем, для которого сохранена копия оригинала. Чтобы не записать в него чужой оригинал, документ не тронут."],
  edited: ["Откатить документ?", "После замены документ изменён. Откат заменит его целиком копией {to}: все правки после замены пропадут{back}."],
  same: ["Откатить документ?", "Документ целиком заменится копией {to}. Замены этой обработки пропадут{back}."],
  unknown: ["Откатить документ?", "Не удалось проверить, менялся ли документ после замены. Откат заменит его целиком копией {to}, и все правки после замены пропадут{back}."],
  uncertain: ["Откатить документ?", "Замена не завершилась, документ мог измениться частично. Откат заменит его целиком копией {to}{back}."],
};
/* Откат стирает документ целиком: сначала сверка с тем, что обезличивалось, потом подтверждение здесь же, в панели. */
async function rollback(backupId, beforeRestore, uncertain) {
  if (!backupId || busy) return;
  setBusy(true); show("busy"); drawSteps((last && last.kind) || "anonymize", 0);
  let status = uncertain ? "uncertain" : "unknown", backupKind = beforeRestore ? "restore" : "anonymize";
  if (!uncertain) {
    try {
      const file = await getFile();
      const post = {method: "POST", body: file, headers: {"Content-Type": "application/octet-stream"}};
      let check;
      try { check = await api("/api/addin/rollback-check/" + backupId + "?strict=1", post); }
      catch (e) {
        if (e.status !== 409) throw e;                            // документ менялся или другой: статус нужен диалогу
        check = await api("/api/addin/rollback-check/" + backupId, post);
      }
      status = check.status; backupKind = check.kind || backupKind;
    } catch (e) { status = "unknown"; }
  }
  setBusy(false);
  const toRestore = backupKind === "restore";
  const [title, text] = RB[status] || RB.unknown;
  const body = text.replace("{to}", toRestore ? "до возврата данных" : "до обезличивания").replace("{back}", toRestore ? "" : ", а настоящие данные вернутся в документ");
  show("result", "ready");
  const go = status === "other" ? "" : `<button class="btn" id="rb-go">${status === "same" ? "Откатить" : "Откатить, правки пропадут"}</button>`;
  $("#result").innerHTML = headline(title, status === "other") + `<p class="sub">${esc(body)}</p>` +
    `<div class="actions"><button class="btn main" id="rb-cancel">${status === "other" ? "Понятно" : "Не откатывать"}</button>${go}</div>`;
  $("#rb-cancel").onclick = () => { show("ready"); refreshState(); };
  const goButton = $("#rb-go"); if (goButton) goButton.onclick = () => performRollback(backupId, beforeRestore);
  $("#rb-cancel").focus();                                       // безопасное действие по умолчанию
}
async function performRollback(backupId, beforeRestore) {
  if (!backupId || busy) return;
  const bound = chatId;
  setBusy(true); show("busy");
  const kind = (last && last.kind) || "anonymize";
  try {
    drawSteps(kind, 2);
    const {structure} = await api("/api/addin/backup-info/" + backupId);
    const r = await api("/api/addin/backup/" + backupId);
    const bytes = new Uint8Array(await r.arrayBuffer());
    // Откат к исходному: документ снова без замен, метку чата в него не пишем. Откат возврата: документ снова обезличен, метка остаётся.
    if (!beforeRestore) chatId = "";
    const failedNames = await applyToDocument(toBase64(bytes), structure) || [];
    if (beforeRestore) { undoneRestore = bound; if (last && last.backup === backupId) last = {...last, backup: null}; await refreshState(); }
    else { if (bound) { lastChat = bound; await clearBinding(); } undoneRestore = ""; docState = {found: false}; renderState(); }
    show("result", "ready");
    $("#result").innerHTML = headline(beforeRestore ? "Документ возвращён к виду до возврата данных. В нём снова коды замены." : "Документ возвращён к состоянию до замены.") +
      (failedNames.length ? noteList([{level: "warn", text: "Не удалось воссоздать: " + failedNames.join(", ") + "."}]) : "");
    focusResult();
  } catch (e) { chatId = bound; renderError(e, false); }
  finally { setBusy(false); }
}

/* ---------- состояние документа ---------- */
const plural = (n, one, few, many) => { const a = n % 100, b = n % 10; return a > 10 && a < 20 ? many : b === 1 ? one : b > 1 && b < 5 ? few : many; };
const note = text => { const el = $("#state-note"); el.textContent = text || ""; el.hidden = !text; };

async function refreshState() {
  if (!HOST || !EXT[HOST]) return;
  try {
    if (!chatId) chatId = await readBinding();
    docState = chatId ? await api("/api/addin/doc-state?chat=" + encodeURIComponent(chatId)) : {found: false};
    if (chatId && !docState.found) { chatId = ""; await clearBinding(); }   // чат удалён: привязка устарела
    // После отката возврата документ снова обезличен, а в чате последний шаг по-прежнему «возврат».
    if (docState.found && undoneRestore === chatId && docState.chat.state === "restored") docState = {...docState, chat: {...docState.chat, state: "anonymized"}};
  } catch (e) { docState = null; }
  renderState();
}

function renderState() {
  syncToggles();
  const found = docState && docState.found, chat = found ? docState.chat : null;
  const kind = chat ? chat.state : "none";
  const box = $("#docstate");
  box.className = "state" + (kind === "anonymized" ? " done" : kind === "restored" ? " back" : "");
  const sub = $("#st-sub");
  if (kind === "anonymized") {
    $("#st-title").textContent = `Обезличен: ${chat.replaced_total} ${plural(chat.replaced_total, "замена", "замены", "замен")} · чат «${chat.title}»`;
  } else if (kind === "restored") {
    $("#st-title").textContent = "Данные возвращены";
    sub.textContent = `Чат «${chat.title}»`;
  } else {
    $("#st-title").textContent = "Документ не обезличен";
  }
  sub.hidden = kind !== "restored";
  $("#lead").hidden = kind !== "none";
  $("#pending").hidden = !(chat && chat.pending_edits > 0);
  const anon = $("#go-anon"), rest = $("#go-rest");
  anon.textContent = kind === "restored" ? "Обезличить снова" : "Обезличить документ";
  const setMain = (btn, on) => btn.classList.toggle("main", on);
  setMain(anon, kind !== "anonymized"); setMain(rest, kind === "anonymized");
  rest.hidden = kind === "restored";
  anon.hidden = kind === "anonymized";
  // Откат: у обезличенного документа к исходному; у возвращённого к виду до возврата (копия этой сессии, иначе список в «Дополнительно»).
  const undoRestore = kind === "restored" && last && last.kind === "restore" && last.backup;
  $("#go-rollback").hidden = !((kind === "anonymized" && chat.has_backup) || undoRestore);
  $("#go-rollback").textContent = undoRestore ? "Откатить к виду до возврата" : "Откатить к исходному";
  $("#state-hint").hidden = !(kind === "restored" && !undoRestore);
  // Один раз и рядом с откатом: копия не вечная, а Office и облако хранят свои версии файла.
  const days = `${backupDays} ${plural(backupDays, "день", "дня", "дней")}`;
  const hint = $("#rollback-hint");
  const keepsOriginal = kind === "anonymized" && chat.has_backup;
  hint.hidden = kind !== "anonymized";
  hint.textContent = keepsOriginal
    ? `Копия оригинала хранится ${days}, потом удаляется. История версий OneDrive и автосохранение Office могут сохранить исходные данные.`
    : `Копии оригинала больше нет: она хранится ${days}. Откатить к исходному нельзя. История версий OneDrive и автосохранение Office могли сохранить исходные данные.`;
  $("#open-chat").hidden = !chat;
  $("#open-app").hidden = !chat;
  $("#match-link").hidden = !!chat;
  const actions = $("#actions");
  // Главная кнопка первой: для обезличенного документа это «Вернуть данные».
  if (kind === "anonymized") actions.insertBefore(rest, actions.firstChild); else actions.insertBefore(anon, actions.firstChild);
  const table = $("#table-box");
  table.hidden = !chat || kind === "none";
  if (table.hidden) table.open = false;
  else if (table.open) loadTable();
}

async function loadTable() {
  const list = $("#repl");
  if (!chatId) return;
  try {
    const data = await api("/api/addin/chat-table?chat=" + encodeURIComponent(chatId));
    list.innerHTML = data.rows.length ? data.rows.map(r => `<li><span class="what"><span>${esc(r.label.charAt(0).toUpperCase() + r.label.slice(1))}</span><span class="val">${esc(r.secret ? "хранится только в программе" : r.value || "")}</span></span><span class="files">${r.files} ${plural(r.files, "файл", "файла", "файлов")}</span></li>`).join("")
      : `<li><span class="meta">Замен пока нет.</span></li>`;
    const more = $("#repl-more");
    more.hidden = data.total <= data.rows.length;
    more.textContent = `Показано ${data.rows.length} из ${data.total}. Полный список в чате.`;
  } catch (e) { list.innerHTML = `<li><span class="meta">Не удалось загрузить список.</span></li>`; }
}

async function matchByMarks() {
  if (busy) return;
  setBusy(true); note("Ищем метки в документе…");
  try {
    const bytes = await getFile();
    const found = await api("/api/addin/match", {method: "POST", body: bytes, headers: {"X-Filename": encodeURIComponent(documentName()), "Content-Type": "application/octet-stream"}});
    if (found.found) { chatId = found.chat.id; docState = found; await writeBinding(chatId); note(""); renderState(); }
    else note("Метки этого документа не найдены ни в одном чате или подходят сразу к нескольким.");
  } catch (e) { note(e.message || String(e)); }
  finally { setBusy(false); }
}

async function openSettings() {
  try { await postJson("/api/addin/open-app", {tab: "anon", settings: true}); note("Программа открыта. Настройки: значок профиля в её окне."); }
  catch (e) { note("Не удалось открыть программу: " + (e.message || e)); }
}
async function openApp(hint) {
  const prefix = typeof hint === "string" ? hint + " " : "";
  try { await postJson("/api/addin/open-app", {tab: "anon", chat: chatId || undefined}); note(chatId ? prefix + "Чат открыт в программе." : prefix.trim()); }
  catch (e) { note("Не удалось открыть программу: " + (e.message || e)); }
}
function openChat() {
  if (!chatId) return;
  note("");
  const dialogs = supported("DialogApi", "1.1") && Office.context.ui && Office.context.ui.displayDialogAsync;
  if (!dialogs) { return openApp("Окно чата в Office недоступно в этой версии."); }
  const url = location.origin + "/addin/chat?chat=" + encodeURIComponent(chatId);
  Office.context.ui.displayDialogAsync(url, {height: 80, width: 70}, res => {
    if (res.status !== Office.AsyncResultStatus.Succeeded) {
      return openApp("Окно чата не открылось" + (res.error && res.error.code ? " (код " + res.error.code + ")" : "") + ".");
    }
    dialog = res.value;
    const closed = () => { dialog = null; refreshState(); };
    dialog.addEventHandler(Office.EventType.DialogMessageReceived, arg => {
      if (arg && arg.message === "close") { try { dialog.close(); } catch (e) { /* уже закрыто */ } closed(); }
    });
    dialog.addEventHandler(Office.EventType.DialogEventReceived, closed);
  });
}

/* ---------- копии, настройки, связь ---------- */
async function loadBackups() {
  const box = $("#backups");
  try {
    const {items} = await api("/api/addin/backups");
    const own = items.filter(i => i.name.toLowerCase().endsWith("." + EXT[HOST]));
    box.innerHTML = own.length ? own.map(i => `<li><span class="name">${esc(i.name)}<div class="meta">${esc(i.kind === "anonymize" ? "до обезличивания" : "до возврата")}, ${new Date(i.time * 1000).toLocaleString("ru-RU")}</div></span><button class="btn small" data-back="${esc(i.id)}">Вернуть</button></li>`).join("")
      : `<li><span class="meta">Пока нет копий.</span></li>`;
    box.querySelectorAll("[data-back]").forEach(b => b.onclick = () => rollback(b.dataset.back));
  } catch (e) { box.innerHTML = ""; }
}

/* Что видно до запуска: недоступная модель имён и менее безопасный режим картинок. Читает /api/state (то же, что окно программы). */
async function loadAlerts() {
  let st = null;
  try { st = await api("/api/state"); } catch (e) { /* нет связи: заметок не показываем */ }
  const ner = !!st && st.ner_available === false, img = !!st && !!st.image_mode_unsafe;
  $("#ner-note").hidden = !ner; $("#img-warn").hidden = !img; $("#alerts").hidden = !(ner || img);
}
async function connect() {
  const conn = $("#conn");
  try {
    const info = await api("/api/addin/info");
    conn.textContent = "Подключено"; conn.className = "conn ok";
    if (info.backup_days) backupDays = info.backup_days;
    globalPrefs = info.prefs || {};
    syncToggles();
    const note = $("#notice");
    note.hidden = !info.notice; note.textContent = info.notice || "";
    loadAlerts();
    if (!last) show("ready");
    $("#more").hidden = false;
    loadBackups();
    if (!busy) refreshState();
    return true;
  } catch (e) {
    conn.textContent = "Нет связи"; conn.className = "conn bad";
    show("offline");
    return false;
  }
}

function init(info) {
  HOST = info && info.host ? String(info.host) : null;
  if (!HOST || !EXT[HOST]) {
    $("#conn").textContent = "Не в Office"; $("#conn").className = "conn bad";
    show("offline");
    $("#offline").innerHTML = `<p class="lead">Панель работает внутри Word, Excel и PowerPoint.</p>`;
    return;
  }
  $("#opt-auto").checked = store.get("auto", true);
  $("#opt-auto").onchange = e => store.set("auto", e.target.checked);
  $("#go-anon").onclick = () => run("anonymize");
  $("#go-rest").onclick = () => run("restore");
  $("#go-rollback").onclick = () => {
    if (docState && docState.found && docState.chat.state === "restored") { if (last && last.backup) rollback(last.backup, true); return; }
    const b = docState && docState.found && docState.chat.backup; if (b) rollback(b);
  };
  $("#open-chat").onclick = openChat;
  $("#open-chat-edit").onclick = openChat;
  $("#open-app").onclick = () => openApp();
  $("#match-link").onclick = matchByMarks;
  $("#table-box").addEventListener("toggle", () => { if ($("#table-box").open) loadTable(); });
  $("#retry").onclick = connect;
  $("#open-settings").onclick = openSettings; $("#open-settings-foot").onclick = openSettings;
  $("#open-folder").onclick = () => postJson("/api/addin/open-app", {tab: "anon"}).catch(() => {});
  window.addEventListener("focus", () => { if (!busy) connect(); });
  connect();
}

/* Кнопки на ленте работают с одного нажатия: общий runtime Office выполняет их в этой же странице. */
let initialized = false, readyWaiters = [];
function whenReady() { return initialized ? Promise.resolve() : new Promise(r => readyWaiters.push(r)); }
async function command(kind, event) {
  dbg("command " + kind + " start");
  try { await Office.addin.showAsTaskpane(); dbg("showAsTaskpane ok"); } catch (e) { dbg("showAsTaskpane error " + (e && e.message)); }
  try { await whenReady(); dbg("ready host=" + HOST); if (HOST && EXT[HOST]) await run(kind); dbg("run finished"); }
  catch (e) { dbg("command error " + (e && e.message)); }
  finally { try { event.completed(); } catch (e) { /* ничего */ } dbg("completed"); }
}
if (window.Office && Office.actions && Office.actions.associate) {
  Office.actions.associate("anonymizeCommand", e => command("anonymize", e));
  Office.actions.associate("restoreCommand", e => command("restore", e));
}

if (window.Office && Office.onReady) Office.onReady(info => { init(info); initialized = true; readyWaiters.forEach(r => r()); });
else init(null);
