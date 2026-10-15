"""Кадры для проверки ручек ширины и меню строки чата в настоящем окне.

Запуск: .venv-mac/bin/python tools/chrome_shots.py ПАПКА
Снимки содержат тексты из case/; папку наружу не отдавать.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import webview  # noqa: E402

import shots_window  # noqa: E402
from anonymizer import desktop  # noqa: E402

TITLES = ["Очень длинное название чата про коммерческие условия и приложения к договору поставки", "Реестр процессов", "Короткий", "Маркетинг: отчёт за квартал", "Данные клиента"]


class ChromeShots(shots_window.Shots):
    def hover_row(self, index: int) -> None:
        self.js(f"document.querySelectorAll('.chat-row')[{index}].querySelector('.row-menu-btn').style.opacity = 1")

    def run(self) -> None:
        self.wait_js("document.readyState==='complete' && window.pywebview && window.pywebview.api && window.pywebview.api.pick_files")
        self.size("wide")
        self.process("Таблица.xlsx")
        for title in TITLES:
            self.app.chats.create(title)
        self.js("loadChats()")
        time.sleep(.8)
        self.js("openChat(chatList[chatList.length - 1].id); setSide(true, {persist: false}); setPane(true)")
        time.sleep(1)
        for theme in ("light", "dark"):
            self.theme(theme)
            self.js("document.querySelectorAll('.chat-row')[0].querySelector('.row-menu-btn').click()")
            self.snap(f"{theme}-menu-open")
            self.js("document.querySelector('#row-menu').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        self.theme("light")
        for name, side in (("wide-side", 400), ("narrow-side", 200)):
            self.js(f"setWidth('side', {side}, {{persist: false}})")
            self.snap(f"light-{name}")
        self.js("setWidth('side', null, {persist: false}); setWidth('pane', 600, {persist: false})")
        self.snap("light-pane-wide")
        self.js("setWidth('pane', null, {persist: false}); setPane(false)")
        self.js("document.querySelector('#split-side').focus()")
        self.snap("light-handle-focus")
        self.js("document.querySelectorAll('.chat-row')[0].querySelector('.row-menu-btn').click(); document.querySelector('#row-menu [data-do=delete]').click()")
        time.sleep(.6)
        self.snap("light-delete-confirm")
        self.theme("dark")
        self.snap("dark-delete-confirm")
        self.click("#ask-cancel")
        self.theme("dark")
        self.js("setWidth('side', 380, {persist: false}); setPane(true)")
        self.snap("dark-side-wide-pane")
        self.finish()


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    driver = ChromeShots(out, False)
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
