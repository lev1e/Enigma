"""Generates packaging/version_info.txt from anonymizer.__version__ (the single source of the version number)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "packaging" / "version_info.txt"

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName','Enigma'), StringStruct('FileDescription','Offline reversible document anonymizer'), StringStruct('FileVersion','{ver}'), StringStruct('InternalName','Anonymizer'), StringStruct('OriginalFilename','Anonymizer.exe'), StringStruct('ProductName','Anonymizer'), StringStruct('ProductVersion','{ver}')])]), VarFileInfo([VarStruct('Translation',[1033,1200])])]
)
"""


def read_version(root: Path = ROOT) -> str:
    """Reads __version__ from anonymizer/__init__.py without importing the package."""
    text = (root / "anonymizer" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("anonymizer/__init__.py: __version__ not found")
    return match.group(1)


def render(version: str) -> str:
    parts = [int(p) for p in re.findall(r"\d+", version)[:4]]
    parts += [0] * (4 - len(parts))
    return TEMPLATE.format(tup="(" + ",".join(map(str, parts)) + ")", ver=version)


def main() -> int:
    version = read_version()
    with open(TARGET, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(version))
    print(f"{TARGET.name}: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
