"""Proof that a speed change leaves detection untouched.

  python tools/perf_compare.py dump OUT.json     findings on corpora v1+v2+en, byte hashes of anonymized real txt/csv/md/html
  python tools/perf_compare.py diff A.json B.json  exits 1 on any difference

Run `dump` before and after a change and `diff` the two files.
"""
import sys, os, json, hashlib, glob, time
sys.path.insert(0, ".")
from tests.helpers import Env

CORPORA = ["tests/eval/text_corpus_v1.jsonl", "tests/eval/text_corpus_v2.jsonl", "tests/eval/text_corpus_en.jsonl"]
REAL_EXT = {".txt", ".csv", ".md", ".html", ".htm"}
MAX_REAL = 3_000_000


def corpus_findings(env):
    out = {}
    for path in CORPORA:
        for line in open(path, encoding="utf-8"):
            case = json.loads(line)
            text = case["text"]
            d = env.service.build_detector(env.service.settings_for({}))
            d.harvest(text, "x.txt")
            found = d.scan(text, "x.txt", "text")
            out[os.path.basename(path) + ":" + case["id"]] = [
                [f.start, f.end, f.category, str(f.decision), f.person_id, f.original, round(f.confidence, 4), f.reason]
                for f in found]
    return out


def real_hashes(env):
    out = {}
    for path in sorted(glob.glob("tests/eval/real/**/*", recursive=True)):
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in REAL_EXT:
            continue
        if os.path.getsize(path) > MAX_REAL:
            continue
        name = os.path.relpath(path, "tests/eval/real")
        t = time.time()
        try:
            data = open(path, "rb").read()
            job = env.anonymize((os.path.basename(path), data))
            # every job stamps a random invisible tag (U+E0000..E007F) into the output: strip it before hashing
            body = "".join(c for c in env.output_bytes(job).decode("utf-8", "replace") if not 0xE0000 <= ord(c) <= 0xE007F)
            h = hashlib.sha256(body.encode("utf-8")).hexdigest() if job.files and job.files[0].out_path else "none"
        except Exception as exc:  # noqa
            h = "ERR " + type(exc).__name__
        out[name] = h
        print("  %-60s %5.1fs" % (name[:60], time.time() - t), file=sys.stderr)
    return out


def main():
    if sys.argv[1] == "dump":
        env = Env()
        res = {"corpus": corpus_findings(env), "real": real_hashes(env)}
        json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, sort_keys=True)
        print("corpus cases", len(res["corpus"]), "real files", len(res["real"]))
    else:
        a, b = (json.load(open(p)) for p in sys.argv[2:4])
        bad = 0
        for part in ("corpus", "real"):
            for k in sorted(set(a[part]) | set(b[part])):
                if a[part].get(k) != b[part].get(k):
                    bad += 1
                    print("DIFF", part, k)
        print("differences:", bad)
        sys.exit(1 if bad else 0)


main()
