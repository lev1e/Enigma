"use strict";
/* Двойник Office.js для проверки панели в обычном браузере (только разработка, отдаётся tools/dev_addin_server.py).
   Документ в памяти двойника - настоящие байты docx/xlsx/pptx из папки case/, их хранит dev-сервер, поэтому документ
   переживает перезагрузку страницы, как в настоящем Office.
   Адрес: taskpane.html?host=Word|Excel|PowerPoint&doc=<файл из case/>[&fresh=1][&desktop=1][&dialog=0][&dialogfail=1].
   Точность ограниченная: проверка настоящего Office делается отдельно. Что двойник НЕ умеет: форматирование, исправления,
   колонтитулы (вызовы принимаются и ничего не делают), настоящие свойства внутри файла (они лежат отдельно, как JSON).
   Сценарии отказов: refuseprops=1 (Office молча не меняет автора, название, организацию), failverify=1 (связь с программой
   пропадает на проверке после замены, один раз), excelfail=insert|delete (Excel не вставляет листы после удаления имён /
   не удаляет прежние листы), pptfail=delete (PowerPoint не удаляет прежние слайды). */
(function () {
  const q = new URLSearchParams(location.search);
  const HOST = q.get("host") || "Word";
  const NAME = q.get("doc") || ({Word: "Договор.docx", Excel: "Таблица.xlsx", PowerPoint: "Презентация.pptx"})[HOST];
  const state = {name: NAME, bytes: null, meta: {props: {}, custom: {}, settings: {}}, sheets: [], slides: [], seq: 0, log: []};
  const log = (...a) => { state.log.push(a.join(" ")); };
  const fromB64 = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  // `fresh=1` сбрасывает документ один раз за вкладку: дальше перезагрузки страницы должны видеть сохранённый документ.
  let fresh = false;
  try { const flag = "fake.fresh." + NAME + location.search; if (q.get("fresh") && !sessionStorage.getItem(flag)) { fresh = true; sessionStorage.setItem(flag, "1"); } } catch (e) { /* без sessionStorage */ }
  if (q.get("failverify") === "1") {
    const realFetch = window.fetch.bind(window); let failed = false;
    window.fetch = (url, opts) => (!failed && String(url).includes("/api/addin/verify/")) ? (failed = true, Promise.reject(new TypeError("Failed to fetch"))) : realFetch(url, opts);
  }
  const dev = path => "/dev/doc/" + path + "?name=" + encodeURIComponent(NAME) + "&host=" + HOST + (fresh && path === "bytes" ? "&fresh=1" : "");
  async function structureOf(bytes) {
    const r = await fetch("/dev/structure?name=" + encodeURIComponent(NAME), {method: "POST", body: bytes});
    return r.json();
  }
  async function save() {
    await fetch(dev("bytes"), {method: "PUT", body: state.bytes});
    await fetch(dev("meta"), {method: "PUT", body: JSON.stringify({...state.meta, sheets: state.sheets.map(s => ({id: s.id, name: s.name, visibility: s.visibility})), slides: state.slides})});
  }
  async function load() {
    const r = await fetch(dev("bytes"));
    fresh = false;
    state.bytes = new Uint8Array(await r.arrayBuffer());
    const meta = await (await fetch(dev("meta"))).json();
    state.meta = {props: meta.props || {}, custom: meta.custom || {}, settings: meta.settings || {}};
    const st = await structureOf(state.bytes);
    state.structure = st;
    if (HOST === "Excel") state.sheets = (meta.sheets && meta.sheets.length ? meta.sheets : st.sheets.map(s => ({id: "s" + (++state.seq), name: s.name, visibility: s.state === "visible" ? "Visible" : s.state === "hidden" ? "Hidden" : "VeryHidden"})));
    if (HOST === "PowerPoint") state.slides = meta.slides && meta.slides.length ? meta.slides : Array.from({length: st.slides}, () => "sl" + (++state.seq));
    if (!Object.keys(state.meta.props).length) state.meta.props = {author: (st.props || {}).author || "", title: (st.props || {}).title || "", company: (st.props || {}).company || "", comments: (st.props || {}).comments || ""};
    for (const c of (st.custom || [])) if (!(c.name in state.meta.custom)) state.meta.custom[c.name] = c.value;
  }

  /* Операции Office выполняются при sync(), как в настоящем Office. */
  function context(extra) {
    const queue = [];
    const ctx = {
      sync: async () => { while (queue.length) await queue.shift()(); await save(); },
      ...extra(queue),
    };
    return ctx;
  }
  const propsObject = () => new Proxy({}, {
    get: (_, k) => k === "load" ? () => {} : k === "customProperties" || k === "custom" ? customBag() : state.meta.props[k] || "",
    set: (_, k, v) => { if (q.get("refuseprops") === "1" && ["author", "title", "company"].includes(k)) return true; state.meta.props[k] = v; return true; },
  });
  const customBag = () => ({
    getItemOrNullObject: name => {
      const has = name in state.meta.custom;
      const item = {isNullObject: !has, value: has ? state.meta.custom[name] : undefined, load() {}, delete() { delete state.meta.custom[name]; }};
      return item;
    },
    add: (name, value) => { state.meta.custom[name] = String(value); },
    deleteAll: () => { state.meta.custom = {}; },
  });
  const headerBody = () => ({insertFileFromBase64() { log("hf insert"); }, clear() {}, insertText() {}});

  async function wordRun(fn) {
    const doc = {changeTrackingMode: "Off", load() {}};
    const ctx = context(queue => ({document: Object.assign(doc, {
      insertFileFromBase64: (b64) => { queue.push(async () => { state.bytes = fromB64(b64); log("word replace doc"); }); },
      properties: propsObject(),
      sections: (() => { const s = {load() {}, items: []}; const n = Math.max(1, ...((state.structure.parts || []).map(p => p.section + 1))); for (let i = 0; i < n; i++) s.items.push({getHeader: headerBody, getFooter: headerBody}); return s; })(),
      body: {insertFileFromBase64: (b64) => { queue.push(async () => { state.bytes = fromB64(b64); log("word replace body"); }); }, getTrackedChanges: () => ({acceptAll() {}})},
    })}));
    await fn(ctx);
  }
  async function excelRun(fn) {
    const sheetObj = s => ({get id() { return s.id; }, get name() { return s.name; }, set name(v) { s.name = v; }, get visibility() { return s.visibility; }, set visibility(v) { s.visibility = v; },
      delete() { ctx._q.push(async () => { if (q.get("excelfail") === "delete" && !s.fresh) throw new Error("Лист защищён"); if (!state.sheets.filter(x => x !== s).length) throw new Error("Нельзя удалить единственный лист"); if (s.visibility !== "Visible" && state.sheets.filter(x => x.visibility === "Visible" && x !== s).length === 0) throw new Error("Нельзя удалить последний видимый лист"); state.sheets = state.sheets.filter(x => x !== s); if (!state.sheets.some(x => !x.fresh)) { state.bytes = state.pending || state.bytes; } }); }});
    let ctx;
    ctx = context(queue => {
      ctx_q = queue;
      return {workbook: {
        properties: propsObject(),
        worksheets: {load() {}, get items() { return state.sheets.map(sheetObj); }, getItem: id => sheetObj(state.sheets.find(s => s.id === id || s.name === id) || (() => { throw new Error("Лист не найден"); })())},
        names: {load() {}, items: [], getItemOrNullObject: name => ({isNullObject: !(state.names || {})[name], load() {}}), add: (name, target) => { queue.push(async () => { (state.names = state.names || {})[name] = true; }); }},
        insertWorksheetsFromBase64: (b64) => queue.push(async () => {
          if (q.get("excelfail") === "insert") throw new Error("Не удалось вставить листы");
          const bytes = fromB64(b64), st = await structureOf(bytes);
          state.pending = bytes;
          for (const sh of st.sheets) {
            let name = sh.name, n = 1;
            while (state.sheets.some(x => x.name === name)) name = sh.name + " (" + (++n) + ")";     // Excel сам переименовывает при совпадении
            state.sheets.push({id: "s" + (++state.seq), name, visibility: "Visible", fresh: true});
          }
        }),
      }};
    });
    ctx._q = ctx_q;
    await fn(ctx);
  }
  let ctx_q;
  async function pptRun(fn) {
    const ctx = context(queue => ({presentation: {
      properties: propsObject(),
      slides: {load() {}, get items() { return state.slides.map(id => ({id})); }, getItem: id => ({delete() { queue.push(async () => { if (q.get("pptfail") === "delete" && !String(id).startsWith("n")) throw new Error("Слайд занят"); state.slides = state.slides.filter(x => x !== id); if (!state.slides.some(x => !String(x).startsWith("n"))) state.bytes = state.pending || state.bytes; }); }})},
      insertSlidesFromBase64: (b64) => queue.push(async () => { const bytes = fromB64(b64); const st = await structureOf(bytes); state.pending = bytes; for (let i = 0; i < st.slides; i++) state.slides.push("n" + (++state.seq)); }),
    }}));
    await fn(ctx);
  }

  const asyncResult = (value, fail) => fail ? {status: "failed", error: {code: fail.code || 0, message: fail.message || "error"}} : {status: "succeeded", value};
  const dialogHandlers = {};
  const Office = {
    AsyncResultStatus: {Succeeded: "succeeded", Failed: "failed"},
    FileType: {Compressed: "compressed"},
    EventType: {DialogMessageReceived: "DialogMessageReceived", DialogEventReceived: "DialogEventReceived"},
    onReady: cb => load().then(() => { const info = {host: HOST, platform: "PC"}; if (cb) cb(info); return info; }),
    actions: {associate() {}},
    addin: {showAsTaskpane: async () => {}},
    context: {
      requirements: {isSetSupported: (set, v) => {
        if (set === "DialogApi") return q.get("dialog") !== "0";
        if (set === "WordApiDesktop") return q.get("desktop") === "1";
        return true;
      }},
      ui: {messageParent(message) { window.__parentMessages = (window.__parentMessages || []).concat([message]); },
        displayDialogAsync(url, opts, cb) {
        state.dialogUrl = url; state.dialogOpts = opts;
        if (q.get("dialogfail") === "1") return setTimeout(() => cb(asyncResult(null, {code: 12009, message: "Dialog blocked"})), 0);
        const dialog = {addEventHandler(type, fn) { dialogHandlers[type] = fn; }, close() { state.dialogClosed = true; }};
        setTimeout(() => cb(asyncResult(dialog)), 0);
      }},
      document: {
        get url() { return "file:///fake/" + encodeURIComponent(NAME); },
        settings: {
          get: k => state.meta.settings[k], set: (k, v) => { state.meta.settings[k] = v; }, remove: k => { delete state.meta.settings[k]; },
          saveAsync: cb => { save().then(() => cb && cb(asyncResult(null)), () => cb && cb(asyncResult(null))); },
        },
        getFileAsync(type, opts, cb) {
          const size = (opts && opts.sliceSize) || 4194304, bytes = state.bytes, count = Math.max(1, Math.ceil(bytes.length / size));
          const file = {sliceCount: count, size: bytes.length, closeAsync() {},
            getSliceAsync: (i, cb2) => setTimeout(() => cb2(asyncResult({data: Array.from(bytes.subarray(i * size, (i + 1) * size)), index: i})), 0)};
          setTimeout(() => cb(asyncResult(file)), 0);
        },
      },
    },
    /* Для скриптов проверки: что сейчас в документе и как отвечает диалог. */
    __fake: {state, host: HOST, name: NAME,
      sendDialogMessage: message => dialogHandlers.DialogMessageReceived && dialogHandlers.DialogMessageReceived({message}),
      closeDialogByUser: () => dialogHandlers.DialogEventReceived && dialogHandlers.DialogEventReceived({error: 12006}),
      currentBytes: () => state.bytes},
  };
  window.Office = Office;
  window.Word = {run: wordRun};
  window.Excel = {run: excelRun};
  window.PowerPoint = {run: pptRun};
})();
