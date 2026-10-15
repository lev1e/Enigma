"""Reuse the approved Enigma light/dark tiles across app, Office and GitHub.

No new drawing: packaging/icon/Enigma-{light,dark}.png are the canonical
approved exports. Run with the main Python environment after changing them.
The macOS ICNS files remain the matching approved exports in packaging/icon.
"""
from __future__ import annotations

import base64
import io
import re
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "anonymizer" / "addin_web"
SIZES = (16, 24, 32, 48, 64, 80, 128, 256)


def png(image: Image.Image, size: int) -> bytes:
    stream = io.BytesIO()
    image.resize((size, size), Image.Resampling.LANCZOS).save(stream, "PNG", optimize=True)
    return stream.getvalue()


def main() -> int:
    docs = ROOT / "docs" / "assets"
    themes = {}
    for theme in ("light", "dark"):
        source = ROOT / "packaging" / "icon" / f"Enigma-{theme}.png"
        themes[theme] = Image.open(source).convert("RGBA")
        shutil.copyfile(source, docs / f"logo-{theme}.png")
        for size in (16, 32, 64, 80, 128):
            filename = f"icon-{size}.png" if theme == "light" else f"icon-dark-{size}.png"
            (OUT / filename).write_bytes(png(themes[theme], size))
    # Compatibility aliases must never reintroduce the retired hood artwork.
    for name in ("logo.png", "logo-mark.png"):
        shutil.copyfile(docs / "logo-light.png", docs / name)
    themes["light"].save(ROOT / "packaging" / "app.ico", format="ICO",
                         sizes=[(size, size) for size in SIZES if size != 80])

    for filename in ("index.html", "ai.html"):
        path = ROOT / "anonymizer" / "web" / filename
        html = path.read_text(encoding="utf-8")
        favicons = []
        for theme in ("light", "dark"):
            uri = "data:image/png;base64," + base64.b64encode(png(themes[theme], 32)).decode("ascii")
            favicons.append(f'<link id="brand-favicon-{theme}" rel="icon" type="image/png" media="(prefers-color-scheme: {theme})" href="{uri}">')
            if filename == "index.html":
                logo = "data:image/png;base64," + base64.b64encode(png(themes[theme], 128)).decode("ascii")
                html, count = re.subn(r"(\.logo-" + theme + r" \{ background: url\()[^)]+", lambda m: m[1] + logo, html)
                if count != 1:
                    raise RuntimeError(f"Expected one {theme} logo in {filename}")
        html = re.sub(r'<link id="brand-favicon-(?:light|dark)"[^>]*>\n?', "", html)
        html = html.replace("<title>", "\n".join(favicons) + "\n<title>", 1)
        path.write_text(html, encoding="utf-8")
    print("Enigma light/dark assets synchronized for desktop, Office, web and GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
