"""S7A proof/bench: identical-output fingerprints + timings.

  python tools/s7a_proof.py fp OUT.json            # fingerprints (output text hash + findings hash) for all fixtures
  python tools/s7a_proof.py bench KIND [MB]        # KIND: rep (repeated corpus v1) | var (digits-randomised mix); prints wall, user-CPU, RSS, hashes
Run from the repo root; sys.path takes the cwd, so running it from a copy of the tree measures that copy.
Fixtures are synthetic (tests/eval corpora + tests/eval/noise + tests/eval/en_corpus); never tests/eval/real or case/."""
import sys, os, json, time, hashlib, resource, random, re
sys.path.insert(0, ".")
from pathlib import Path
from tests.helpers import Env


def strip(s): return "".join(c for c in s if not 0xE0000 <= ord(c) <= 0xE007F)


def corpus_texts(*names):
    out = []
    for n in names:
        for line in open(f"tests/eval/{n}", encoding="utf-8"):
            out.append(json.loads(line)["text"])
    return out


def big_rep(size):
    parts = [t + "\n\n" for t in corpus_texts("text_corpus_v1.jsonl")]
    out, n, i = [], 0, 0
    while n < size:
        t = parts[i % len(parts)]; out.append(t); n += len(t.encode()); i += 1
    return "".join(out).encode()[:size]


def big_var(size):
    rnd = random.Random(11)
    parts = [t + "\n\n" for t in corpus_texts("text_corpus_v1.jsonl", "text_corpus_v2.jsonl", "text_corpus_en.jsonl")]
    out, n = [], 0
    while n < size:
        t = rnd.choice(parts)
        t = re.sub(r"\d", lambda m: str(rnd.randrange(10)), t)
        out.append(t); n += len(t.encode())
    return "".join(out).encode()[:size]


_CAP = []
def _install():
    from anonymizer import formats
    orig = formats.replace_findings
    def wrap(text, findings, ctx, *a, **k):
        _CAP.append(list(findings)); return orig(text, findings, ctx, *a, **k)
    formats.replace_findings = wrap
_install()


def run(name, data):
    env = Env()
    try:
        _CAP.clear()
        job = env.anonymize((name, data))
        fr = type("R", (), {"findings": [f for fs in _CAP for f in fs], "status": job.files[0].status})
        out = env.output(job)
        txt = strip(out.read_bytes().decode("utf-8", "replace")) if out.suffix in (".txt", ".md", ".log", ".csv") else out.read_bytes().hex()
        fl = ";".join(f"{f.category},{f.start},{f.end},{getattr(f.decision, 'value', f.decision)}" for f in fr.findings)
        return (hashlib.sha256(txt.encode()).hexdigest()[:16], hashlib.sha256(fl.encode()).hexdigest()[:16], len(fr.findings), str(fr.status))
    finally:
        env.close()


def fixtures():
    fx = {}
    d = Path("tests/eval")
    files = sorted(p for p in (d / "noise").iterdir() if p.is_file()) + sorted(p for p in (d / "en_corpus" / "clean").iterdir() if p.is_file())
    pick = files[:20]
    for p in pick:
        fx["file:" + p.name] = (p.name, p.read_bytes())
    for k in ("text_corpus_v1", "text_corpus_v2", "text_corpus_en"):
        fx["corpus:" + k] = (k + ".txt", ("\n\n".join(corpus_texts(k + ".jsonl"))).encode())
    for i, t in enumerate(corpus_texts("text_corpus_v1.jsonl", "text_corpus_en.jsonl")[::97][:6]):
        fx[f"snip{i}"] = (f"s{i}.txt", t.encode())
    fx["big12_rep"] = ("bench.txt", big_rep(12_000_000))
    fx["big3_var"] = ("bench.txt", big_var(3_000_000))
    return fx


def main():
    cmd = sys.argv[1]
    if cmd == "fp":
        res = {}
        for k, (n, b) in fixtures().items():
            if os.environ.get("S7A_SKIPBIG") and k.startswith("big"): continue
            res[k] = run(n, b); print(k, res[k], flush=True)
        json.dump(res, open(sys.argv[2], "w"), indent=1)
    else:
        kind = sys.argv[2]; mb = float(sys.argv[3]) if len(sys.argv) > 3 else 12
        data = (big_rep if kind == "rep" else big_var)(int(mb * 1e6))
        r0 = resource.getrusage(resource.RUSAGE_SELF); t = time.time()
        h = run("bench.txt", data)
        r1 = resource.getrusage(resource.RUSAGE_SELF)
        print(f"{kind} {mb}MB wall={time.time()-t:.1f} user={r1.ru_utime-r0.ru_utime:.1f} load={os.getloadavg()[0]:.1f} rssGB={r1.ru_maxrss/1e9:.2f} {h}")
main()
