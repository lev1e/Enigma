"""Распознавание текста на изображениях и сканах (русский и английский), офлайн.

Провайдер возвращает слова с рамками в пикселях изображения. Дальше слова превращаются в `OcrChars` — карту символов
той же формы, что и у `PageChars`, — поэтому поиск данных, закраска и проверка результата работают так же, как для
обычного текста страницы.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import fitz

from .pdftext import Ch, PageChars, RectGrid

HERE = Path(__file__).resolve().parent
OCR_DPI = 300
HOMOGLYPHS = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "А": "A", "В": "B",
                            "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X"})


def _sweep_script_dirs() -> None:
    """Папки скрипта распознавания (`anonymizer-ocr-<pid>`) прежних запусков, которые не дожили до выхода."""
    for path in Path(tempfile.gettempdir()).glob("anonymizer-ocr-*"):
        pid = path.name.rsplit("-", 1)[-1]
        if not pid.isdigit() or int(pid) == os.getpid() or not path.is_dir():
            continue
        if sys.platform == "win32":                    # os.kill(pid, 0) на Windows завершает процесс: судим по возрасту папки
            try:
                old = path.stat().st_mtime < time.time() - 86400
            except OSError:
                continue
            if old:
                shutil.rmtree(path, ignore_errors=True)
            continue
        try:
            os.kill(int(pid), 0)
            continue                                   # процесс жив
        except PermissionError:
            continue
        except OSError:
            shutil.rmtree(path, ignore_errors=True)


@cache
def _native_cache_dir() -> Path:
    # A predictable shared-temp path can be pre-populated with an executable or
    # symlink by another local user. mkdtemp creates a fresh private directory.
    directory = Path(tempfile.mkdtemp(prefix="anonymizer-native-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return directory


@dataclass(slots=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    line: int
    cx: list | None = None      # границы по x каждого символа слова, если движок их даёт
    conf: float = 0.6           # уверенность движка 0..1 (если движок её не даёт, считаем средней)
    rot: int = 0                # направление текста на странице: 0, 90, 180, 270 (как у PageChars)
    boxes: list | None = None   # рамки символов на странице (x0, y0, x1, y1), если слово повёрнуто


class OcrUnavailable(RuntimeError):
    pass


class VisionProvider:
    name = "apple-vision"
    native_rotation = True      # читает повёрнутый текст сам и возвращает направление строки

    def __init__(self) -> None:
        self.binary: Path | None = None

    def available(self) -> bool:
        return sys.platform == "darwin" and bool(self._packaged() or shutil.which("swiftc") or self._cached().exists())

    def _packaged(self) -> Path | None:
        """Готовый помощник, собранный вместе с программой (на Mac без Xcode компилятора нет)."""
        ready = HERE / "ocr_helpers" / "vision_ocr"
        return ready if ready.is_file() and os.access(ready, os.X_OK) else None

    def _cached(self) -> Path:
        source = HERE / "ocr_helpers" / "vision_ocr.swift"
        digest = hashlib.sha1(source.read_bytes()).hexdigest()[:10] if source.exists() else "none"
        return _native_cache_dir() / f"vision_ocr-{digest}"

    def _build(self) -> Path:
        packaged = self._packaged()
        if packaged:
            return packaged
        target = self._cached()
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        done = subprocess.run(["swiftc", "-O", str(HERE / "ocr_helpers" / "vision_ocr.swift"), "-o", str(target)],
                              capture_output=True, text=True, timeout=300)
        if done.returncode != 0 or not target.exists():
            raise OcrUnavailable("Не удалось подготовить распознавание текста macOS")
        return target

    def words(self, png: Path) -> list[Word]:
        binary = self.binary or self._build()
        self.binary = binary
        done = subprocess.run([str(binary), str(png)], capture_output=True, timeout=180)
        if done.returncode != 0:
            raise OcrUnavailable("Распознавание текста завершилось с ошибкой")
        return [Word(d["t"], d["x0"], d["y0"], d["x1"], d["y1"], d["line"], d.get("cx"), d.get("conf", 0.6),
                     d.get("rot", 0), [tuple(b) for b in d["cb"]] if d.get("rot") and d.get("cb") else None)
                for d in json.loads(done.stdout or b"[]")]


def _helper_binary(stem: str) -> Path | None:
    """Готовый или собираемый из исходника Swift-помощник (vision_ocr, vision_barcode); None — собрать нечем."""
    ready = HERE / "ocr_helpers" / stem
    if ready.is_file() and os.access(ready, os.X_OK):
        return ready
    source = HERE / "ocr_helpers" / f"{stem}.swift"
    if not source.exists():
        return None
    digest = hashlib.sha1(source.read_bytes()).hexdigest()[:10]
    target = _native_cache_dir() / f"{stem}-{digest}"
    if target.exists():
        return target
    if not shutil.which("swiftc"):
        return None
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    done = subprocess.run(["swiftc", "-O", str(source), "-o", str(target)], capture_output=True, text=True, timeout=300)
    return target if done.returncode == 0 and target.exists() else None


@dataclass(slots=True)
class Barcode:
    payload: str            # "" — код найден, но не декодирован
    rect: fitz.Rect         # в координатах страницы (точки PDF) или пикселях картинки


_BARCODE_BIN: Path | None = None


def barcodes_available() -> bool:
    """Поиск QR и штрихкодов умеет только Apple Vision (macOS)."""
    global _BARCODE_BIN
    if sys.platform != "darwin":
        return False
    if _BARCODE_BIN is None:
        _BARCODE_BIN = _helper_binary("vision_barcode")
    return _BARCODE_BIN is not None


def detect_barcodes_png(png: Path) -> list[Barcode]:
    if not barcodes_available():
        raise OcrUnavailable("Нет движка поиска штрихкодов")
    done = subprocess.run([str(_BARCODE_BIN), str(png)], capture_output=True, timeout=120)
    if done.returncode != 0:
        raise OcrUnavailable("Поиск штрихкодов завершился с ошибкой")
    return [Barcode(d.get("p") or "", fitz.Rect(d["x0"], d["y0"], d["x1"], d["y1"])) for d in json.loads(done.stdout or b"[]")]


def detect_barcodes(page, rect: fitz.Rect | None = None, scale: float = 3.0) -> list[Barcode]:
    """QR и штрихкоды в области страницы; рамки в координатах страницы."""
    clip = fitz.Rect(_tr(page.rotation_matrix, rect)) if rect is not None and page.rotation else (rect or page.rect)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False, annots=False)
    with tempfile.TemporaryDirectory(prefix="anon-bar-") as tmp:
        png = Path(tmp) / "page.png"
        pix.save(str(png))
        found = detect_barcodes_png(png)
    out = []
    for b in found:
        box = fitz.Rect(clip.x0 + b.rect.x0 / scale, clip.y0 + b.rect.y0 / scale,
                        clip.x0 + b.rect.x1 / scale, clip.y0 + b.rect.y1 / scale)
        out.append(Barcode(b.payload, fitz.Rect(_tr(page.derotation_matrix, box)) if page.rotation else box))
    return out


class TesseractProvider:
    name = "tesseract"

    def __init__(self) -> None:
        self.exe = os.environ.get("ANONYMIZER_TESSERACT") or shutil.which("tesseract")

    def available(self) -> bool:
        if not self.exe:
            return False
        try:
            done = subprocess.run([self.exe, "--list-langs"], capture_output=True, text=True, timeout=20)
        except Exception:
            return False
        langs = set(done.stdout.split())
        return {"rus", "eng"} <= langs

    def words(self, png: Path) -> list[Word]:
        # TSV has no text-direction field. Tesseract's implicit vertical-text
        # recognition otherwise returns sideways word boxes as horizontal text,
        # causing incorrect character placement and incomplete redaction. Keep
        # page segmentation, but let our explicit orientation passes rotate both
        # the text and its boxes together.
        done = subprocess.run([self.exe, str(png), "stdout", "-l", getattr(self, "lang", "rus+eng"), "--dpi", str(OCR_DPI),
                               "-c", "textord_tabfind_vertical_text=0", *getattr(self, "extra", ()), "tsv"],
                              capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            raise OcrUnavailable("Tesseract завершился с ошибкой")
        words: list[Word] = []
        keys: dict[tuple[str, str, str], int] = {}
        rows = [row.split("\t") for row in done.stdout.splitlines()[1:]]
        # Some Tesseract versions still rotate an inverted vertical block even
        # with vertical detection disabled. TSV exposes its tall line box, but
        # not the rotation. Defer such lines to the explicit rotated passes;
        # retain narrow one-character fields, which have no readable direction.
        tall_lines = {tuple(c[2:5]) for c in rows if len(c) >= 12 and c[0] == "4"
                      and float(c[9]) > 2 * float(c[8])}
        vertical_lines = {tuple(c[2:5]) for c in rows if len(c) >= 12 and c[0] == "5"
                          and len(c[11].strip()) >= 3 and tuple(c[2:5]) in tall_lines}
        for cols in rows:
            if len(cols) < 12 or cols[0] != "5" or not cols[11].strip():
                continue
            if tuple(cols[2:5]) in vertical_lines:
                continue
            line = keys.setdefault((cols[2], cols[3], cols[4]), len(keys))
            x, y, w, h = (float(cols[i]) for i in (6, 7, 8, 9))
            try:
                conf = max(0.0, float(cols[10])) / 100.0
            except ValueError:
                conf = 0.6
            words.append(Word(cols[11], x, y, x + w, y + h, line, None, conf))
        return words


WINDOWS_OCR_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result
}
$langs = @{}
foreach ($l in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) { $langs[$l.LanguageTag.Split('-')[0].ToLower()] = $l.LanguageTag }
if ($args[0] -eq '--langs') { $langs.Keys | ConvertTo-Json -Compress; exit 0 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($args[0])) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$out = @()
foreach ($code in @('ru', 'en')) {
    if (-not $langs.ContainsKey($code)) { continue }
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($langs[$code]))
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $i = 0
    foreach ($line in $result.Lines) {
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            $out += [pscustomobject]@{ l = $code; t = $w.Text; x0 = $r.X; y0 = $r.Y; x1 = $r.X + $r.Width; y1 = $r.Y + $r.Height; line = $i }
        }
        $i++
    }
}
ConvertTo-Json -InputObject @($out) -Compress
"""


def _script_purity(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.5
    cyr = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
    return max(cyr, len(letters) - cyr) / len(letters)


def merge_language_words(rows: list[dict]) -> list[Word]:
    """Слова двух движков (ru, en) сводятся в один набор: на одном месте остаётся запись с однородным алфавитом.

    Русский движок путает латиницу с кириллицей, английский не знает кириллицы: смесь букв двух алфавитов в одном слове
    почти всегда ошибка, а значит побеждает слово, где алфавит один; при равенстве — русский.
    """
    chosen: list[dict] = []
    for row in sorted(rows, key=lambda r: (r["l"] != "ru", r["y0"], r["x0"])):
        clash = None
        for other in chosen:
            ix = min(row["x1"], other["x1"]) - max(row["x0"], other["x0"])
            iy = min(row["y1"], other["y1"]) - max(row["y0"], other["y0"])
            if ix > 0 and iy > 0 and ix * iy > .4 * min((row["x1"] - row["x0"]) * (row["y1"] - row["y0"]),
                                                          (other["x1"] - other["x0"]) * (other["y1"] - other["y0"])):
                clash = other
                break
        if clash is None:
            chosen.append(row)
        elif _script_purity(row["t"]) > _script_purity(clash["t"]) + .05:
            chosen[chosen.index(clash)] = row
    # Номера строк у двух движков свои: строка определяется по высоте слова, слова одной линии получают общий номер.
    chosen.sort(key=lambda r: ((r["y0"] + r["y1"]) / 2, r["x0"]))
    words: list[Word] = []
    line, last_mid, last_h = -1, None, 0.0
    for r in chosen:
        mid, height = (r["y0"] + r["y1"]) / 2, r["y1"] - r["y0"]
        if last_mid is None or abs(mid - last_mid) > max(last_h, height) * .6:
            line += 1
        last_mid, last_h = mid, height
        words.append(Word(r["t"], r["x0"], r["y0"], r["x1"], r["y1"], line))
    return words


class TesseractSupplement(TesseractProvider):
    """Второй движок для сверки: Tesseract с тем, что установлено (хотя бы английский). Vision и Windows OCR пропускают целые строки
    (ключи, пароли мелким шрифтом внизу длинной картинки), а латинские секреты Tesseract читает."""
    name = "tesseract-supplement"
    extra = ("--psm", "6")          # сплошной текст: режим по умолчанию пропускает строки внизу длинных снимков

    def available(self) -> bool:
        if not self.exe:
            return False
        try:
            done = subprocess.run([self.exe, "--list-langs"], capture_output=True, text=True, timeout=20)
        except Exception:
            return False
        langs = set(done.stdout.split())
        if "eng" not in langs:
            return False
        self.lang = "rus+eng" if "rus" in langs else "eng"
        return True

    def words(self, png: Path) -> list[Word]:
        # Шум на картинках без текста даёт слова с низкой уверенностью: сверка берёт только уверенные.
        # Исключение: строка с уверенно прочитанной меткой (password, key, token, secret): значение рядом читается плохо,
        # но именно оно и есть секрет.
        words = super().words(png)
        labelled = {w.line for w in words if w.conf >= SUPPLEMENT_MIN_CONF and SECRET_LABEL.search(w.text)}
        return [w for w in words if w.conf >= SUPPLEMENT_MIN_CONF or w.line in labelled]


SUPPLEMENT_MIN_CONF = 0.5
SECRET_LABEL = re.compile(r"(?i)^\W*(?:pass(?:word|wd)?|pwd|secret|token|api|key|парол\w*|ключ\w*|токен\w*)\W*$")
_SUPPLEMENT: list = []


def supplement():
    """Дополнительный движок или None; не тот же, что основной."""
    if not _SUPPLEMENT:
        candidate = TesseractSupplement()
        try:
            _SUPPLEMENT.append(candidate if candidate.available() else None)
        except Exception:
            _SUPPLEMENT.append(None)
    main = provider()
    return None if isinstance(main, TesseractProvider) else _SUPPLEMENT[0]


def supplement_words(page, rect: fitz.Rect | None = None, scale: float | None = None) -> list[Word]:
    """Слова второго движка для страницы или её части; пусто, если его нет или он не сработал."""
    extra = supplement()
    if extra is None or page.rotation:
        return []
    try:
        from PIL import Image
        scale = scale or OCR_DPI / 72.0
        clip = fitz.Rect(rect) if rect is not None else page.rect
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False, annots=False)
        with tempfile.TemporaryDirectory(prefix="anon-ocr-") as tmp:
            png = Path(tmp) / "page.png"
            Image.frombytes("RGB", (pix.width, pix.height), pix.samples).save(png)
            return _scaled_words(extra.words(png), clip, scale)
    except Exception:
        return []


class WindowsProvider:
    """Windows.Media.Ocr через PowerShell: встроено в Windows 10/11, ничего ставить не нужно. Нужны языки ru и en."""
    name = "windows-ocr"

    def __init__(self) -> None:
        self.exe = shutil.which("powershell") or shutil.which("powershell.exe")
        self.script: Path | None = None

    def _script(self) -> Path:
        if self.script is None or not self.script.exists():
            _sweep_script_dirs()
            folder = Path(tempfile.gettempdir()) / f"anonymizer-ocr-{os.getpid()}"
            folder.mkdir(parents=True, exist_ok=True)
            atexit.register(shutil.rmtree, folder, True)
            self.script = folder / "win_ocr.ps1"
            self.script.write_text(WINDOWS_OCR_SCRIPT, encoding="utf-8-sig")
        return self.script

    def _run(self, arg: str, timeout: int) -> bytes:
        done = subprocess.run([self.exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(self._script()), arg], capture_output=True, timeout=timeout)
        if done.returncode != 0:
            raise OcrUnavailable("Распознавание текста Windows завершилось с ошибкой")
        return done.stdout

    def available(self) -> bool:
        if sys.platform != "win32" or not self.exe:
            return False
        try:
            tags = json.loads(self._run("--langs", 60).decode("utf-8-sig") or "[]")
        except Exception:
            return False
        tags = {tags} if isinstance(tags, str) else set(tags)
        return {"ru", "en"} <= tags

    def words(self, png: Path) -> list[Word]:
        raw = self._run(str(png), 180).decode("utf-8-sig").strip()
        rows = json.loads(raw) if raw else []
        if isinstance(rows, dict):
            rows = [rows]
        return merge_language_words(rows)


_PROVIDER = None
_PROVIDER_SET = False


def provider():
    """Первый доступный движок или None. На macOS предпочтителен Vision: точнее и ничего не нужно ставить."""
    global _PROVIDER, _PROVIDER_SET
    if not _PROVIDER_SET:
        _PROVIDER_SET = True
        for cls in (VisionProvider, WindowsProvider, TesseractProvider):
            candidate = cls()
            try:
                if candidate.available():
                    _PROVIDER = candidate
                    break
            except Exception:
                continue
    return _PROVIDER


def available() -> bool:
    return provider() is not None


def reset_provider() -> None:
    global _PROVIDER, _PROVIDER_SET
    _PROVIDER, _PROVIDER_SET = None, False
    _SUPPLEMENT.clear()


def fold(text: str) -> str:
    """Кириллица, похожая на латиницу, внутри адресов и номеров читается как латиница."""
    return text.translate(HOMOGLYPHS)


FORCE_PROBE = False             # проверки: прогон четырёх поворотов и для движка, который читает повёрнутое сам
ORIENT_PROBE_SCALE = 1.6        # разведка поворота идёт в сниженном разрешении: в четыре раза дешевле полного прохода
ORIENT_MIN_SCORE = 20.0         # меньше этого — на странице нет читаемого текста в данном повороте
ORIENT_KEEP_SHARE = .35         # поворот учитывается, если читается не меньше этой доли от лучшего


def _run_engine(engine, page, clip: fitz.Rect, scale: float, angle: int = 0) -> tuple[list[Word], "fitz.Matrix", "fitz.Pixmap"]:
    matrix = fitz.Matrix(scale, scale).prerotate(angle)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False, annots=False)
    with tempfile.TemporaryDirectory(prefix="anon-ocr-") as tmp:
        png = Path(tmp) / "page.png"
        pix.save(str(png))
        return engine.words(png), matrix, pix


def _readable(words: list[Word]) -> float:
    """Сколько уверенно прочитанного текста: мусор из неверно повёрнутой страницы даёт малую уверенность и короткие слова."""
    return sum(len(w.text) * w.conf for w in words if len(w.text) >= 3 and w.conf >= .5)


def _to_page(words: list[Word], matrix: "fitz.Matrix", pix: "fitz.Pixmap", angle: int) -> list[Word]:
    """Слова повёрнутого прохода — в координаты страницы, с рамкой каждого символа и направлением текста."""
    inv = ~matrix
    origin = fitz.Point(pix.x, pix.y)
    d = fitz.Point(1, 0) * inv - fitz.Point(0, 0) * inv
    rot = int(round(math.degrees(math.atan2(-d.y, d.x)) / 90.0)) * 90 % 360

    def box(x0, y0, x1, y1) -> tuple[float, float, float, float]:
        pts = [fitz.Point(x, y) + origin for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        pts = [p * inv for p in pts]
        return (min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts))

    out = []
    for w in words:
        n = max(1, len(w.text))
        step = (w.x1 - w.x0) / n
        if w.cx and len(w.cx) == n:
            spans = [(w.cx[j][0], w.cx[j][1]) for j in range(n)]
        else:
            spans = [(w.x0 + j * step, w.x0 + (j + 1) * step) for j in range(n)]
        boxes = [box(a, w.y0, b, w.y1) for a, b in spans]
        b = box(w.x0, w.y0, w.x1, w.y1)
        out.append(Word(w.text, *b, w.line + 100000 * (angle // 90 or 1), None, w.conf, rot, boxes))
    return out


def _tr(matrix: "fitz.Matrix", box) -> tuple[float, float, float, float]:
    r = fitz.Rect(box)
    pts = [fitz.Point(x, y) * matrix for x, y in ((r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1))]
    return (min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts))


def unrotated_rect(page) -> fitz.Rect:
    """Лист в тех координатах, в которых PyMuPDF отдаёт текст, картинки и принимает закраску (без поворота /Rotate)."""
    return fitz.Rect(_tr(page.derotation_matrix, page.rect)) if page.rotation else fitz.Rect(page.rect)


def _unrotate(words: list[Word], page) -> list[Word]:
    """У страницы с /Rotate изображение для OCR снимается повёрнутым, а текст и закраска живут в неповёрнутых координатах."""
    if not page.rotation:
        return words
    m = page.derotation_matrix
    out = []
    for w in words:
        n = max(1, len(w.text))
        if w.boxes and len(w.boxes) == n:
            boxes = list(w.boxes)
        elif w.cx and len(w.cx) == n:
            boxes = [(a, w.y0, b, w.y1) for a, b in w.cx]
        else:
            step = (w.x1 - w.x0) / n
            boxes = [(w.x0 + j * step, w.y0, w.x0 + (j + 1) * step, w.y1) for j in range(n)]
        out.append(Word(w.text, *_tr(m, (w.x0, w.y0, w.x1, w.y1)), w.line, None, w.conf,
                        (w.rot + page.rotation) % 360, [_tr(m, b) for b in boxes]))
    return out


def _inside_any(word: Word, others: list[Word]) -> bool:
    cx, cy = (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2
    return any(o.x0 <= cx <= o.x1 and o.y0 <= cy <= o.y1 for o in others)


def ocr_page_words(page, rect: fitz.Rect | None = None, scale: float | None = None,
                   orientations: bool = True) -> tuple[list[Word], float]:
    """Слова страницы в координатах страницы (точки PDF). rect — часть страницы.

    Скан бывает повёрнут на 90, 180 или 270 градусов (боком или вверх ногами): движок читает только прямой текст. Поэтому
    страница сначала пробуется во всех четырёх поворотах в сниженном разрешении, и те повороты, где читается текст,
    распознаются полностью. Слова неверных поворотов (мусор) отбрасываются.
    """
    engine = provider()
    if engine is None:
        raise OcrUnavailable("Нет движка распознавания текста")
    scale = scale or OCR_DPI / 72.0
    clip = fitz.Rect(_tr(page.rotation_matrix, rect)) if rect is not None and page.rotation else (rect or page.rect)
    base, _, _ = _run_engine(engine, page, clip, scale)
    out = []
    for w in base:
        boxes = None
        if w.rot and w.boxes and len(w.boxes) == len(w.text):
            boxes = [(clip.x0 + a / scale, clip.y0 + b / scale, clip.x0 + c / scale, clip.y0 + d / scale) for a, b, c, d in w.boxes]
        out.append(Word(w.text, clip.x0 + w.x0 / scale, clip.y0 + w.y0 / scale,
                        clip.x0 + w.x1 / scale, clip.y0 + w.y1 / scale, w.line,
                        [(clip.x0 + a / scale, clip.x0 + b / scale) for a, b in w.cx] if w.cx else None, w.conf,
                        w.rot if boxes else 0, boxes))
    if not orientations or (getattr(engine, "native_rotation", False) and not FORCE_PROBE):
        return _unrotate(out, page), scale
    probe = min(scale, ORIENT_PROBE_SCALE)
    scores = {}
    for angle in (0, 90, 180, 270):
        words, _, _ = _run_engine(engine, page, clip, probe, angle)
        scores[angle] = _readable(words)
    best = max(scores.values())
    if best < ORIENT_MIN_SCORE:
        return _unrotate(out, page), scale
    keep = [a for a in scores if scores[a] >= max(ORIENT_MIN_SCORE, ORIENT_KEEP_SHARE * best)]
    result = out if 0 in keep else []
    for angle in keep:
        if angle == 0:
            continue
        words, matrix, pix = _run_engine(engine, page, clip, scale, angle)
        for w in _to_page(words, matrix, pix, angle):
            if not _inside_any(w, result):
                result.append(w)
    return _unrotate(result, page), scale


PAD = 2.5   # точек PDF: рамки слов подрастают, чтобы закраска накрыла края букв


def add_ocr_chars(chars: PageChars, words: list[Word]) -> int:
    """Добавляет слова в карту символов страницы. Слова, уже занятые обычным текстом, пропускаются.

    Каждому символу достаётся своя доля рамки слова. Строки OCR идут после строк обычного текста.
    Возвращает число добавленных слов.
    """
    real = RectGrid(fitz.Rect(c.x0, c.y0, c.x1, c.y1) for c in chars.chars)
    by_line: dict[int, list[Word]] = {}
    for w in words:
        centre = fitz.Point((w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2)
        if real.contains(centre):
            continue
        # Центр слова мог попасть в просвет между знаками обычного текста («Research» в pdf_en_hiros): слово, чья рамка в основном
        # лежит на знаках текстового слоя, тоже уже занято, иначе то же слово находится дважды и метка рисуется два раза.
        box = fitz.Rect(w.x0, w.y0, w.x1, w.y1)
        if box.get_area() > 0 and sum((box & q).get_area() for q in real.near(box) if box.intersects(q)) >= .5 * box.get_area():
            continue
        by_line.setdefault(w.line, []).append(w)
    added = 0
    for key in sorted(by_line):
        rot = by_line[key][0].rot
        if rot:
            ws = sorted(by_line[key], key=lambda w: {90: -(w.y0 + w.y1), 180: -(w.x0 + w.x1), 270: w.y0 + w.y1}[rot])
        else:
            ws = sorted(by_line[key], key=lambda w: w.x0)
        li = len(chars.lines)
        ids: list[int] = []
        for k, w in enumerate(ws):
            if rot:
                prev = ws[k - 1].boxes[-1] if k and ws[k - 1].boxes else None
                if prev is not None and w.boxes:
                    first = w.boxes[0]
                    ids.append(len(chars.chars))
                    chars.chars.append(Ch(" ", min(prev[0], first[0]), min(prev[1], first[1]),
                                          max(prev[2], first[2]), max(prev[3], first[3]), 4.0, 0, rot, li))
                _add_rotated_word(chars, w, rot, li, ids)
                added += 1
                continue
            if k:
                ids.append(len(chars.chars))
                gap_x0 = ws[k - 1].x1
                chars.chars.append(Ch(" ", gap_x0, w.y0, max(gap_x0, w.x0), w.y1, w.y1 - w.y0, 0, 0, li))
            n = max(1, len(w.text))
            step = (w.x1 - w.x0) / n
            for j, c in enumerate(w.text):
                ids.append(len(chars.chars))
                left = PAD if j == 0 else 0.0
                right = PAD if j == n - 1 else 0.0
                a, b = w.cx[j] if w.cx and len(w.cx) == n else (w.x0 + j * step, w.x0 + (j + 1) * step)
                chars.chars.append(Ch(c, a - left, w.y0 - PAD * .6, b + right, w.y1 + PAD * .6,
                                      max(4.0, (w.y1 - w.y0) * .8), 0, 0, li))
            added += 1
        chars.lines.append(ids)
        chars.blocks.append([li])
    if added:
        chars.has_ocr = True
    return added


def _add_rotated_word(chars: PageChars, w: Word, rot: int, li: int, ids: list[int]) -> None:
    n = len(w.boxes)
    horizontal = rot in (0, 180)
    for j, (c, (x0, y0, x1, y1)) in enumerate(zip(w.text, w.boxes)):
        end = PAD if j in (0, n - 1) else 0.0
        side = PAD * .6
        if horizontal:
            x0, x1, y0, y1 = x0 - end, x1 + end, y0 - side, y1 + side
        else:
            x0, x1, y0, y1 = x0 - side, x1 + side, y0 - end, y1 + end
        ids.append(len(chars.chars))
        size = max(4.0, ((y1 - y0) if horizontal else (x1 - x0)) * .8)
        chars.chars.append(Ch(c, x0, y0, x1, y1, size, 0, rot, li))


# ---------------------------------------------------------------------------
# Несколько проходов распознавания для картинок: логотип с белым стилизованным текстом на фото движок часто теряет
# ---------------------------------------------------------------------------

IMAGE_PASSES = ("contrast", "invert", "up2", "r", "g", "b")
TALL_RATIO = 1.3                # во сколько раз высота больше ширины, чтобы читать нижнюю полосу отдельно
STRIP_FRACTION = 0.3
MAX_SIDE = 4800


def _variant(img, name: str):
    """(картинка для движка, во сколько раз она крупнее исходной)."""
    from PIL import Image, ImageFilter, ImageOps
    if name in ("r", "g", "b"):
        return ImageOps.autocontrast(img.convert("RGB").getchannel("rgb".index(name)), cutoff=1), 1.0
    gray = ImageOps.equalize(ImageOps.autocontrast(img.convert("L"), cutoff=2))
    if name == "contrast":
        return gray, 1.0
    if name == "invert":
        return ImageOps.invert(gray), 1.0
    factor = 2.0 if max(img.size) * 2 <= MAX_SIDE else 1.0
    big = img.convert("RGB").resize((int(img.width * factor), int(img.height * factor)), Image.LANCZOS)
    return big.filter(ImageFilter.UnsharpMask(radius=2, percent=120)), factor


def _scaled_words(words: list[Word], clip: fitz.Rect, factor: float) -> list[Word]:
    out = []
    for w in words:
        if w.rot:
            continue
        out.append(Word(w.text, clip.x0 + w.x0 / factor, clip.y0 + w.y0 / factor, clip.x0 + w.x1 / factor,
                        clip.y0 + w.y1 / factor, w.line, [(clip.x0 + a / factor, clip.x0 + b / factor) for a, b in w.cx] if w.cx else None,
                        w.conf))
    return out


def ocr_image_layers(page, scale: float | None = None, passes: tuple[str, ...] = IMAGE_PASSES,
                     rect: fitz.Rect | None = None) -> list[list[Word]]:
    """Слои слов одной картинки: обычное чтение и чтение после усиления контраста, инверсии, увеличения, по цветовым каналам.

    Слои не смешиваются в одну карту: у разных проходов одно и то же слово читается по-разному, и каждый слой проверяется
    отдельно, а закрашивается объединение находок.
    """
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    engine = provider()
    if engine is None:
        raise OcrUnavailable("Нет движка распознавания текста")
    scale = scale or OCR_DPI / 72.0
    base, _ = ocr_page_words(page, rect, scale=scale)
    layers = [base]
    if page.rotation or not passes:
        return layers
    clip = fitz.Rect(rect) if rect is not None else page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False, annots=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def run(name: str) -> list[Word]:
        picture, factor = _variant(img, name)
        with tempfile.TemporaryDirectory(prefix="anon-ocr-") as tmp:
            png = Path(tmp) / "page.png"
            picture.save(png)
            words = engine.words(png)
        return _scaled_words(words, clip, scale * factor)

    with ThreadPoolExecutor(max_workers=3) as pool:
        layers.extend(pool.map(run, passes))
    extra = supplement()
    if extra is not None:
        try:
            with tempfile.TemporaryDirectory(prefix="anon-ocr-") as tmp:
                png = Path(tmp) / "page.png"
                img.save(png)
                layers.append(_scaled_words(extra.words(png), clip, scale))
        except Exception:
            pass                    # сверка необязательна: основной движок уже отработал
    if img.height >= TALL_RATIO * img.width:
        # Длинный снимок: движки пропускают мелкие строки внизу (ИНН и ключ в нижней полосе). Нижняя треть читается отдельно и крупнее.
        top = int(img.height * (1 - STRIP_FRACTION))
        strip = img.crop((0, top, img.width, img.height))
        factor = 2.0 if max(strip.size) * 2 <= MAX_SIDE else 1.0
        big = strip.resize((int(strip.width * factor), int(strip.height * factor)), Image.LANCZOS) if factor > 1 else strip
        strip_clip = fitz.Rect(clip.x0, clip.y0 + top / scale, clip.x1, clip.y1)
        for reader in (engine, extra):
            if reader is None:
                continue
            try:
                with tempfile.TemporaryDirectory(prefix="anon-ocr-") as tmp:
                    png = Path(tmp) / "strip.png"
                    big.save(png)
                    layers.append(_scaled_words(reader.words(png), strip_clip, scale * factor))
            except Exception:
                pass
    return layers
