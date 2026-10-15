"""Why is restore not equal: python tools/en_restore.py prose_md_1.md  (text formats: prints differing lines; office: differing units)"""
import sys, json, difflib, tempfile
from pathlib import Path
sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from tests.helpers import Env

fid = sys.argv[1]
path = Path("tests/eval/en_corpus/files") / fid
data = path.read_bytes()
env = Env(**({"retain_secrets_for_restore": True} if path.suffix == ".pdf" else {}))
job = env.anonymize((path.name, data))
f = job.files[0]
out = Path(f.out_path).read_bytes()
rj = env.restore(env.as_upload(job))
back = Path(rj.files[0].out_path).read_bytes()
ext = path.suffix.lower()
if ext in (".docx", ".xlsx", ".pptx"):
    from tests.helpers import content_units
    with tempfile.TemporaryDirectory() as t:
        pa, pb = Path(t) / ("a" + ext), Path(t) / ("b" + ext)
        pa.write_bytes(data); pb.write_bytes(back)
        ua, ub = content_units(pa), content_units(pb)
    for k in sorted(set(ua) | set(ub)):
        if ua.get(k) != ub.get(k):
            print("UNIT", k, "\n  A:", repr(ua.get(k))[:400], "\n  B:", repr(ub.get(k))[:400])
elif ext == ".pdf":
    import fitz
    a = "\n".join(p.get_text() for p in fitz.open(stream=data, filetype="pdf"))
    b = "\n".join(p.get_text() for p in fitz.open(stream=back, filetype="pdf"))
    for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0):
        print(l[:300])
else:
    a, b = data.decode("utf-8", "ignore"), back.decode("utf-8", "ignore")
    for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0):
        print(l[:400])
    print("STATUS", f.status)
    if "-v" in sys.argv:
        print(out.decode("utf-8", "ignore")[:2500])
if data != back:
    import itertools
    i = next((k for k, (x, y) in enumerate(zip(data, back)) if x != y), min(len(data), len(back)))
    print("BYTES DIFFER at", i, len(data), len(back), repr(data[max(0, i - 60):i + 60]), repr(back[max(0, i - 60):i + 60]))
sm = difflib.SequenceMatcher(None, a if ext not in (".docx", ".xlsx", ".pptx", ".pdf") else "", b if ext not in (".docx", ".xlsx", ".pptx", ".pdf") else "", autojunk=False)
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag != "equal":
        print(tag, repr(a[i1 - 15:i2 + 15]), "->", repr(b[j1 - 15:j2 + 15]))
