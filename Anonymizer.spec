# -*- mode: python ; coding: utf-8 -*-
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

VERSION = re.search(r'__version__ = "([^"]+)"', Path("anonymizer/__init__.py").read_text("utf-8")).group(1)

hiddenimports = (collect_submodules("fitz") + collect_submodules("cryptography")
                 + collect_submodules("pymorphy3") + ["dawg2_python"])

# Словарь OpenCorpora — это файлы данных внутри пакета, а не модули. Без явного сбора
# PyInstaller их не положит, и в собранном .exe разбор молча откатится на суффиксные
# правила: программа запустится, но косвенные падежи перестанут распознаваться.
datas = collect_data_files("pymorphy3_dicts_ru") + [("anonymizer/web", "anonymizer/web"), ("THIRD_PARTY_NOTICES.md", "."), ("anonymizer/addin_web", "anonymizer/addin_web"),
                                                                   ("anonymizer/ocr_helpers", "anonymizer/ocr_helpers")]
binaries = []

# Окно программы: pywebview показывает страницу через WebView2. Его библиотеки (Microsoft.Web.WebView2.*.dll,
# WebBrowserInterop) и скрипты лежат внутри пакета; на Windows нужны ещё pythonnet и clr_loader (мост к .NET).
for package in ("webview",) + (("pythonnet", "clr_loader") if sys.platform == "win32" else ()):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
if sys.platform == "win32":
    hiddenimports += ["clr"]

# Необязательная NER-модель (anonymizer/ner.py). Веса лежат внутри пакетов natasha/slovnet/navec как файлы данных
# (natasha/data/model/*.tar, 36 МБ); без collect_all сборка запустится, но признак молча выключится.
# РИСК СБОРКИ: на Windows сборка не проверялась. Если natasha не установлена, блок пропускается, а ner.py сам отключается.
# W7b: natasha/slovnet нуждаются в numpy, поэтому numpy нельзя держать в excludes (раньше он там стоял, и в собранной программе
# признак молча выключался). Ещё нужны pymorphy2 (natasha импортирует его при загрузке пакета), razdel, yargy, ipymarkup,
# intervaltree, dawg_python; словарь pymorphy2_dicts_ru (14 МБ) для NER не нужен и не собирается.
# Ожидаемый рост сборки (оценка с диска, не измерено): natasha data 36 МБ (из них нужны NER-веса 2,4 МБ и navec 26,6 МБ),
# numpy около 34 МБ на диске (примерно 12-15 МБ в сжатом виде), прочие пакеты около 1,5 МБ: порядка +60...70 МБ в папке, +25...35 МБ в установщике.
NER_EXCLUDES = ["pytest", "pandas", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi", "cefpython3"]
try:
    import natasha  # noqa: F401
    HAVE_NER = True
    hiddenimports += ["numpy", "pymorphy2", "razdel", "yargy", "ipymarkup", "intervaltree", "dawg_python"]
    for package in ("natasha", "slovnet", "navec"):
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
except ImportError:
    HAVE_NER = False

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Другие оболочки окна pywebview не нужны: на Windows работает только WebView2, а лишние Qt и GTK добавили бы сотни мегабайт.
    excludes=NER_EXCLUDES + ([] if HAVE_NER else ["numpy"]),
    noarchive=False,
)
pyz = PYZ(a.pure)
MAC = sys.platform == "darwin"
exe = EXE(
    pyz,
    a.scripts,
    # Windows: один .exe. macOS: папочная сборка внутри .app — без распаковки 50 МБ во временную папку при каждом запуске
    # (а запусков два: фоновая программа и окно) и с нормальной подписью каждого файла пакета.
    *([] if MAC else [a.binaries, a.datas]),
    [],
    exclude_binaries=MAC,
    name="Anonymizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64" if MAC else None,
    codesign_identity=None,       # macOS: подпись ставит tools/release_mac.py (ad hoc, без hardened runtime), см. docs/MAC_RELEASE.md
    entitlements_file=None,
    manifest="packaging/app.manifest",
    icon="packaging/app.ico",
    version="packaging/version_info.txt",
)

if MAC:
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Anonymizer")
    # Приложение для macOS: значок следует светлой теме; Dock-значок не умеет менять тему без каталога ресурсов.
    app = BUNDLE(
        coll,
        name="Anonymizer.app",
        icon="packaging/icon/Enigma-light.icns",
        bundle_identifier="dev.enigma.anonymizer",
        info_plist={"CFBundleDisplayName": "Anonymizer", "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                    "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "12.0"},
    )
