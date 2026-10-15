"""Проход по интерфейсу в настоящем окне как пользователь: несколько чатов, переключение, таблица замен, правки.

Снимает кадры и меряет, что двигается при каждом действии (прямоугольники опорных элементов до и после).
Запуск: .venv-mac/bin/python tools/usability_window.py ПАПКА
Данные: файлы из case/, снимки содержат настоящие тексты кейса; папку наружу не отдавать.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import webview  # noqa: E402

import e2e_window  # noqa: E402
import shots_window  # noqa: E402
from anonymizer import desktop  # noqa: E402

CASE = ROOT / "case"
ANCHORS = ["#side", ".chat-head", "#chat-title", "#btn-table", ".composer", "#btn-chat-anon", "#plan-line", "#pane", "#pane .pane-head", ".ent-row", "#pane-note", ".page"]
FILES = [p.name for p in sorted(CASE.glob("*.[xdp][lo][sc]x"))[:4]] if CASE.is_dir() else []   # имена берутся из приватной папки case/, в коде их нет
class Usability(shots_window.Shots):
    def rects(self) -> dict:
        code = """(() => { const out = {}; for (const s of %s) { const e = document.querySelector(s); if (!e) { out[s] = null; continue; }
            const b = e.getBoundingClientRect(); out[s] = [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)]; }
            out.scroll = [Math.round(window.scrollY), Math.round((document.querySelector('#pane')||{}).scrollTop||0), Math.round((document.querySelector('#chat-list')||{}).scrollTop||0)];
            out.docH = document.documentElement.scrollHeight; out.focus = document.activeElement.tagName + '#' + document.activeElement.id; return JSON.stringify(out); })()""" % json.dumps(ANCHORS)
        return json.loads(self.js(code))

    def diff(self, label: str, before: dict, after: dict, ignore: tuple = ()) -> None:
        moved = []
        for key, a in before.items():
            b = after.get(key)
            if key in ignore or a == b:
                continue
            moved.append(f"{key}: {a} -> {b}")
        print(f"[{label}] " + ("ничего не сдвинулось" if not moved else "ИЗМЕНИЛОСЬ: " + "; ".join(moved)), flush=True)

    def step(self, label: str, action, settle: float = .7, ignore: tuple = ()) -> None:
        before = self.rects()
        action()
        time.sleep(settle)
        self.diff(label, before, self.rects(), ignore)

    def run(self) -> None:
        self.wait_js("document.readyState==='complete' && window.pywebview && window.pywebview.api && window.pywebview.api.pick_files")
        self.theme("light")
        self.size("wide")
        self.js("setSide(true, {persist: false})")
        # 1. обезличивание четырёх файлов с кадрами хода и результата
        for i, name in enumerate(FILES):
            self.js("modes.chat.files.length = 0; modes.chat.folder = null; startDraft();")
            self.queue = [[str(CASE / name)]]
            self.click("#pick-chat")
            self.wait_js("modes.chat.files.length===1 && modes.chat.files[0].state==='ready'", 60)
            self.snap(f"u{i}-1-file-added")
            before = self.rects()
            self.click("#btn-chat-anon")
            time.sleep(.6)
            self.snap(f"u{i}-2-progress")
            mid = self.rects()
            self.wait_js("document.querySelector('#result-chat .status')", 300)
            time.sleep(.8)
            self.snap(f"u{i}-3-result")
            self.diff(f"{name}: старт обработки", before, mid)
            self.diff(f"{name}: результат появился", mid, self.rects(), ignore=("docH",))
        # 2. переключение чатов
        ids = json.loads(self.js("JSON.stringify(chatList.map(c => c.id))"))
        print("чатов:", len(ids), flush=True)
        for k in range(2):
            for n, cid in enumerate(ids):
                self.step(f"чат {n + 1}/{len(ids)}, круг {k + 1}", lambda c=cid: self.js(f"openChat({json.dumps(c)})"), 1.0,
                          ignore=("#chat-title", "#plan-line", ".ent-row", "#pane-note", "docH"))
            self.snap(f"u-chat-switch-{k}")
        # 3. таблица
        big = self.js("chatList[0].id")
        self.js(f"openChat({json.dumps(big)})")
        time.sleep(1)
        self.step("открыть таблицу", lambda: self.click("#btn-table"), 1.0)
        self.snap("u-table-hidden")
        self.step("показать значения", lambda: self.click("#btn-reveal"), .6)
        self.snap("u-table-revealed")
        rows = int(self.js("document.querySelectorAll('.ent-row').length"))
        print("строк в таблице:", rows, flush=True)
        self.step("раскрыть первую строку", lambda: self.js("document.querySelector('.ent-row').click()"), .7)
        self.snap("u-table-row-open")
        base = self.js("document.querySelector('.ent-row').dataset.toggle")
        before = self.rects()
        self.js(f"document.querySelector('[data-act=\"edit\"][data-base=\"{base}\"]').click()")
        self.wait_js("document.querySelector('#ask').open", 10)
        time.sleep(.5)
        self.snap("u-dialog-edit")
        self.js("document.querySelector('#ask-input').value = 'Длинное-длинное-значение-без-пробелов-Иванов-Петров-Сидоров-Кузнецов-0123456789'")
        self.click("#ask-ok")
        self.wait_js("!document.querySelector('#ask').open", 10)
        time.sleep(1.5)
        self.diff("правка значения (диалог + сохранение)", before, self.rects(), ignore=("#pane-note", "docH"))
        print("фокус после правки:", self.rects()["focus"], flush=True)
        self.snap("u-table-after-edit")
        self.step("поиск в таблице", lambda: self.js("(() => { const s = document.querySelector('#pane-search'); s.value = 'а'; s.dispatchEvent(new Event('input')); })()"), .6, ignore=("#pane-note", ".ent-row", "docH"))
        self.js("(() => { const s = document.querySelector('#pane-search'); s.value = ''; s.dispatchEvent(new Event('input')); })()")
        self.step("закрыть таблицу", lambda: self.click("#btn-pane-close"), 1.0, ignore=("#pane", "#pane .pane-head", ".ent-row", "#pane-note"))
        # 4. узкое окно
        for key in ("mid", "min"):
            self.size(key)
            self.js("setPane(true)")
            time.sleep(.8)
            self.snap(f"u-{key}-table-open")
            self.js("setPane(false)")
        self.size("wide")
        self.finish()


def main() -> int:
    out = Path(sys.argv[1])
    driver = Usability(out, False)
    driver.exit_code = 2
    window = webview.create_window(desktop.TITLE, f"http://127.0.0.1:{driver.port}/?t={driver.app.token}", js_api=driver.bridge,
                                   width=1280, height=800, min_size=(520, 520), text_select=True)
    driver.holder["window"] = window
    webview.start(driver.run, private_mode=True)
    driver.server.shutdown()
    shutil.rmtree(driver.home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
