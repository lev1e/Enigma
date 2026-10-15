"""S6D speed bench: python tools/s6d_bench.py pdf|txt [--prof] -> seconds, RSS, hash of output text.
Output hashes (invisible per-job tag U+E0000..E007F stripped; PDF: per-page text) prove identical output before/after."""
import sys, os, json, time, hashlib, resource, random
sys.path.insert(0, ".")
from tests.helpers import Env


def sparse_pdf(pages: int = 100) -> bytes:
    import fitz
    rnd = random.Random(7)
    names = ["Ivan Petrov", "Maria Sidorova", "John Smith", "Anna Kowalski"]
    doc = fitz.open()
    for i in range(pages):
        p = doc.new_page()
        p.insert_text((72, 100), f"Page {i + 1}", fontsize=14)
        p.insert_text((72, 140), f"Contact {rnd.choice(names)} tel +1 415 555 {1000 + i}", fontsize=11)
        if i % 3 == 0:
            p.insert_text((72, 180), f"email user{i}@example.org", fontsize=11)
    b = doc.tobytes(); doc.close(); return b


def big_txt(size: int = 12_000_000) -> bytes:
    parts, n = [], 0
    for line in open("tests/eval/text_corpus_v1.jsonl", encoding="utf-8"):
        t = json.loads(line)["text"] + "\n\n"
        parts.append(t); n += len(t.encode())
    out, n2, i = [], 0, 0
    while n2 < size:
        t = parts[i % len(parts)]; out.append(t); n2 += len(t.encode()); i += 1
    return "".join(out).encode()[:size]


def strip(s): return "".join(c for c in s if not 0xE0000 <= ord(c) <= 0xE007F)


def main():
    kind = sys.argv[1]; prof = "--prof" in sys.argv
    data = sparse_pdf() if kind == "pdf" else big_txt()
    name = "bench." + kind
    env = Env()
    import cProfile, pstats
    pr = cProfile.Profile() if prof else None
    t = time.time(); l0 = os.getloadavg()[0]
    if pr: pr.enable()
    job = env.anonymize((name, data))
    if pr: pr.disable()
    dt = time.time() - t
    out = env.output(job)
    if kind == "pdf":
        import fitz
        d = fitz.open(out)
        hs = [hashlib.sha256(strip(pg.get_text()).encode()).hexdigest()[:12] for pg in d]
        h = hashlib.sha256("".join(hs).encode()).hexdigest()
    else:
        h = hashlib.sha256(strip(out.read_bytes().decode("utf-8", "replace")).encode()).hexdigest()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
    print(f"{kind} {dt:.1f}s load_before={l0:.1f} load_after={os.getloadavg()[0]:.1f} rssGB={rss:.2f} hash={h}")
    if pr:
        pstats.Stats(pr).sort_stats("cumulative").print_stats(70)
main()
