"""W7b: review-list volume, recall gain, time and memory of the optional NER name finder on the committed public corpus.

python tools/ner_measure.py [--lang ru|en] [--limit N] [--out FILE]
Runs the normal Service path (tests.helpers.Env) per document with ner_candidates False then True. Corpus: tests/eval/real
(public documents from real_manifest.json; never case/). Pass A = raw document (volume, time); pass B = document with dense
injected gold (tools/eval_ids.dense) for recall gain. Writes JSON; analysis is done by the caller.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import resource
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
REAL = Path(os.environ.get("EVAL_REAL_DIR") or ROOT / "tests" / "eval" / "real")
FMTS = {"txt", "md", "html", "csv", "tsv", "json", "xml", "yaml", "yml", "pdf", "docx"}


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576      # bytes on macOS


def fold(s: str) -> str:
    return s.casefold().replace("ё", "е")


def run_one(env, name: str, data: bytes):
    t = time.time()
    job = env.anonymize((name, data))
    dt = time.time() - t
    r = job.result or {}
    sugg = [{"text": s["text"], "count": s.get("count", 1), "reason": s.get("reason", "")} for s in r.get("suggestions", [])]
    originals = [str(i["original"]) for items in (r.get("groups") or {}).values() for i in items]
    return dt, sugg, originals


def text_len(name: str, data: bytes) -> int:
    from anonymizer.formats import extract_text
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_bytes(data)
        try:
            return len(extract_text(p))
        except Exception:                                     # noqa: BLE001
            return 0


def docs(lang: str, limit: int | None):
    from eval_ids import dense
    from eval_inject import inject as dinject
    out = []
    for e in json.loads((ROOT / "tests/eval/real_manifest.json").read_text(encoding="utf-8"))["files"]:
        if e["lang"] != lang or e["fmt"] not in FMTS or "scan" in e.get("traits", ""):
            continue
        p = REAL / e["path"]
        if not p.exists():
            continue
        raw = p.read_bytes()
        pack = dense(e["id"], lang)
        try:
            inj = dinject(e["fmt"], raw, pack, e["traits"])
        except Exception:                                     # noqa: BLE001
            inj = None
        out.append((e["id"], e["fmt"], raw, inj, [v for c, v in pack.gold if c == "PERSON"]))
    return out[:limit] if limit else out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(ROOT / "ner_measure.json"))
    a = ap.parse_args()
    from tests.helpers import Env
    items = docs(a.lang, a.limit)
    res = {"lang": a.lang, "docs": []}
    rows = {i[0]: {"id": i[0], "fmt": i[1], "bytes": len(i[2]), "gold": i[4]} for i in items}
    rss0 = rss_mb()
    for mode in (False, True):
        if mode:
            res["rss_before_model_mb"] = round(rss_mb(), 1)
            from anonymizer import ner
            t = time.time()
            ok = ner._load() is not False
            res["model_load_s"] = round(time.time() - t, 2)
            res["model_available"] = ok
            res["rss_after_load_mb"] = round(rss_mb(), 1)
        env = Env(ner_candidates=mode)
        for did, fmt, raw, inj, gold in items:
            row = rows[did]
            for tag, data in (("raw", raw), ("inj", inj)):
                if data is None:
                    continue
                name = f"{did}.{fmt}"
                try:
                    dt, sugg, orig = run_one(env, name, data)
                except Exception as ex:                       # noqa: BLE001
                    row[f"{tag}_{mode}_err"] = f"{type(ex).__name__}: {str(ex)[:80]}"
                    continue
                row[f"{tag}_{mode}"] = {"t": round(dt, 2), "sugg": sugg, "orig": orig}
                if tag == "raw" and not mode:
                    row["chars"] = text_len(name, data)
        env.close()
        print("pass done", mode, round(rss_mb()), flush=True)
    res["rss_peak_mb"] = round(rss_mb(), 1)
    res["rss_start_mb"] = round(rss0, 1)
    res["docs"] = list(rows.values())
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("written", a.out)


if __name__ == "__main__":
    main()
