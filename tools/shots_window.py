"""Снимки настоящего окна программы в разных размерах и темах (macOS, WKWebView): для визуальной проверки интерфейса.

Запуск: .venv-mac/bin/python tools/shots_window.py ПАПКА [--only имя,имя]
Данные: файлы из case/ обезличиваются в самом окне, поэтому в снимках настоящие тексты кейса; папку наружу не отдавать.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import webview  # noqa: E402

import e2e_window  # noqa: E402
from tests.helpers import docx_bytes, xlsx_bytes  # noqa: E402
from anonymizer import desktop  # noqa: E402

CASE = ROOT / "case"
SIZES = {"wide": (1280, 800), "mid": (900, 700), "min": (520, 520), "short": (760, 520),
         "hd": (1440, 900), "fhd": (1920, 1080), "qhd": (2560, 1440)}
# Собственные настоящие размеры окна для проверки «во весь экран»: пустой чат, чат с лентой, результат с замечаниями.
BIG = ("hd", "fhd", "qhd")


CONTRAST_JS = """(() => {
  const c = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  const rgb = v => { c.clearRect(0,0,1,1); c.fillStyle = '#000'; c.fillStyle = v; c.fillRect(0,0,1,1); return Array.from(c.getImageData(0,0,1,1).data).slice(0,3); };
  const lum = a => { const f = x => { x /= 255; return x <= .03928 ? x/12.92 : Math.pow((x+.055)/1.055, 2.4); }; return .2126*f(a[0]) + .7152*f(a[1]) + .0722*f(a[2]); };
  const out = [];
  document.querySelectorAll('.btn.main').forEach(b => {
    if (!b.offsetParent) return;
    const st = getComputedStyle(b), l1 = lum(rgb(st.color)), l2 = lum(rgb(st.backgroundColor));
    const r = (Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);
    out.push((b.id || b.textContent.trim().slice(0,20)) + ': ' + r.toFixed(2) + (b.disabled ? ' (off)' : ''));
  });
  const clip = [];
  document.querySelectorAll('#feed .status, #feed .sub, #feed .detail').forEach(e => { if (e.scrollWidth > e.clientWidth + 1 || e.getBoundingClientRect().right > innerWidth + 1) clip.push(e.className); });
  return out.join('; ') + (clip.length ? ' CLIP: ' + clip.join(',') : ' noclip');
})()"""


class Shots(e2e_window.Driver):
    only = None

    def theme(self, name: str) -> None:
        self.js(f"document.documentElement.dataset.theme = {name!r}")
        time.sleep(.25)

    def size(self, key: str) -> None:
        self.holder["window"].resize(*SIZES[key])
        time.sleep(.9)

    def process(self, name: str) -> None:
        self.js("modes.chat.files.length = 0; modes.chat.folder = null; startDraft();")
        self.queue = [[str(CASE / name)]]
        self.click("#pick-chat")
        self.wait_js("modes.chat.files.length===1 && modes.chat.files[0].state==='ready'", 30)
        self.click("#btn-chat-anon")
        self.wait_js("document.querySelector('#result-chat .status')", 240)
        time.sleep(.8)

    def snap(self, name: str) -> None:
        # Окно в фоне не двигает CSS-переходы, и снимок ловит их на полпути: для статичных снимков переходы выключаются.
        self.js("if (!document.getElementById('shot-style')) { const s = document.createElement('style'); s.id = 'shot-style'; s.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(s); }")
        time.sleep(.5)
        self.shot(name)

    def big(self) -> None:
        """Крупные окна: боковая панель открыта и закрыта, таблица открыта, светлая и тёмная тема; результат с замечаниями."""
        self.size("hd")
        self.theme("light")
        self.process("Презентация.pptx")
        for key in BIG:
            self.size(key)
            for theme in ("light", "dark"):
                self.theme(theme)
                self.js("setPane(false); setSide(true, {persist: false}); window.scrollTo(0, 0)")
                self.snap(f"big-{key}-{theme}-1-result-side")
                self.js("setSide(false, {persist: false})")
                self.snap(f"big-{key}-{theme}-2-result-noside")
                self.js("setSide(true, {persist: false}); document.querySelector('.more-words summary').click()")
                time.sleep(.5)
                self.js("document.querySelector('.more-words').scrollIntoView({block: 'nearest'})")
                self.snap(f"big-{key}-{theme}-3-suspects-open")
                self.js("document.querySelector('.more-words summary').click()")
                time.sleep(.4)
                self.js("setPane(true)")
                self.snap(f"big-{key}-{theme}-4-table")
                self.js("setPane(false)")
        self.process("20261709_Кейс_v1.pptx")        # много сомнительных слов
        for key in ("hd", "fhd"):
            self.size(key)
            for theme in ("light", "dark"):
                self.theme(theme)
                self.js("setSide(true, {persist: false}); window.scrollTo(0, 0)")
                self.snap(f"sus-{key}-{theme}-1-collapsed")
                self.js("document.querySelector('.more-words summary').click()")
                time.sleep(.5)
                self.js("document.querySelector('.more-words').scrollIntoView({block: 'nearest'})")
                self.snap(f"sus-{key}-{theme}-2-open")
                self.js("document.querySelector('.more-words summary').click()")
                time.sleep(.4)
        for key in BIG:                              # переход в другой чат стирает результат: пустое состояние и чат снимаются после
            self.size(key)
            for theme in ("light", "dark"):
                self.theme(theme)
                self.js("startDraft(); setSide(true, {persist: false}); window.scrollTo(0, 0)")
                self.snap(f"big-{key}-{theme}-5-empty")
                self.js("openChat(chatList[0].id)")
                time.sleep(.5)
                self.snap(f"big-{key}-{theme}-6-chat")
        self.size("wide")
        self.finish()

    def projects(self) -> None:
        """Папка как проект: выбор способа и результат с деревом, 1440x900 и 520, светлая и тёмная тема."""
        name = "Клиент Ромашка с очень длинным названием папки для проверки переноса строк"
        src = self.home / name
        deep = src / "Договоры и приложения" / "2024 год" / "Дополнительные соглашения к договорам поставки"
        deep.mkdir(parents=True)
        (src / "Отчёты").mkdir()
        sec = "Смирнов Алексей Петрович"
        (deep / "Дополнительное соглашение номер 7 к договору поставки оборудования.docx").write_bytes(docx_bytes([f"Подписал {sec}."]))
        (src / "Договоры и приложения" / "Договор.docx").write_bytes(docx_bytes([f"Директор {sec}."]))
        (src / "Отчёты" / "Договор.docx").write_bytes(docx_bytes([f"Директор {sec}."]))
        (src / "Отчёты" / "Реестр.xlsx").write_bytes(xlsx_bytes({"A1": "ФИО", "A2": sec}))
        (src / "заметка.txt").write_text(f"Звонил {sec}", encoding="utf-8")
        (src / "схема.png").write_bytes(b"\x89PNG")
        (src / "видео.mp4").write_bytes(b"0")
        for key in ("hd", "min"):
            self.size(key)
            for theme in ("light", "dark"):
                self.theme(theme)
                self.js("modes.chat.files.length = 0; modes.chat.folder = null; startDraft(); setSide(false, {persist: false}); window.scrollTo(0, 0)")
                self.queue = [[str(src)]]
                self.click("#pick-folder-chat")
                self.wait_js("modes.chat.folder && modes.chat.folder.id", 30)
                self.js("document.querySelector('#files-chat .skip').open = true; window.scrollTo(0, 99999)")
                print("contrast", key, theme, "choice", self.js(CONTRAST_JS), flush=True)
                self.snap(f"proj-{key}-{theme}-1-choice")
                self.click("#btn-chat-anon")
                self.wait_js("chatData && chatData.project && !modes.chat.running", 240)
                time.sleep(.6)
                self.js("document.querySelector('#feed .skip').open = true; document.querySelector('#feed').scrollIntoView(); window.scrollTo(0, 0)")
                print("contrast", key, theme, "result", self.js(CONTRAST_JS), flush=True)
                self.snap(f"proj-{key}-{theme}-2-result")
                self.js("setSide(true, {persist: false})")
                self.snap(f"proj-{key}-{theme}-3-result-side")
                if (key, theme) != ("min", "dark"):
                    self.js("startDraft()")      # следующий круг начинает с нового чата
        self.size("wide")
        self.finish()

    def run(self) -> None:
        w = self.holder["window"]
        self.wait_js("document.readyState==='complete' && window.pywebview && window.pywebview.api && window.pywebview.api.pick_files")
        print("focus at start:", self.js("document.activeElement.tagName + '#' + document.activeElement.id"), flush=True)
        if self.only == "big":
            return self.big()
        if self.only == "project":
            return self.projects()
        for theme in ("light", "dark"):
            self.theme(theme)
            self.size("wide")
            self.js("startDraft(); setSide(true, {persist: false})")
            self.snap(f"{theme}-01-empty")
        self.theme("light")
        self.process("Договор.docx")
        self.process("Таблица.xlsx")
        for i in range(6):                         # длинный список чатов
            self.process("Договор.docx")
        for theme in ("light", "dark"):
            self.theme(theme)
            self.size("wide")
            self.js("openChat(chatList[chatList.length-1].id); setSide(true, {persist: false}); setPane(false);")
            time.sleep(.6)
            self.snap(f"{theme}-02-chat")
            self.js("document.querySelector('#opts').open = true; window.scrollTo(0, 99999)")
            self.snap(f"{theme}-03-options")
            self.js("document.querySelector('#opts').open = false; window.scrollTo(0, 0); setPane(true); revealValues = true; syncReveal(); renderTable();")
            self.snap(f"{theme}-04-table")
            self.js("revealValues = false; syncReveal(); setPane(false); setSide(false, {persist: false})")
            self.snap(f"{theme}-05-collapsed")
            self.js("setSide(true, {persist: false}); document.querySelector('#open-settings').click()")
            time.sleep(.6)
            self.snap(f"{theme}-06-settings")
            self.js("document.querySelector('#settings').close()")
        self.theme("light")
        for key in ("mid", "min", "short"):
            self.size(key)
            self.js("setSide(true, {persist: false}); setPane(false); window.scrollTo(0,0)")
            self.snap(f"light-10-{key}-side-open")
            self.js("setSide(false, {persist: false})")
            self.snap(f"light-11-{key}-side-closed")
            self.js("setPane(true)")
            self.snap(f"light-12-{key}-table")
            self.js("setPane(false)")
        self.theme("dark")
        self.size("min")
        self.js("setSide(false, {persist: false})")
        self.snap("dark-11-min-side-closed")
        self.js("setSide(true, {persist: false})")
        self.snap("dark-10-min-side-open")
        self.finish()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--only", choices=["big", "project"], help="big: только крупные окна (1440x900, 1920x1080, 2560x1440)")
    args = parser.parse_args()
    driver = Shots(args.out, False)
    driver.only = args.only
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
