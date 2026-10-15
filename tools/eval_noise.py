"""Noise corpus: innocuous documents (recipes, changelogs, math, code, weather, how-tos, generic tables; RU and EN).

Nothing in them is personal data, so the product should replace nothing. Prints one line per file and
`TOTAL files=N replaced=R files_with_replacements=K`; the quality gate keeps R at or below its baseline.

  python tools/eval_noise.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NOISE = ROOT / "tests" / "eval" / "noise"


def main() -> int:
    from tests.helpers import Env
    files = sorted(p for p in NOISE.iterdir() if p.is_file())
    total = hit_files = 0
    for p in files:
        env = Env()
        try:
            job = env.anonymize((p.name, p.read_bytes()))
            f = job.files[0]
            n = int(f.total or 0)
            samples = [str(getattr(r, "original", r))[:30] for r in (job.replaced or [])][:5]
        finally:
            env.close()
        total += n
        hit_files += bool(n)
        print(f"{p.name:<22} status={f.status} replaced={n} {samples if n else ''}", flush=True)
    print(f"TOTAL files={len(files)} replaced={total} files_with_replacements={hit_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
