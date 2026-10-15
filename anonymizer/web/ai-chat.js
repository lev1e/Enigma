"use strict";
/* Общий чат с ИИ: одна реализация для страницы /ai и для чата с файлами на главной.
   Наружу уходит только текст с метками, который одобрил охранник на сервере; ответ возвращается локально.
   Все запросы идут на тот же адрес (никаких новых источников). */
(function () {
  const H = {"X-Requested-With": "anonymizer", "Content-Type": "application/json"};
  async function api(method, path, body) {
    const r = await fetch(path, {method, headers: H, body: body === undefined ? undefined : JSON.stringify(body)});
    let data = {};
    try { data = await r.json(); } catch (e) { /* empty body */ }
    if (!r.ok) throw new Error(ru(data.error || "Ошибка запроса"));
    return data;
  }
  /* Часть сообщений сервера пока приходит по-английски: показываем по-русски (запрос владельцу Python в s6e-report). */
  const RU = [
    [/^AI is switched off in the settings/, "ИИ выключен в общих настройках. Включите его на странице «Провайдер и ключ»."],
    [/^AI is switched off for this chat/, "ИИ выключен для этого чата. Отметьте «ИИ включён для этого чата»."],
    [/^Stopped$/, "Остановлено."],
    [/^No provider is set up/, "Провайдер не настроен. Откройте «Провайдер и ключ»."],
    [/^No such provider/, "Такого провайдера нет."],
    [/^Write a message first/, "Сначала напишите сообщение."],
    [/^The message is too long/, "Сообщение слишком длинное."],
    [/^A reply is already running/, "Ответ уже идёт. Дождитесь его или нажмите «Остановить»."],
    [/^The attached file is no longer available/, "Прикреплённый файл больше недоступен. Прикрепите его снова."],
    [/^No API key is saved/, "Для провайдера не сохранён ключ."],
    [/^A remote custom endpoint needs an API key/, "Для внешнего адреса нужен ключ."],
    [/^The provider rejected the API key/, "Провайдер не принял ключ (401/403)."],
    [/^The provider's rate or quota limit/, "Достигнут лимит провайдера (429). Повторите позже."],
    [/^The provider did not answer in time|^No answer from the provider in time|^The stream timed out/, "Провайдер не ответил вовремя."],
    [/^Cannot reach the provider/, "Не удалось связаться с провайдером: проверьте сеть и адрес."],
    [/^The secure connection to the provider failed/, "Не удалось установить защищённое соединение с провайдером."],
    [/^The provider reports a server error|^Unexpected answer from the provider|^The provider reported an error/, "Провайдер вернул ошибку. Повторите позже."],
    [/^Не настроен ни один провайдер|^ИИ выключен в настройках/, "Чтобы написать ИИ, подключите провайдера и ключ в настройках. Без этого сообщение никуда не уходит."],
    [/^Sending blocked/, "Отправка остановлена: в тексте нашлись необезличенные данные. Ничего не отправлено."],
    [/^No such chat|^No such reply|^Not found/, "Не найдено."],
  ];
  const NEEDS_PROVIDER = /подключите провайдера/;
  const ru = t => { for (const [re, to] of RU) if (re.test(t)) return to; return t; };
  const CSS = `
.aic-list { list-style: none; margin: 0 auto; padding: 0; display: grid; gap: var(--s5, 24px); width: 100%; max-width: 740px; }
.aic-list:empty { display: none; }
.aic-msg { display: grid; gap: var(--s1, 4px); min-width: 0; }
.aic-msg.user { justify-self: end; max-width: min(85%, 60ch); }
.aic-bubble { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; font-size: var(--fs-md, 15px); }
.aic-msg.user .aic-bubble { padding: var(--s2, 8px) var(--s4, 16px); border-radius: 20px; background: var(--field, #eee); }
.aic-ctx { justify-self: end; color: var(--muted, #666); font-size: var(--fs-xs, 12px); }
.aic-who { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.aic-tools { display: flex; gap: var(--s1, 4px); margin-left: calc(-1 * var(--s2, 8px)); opacity: 0; transition: opacity var(--dur-2, .18s) var(--ease, ease-out); }
.aic-msg:hover .aic-tools, .aic-tools:focus-within, .aic-msg.last .aic-tools { opacity: 1; }
.aic-ib { display: inline-grid; place-items: center; width: 44px; height: 44px; padding: 0; border: 0; border-radius: 12px; background: transparent; color: var(--muted, #666); cursor: pointer; transition: background-color var(--dur-1, .15s) var(--ease, ease-out), color var(--dur-1, .15s) var(--ease, ease-out); }
.aic-ib:hover { background: var(--field, #eee); color: var(--text, inherit); }
.aic-ib svg, .aic-send svg, .aic-plus svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.aic-card { display: flex; align-items: center; gap: var(--s3, 12px); width: min(100%, 420px); min-height: 56px; padding: var(--s2, 8px) var(--s4, 16px) var(--s2, 8px) var(--s3, 12px); border: 1px solid var(--line-strong, #bbb); border-radius: 14px; background: var(--surface, transparent); color: inherit; text-align: left; font: inherit; cursor: pointer; transition: background-color var(--dur-1, .15s) var(--ease, ease-out); }
.aic-card:hover { background: var(--field, #eee); }
.aic-card i { flex: none; display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; background: var(--field, #eee); font: 600 11px/1 var(--sans, sans-serif); font-style: normal; letter-spacing: .02em; color: var(--text, inherit); }
.aic-card span { display: grid; min-width: 0; } .aic-card b { font-weight: 600; font-size: var(--fs-md, 14px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .aic-card small { color: var(--muted, #666); font-size: var(--fs-xs, 12px); }
.aic-empty { margin: 0 auto; padding: var(--s6, 32px) 0 var(--s4, 16px); width: 100%; max-width: 740px; display: grid; gap: var(--s4, 16px); }
.aic-empty[hidden] { display: none; }
.aic-empty h3 { margin: 0; font-size: var(--fs-xl, 22px); font-weight: 600; letter-spacing: -.01em; }
.aic-empty p { margin: 0; color: var(--muted, #666); max-width: 56ch; font-size: var(--fs-sm, 13px); }
.aic-ex { display: grid; gap: var(--s2, 8px); grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.aic-ex button { min-height: 44px; padding: var(--s2, 8px) var(--s4, 16px); border: 1px solid var(--line, #ddd); border-radius: 14px; background: transparent; color: var(--text, inherit); text-align: left; font: inherit; font-size: var(--fs-sm, 13px); cursor: pointer; transition: background-color var(--dur-1, .15s) var(--ease, ease-out); }
.aic-ex button:hover { background: var(--field, #eee); }
.aic-box { display: grid; gap: var(--s2, 8px); width: 100%; max-width: 740px; margin: 0 auto; }
.aic-pill { position: relative; display: grid; grid-template-columns: 44px minmax(0, 1fr) 44px; align-items: end; gap: var(--s1, 4px); padding: 4px; border: 1px solid var(--field-line, #999); border-radius: 28px; background: var(--surface, transparent); }
.aic-pill:focus-within { outline: 2px solid var(--accent, #36c); outline-offset: 2px; }
.aic-text { width: 100%; min-height: 44px; max-height: calc(6 * 1.5em + 20px); resize: none; padding: 10px var(--s2, 8px); background: transparent; border: 0; outline: 0; line-height: 1.5; font: inherit; color: inherit; overflow-y: auto; }
.aic-plus, .aic-send { display: grid; place-items: center; width: 44px; height: 44px; padding: 0; border: 0; border-radius: 50%; cursor: pointer; }
.aic-plus { background: transparent; color: var(--muted, #666); transition: background-color var(--dur-1, .15s) var(--ease, ease-out), color var(--dur-1, .15s) var(--ease, ease-out); }
.aic-plus:hover, .aic-plus[aria-expanded="true"] { background: var(--field, #eee); color: var(--text, inherit); }
.aic-send { position: relative; background: var(--text, #111); color: var(--bg, #fafafa); transition: opacity var(--dur-2, .18s) var(--ease, ease-out); }
.aic-send:disabled { opacity: .35; cursor: default; }
.aic-send svg { position: absolute; transition: opacity var(--dur-2, .18s) var(--ease, ease-out), transform var(--dur-2, .18s) var(--ease, ease-out); }
.aic-send .i-stop { opacity: 0; transform: scale(.6); } .aic-send.busy .i-go { opacity: 0; transform: scale(.6); } .aic-send.busy .i-stop { opacity: 1; transform: none; }
.aic-send .i-stop { fill: currentColor; }
.aic-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--s2, 8px); min-width: 0; }
.aic-foot[hidden] { display: none; }
.mi-sel { display: grid; gap: 4px; padding: 4px 12px 8px; }
.mi-sel .mh { margin: 0; padding: 0; }
.mi-sel .aic-model { max-width: 100%; border: 1px solid var(--line, #ccc); }
.aic-model { max-width: 55%; min-height: 44px; padding: 0 var(--s2, 8px); border: 0; border-radius: 12px; background: transparent; color: var(--muted, #666); font: inherit; font-size: var(--fs-xs, 12px); cursor: pointer; text-overflow: ellipsis; }
.aic-model:hover { background: var(--field, #eee); color: var(--text, inherit); }
.aic-menu .mi.sub { padding-left: 42px; color: var(--muted, #666); }
.aic-status.warn { color: var(--text, inherit); }
@media (max-width: 480px) { .aic-foot .aic-hint { display: none; } .aic-model { max-width: 100%; } }
.aic-hint { margin: 0; text-align: right; font-size: var(--fs-xs, 12px); color: var(--muted, #666); }
.aic-chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--s2, 8px); }
.aic-chips:empty { display: none; }
.aic-chip { display: inline-flex; gap: var(--s1, 4px); align-items: center; max-width: 100%; padding: 0 0 0 var(--s3, 12px); border: 1px solid var(--line-strong, #bbb); border-radius: 999px; font-size: var(--fs-sm, 13px); }
.aic-chip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.aic-chip button { display: grid; place-items: center; width: 44px; height: 44px; margin-block: -6px; border: 0; background: transparent; color: var(--muted, #666); border-radius: 999px; cursor: pointer; font-size: 18px; line-height: 1; }
.aic-chip button:hover { color: var(--text, inherit); }
.aic-menu { position: fixed; z-index: 50; min-width: 260px; max-width: min(360px, calc(100vw - 24px)); max-height: 60dvh; overflow: auto; padding: var(--s2, 8px); border: 1px solid var(--line-strong, #bbb); border-radius: 16px; background: var(--surface, #fafafa); box-shadow: 0 8px 32px color-mix(in oklab, var(--text, #111) 14%, transparent); transform-origin: bottom left; }
.aic-menu[hidden] { display: none; }
.aic-menu .mi { display: flex; align-items: center; gap: var(--s3, 12px); width: 100%; min-height: 44px; padding: 0 var(--s3, 12px); border: 0; border-radius: 10px; background: transparent; color: inherit; text-align: left; font: inherit; font-size: var(--fs-sm, 13px); cursor: pointer; }
.aic-menu .mi:hover, .aic-menu .mi:focus-visible { background: var(--field, #eee); }
.aic-menu .mi[aria-disabled="true"] { color: var(--faint, #888); cursor: default; }
.aic-menu .mi .ck { flex: none; width: 18px; height: 18px; display: grid; place-items: center; border: 1.5px solid var(--field-line, #999); border-radius: 5px; font-size: 12px; line-height: 1; }
.aic-menu .mi[aria-checked="true"] .ck::after { content: ""; width: 5px; height: 9px; margin-top: -2px; border: solid currentColor; border-width: 0 2px 2px 0; transform: rotate(45deg); }
.aic-menu .mi[aria-checked="true"] .ck { background: var(--text, #111); border-color: var(--text, #111); color: var(--bg, #fafafa); }
.aic-menu .mi .nm { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aic-menu .mh { margin: var(--s2, 8px) var(--s3, 12px) var(--s1, 4px); font-size: var(--fs-xs, 12px); color: var(--muted, #666); }
.aic-menu hr { border: 0; border-top: 1px solid var(--line, #ddd); margin: var(--s2, 8px) 0; }
.aic-status { margin: 0; font-size: var(--fs-sm, 13px); color: var(--muted, #666); text-align: center; }
.aic-status:empty { display: none; }
.aic-status.err { color: var(--error, #b00); } .aic-status.ok { color: var(--muted, #666); }
.aic-finds { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--s2, 8px); }
.aic-find { display: flex; flex-wrap: wrap; gap: var(--s2, 8px); align-items: center; padding: var(--s2, 8px) var(--s3, 12px); border: 1px solid var(--line-strong, #bbb); border-radius: var(--r-block, 8px); font-size: var(--fs-sm, 13px); }
.aic-find .btn { min-height: 44px; }
.aic-dry { font: var(--fs-sm, 13px)/1.45 var(--mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; margin: 0; }
.aic-dots { display: inline-flex; gap: 5px; padding: 8px 0; } .aic-dots i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted, #666); opacity: .35; }
.aic-prop { display: grid; gap: var(--s2, 8px); max-width: min(100%, 560px); }
.aic-pc { display: grid; gap: var(--s1, 4px); padding: var(--s3, 12px); border: 1px solid var(--line, #ddd); border-radius: 14px; background: var(--surface, transparent); }
.aic-pc small { color: var(--muted, #666); font-size: var(--fs-xs, 12px); }
.aic-pc .was { color: var(--muted, #666); text-decoration: line-through; overflow-wrap: anywhere; white-space: pre-wrap; }
.aic-pc .now { overflow-wrap: anywhere; white-space: pre-wrap; }
.aic-pc .arr { color: var(--muted, #666); font-size: var(--fs-xs, 12px); }
.aic-pa { display: flex; flex-wrap: wrap; gap: var(--s2, 8px); }
.aic-pa .btn { min-height: 44px; }
.aic-qnote { margin: 0; color: var(--muted, #666); font-size: var(--fs-sm, 13px); overflow-wrap: anywhere; }
.aic-sel { border-style: dashed; }
@media (prefers-reduced-motion: no-preference) {
  .aic-prop > * { animation: aic-in var(--dur-2, .18s) var(--ease, ease-out) both; }
  .aic-msg { animation: aic-in var(--dur-3, .24s) var(--ease, ease-out) both; }
  .aic-menu:not([hidden]) { animation: aic-pop var(--dur-2, .18s) var(--ease, ease-out) both; }
  .aic-dots i { animation: aic-dot 1.1s var(--ease, ease-out) infinite; } .aic-dots i:nth-child(2) { animation-delay: .15s; } .aic-dots i:nth-child(3) { animation-delay: .3s; }
}
@media (prefers-reduced-motion: reduce) { .aic-msg, .aic-prop > *, .aic-menu, .aic-dots i, .aic-send svg, .aic-tools { animation: none; transition: none; } .aic-dots i { opacity: .7; } }
@media (pointer: coarse) { .aic-tools { opacity: 1; } }
@keyframes aic-in { from { opacity: 0; transform: translateY(6px); } }
@keyframes aic-pop { from { opacity: 0; transform: translateY(6px) scale(.98); } }
@keyframes aic-dot { 0%, 80%, 100% { opacity: .3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-3px); } }
`;
  const ICON = {
    plus: "M12 5v14M5 12h14", opts: "M4 7h9M17 7h3M4 17h3M11 17h9M15 4v6M9 14v6", up: "M12 19V5M5 12l7-7 7 7", copy: "M9 9h10v11H9zM5 15V4h10", down: "M12 4v12M6 11l6 6 6-6M5 20h14",
  };
  function svg(d, cls) { const n = "http:" + "//www.w3.org/2000/svg", s = document.createElementNS(n, "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); if (cls) s.setAttribute("class", cls); const p = document.createElementNS(n, "path"); p.setAttribute("d", d); s.append(p); return s; }
  const EXAMPLES = ["Перескажи файл в пяти пунктах", "Найди в тексте опечатки и неточности", "Поправь пункт 3: срок оплаты 30 дней"];
  const extOf = n => { const m = /\.([A-Za-z0-9]{1,5})$/.exec(n || ""); return m ? m[1].toUpperCase() : "ФАЙЛ"; };
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }

  /* mount({list, composer, onChange, getFiles, openFile}): list и composer это два контейнера (на /ai они рядом, на главной список в ленте, а поле в закреплённой панели).
     getFiles() возвращает файлы чата [{id, name}] с обезличенной версией: из них пользователь выбирает, с какими работает следующее сообщение. */
  function mount(opts) {
    if (!document.getElementById("aic-style")) { const s = el("style"); s.id = "aic-style"; s.textContent = CSS; document.head.append(s); }
    const S = {chat: "", run: "", files: [], off: new Set(), resolve: {anonymize: [], allow: []}, busy: false, ai: false, last: null, prov: [], choice: {provider: "", model: ""}, src: {}, confirm: "", sel: {file: "", items: []}};
    const list = el("ol", "aic-list"); list.setAttribute("aria-label", "Сообщения ИИ-чата");
    const empty = el("div", "aic-empty"); empty.append(el("h3", "", "Чем помочь с файлами?"), el("p", "", "Провайдеру уходит только текст с метками, исходные данные остаются здесь. Правка файла появится новой версией."));
    const ex = el("div", "aic-ex"); ex.setAttribute("role", "group"); ex.setAttribute("aria-label", "Примеры запросов");
    for (const t of EXAMPLES) { const b = el("button", "", t); b.type = "button"; b.onclick = () => { ta.value = t; fit(); ta.focus(); }; ex.append(b); }
    empty.append(ex);
    empty.hidden = true;   // U1: examples are not shown; the bar appears only after a result
    opts.list.replaceChildren(list, empty);

    const box = el("div", "aic-box"); box.setAttribute("role", "group"); box.setAttribute("aria-label", "Спросить ИИ про эти файлы");
    const status = el("p", "aic-status"); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const report = el("p", "aic-status"); report.setAttribute("aria-live", "polite");
    const chips = el("ul", "aic-chips"); chips.setAttribute("aria-label", "Файлы для следующего сообщения");
    const finds = el("ul", "aic-finds"); finds.setAttribute("aria-label", "Найденные данные");
    const dryBox = el("details"); dryBox.hidden = true;
    const dryS = el("summary", "", "Запрос, который уйдёт провайдеру"); const dry = el("pre", "aic-dry"); dryBox.append(dryS, dry);
    const pill = el("div", "aic-pill");
    const bPlus = el("button", "aic-plus"); bPlus.type = "button"; bPlus.append(svg(ICON.opts)); bPlus.setAttribute("aria-label", "Параметры"); bPlus.setAttribute("aria-haspopup", "menu"); bPlus.setAttribute("aria-expanded", "false"); bPlus.title = "Параметры: модель, файлы, версия";
    const ta = el("textarea", "aic-text"); ta.rows = 1; ta.maxLength = 60000; const phq = window.matchMedia ? window.matchMedia("(max-width: 480px)") : null; const phset = () => { ta.placeholder = phq && phq.matches ? "Спросить ИИ" : "Спросить ИИ про эти файлы"; }; phset(); if (phq && phq.addEventListener) phq.addEventListener("change", phset); ta.setAttribute("aria-label", "Сообщение ИИ"); ta.setAttribute("aria-keyshortcuts", "Enter Shift+Enter"); ta.title = "Enter отправляет, Shift+Enter переносит строку";
    const bSend = el("button", "aic-send"); bSend.type = "button"; bSend.setAttribute("aria-label", "Отправить"); bSend.title = "Отправить"; bSend.append(svg(ICON.up, "i-go"), svg("M7 7h10v10H7z", "i-stop"));
    pill.append(bPlus, ta, bSend);
    const hint = el("p", "aic-hint", "ИИ может ошибаться. Проверяйте важное.");
    const pick = el("select", "aic-model"); pick.setAttribute("aria-label", "Модель ИИ"); pick.title = "Модель для следующих сообщений"; pick.hidden = true;
    const foot = el("div", "aic-foot"); foot.hidden = true; foot.append(pick, hint);
    const file = el("input"); file.type = "file"; file.hidden = true; file.accept = ".txt,.md,.csv,.docx,.xlsx,.pptx,.pdf";
    const menu = el("div", "aic-menu"); menu.setAttribute("role", "menu"); menu.setAttribute("aria-label", "Параметры"); menu.hidden = true;
    box.append(chips, finds, dryBox, pill, foot, status, report, file, menu);
    opts.composer.replaceChildren(box);

    const say = (t, c) => {
      const msg = ru(t || ""); status.textContent = msg; status.className = "aic-status" + (c ? " " + c : "");
      if (NEEDS_PROVIDER.test(msg)) { const a = el("a", "", " Открыть настройки провайдера"); a.href = providerHref(); a.style.padding = "12px 4px"; status.append(a); }
    };
    const provOf = id => S.prov.find(p => p.id === id);
    function renderPick() {
      pick.replaceChildren();
      for (const p of S.prov) {
        const g = document.createElement("optgroup"); g.label = p.name + " · " + p.badge;
        for (const m of (p.models && p.models.length ? p.models : [p.model || ""])) { const o = new Option(m || "модель по умолчанию", p.id + "|" + m); g.append(o); }
        pick.append(g);
      }
      const want = S.choice.provider + "|" + S.choice.model, o = [...pick.options].find(x => x.value === want);
      if (o) pick.value = want; else if (pick.options.length) { const f = pick.options[0]; pick.value = f.value; const i = f.value.indexOf("|"); S.choice = {provider: f.value.slice(0, i), model: f.value.slice(i + 1)}; }
      pick.hidden = !S.prov.length; foot.hidden = true;
    }
    async function loadProv() {
      try { const d = await api("GET", "/api/ai/providers"); S.prov = (d.items || []).filter(p => p.saved || p.local); S.cfg = S.prov.length > 0 && d.enabled !== false; } catch (e) { S.prov = []; S.cfg = false; }
      renderPick(); sync();
    }
    pick.onchange = guard0(async () => {
      const i = pick.value.indexOf("|"); S.choice = {provider: pick.value.slice(0, i), model: pick.value.slice(i + 1)}; S.confirm = "";
      if (S.chat) await api("POST", "/api/ai/chats/" + S.chat + "/choice", S.choice);
    });
    function guard0(fn) { return async () => { try { await fn(); } catch (e) { say(e.message, "err"); } }; }
    let provHref = "/ai"; const providerHref = () => provHref;
    const fit = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, Math.round(6 * 24 + 20)) + "px"; };
    const scrollEnd = () => { if (list.lastElementChild) list.lastElementChild.scrollIntoView({block: "end"}); };
    const resetAsk = () => { finds.replaceChildren(); dryBox.hidden = true; report.textContent = ""; S.resolve = {anonymize: [], allow: []}; };
    const setBusy = on => {
      S.busy = on; bSend.classList.toggle("busy", on); ta.readOnly = on;
      bSend.setAttribute("aria-label", on ? "Остановить" : "Отправить"); bSend.title = on ? "Остановить" : "Отправить";
    };
    const chatFiles = () => { try { return (opts.getFiles ? opts.getFiles() : []) || []; } catch (e) { return []; } };
    const picked = () => chatFiles().filter(f => !S.off.has(f.id));

    function mark() { list.querySelectorAll(".aic-msg.last").forEach(n => n.classList.remove("last")); const l = [...list.querySelectorAll(".aic-msg.ai")].pop(); if (l) l.classList.add("last"); }
    const PATCH_FENCE = /`{3}(?:json|JSON)?[ \t]*\r?\n\s*\{\s*"v"[\s\S]*?(?:`{3}|$)/g;      // служебный патч правки: пользователю его не показываем, вместо него карточки
    const noPatch = t => String(t).replace(PATCH_FENCE, "").replace(/\n{3,}/g, "\n\n").trim();
    function addMsg(role, text, index, mode) {
      const li = el("li", "aic-msg " + (role === "user" ? "user" : "ai"));
      li.append(el("span", "aic-who", role === "user" ? "Вы" : "ИИ (значения возвращены локально)"));
      let ctx = 0, shownUser = text;
      if (role === "user") { const m = /\n*\[Файл \d+\]/.exec(String(text)); if (m) { shownUser = String(text).slice(0, m.index); ctx = (String(text).match(/\[Файл \d+\]/g) || []).length; } }
      const shown = role === "user" ? shownUser : noPatch(text).replace(/<<<ФАЙЛ>>>[\s\S]*?(<<<КОНЕЦ>>>|$)/, "[Текст файла скрыт: правка сохраняется отдельной версией файла]");
      const body = el("div", "aic-bubble", shown); li.append(body);
      if (ctx) li.append(el("small", "aic-ctx", "С файлами: " + ctx + (mode === "orig" ? " (исходные данные)" : " (текст с метками; полный запрос в меню «+»)")));
      if (mode === "orig" && !ctx) li.append(el("small", "aic-ctx", "Исходные данные"));
      if (role !== "user") li.append(tools(body, index));
      list.append(li); empty.hidden = true; mark(); return body;
    }
    function tools(body, index) {
      const t = el("div", "aic-tools"); t.setAttribute("role", "group"); t.setAttribute("aria-label", "Действия с ответом");
      const c = el("button", "aic-ib"); c.type = "button"; c.append(svg(ICON.copy)); c.setAttribute("aria-label", "Копировать ответ"); c.title = "Копировать ответ";
      c.onclick = async () => { try { await navigator.clipboard.writeText(body.textContent); say("Ответ скопирован.", "ok"); } catch (e) { say("Не удалось скопировать: выделите текст вручную.", "err"); } };
      t.append(c);
      if (index !== undefined) {
        const b = el("button", "aic-ib aic-save"); b.type = "button"; b.append(svg(ICON.down)); b.setAttribute("aria-label", "Сохранить ответ с возвратом значений"); b.title = "Сохранить ответ с возвратом значений";
        b.onclick = async () => { try { await saveAnswer(index, false, b); } catch (e) { say(e.message, "err"); } };
        t.append(b);
      }
      return t;
    }
    function fileCard(msgBody, e) {
      const c = el("button", "aic-card"); c.type = "button"; c.setAttribute("aria-label", "Открыть просмотр: " + e.name);
      const sp = el("span"); sp.append(el("b", "", e.name), el("small", "", "Новая версия, " + extOf(e.name)));
      c.append(el("i", "", extOf(e.name).slice(0, 4)), sp);
      c.onclick = () => { if (opts.openFile) opts.openFile(e.file); };
      msgBody.parentElement.insertBefore(c, msgBody.parentElement.querySelector(".aic-tools"));
    }
    async function saveAnswer(index, accept, btn) {
      const r = await fetch("/api/ai/chats/" + S.chat + "/export", {method: "POST", headers: H, body: JSON.stringify({index, accept_damaged: accept})});
      if ((r.headers.get("Content-Type") || "").startsWith("application/json")) {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "Ошибка запроса");
        if (d.needs_confirm) {
          const rep = d.report, bad = Object.keys(rep.unknown).length + Object.keys(rep.removed).length + rep.damaged_but_restored;
          say("В ответе искажённых или неизвестных меток: " + bad + ". Они не угаданы и останутся в файле как есть. Нажмите ещё раз, чтобы сохранить так.", "err");
          btn.onclick = async () => { try { await saveAnswer(index, true, btn); } catch (e) { say(e.message, "err"); } };
          return;
        }
      }
      if (!r.ok) throw new Error("Ошибка запроса");
      const blob = await r.blob(), a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "ai-answer-" + (index + 1) + ".txt"; document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      say("Ответ сохранён: значения возвращены на этом компьютере.", "ok");
    }
    /* Чипы: файлы чата, с которыми работает следующее сообщение (крестик убирает из выбора), и вложения этого сообщения. */
    function sync() { const on = !!S.cfg && chatFiles().length > 0; opts.composer.hidden = !on; box.hidden = !on; if (!on) closeMenu(true); }
    function renderChips() {
      chips.replaceChildren(); sync();
      const mk = (label, aria, onx) => {
        const li = el("li", "aic-chip"); li.append(el("span", "", label));
        const x = el("button", "", "×"); x.type = "button"; x.setAttribute("aria-label", aria); x.title = "Убрать";
        x.onclick = onx; li.append(x); chips.append(li);
      };
      if (chatFiles().length > 1) picked().forEach(f => mk(f.name + (S.src[f.id] === "original" ? " · исходный" : ""), "Не использовать файл " + f.name, () => { S.off.add(f.id); renderChips(); bPlus.focus(); }));
      if (S.sel.items.length) {
        const n = S.sel.items.length, first = S.sel.items[0].label;
        mk("Выделено: " + (n === 1 ? first : n + " " + (n % 10 === 1 && n % 100 !== 11 ? "элемент" : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "элемента" : "элементов")) + ", " + first + " и др."), "Снять выделение", () => { clearSel(); ta.focus(); });
        chips.lastElementChild.classList.add("aic-sel");
      }
      S.files.forEach((f, i) => mk(f.name + " (" + f.chars + " зн.)", "Убрать файл " + f.name, () => { S.files.splice(i, 1); renderChips(); bPlus.focus(); }));
    }
    function clearSel() { S.sel = {file: "", items: []}; if (opts.onClearSelection) opts.onClearSelection(); renderChips(); }
    /* Меню «+»: файлы чата с галочками, вложение с компьютера, показать запрос, очистить беседу, ИИ вкл/выкл, настройки провайдера. */
    let items = [];
    function item(label, role, onclick, extra) {
      const b = el("button", "mi"); b.type = "button"; b.setAttribute("role", role || "menuitem"); b.tabIndex = -1;
      if (role === "menuitemcheckbox") { const ck = el("span", "ck"); ck.setAttribute("aria-hidden", "true"); b.append(ck); b.setAttribute("aria-checked", String(!!extra)); }
      b.append(el("span", "nm", label)); b.onclick = onclick; menu.append(b); return b;
    }
    function buildMenu() {
      menu.replaceChildren();
      if (S.prov.length) { const w = el("div", "mi-sel"); w.append(el("label", "mh", "Модель"), pick); pick.hidden = false; menu.append(w); }
      const fs = chatFiles();
      item("Прикрепить файл", "menuitem", () => { closeMenu(true); file.click(); });
      if (fs.length) {
        menu.append(el("p", "mh", "С какими файлами работаем"));
        for (const f of fs) {
          const on = !S.off.has(f.id);
          const it = item(f.name, "menuitemcheckbox", () => { if (S.off.has(f.id)) S.off.delete(f.id); else S.off.add(f.id); renderChips(); buildMenu(); const n = [...menu.querySelectorAll(".mi")].find(x => x.dataset.fid === f.id); if (n) n.focus(); }, on);
          it.dataset.fid = f.id; it.title = f.name;
          if (on) {
            const o = S.src[f.id] === "original";
            const sb = item("Версия: " + (o ? "Исходный" : "Обезличенный"), "menuitem", () => { if (o) delete S.src[f.id]; else S.src[f.id] = "original"; S.confirm = ""; renderChips(); buildMenu(); const n = [...menu.querySelectorAll(".mi")].find(x => x.dataset.sid === f.id); if (n) n.focus(); });
            sb.dataset.sid = f.id; sb.classList.add("sub"); sb.title = "Какая версия файла уходит модели";
          }
        }
      }
      menu.append(document.createElement("hr"));
      const dis = b => { b.setAttribute("aria-disabled", "true"); };
      const bd = item("Показать запрос, который уйдёт провайдеру", "menuitem", () => { if (!S.chat) return; closeMenu(true); guard(() => ask(false))(); });
      const bc = item("Очистить беседу", "menuitem", () => { if (!S.chat) return; closeMenu(true); guard(async () => { await api("DELETE", "/api/ai/chats/" + S.chat + "/history"); await load(); })(); });
      if (!S.chat) { dis(bd); dis(bc); }
      const ai = item("ИИ включён для этого чата", "menuitemcheckbox", () => { if (!S.chat) return; guard(async () => { S.ai = !S.ai; await api("POST", "/api/ai/chats/" + S.chat + "/toggle", {on: S.ai}); buildMenu(); const n = menu.querySelector("[data-ai]"); if (n) n.focus(); })(); }, S.ai);
      ai.dataset.ai = "1"; if (!S.chat) dis(ai);
      const cfg = item("Провайдер и ключ", "menuitem", () => { location.href = provHref; });
      menu.append(el("p", "mh", "ИИ может ошибаться. Проверяйте важное."));
      items = [...menu.querySelectorAll(".mi")];
    }
    function openMenu() {
      buildMenu(); menu.hidden = false; bPlus.setAttribute("aria-expanded", "true");
      const r = bPlus.getBoundingClientRect(), mh = menu.offsetHeight;
      menu.style.left = Math.max(12, Math.min(r.left, window.innerWidth - menu.offsetWidth - 12)) + "px";
      menu.style.top = Math.max(12, r.top - mh - 8) + "px";
      items[0].focus();
    }
    function closeMenu(noFocus) { if (menu.hidden) return; menu.hidden = true; bPlus.setAttribute("aria-expanded", "false"); if (!noFocus) bPlus.focus(); }
    bPlus.onclick = () => { if (menu.hidden) openMenu(); else closeMenu(); };
    menu.addEventListener("keydown", e => {
      const i = items.indexOf(document.activeElement);
      if (document.activeElement === pick) { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMenu(); } return; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMenu(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
      else if (e.key === "Tab") closeMenu(true);
    });
    document.addEventListener("pointerdown", e => { if (!menu.hidden && !menu.contains(e.target) && !bPlus.contains(e.target)) closeMenu(true); });
    window.addEventListener("resize", () => closeMenu(true));
    document.addEventListener("scroll", e => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(true); }, true);

    let loading = Promise.resolve();
    async function need() {
      if (S.chat) return true;
      if (!opts.ensureChat) { say("Сначала добавьте файл или откройте чат.", "err"); return false; }
      S.chat = await opts.ensureChat(); await loading;
      return !!S.chat;
    }
    async function load() {
      if (!S.chat) { list.replaceChildren(); empty.hidden = true; S.ai = false; renderChips(); return; }
      const id = S.chat;
      const d = await api("GET", "/api/ai/chats/" + id);
      if (id !== S.chat) return;
      S.ai = !!d.ai; if (d.choice && d.choice.provider) S.choice = d.choice; renderPick();
      list.replaceChildren(); d.messages.forEach((m, i) => addMsg(m.role, m.text, i, m.mode)); empty.hidden = true;
      S.files = []; renderChips(); resetAsk(); renderProposals(d.proposals || []); scrollEnd();
    }
    /* P2D: карточки предложенных правок под последним ответом ИИ. Ничего не меняется, пока не нажато «Применить». */
    function renderProposals(props) {
      list.querySelectorAll(".aic-prop").forEach(n => n.remove());
      const last = [...list.querySelectorAll(".aic-msg.ai")].pop();
      if (!last) return;
      for (const pr of props) {
        const box = el("div", "aic-prop"); box.setAttribute("role", "group"); box.setAttribute("aria-label", "Предложенные правки");
        const items = pr.items || [], done = new Set(pr.done || []);
        const pending = () => items.map((it, i) => i).filter(i => !items[i].comment && !done.has(i));
        const act = async (action, ops, btn) => {
          box.querySelectorAll("button").forEach(b => { b.disabled = true; });
          try {
            const r = await api("POST", "/api/ai/chats/" + S.chat + "/patch", {id: pr.id, action, ops});
            if (action === "reject") { (ops === "all" ? pending() : ops).forEach(i => done.add(i)); say("Правки отклонены. Файл не менялся.", "ok"); }
            else if (!r.ok) { say(r.reason || "Правки не применены. Файл остался прежним.", "err"); }
            else {
              const left = new Set(r.left || []); items.forEach((it, i) => { if (!it.comment && !left.has(i)) done.add(i); });
              say(r.note || "Правки применены: создана новая версия файла.", "ok");
              if (opts.onEdit) opts.onEdit({applied: true, file: r.file, name: r.name, source: r.source, hint: r.hint});
              if (r.file) { const c = el("button", "aic-card"); c.type = "button"; c.setAttribute("aria-label", "Открыть просмотр: " + r.name);
                const sp = el("span"); sp.append(el("b", "", r.name), el("small", "", "Новая версия")); c.append(el("i", "", extOf(r.name).slice(0, 4)), sp);
                c.onclick = () => { if (opts.openFile) opts.openFile(r.file); }; box.before(c); }
            }
          } catch (e) { say(e.message, "err"); }
          draw(true);
        };
        const draw = keepFocus => {
          box.replaceChildren();
          const todo = pending();
          items.forEach((it, i) => {
            if (it.comment) {
              if (!done.has(i)) box.append(el("p", "aic-qnote", (it.at ? it.at + ": " : "") + (it.now || it.text || "")));
              return;
            }
            if (done.has(i)) return;
            const c = el("div", "aic-pc"), txt = String(it.text || ""), cut = txt.indexOf(": было");
            c.append(el("small", "", cut > 0 ? txt.slice(0, cut) : (it.at || "")));
            if (it.was != null || it.now != null) {
              c.append(el("div", "was", it.was == null ? "(нет)" : String(it.was)), el("div", "arr", "стало"), el("div", "now", it.now == null ? "(удалено)" : String(it.now)));
            } else c.append(el("div", "now", txt));
            const a = el("div", "aic-pa"), ok = el("button", "btn", "Применить"), no = el("button", "btn", "Отклонить");
            ok.type = no.type = "button";
            ok.setAttribute("aria-label", "Применить правку: " + (cut > 0 ? txt.slice(0, cut) : it.at || (i + 1)));
            no.setAttribute("aria-label", "Отклонить правку: " + (cut > 0 ? txt.slice(0, cut) : it.at || (i + 1)));
            ok.onclick = () => act("apply", [i], ok); no.onclick = () => act("reject", [i], no);
            a.append(ok, no); c.append(a); box.append(c);
          });
          if (todo.length > 1) {
            const a = el("div", "aic-pa"), all = el("button", "btn main", "Применить все"), none = el("button", "btn", "Отклонить");
            all.type = none.type = "button"; all.onclick = () => act("apply", "all", all); none.onclick = () => act("reject", "all", none);
            a.append(all, none); box.append(a);
          }
          box.hidden = !box.childElementCount;
        };
        draw(); last.insertBefore(box, last.querySelector(".aic-tools"));
        if (!box.hidden) say("Предложено правок: " + pending().length + ". Ниже карточки.", "ok");
      }
    }
    function renderFindings(res, again) {
      finds.replaceChildren();
      for (const f of res.findings) {
        const li = el("li", "aic-find"); li.append(el("q", "", res.anonymized.slice(f.start, f.end)), el("span", "", f.possible ? "возможные данные" : "точные данные"));
        const a = el("button", "btn", "Обезличить"); a.type = "button"; a.onclick = () => { S.resolve.anonymize.push(f.id); again ? (a.disabled = true, say("Отмечено. Нажмите «Отправить» ещё раз.", "ok")) : ask(true).catch(e => say(e.message, "err")); }; li.append(a);
        if (f.possible) { const b = el("button", "btn", "Разрешить один раз"); b.type = "button"; b.onclick = () => { S.resolve.allow.push(f.id); again ? (b.disabled = true, say("Разрешено один раз. Нажмите «Отправить» ещё раз.", "ok")) : ask(true).catch(e => say(e.message, "err")); }; li.append(b); }
        finds.append(li);
      }
      if (res.other_findings) finds.append(el("li", "aic-status", "В истории беседы найдено ещё данных: " + res.other_findings + ". Очистите беседу."));
    }
    function fileIds() { return opts.getFiles ? picked().map(f => f.id) : undefined; }
    function extra() {
      const o = {provider: S.choice.provider, model: S.choice.model}, ids = fileIds();
      if (ids) { o.with_files = true; o.file_ids = ids; const src = {}; for (const i of ids) if (S.src[i] === "original") src[i] = "original"; o.sources = src; }
      return o;
    }
    async function ask(keep) {
      if (!keep) S.resolve = {anonymize: [], allow: []};
      const res = await api("POST", "/api/ai/chats/" + S.chat + "/prepare", Object.assign({text: ta.value, resolve: S.resolve, attachments: S.files.map(f => f.id)}, extra()));
      dry.textContent = JSON.stringify(res.dry_run, null, 2); dryBox.hidden = false; renderFindings(res);
      if (res.blocked) say(res.message, "err"); else say("Запрос чистый. Ключ в запрос не входит.", "ok");
      return res;
    }
    async function send() {
      const text = ta.value; if (!text.trim() || S.busy) return;
      say("");
      if (!S.chat) {          // пустой чат: сначала проверяем, что провайдер вообще подключён, чтобы не плодить пустые чаты
        const st = await api("GET", "/api/ai/providers").catch(() => ({}));
        if (!st.enabled || !(st.items || []).some(p => p.saved || p.local)) { say("Не настроен ни один провайдер", "err"); return; }
        if (!(await need())) return;
      }
      if (!S.ai) { await api("POST", "/api/ai/chats/" + S.chat + "/toggle", {on: true}); S.ai = true; }   // отправка в этом поле и есть включение
      const body = Object.assign({text, resolve: S.resolve, attachments: S.files.map(f => f.id), with_files: true}, extra());
      if (body.file_ids === undefined && opts.getFiles) body.file_ids = [];
      if (S.sel.items.length && S.sel.file) { body.selected = S.sel.items.map(x => x.addr); body.selected_file = S.sel.file; }
      const sig = JSON.stringify([text, body.provider, body.model, body.file_ids, body.sources, body.attachments, body.selected]);
      if (S.confirm === sig) body.confirm_originals = true;
      const res = await api("POST", "/api/ai/chats/" + S.chat + "/send", body);
      if (res.needs_confirm_originals) {   // тихое уведомление в одну строку: Enter подтверждает
        const n = res.notice || {}; S.confirm = sig;
        say("Отправляются исходные данные: " + (n.provider || "провайдер") + " (" + (n.badge || "") + "). Enter — отправить." + (n.secrets_removed ? " Пароли и ключи убраны: " + n.secrets_removed + "." : ""), "warn");
        return;
      }
      S.confirm = "";
      if (res.blocked) { renderFindings(res, true); say(res.message || "Отправка остановлена.", "err"); return; }
      ta.value = ""; fit(); resetAsk(); S.files = []; if (S.sel.items.length) clearSel(); else renderChips();
      addMsg("user", text, undefined, res.mode === "original" ? "orig" : undefined); const out = addMsg("ai", ""); out.textContent = ""; const dots = el("span", "aic-dots"); dots.setAttribute("aria-hidden", "true"); dots.append(el("i"), el("i"), el("i")); out.append(dots); scrollEnd();
      say("ИИ отвечает.");
      S.run = res.run; setBusy(true); let first = true;
      const put = t => { if (first) { out.textContent = ""; first = false; } out.textContent += t; };
      try {
        const fin = p => {
          if (p.edit && (p.edit.proposal || p.edit.note)) out.textContent = noPatch(out.textContent);
          if (p.error) say(p.error, "err");
          else if (p.edit && p.edit.note) { say(p.edit.note, p.edit.applied || p.edit.proposal ? "ok" : "err"); if (!p.edit.applied && !p.edit.proposal) S.noteAfter = p.edit.note; if (p.edit.applied) { fileCard(out, p.edit); if (opts.onEdit) opts.onEdit(p.edit); } }
          else if (res.note) say(res.note, "err");
          else say("Ответ ИИ получен.", "ok");
          const r = p.report;
          if (r && r.damaged) report.textContent = "Модель исказила метки: не найдено " + Object.keys(r.unknown).length + ", восстановлено с поправкой " + r.damaged_but_restored + ", удалено " + Object.keys(r.removed).length + ".";
        };
        const streamed = await new Promise(resolve => {
          if (!window.EventSource) return resolve(false);
          const es = new EventSource("/api/ai/runs/" + res.run + "/events");
          es.addEventListener("delta", e => { put(JSON.parse(e.data).text); scrollEnd(); });
          es.addEventListener("done", e => { es.close(); fin(JSON.parse(e.data)); resolve(true); });
          es.onerror = () => { es.close(); resolve(false); };
        });
        if (!streamed) {            // запасной путь: опрос раз в 250 мс
          for (;;) {
            const p = await api("GET", "/api/ai/runs/" + res.run);
            if (p.text) { out.textContent = p.text; first = false; }
            if (p.done) { fin(p); break; }
            await new Promise(r => setTimeout(r, 250));
          }
        }
        const card = out.parentElement.querySelector(".aic-card");
        await load();
        if (S.noteAfter) { const last = list.querySelector(".aic-msg.ai:last-child"); if (last) last.insertBefore(el("p", "aic-qnote", S.noteAfter), last.querySelector(".aic-tools")); S.noteAfter = ""; }
        if (card) { const last = list.querySelector(".aic-msg.ai:last-child"); if (last) last.insertBefore(card, last.querySelector(".aic-tools")); }
      } finally { setBusy(false); S.run = ""; }
    }
    async function attach() {
      const f = file.files[0]; file.value = "";
      if (!f) return;
      if (!(await need())) return;
      if (f.size > 5 * 1024 * 1024) { say("Файл больше 5 МБ: он не отправлен.", "err"); return; }
      say("Обезличиваю файл на этом компьютере...");
      const buf = new Uint8Array(await f.arrayBuffer()); let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      const res = await api("POST", "/api/ai/chats/" + S.chat + "/attach", {name: f.name, data: btoa(bin)});
      if (!res.ok) { say(res.reason, "err"); return; }
      S.files.push({id: res.id, name: res.name, chars: res.chars}); renderChips();
      say("Файл обезличен и прикреплён. Провайдеру уйдёт только текст с метками.", "ok");
    }
    const guard = fn => async () => { try { await fn(); } catch (e) { say(e.message, "err"); } };
    bSend.onclick = guard(async () => { if (S.busy) { if (S.run) await api("POST", "/api/ai/runs/" + S.run + "/stop"); } else await send(); });
    file.onchange = guard(attach);
    ta.addEventListener("input", () => { S.resolve = {anonymize: [], allow: []}; fit(); });
    ta.addEventListener("keydown", e => { if (e.key === "Escape" && S.sel.items.length) { e.preventDefault(); clearSel(); return; } if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!S.busy) bSend.click(); } });
    renderChips(); loadProv();
    return {
      /* Чат переключается только при смене номера: повторные перерисовки страницы беседу не трогают. */
      async setChat(id, force) { id = id || ""; if (id === S.chat && !force) return; S.chat = id; S.off = new Set(); S.src = {}; S.confirm = ""; provHref = id ? "/ai?chat=" + encodeURIComponent(id) : "/ai"; loading = load().catch(e => say(e.message, "err")); await loading; },
      async reload() { try { await load(); } catch (e) { say(e.message, "err"); } },
      refreshFiles() { renderChips(); },
      setSelection(file, items) { S.sel = {file: file || "", items: items || []}; renderChips(); },
      refreshProviders() { return loadProv(); },
      focus() { ta.focus(); box.scrollIntoView({block: "nearest"}); },
      say,
    };
  }
  window.AIChat = {mount};
})();
