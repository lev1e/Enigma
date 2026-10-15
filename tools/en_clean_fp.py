"""False positives on clean English prose that carries no personal data: Python's own pydoc topics (technical prose), the Zen of Python, licences.

  python tools/en_clean_fp.py [max_chars]   -> AUTO findings per 1000 words and the most common wrongly hidden strings
"""
import sys, collections, re, importlib, pydoc_data.topics as T
sys.path.insert(0, ".")
from tests.helpers import Env

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 150000
texts = []
body = "\n\n".join(T.topics.values())
body = re.sub(r"[ \t]+\n", "\n", body)
for i in range(0, min(len(body), limit), 20000):
    texts.append(body[i:i + 20000])
import this, io, contextlib                                            # noqa: E401
env = Env(); words = 0; hits = []
for t in texts:
    det = env.service.build_detector(env.service.settings_for({}))
    det.harvest(t, "x.txt")
    fs = [f for f in det.scan(t, "x.txt", "text") if f.decision.value == "AUTO"]
    words += len(t.split()); hits += [(f.category, f.original.strip()) for f in fs]
print(f"{len(texts)} chunks, {words} words, AUTO findings={len(hits)} ({1000 * len(hits) / max(1, words):.2f} per 1000 words)")
for k, n in collections.Counter(hits).most_common(45):
    print(n, k)
