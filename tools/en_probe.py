"""Show detector findings for text: python tools/en_probe.py "some text" | python tools/en_probe.py -f file.txt"""
import sys
sys.path.insert(0, ".")
from tests.helpers import Env

text = open(sys.argv[2], encoding="utf-8").read() if sys.argv[1] == "-f" else sys.argv[1]
env = Env()
d = env.service.build_detector(env.service.settings_for({}))
d.harvest(text, "x.txt")
for f in d.scan(text, "x.txt", "text"):
    print(f.decision.value, f.category, getattr(f,"reason",""), repr(f.original), "|", text[max(0, f.start - 25):f.end + 15].replace("\n", " "))
