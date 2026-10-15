"""Print every finding (AUTO and review) for text from argv[1] or stdin."""
import sys

sys.path.insert(0, ".")
from tests.helpers import Env  # noqa: E402

text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
e = Env()
d = e.service.build_detector(e.service.settings_for({}))
d.harvest(text, "x.txt")
for f in sorted(d.scan(text, "x.txt", "text"), key=lambda f: f.start):
    print(f"{f.decision.value:7}{f.category:16}{f.confidence:.2f} {f.original!r}  [{f.reason[:50]}]")
