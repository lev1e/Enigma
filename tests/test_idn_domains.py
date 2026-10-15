"""Русские домены, URL и адреса почты на них: замена и возврат без потерь."""
from __future__ import annotations

import unittest

from tests.helpers import Env
from tests.test_review_fixes import make_app, run_job

TEXT = ("Сайт https://пример.рф/страница и москва.рф, www.пример.рф, ivan@пример.рф, иван@почта.рф, "
        "xn--e1afmkfd.xn--p1ai, а также т.е. и г.Москва, файл a.docx.\n")


class IdnDomains(unittest.TestCase):
    def test_hidden_and_restored(self):
        env = Env(); self.addCleanup(env.close)
        app = make_app(env); self.addCleanup(app.cleanup_open)
        chat = app.chats.create("a", keep_originals=True)["id"]
        run_job(app, "anonymize", [("a.txt", TEXT)], chat_id=chat, options={})
        rec = app.chats.get(chat)["files"][-1]
        out = app.chats.read_blob(chat, rec["id"], "anon").decode()
        for leak in ("пример", "москва.рф", "почта", "иван@", "ivan@", "xn--"):
            self.assertNotIn(leak, out)
        self.assertIn("т.е.", out)                      # сокращения не принимаются за домены


if __name__ == "__main__":
    unittest.main()
