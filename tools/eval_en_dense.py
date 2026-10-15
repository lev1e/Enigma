"""Fast English dense-corpus check: tools/eval_ids.dense(seed,'en') values placed by tools/eval_inject.synth into txt documents,
scanned with the detector only (no file formats), per-kind leak counts.

Usage: .venv-mac/bin/python tools/eval_en_dense.py [n_seeds=40] [-v]
"""
import collections
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from tests.helpers import Env                      # noqa: E402
import eval_ids                                    # noqa: E402
import eval_inject                                 # noqa: E402
from eval_real import canon, needles               # noqa: E402

KINDS = ["contract", "invoice", "resume", "ruling", "minutes", "mail"]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 40
    verbose = "-v" in sys.argv
    env = Env()
    tot = collections.defaultdict(lambda: [0, 0])
    leaks = collections.defaultdict(list)
    ctx = collections.defaultdict(list)
    nat = collections.Counter()
    natsamples = collections.Counter()
    for i in range(n):
        seed = f"endense{i}"
        pack = eval_ids.dense(seed, "en")
        kind = KINDS[i % len(KINDS)]
        text = eval_inject.synth(kind, "txt", pack, seed).decode("utf-8")
        det = env.service.build_detector(env.service.settings_for({}))
        det.harvest(text, "x.txt")
        fs = [f for f in det.scan(text, "x.txt", "text") if f.decision.value == "AUTO"]
        keep = [True] * len(text)
        for f in fs:
            for j in range(f.start, f.end):
                keep[j] = False
        rest = canon("".join(c if k else " " for c, k in zip(text, keep)))
        gold_c = [canon(v) for _, v in pack.gold]
        for cat, val in pack.gold:
            leaked = any(nd and nd in rest for nd in needles(cat, val))
            tot[cat][0] += 1
            tot[cat][1] += leaked
            if leaked:
                leaks[cat].append(val)
                if verbose and len(ctx[cat]) < 8:
                    ln, pos = [], 0
                    for l in text.split("\n"):
                        seg = "".join(c if keep[pos + j] else " " for j, c in enumerate(l))
                        if any(nd and nd in canon(seg) for nd in needles(cat, val)):
                            ln.append(l)
                        pos += len(l) + 1
                    ctx[cat].extend(l[:150] for l in ln[:2])
        for f in fs:
            oc = canon(f.original)
            if not oc or any(oc in g or (len(g) >= 4 and g in oc) for g in gold_c):
                continue
            nat[f.category] += 1
            natsamples[(f.category, f.original[:40])] += 1
    print(f"{'kind':10}{'gold':>6}{'leak':>6}  recall")
    for c, (g, l) in sorted(tot.items()):
        print(f"{c:10}{g:6}{l:6}  {1 - l / g:.3f}")
    print("natural/FP replacements:", dict(nat))
    if verbose:
        for c, v in leaks.items():
            print("LEAK", c, sorted(set(v))[:12])
        for c, v in ctx.items():
            for l in v:
                print("CTX", c, "|", l)
        for (c, o), k in natsamples.most_common(40):
            print("NAT", c, o, k)


if __name__ == "__main__":
    main()
