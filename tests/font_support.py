"""System fonts for synthetic PDF/image fixtures, with Cyrillic coverage.

Do not fall back to a built-in Latin-only PDF font: that would silently remove
sensitive Cyrillic text from leak tests. Missing fonts must fail fixture creation.
"""
from pathlib import Path


def system_font(*, serif: bool = False) -> str:
    family = "Times New Roman" if serif else "Arial"
    windows = "times" if serif else "arial"
    dejavu = "DejaVuSerif" if serif else "DejaVuSans"
    liberation = "LiberationSerif" if serif else "LiberationSans"
    candidates = [
        Path(f"/System/Library/Fonts/Supplemental/{family}.ttf"),
        Path(f"C:/Windows/Fonts/{windows}.ttf"),
        Path(f"/usr/share/fonts/truetype/dejavu/{dejavu}.ttf"),
        Path(f"/usr/share/fonts/truetype/liberation2/{liberation}-Regular.ttf"),
        Path(f"/usr/share/fonts/truetype/liberation/{liberation}-Regular.ttf"),
    ]
    return str(next((p for p in candidates if p.is_file()), candidates[0]))
