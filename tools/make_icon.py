"""Иконка приложения в стиле macOS: объёмная плитка-«суперэллипс», две темы (светлая #F4F7FC, тёмная #080F24).

Глиф берётся из packaging/icon/enigma-glyph.svg. Результат: packaging/icon/Enigma-{light,dark}.png (1024),
.icns для обеих тем, app.ico (светлая тема) и маленькие PNG для окна программы.
Запуск: .venv312/bin/python tools/make_icon.py
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "icon"
S = 2048                      # рабочий размер (потом уменьшается до 1024)
BODY = int(S * 824 / 1024)    # размер плитки по сетке иконок macOS
THEMES = {
    "light": {"base": (0xF4, 0xF7, 0xFC), "glow": (0x7A, 0xB4, 0xFF), "glow2": (0xC9, 0xDC, 0xFF), "ring": (0x3A, 0x6B, 0xD8),
              "ring_a": 26, "shade": 0.20, "edge": (255, 255, 255)},
    "dark": {"base": (0x08, 0x0F, 0x24), "glow": (0x1F, 0x5B, 0xE0), "glow2": (0x0E, 0x2A, 0x72), "ring": (0x6F, 0xB0, 0xFF),
             "ring_a": 34, "shade": 0.45, "edge": (150, 190, 255)},
}


def squircle_mask(size: int, n: float = 5.0) -> Image.Image:
    ss = 4
    big = size * ss
    pts = []
    for k in range(720):
        a = k / 720 * 2 * math.pi
        c, s_ = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** (2 / n), c)
        y = math.copysign(abs(s_) ** (2 / n), s_)
        pts.append(((x + 1) / 2 * big, (y + 1) / 2 * big))
    img = Image.new("L", (big, big), 0)
    ImageDraw.Draw(img).polygon(pts, fill=255)
    return img.resize((size, size), Image.LANCZOS)


def radial(size: int, cx: float, cy: float, r: float, color, alpha: float) -> Image.Image:
    """Мягкое цветовое пятно: центр (cx, cy) и радиус r в долях размера, прозрачность к краю падает до нуля."""
    g = Image.radial_gradient("L").resize((256, 256), Image.BICUBIC)       # 0 в центре, 255 по краю
    g = g.point(lambda v: int(max(0, 255 - v * 1.45) * alpha))
    side = int(2 * r * size)
    g = g.resize((side, side), Image.BICUBIC)
    mask = Image.new("L", (size, size), 0)
    mask.paste(g, (int(cx * size - side / 2), int(cy * size - side / 2)))
    layer = Image.new("RGBA", (size, size), tuple(color) + (255,))
    layer.putalpha(mask)
    return layer


def vgrad(size: int, lo: float, hi: float, power: float = 1.0, peak: int = 255) -> Image.Image:
    """Вертикальная маска: 0 выше lo, peak ниже hi (или наоборот, если lo > hi)."""
    g = Image.linear_gradient("L").resize((size, size), Image.BICUBIC)      # 0 сверху, 255 снизу
    def f(v: int) -> int:
        t = (v / 255 - lo) / (hi - lo)
        t = min(1.0, max(0.0, t)) ** power
        return int(t * peak)
    return g.point(f)


def _lerp(stops, t):
    t = min(1.0, max(0.0, t))
    for (o0, c0), (o1, c1) in zip(stops, stops[1:]):
        if t <= o1:
            u = (t - o0) / (o1 - o0) if o1 > o0 else 0
            return tuple(int(c0[i] + (c1[i] - c0[i]) * u) for i in range(3))
    return stops[-1][1]


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


HORIZ = [(0, _hex("#073FD4")), (.13, _hex("#0750E1")), (.27, _hex("#0964ED")), (.43, _hex("#0B77F6")), (.61, _hex("#078DF8")),
         (.78, _hex("#0EA9FA")), (.91, _hex("#18BDFB")), (1, _hex("#32D0FF"))]
VERT = [(0, _hex("#0957ED")), (.32, _hex("#084DDE")), (.5, _hex("#095BE8")), (.72, _hex("#084DDE")), (1, _hex("#0957ED"))]
NODE_L = [(0, _hex("#2688FE")), (.2, _hex("#177AF8")), (.4, _hex("#0D6CF0")), (.62, _hex("#095CEA")), (.82, _hex("#074FE0")), (1, _hex("#063FD0"))]
NODE_R = [(0, _hex("#65D9FF")), (.17, _hex("#44CFFD")), (.38, _hex("#25C1FB")), (.6, _hex("#11AFF9")), (.81, _hex("#079DF5")), (1, _hex("#0789ED"))]
WIDTH = 38


def _bezier(p0, p1, p2, p3, n=60):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def glyph_layer(size: int, scale: float) -> Image.Image:
    """Глиф «E» из исходного SVG, нарисованный напрямую: MuPDF не умеет градиентные штрихи."""
    ss = 2
    px = size * ss
    k = px * scale / 640
    ox = (px - 600 * k) / 2
    oy = (px - 640 * k) / 2 
    def pt(x, y):
        return (ox + x * k, oy + y * k)

    def stroke_mask(points):
        m = Image.new("L", (px, px), 0)
        d = ImageDraw.Draw(m)
        pts = [pt(*p) for p in points]
        d.line(pts, fill=255, width=int(WIDTH * k), joint="curve")
        r = WIDTH * k / 2
        for x, y in pts[::2] + [pts[-1]]:
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
        return m

    def paint(mask, fn):
        """Заливка маски градиентом fn(x, y) -> цвет (по сетке 1/8 размера, затем сглаживание)."""
        layer = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        layer.paste(fn, (0, 0), mask)
        return layer

    def hgrad():
        row = Image.new("RGB", (256, 1))
        for i in range(256):
            x = 79 + (518 - 79) * i / 255
            row.putpixel((i, 0), _lerp(HORIZ, (x - 79) / (518 - 79)))
        img = row.resize((int((518 - 79) * k), px), Image.BILINEAR)
        full = Image.new("RGB", (px, px), HORIZ[0][1])
        full.paste(img, (int(pt(79, 0)[0]), 0))
        edge = int(pt(518, 0)[0])
        if edge < px:
            full.paste(Image.new("RGB", (px - edge, px), HORIZ[-1][1]), (edge, 0))
        return full

    def vgrad_img():
        col = Image.new("RGB", (1, 256))
        for i in range(256):
            col.putpixel((0, i), _lerp(VERT, i / 255))
        h = int((577 - 63) * k)
        img = col.resize((px, h), Image.BILINEAR)
        full = Image.new("RGB", (px, px), VERT[0][1])
        full.paste(img, (0, int(pt(0, 63)[1])))
        return full

    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    hg = hgrad()
    out.alpha_composite(paint(stroke_mask([(132, 116), (132, 524)]), vgrad_img()))
    for line in ([(132, 116), (475, 116)], [(132, 320), (450, 320)], [(132, 524), (475, 524)]):
        out.alpha_composite(paint(stroke_mask(line), hg)) if False else None
    horizontals = Image.new("L", (px, px), 0)
    for line in ([(132, 116), (475, 116)], [(132, 320), (450, 320)], [(132, 524), (475, 524)],
                 _bezier((164.5, 141.5), (212.5, 205.5), (289, 285), (347, 311)) + _bezier((347, 311), (368, 320), (399, 320), (436, 320))):
        horizontals = ImageChops.lighter(horizontals, stroke_mask(line))
    out.alpha_composite(paint(horizontals, hg))
    nodes = [((132, 116), 53, NODE_L), ((132, 320), 49, NODE_L), ((132, 524), 53, NODE_L),
             ((475, 116), 40, NODE_R), ((450, 320), 44, NODE_R), ((475, 524), 40, NODE_R)]
    for (cx, cy), r, stops in nodes:
        m = Image.new("L", (px, px), 0)
        x, y = pt(cx, cy)
        ImageDraw.Draw(m).ellipse((x - r * k, y - r * k, x + r * k, y + r * k), fill=255)
        # радиальный градиент со смещённым к левому верху центром
        fx, fy, fr = x - r * k * .42, y - r * k * .55, r * k * 1.8
        side = int(2 * fr)
        g = Image.radial_gradient("L").resize((256, 256), Image.BICUBIC)
        lut = Image.new("RGB", (256, 1))
        for i in range(256):
            lut.putpixel((i, 0), _lerp(stops, i / 255 / .72))
        colored = Image.merge("RGB", [g.point(lambda v, c=c: 0) for c in range(3)])
        ramp = Image.new("RGB", (256, 256))
        gp = g.load()
        rp = ramp.load()
        lp = lut.load()
        for yy in range(256):
            for xx in range(256):
                rp[xx, yy] = lp[min(255, int(gp[xx, yy] * 1.0)), 0]
        ramp = ramp.resize((side, side), Image.BICUBIC)
        full = Image.new("RGB", (px, px), stops[-1][1])
        full.paste(ramp, (int(fx - fr), int(fy - fr)))
        out.alpha_composite(paint(m, full))
    return out.resize((size, size), Image.LANCZOS)


def solid(size: int, color, mask: Image.Image, opacity: float = 1.0) -> Image.Image:
    layer = Image.new("RGBA", (size, size), tuple(color) + (255,))
    layer.putalpha(mask.point(lambda v: int(v * opacity)))
    return layer


def tile(theme: str) -> Image.Image:
    """Плитка macOS: только фон нужного цвета и логотип без изменений (цвета глифа как в исходном SVG)."""
    t = THEMES[theme]
    body = BODY
    base = Image.new("RGBA", (body, body), t["base"] + (255,))
    base.alpha_composite(glyph_layer(body, .80))
    mask = squircle_mask(body)
    base.putalpha(mask)
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    off = (S - body) // 2
    dm = Image.new("L", (S, S), 0)
    dm.paste(mask.point(lambda v: int(v * .35)), (off, off + int(S * .012)))
    dm = dm.filter(ImageFilter.GaussianBlur(S * .012))
    canvas.alpha_composite(solid(S, (0, 0, 0), dm))
    canvas.alpha_composite(base, (off, off))
    return canvas.resize((1024, 1024), Image.LANCZOS)


def write_icns(img: Image.Image, name: str) -> None:
    folder = OUT / f"{name}.iconset"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    for size in (16, 32, 128, 256, 512):
        img.resize((size, size), Image.LANCZOS).save(folder / f"icon_{size}x{size}.png")
        img.resize((size * 2, size * 2), Image.LANCZOS).save(folder / f"icon_{size}x{size}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(folder), "-o", str(OUT / f"{name}.icns")], check=True)
    shutil.rmtree(folder)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        img = tile(theme)
        img.save(OUT / f"Enigma-{theme}.png")
        img.resize((256, 256), Image.LANCZOS).save(OUT / f"Enigma-{theme}-256.png")
        write_icns(img, f"Enigma-{theme}")
        if theme == "light":
            img.save(ROOT / "packaging" / "app.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("ok", sorted(p.name for p in OUT.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
