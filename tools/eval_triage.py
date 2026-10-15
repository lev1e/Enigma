"""Rule-based triage of the natural hits (entities the product replaced that were NOT injected) in tests/eval/real_results.json.

  python tools/eval_triage.py            -> prints a markdown section (counts per verdict, sample values) for tests/eval/triage.md

Verdicts (heuristic, reviewed by hand on the printed samples):
  TP      really a person / organisation / contact / place worth hiding (legal form, full personal name, e-mail, handle, city/country name)
  TP?     plausible but ambiguous (single capitalised word, bare surname, public figure in encyclopaedic text)
  FP      should have stayed: sentence fragment, common noun, adjective form ("германском"), generic file/term, public URL (wikidata entity), page number
"""
from __future__ import annotations

import collections
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGAL = re.compile(r"\b(ООО|АО|ПАО|ЗАО|ОАО|ИП|LLC|Inc\.?|Ltd\.?|Corp\.?|GmbH|Bank|Банк|Фонд|Университет|University|Institute|Институт|Company|Group|Holdings?|Partners|Capital|Labs?|Logistics)\b", re.I)
ADJ = re.compile(r"(ого|его|ский|ская|ское|ские|ских|ом|ой|ий|ые|ая|ое|ому|ым)$", re.I)
PUBLIC_URL = re.compile(r"wikidata\.org|wikipedia\.org|wikimedia|github\.io|githubusercontent|w3\.org|schemas?\.|apache\.org/licenses|example\.", re.I)


def verdict(group: str, kind: str, orig: str) -> str:
    o = orig.strip()
    words = o.split()
    cap = lambda w: w[:1].isupper()                      # noqa: E731
    if kind == "ORG":
        if LEGAL.search(o):
            return "TP"
        if len(words) >= 4 or not any(cap(w) for w in words) or (words and not cap(words[0])):
            return "FP"
        return "TP?" if all(cap(w) or not w.isalpha() for w in words) else "FP"
    if kind == "PERSON":
        if not words or not cap(words[0]):
            return "FP"
        if len(words) >= 2 and all(cap(w) for w in words):
            return "TP"
        return "TP?" if not ADJ.search(o) else "FP"
    if kind == "DOMAIN":
        return "FP" if PUBLIC_URL.search(o) else "TP?"
    if kind == "COUNTRY":
        return "FP" if (ADJ.search(o) and o.islower() or ADJ.search(o) and o[:1].isupper() and o.lower() != o and len(o) > 5 and o.lower().endswith(("ом", "ой", "ого", "ских", "ский", "ое"))) else "TP"
    if kind in ("CITY", "ADDRESS"):
        return "TP"
    if kind == "REGION":
        return "TP?"                                     # macro-regions are hidden by policy
    if kind in ("EMAIL", "PHONE"):
        return "FP" if re.search(r"example|noreply|dev@|users@|announce@|\b0{4,}", o, re.I) else "TP"
    if kind == "USERNAME":
        return "TP" if o.startswith("@") or "github.com/" in o else "TP?"
    if kind in ("FILE", "TERM", "CONTRACT", "PROJECT"):
        return "FP" if kind in ("FILE", "TERM") else "TP?"
    return "TP?"


def main() -> None:
    import os
    _cands = [Path(os.environ["EVAL_RESULTS"])] if os.environ.get("EVAL_RESULTS") else []
    _cands += [ROOT / "tests" / "eval" / "real" / "_results.json", ROOT / "tests" / "eval" / "real_results.json"]
    rows = json.loads(next(c for c in _cands if c.exists()).read_text(encoding="utf-8"))
    real = [r for r in rows if "adversarial" not in r.get("traits", "") and r.get("source") != "adversarial"]
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in real:
        for lab, kind, orig, cnt, reason in r.get("natural") or []:
            by[(lab, kind)][verdict(lab, kind, orig)].append((orig, r["id"]))
    random.seed(11)
    tot = collections.Counter()
    out = ["| group | kind | unique natural hits | TP | TP? | FP | FP share | FP samples (random) |", "|---|---|---|---|---|---|---|---|"]
    for (lab, kind), d in sorted(by.items(), key=lambda x: -sum(len(v) for v in x[1].values())):
        n = {v: len(d.get(v, [])) for v in ("TP", "TP?", "FP")}
        tot.update(n)
        t = sum(n.values())
        fps = random.sample(d.get("FP", []), min(5, len(d.get("FP", []))))
        out.append(f"| {lab} | {kind} | {t} | {n['TP']} | {n['TP?']} | {n['FP']} | {100 * n['FP'] / t:.0f}% | " + "; ".join(f"`{o[:30].replace('|', '/')}` ({i})" for o, i in fps) + " |")
    t = sum(tot.values())
    out.insert(0, f"Total unique natural hits {t}: TP {tot['TP']} ({100 * tot['TP'] / t:.0f}%), TP? {tot['TP?']} ({100 * tot['TP?'] / t:.0f}%), FP {tot['FP']} ({100 * tot['FP'] / t:.0f}%).\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
