"""One-command quality gate: runs the eval tools, compares with tests/eval/baseline.json, exits non-zero on regression.

  python tools/quality_gate.py                 # fast gates: text v1/v2/en + noise corpus
  python tools/quality_gate.py --full          # + images, pinned real subset, triage on that subset
  python tools/quality_gate.py --only text_v1,noise
  python tools/quality_gate.py --full --update-baseline   # re-measure and rewrite the baseline (owner decision!)

Regression rules (see compare()):
  leaks / misses      may not rise                                    (hard)
  false positives     may rise by at most FP_SLACK over the baseline  (budget)
  restore equality    may not drop                                    (hard)
  refusals            tracked separately: reported on their own line; a rise fails unless --allow-refusals
  noise corpus        replacements may not rise                       (hard)
  failing per-kind gates of eval_text must be a subset of the baseline's
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "eval" / "baseline.json"
PY = sys.executable
FP_SLACK = {"text": 2, "real_fp_strings_pct": 10, "triage_fp": 5}
TEXT = {"text_v1": "tests/eval/text_corpus_v1.jsonl", "text_v2": "tests/eval/text_corpus_v2.jsonl", "text_en": "tests/eval/text_corpus_en.jsonl"}
# pinned real subset: light cases across formats and both languages (inputs come from the raw corpus, see EVAL_REAL_DIR)
REAL_PINNED = ["gh_cpython_acks", "wd_en_actors_csv", "txt_ru_moscow", "syn_minutes_ru_csv", "syn_mail_ru_log", "syn_contract_ru_docx",
               "syn_invoice_en_xlsx", "syn_minutes_ru_pptx", "syn_contract_ru_html", "syn_mail_en_log", "gh_flask_changes", "md_ru_gazprom",
               "wd_ru_writers_xml", "syn_mail_ru_json", "cm_pdf_ru_005", "cm_jpg_en_041"]
ALL_STEPS = ["text_v1", "text_v2", "text_en", "noise", "images", "real", "triage"]
FAST_STEPS = ["text_v1", "text_v2", "text_en", "noise"]


def sh(args: list[str], env: dict | None = None, timeout: int = 3600) -> str:
    p = subprocess.run([PY, *args], capture_output=True, cwd=ROOT, timeout=timeout, env={**os.environ, **(env or {})})
    out = p.stdout.decode("utf-8", "ignore") + p.stderr.decode("utf-8", "ignore")
    return out


# ------------------------------------------------------------------ measurements
def m_text(corpus: str) -> dict:
    with tempfile.TemporaryDirectory() as t:
        out = sh(["tools/eval_text.py", corpus, str(Path(t) / "r.json")])
    m = re.search(r"TOTAL gold (\d+) full (\d+) partial (\d+) miss (\d+) wrongcat (\d+) leak (\d+) fp (\d+)", out)
    if not m:
        return {"error": out[-300:]}
    g, full, part, miss, wrong, leak, fp = map(int, m.groups())
    g2 = re.search(r"GATE: (.*)", out)
    bad = [] if (g2 and "ALL PASS" in g2.group(1)) else sorted((g2.group(1).replace("FAIL", "").strip().split(",") if g2 else ["?"]))
    return {"gold": g, "full": full, "partial": part, "miss": miss, "wrongcat": wrong, "leak": leak, "fp": fp, "failing_kinds": bad}


def m_noise() -> dict:
    out = sh(["tools/eval_noise.py"])
    m = re.search(r"TOTAL files=(\d+) replaced=(\d+) files_with_replacements=(\d+)", out)
    return {"files": int(m[1]), "replaced": int(m[2]), "files_hit": int(m[3])} if m else {"error": out[-300:]}


def m_images() -> dict:
    out = sh(["tools/eval_images.py"])
    m = re.search(r"TOTAL cases=(\d+) leaked_values=(\d+) blocked=(\d+) restore_exact=(\d+)", out)
    return {"cases": int(m[1]), "leaked_values": int(m[2]), "blocked": int(m[3]), "restore_exact": int(m[4])} if m else {"error": out[-300:]}


def m_real(jobs: int, results: Path) -> dict:
    env = {"EVAL_RESULTS": str(results)}
    if results.exists():
        results.unlink()
    sh(["tools/eval_real.py", "run", "--only", ",".join(REAL_PINNED), "--jobs", str(jobs)], env)
    if not results.exists():
        return {"error": "eval_real produced no results"}
    rows = [r for r in json.loads(results.read_text(encoding="utf-8")) if r["id"] in REAL_PINNED]
    # eval_real deliberately merges subset runs into historical results. Triage
    # must measure the same freshly evaluated pinned cases as this gate.
    results.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    leaks = {r["id"]: sum(v[1] for v in r.get("cats", {}).values()) for r in rows}
    return {"cases": len(rows), "missing": sorted(set(REAL_PINNED) - {r["id"] for r in rows}),
            "gold": sum(r.get("gold", 0) for r in rows), "leaked": sum(leaks.values()), "leaking_cases": sorted(k for k, v in leaks.items() if v),
            "refused": sum(1 for r in rows if r.get("blocked")), "crashed": sum(1 for r in rows if r.get("crash")),
            "fp_strings": sum(r.get("fp", 0) for r in rows),
            "restore_content_equal": sum(1 for r in rows if r.get("restore_content_equal"))}


def m_triage(results: Path) -> dict:
    out = sh(["tools/eval_triage.py"], {"EVAL_RESULTS": str(results)})
    m = re.search(r"Total unique natural hits (\d+): TP (\d+) .*?TP\? (\d+) .*?FP (\d+)", out)
    return {"hits": int(m[1]), "tp": int(m[2]), "tp_maybe": int(m[3]), "fp": int(m[4])} if m else {"error": out[-300:]}


# ------------------------------------------------------------------ comparison
def compare(name: str, cur: dict, base: dict, allow_refusals: bool) -> tuple[list[str], list[str]]:
    """Returns (failures, notes)."""
    bad: list[str] = []
    notes: list[str] = []
    if "error" in cur:
        return [f"{name}: measurement failed: {cur['error']}"], notes
    if not base:
        return [f"{name}: no baseline entry (run with --update-baseline)"], notes

    def le(key: str, slack: int = 0, label: str | None = None):
        if cur[key] > base[key] + slack:
            bad.append(f"{name}: {label or key} {base[key]} -> {cur[key]}" + (f" (budget +{slack})" if slack else ""))

    def ge(key: str):
        if cur[key] < base[key]:
            bad.append(f"{name}: {key} {base[key]} -> {cur[key]}")
    if name.startswith("text_"):
        le("leak"); le("miss"); le("fp", FP_SLACK["text"]); notes.append(f"wrongcat {base['wrongcat']} -> {cur['wrongcat']} (tracked)")
        new = sorted(set(cur["failing_kinds"]) - set(base["failing_kinds"]))
        if new:
            bad.append(f"{name}: new failing per-kind gates {new}")
    elif name == "noise":
        le("replaced")
    elif name == "images":
        le("leaked_values"); ge("restore_exact")
        if cur["blocked"] > base["blocked"]:
            (notes if allow_refusals else bad).append(f"{name}: REFUSALS {base['blocked']} -> {cur['blocked']}")
    elif name == "real":
        le("leaked"); le("crashed"); ge("restore_content_equal")
        new = sorted(set(cur["leaking_cases"]) - set(base["leaking_cases"]))
        if new:
            bad.append(f"{name}: newly leaking cases {new}")
        if cur["missing"]:
            bad.append(f"{name}: pinned cases not run {cur['missing']}")
        le("fp_strings", int(base["fp_strings"] * FP_SLACK["real_fp_strings_pct"] / 100) + 3, "FP strings")
        if cur["refused"] > base["refused"]:
            (notes if allow_refusals else bad).append(f"{name}: REFUSALS {base['refused']} -> {cur['refused']}")
    elif name == "triage":
        le("fp", FP_SLACK["triage_fp"], "natural-hit FP")
    return bad, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="also images, pinned real subset, triage")
    ap.add_argument("--only", help="comma list of steps: " + ",".join(ALL_STEPS))
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--allow-refusals", action="store_true", help="a rise in refusals is reported but does not fail")
    ap.add_argument("--baseline", default=str(BASELINE))
    a = ap.parse_args()
    steps = a.only.split(",") if a.only else (ALL_STEPS if a.full else FAST_STEPS)
    if "triage" in steps and "real" not in steps:
        steps.append("real")
    results = Path(tempfile.mkdtemp()) / "real_results.json"
    cur: dict[str, dict] = {}
    for s in ALL_STEPS:
        if s not in steps:
            continue
        print(f"[gate] {s} ...", flush=True)
        cur[s] = (m_text(TEXT[s]) if s in TEXT else m_noise() if s == "noise" else m_images() if s == "images"
                  else m_real(a.jobs, results) if s == "real" else m_triage(results))
        print(f"[gate] {s}: {json.dumps(cur[s], ensure_ascii=False)}", flush=True)
    bpath = Path(a.baseline)
    if a.update_baseline:
        old = json.loads(bpath.read_text(encoding="utf-8")) if bpath.exists() else {}
        old.update(cur)
        bpath.write_text(json.dumps(old, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[gate] baseline written: {bpath}")
        return 1 if any("error" in v for v in cur.values()) else 0
    base = json.loads(bpath.read_text(encoding="utf-8")) if bpath.exists() else {}
    failures: list[str] = []
    for name, c in cur.items():
        bad, notes = compare(name, c, base.get(name, {}), a.allow_refusals)
        failures += bad
        for n in notes:
            print(f"[gate] note  {name}: {n}")
    if failures:
        print("\nQUALITY GATE: FAIL")
        for f in failures:
            print("  - " + f)
        return 1
    print("\nQUALITY GATE: PASS (" + ",".join(cur) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
