"""Run selected en_corpus files end to end: python tools/en_one.py table_txt_0.txt ...  (prints leaks / restore equality)."""
import sys, json
from pathlib import Path
sys.path.insert(0, ".")
sys.path.insert(0, "tools")
import make_en_corpus as M

man = {m["id"]: m for m in json.loads(Path("tests/eval/en_corpus/gold.json").read_text())}
for fid in sys.argv[1:]:
    r = M.one(Path("tests/eval/en_corpus/files") / fid, man[fid])
    print(fid, "leaks=", r.get("leaks"), "restore=", r.get("restore_equal"), r.get("status"), r.get("crash", ""))
