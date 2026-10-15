"""S8B: NER inference proof/bench. Fingerprints of ner._raw_spans / person_spans on fixtures.

  python tools/s8b_proof.py fp OUT.json [--real]      # sha of (start,end,round(conf,3)) per fixture
  python tools/s8b_proof.py bench [MB]                # time person_spans on synthetic Russian prose
Fixtures: synthetic corpora (tests/eval/text_corpus_v1/v2.jsonl), real RU docs under tests/eval/real (never case/).
"""
import sys, os, json, time, hashlib, resource, random, re
sys.path.insert(0, ".")
from pathlib import Path
from anonymizer import ner
ner.MAX_TEXT = max(ner.MAX_TEXT, 10**9)   # base has a 400k skip; lift it so the 3 MB fixture compares


def corpus(*names):
    out = []
    for n in names:
        for line in open(f"tests/eval/{n}", encoding="utf-8"):
            out.append(json.loads(line)["text"])
    return out


def prose(size, seed=5):
    rnd = random.Random(seed)
    parts = [t for t in corpus("text_corpus_v1.jsonl", "text_corpus_v2.jsonl") if len(t) > 60]
    out, n = [], 0
    while n < size:
        t = rnd.choice(parts)
        t = re.sub(r"\d", lambda m: str(rnd.randrange(10)), t)
        out.append(t); n += len(t) + 2
    return "\n\n".join(out)[:size]


def table(size):
    rows = ["Иванов Пётр Сергеевич\tдиректор\tМосква", "Свидетель Кувшинов подтвердил показания.", "Заявитель: Тарнов Андрей Олегович",
            "Договор подписал директор Мерцов в присутствии свидетелей."]
    out, n = [], 0
    while n < size:
        out.append(rows[len(out) % len(rows)]); n += len(out[-1]) + 1
    return "\n".join(out)


def real_texts(limit=20):
    res = []
    for d in sorted(Path("tests/eval/real").iterdir()):
        if "_ru_" not in d.name or d.name.startswith("cm_") or not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in (".txt", ".md", ".html", ".csv", ".json", ".tsv", ".xml"):
                t = p.read_text("utf-8", "replace")
                if p.suffix.lower() in (".html", ".xml", ".md"):
                    t = re.sub(r"<[^>]+>|[#*`|]", " ", t)
                    t = re.sub(r"[ \t]+", " ", t)
                if len(re.findall(r'[А-Яа-яЁё]', t[:200_000])) > 3000:   # raw spans are compared even where person_spans would call the text ineligible
                    res.append((d.name + "/" + p.name, t[:400_000]))
    return res[:limit]



def fp(spans):
    return hashlib.sha256(";".join(f"{s},{e},{c:.3f}" for s, e, c in spans).encode()).hexdigest()[:16]


def main():
    cmd = sys.argv[1]
    if cmd == "fp":
        res = {}
        fx = {}
        for name, t in real_texts():
            fx["real:" + name] = t
        full = Path("tests/eval/real/md_ru_putin").glob("*.md")
        for q in full:
            tt = re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>|[#*`|]", " ", q.read_text("utf-8", "replace")))
            fx["real:md_putin_tail"] = tt[400_000:]
            fx["real:md_putin_mid"] = tt[150_000:250_000]
        if os.environ.get("S8B_SKIPBIG"):
            pass
        fx["prose3mb"] = prose(3_000_000)
        fx["table1mb"] = table(1_000_000)
        for k, t in fx.items():
            if os.environ.get("S8B_SKIPBIG") and k in ("prose3mb", "table1mb"):
                continue
            t0 = time.time()
            raw = ner._raw_spans(t)
            ps = ner.person_spans(t)
            res[k] = [len(t), len(raw), fp(raw), len(ps), fp(ps)]
            print(k, res[k], f"{time.time()-t0:.1f}s", flush=True)
        json.dump(res, open(sys.argv[2], "w"), indent=1)
    else:
        mb = float(sys.argv[2]) if len(sys.argv) > 2 else 1
        t = prose(int(mb * 1e6))
        ner._load()
        r0 = resource.getrusage(resource.RUSAGE_SELF); t0 = time.time()
        raw = ner._raw_spans(t)
        r1 = resource.getrusage(resource.RUSAGE_SELF)
        print(f"{mb}MB wall={time.time()-t0:.1f} user={r1.ru_utime-r0.ru_utime:.1f} load={os.getloadavg()[0]:.1f} rssGB={r1.ru_maxrss/1e9:.2f} spans={len(raw)} {fp(raw)}")


main()
