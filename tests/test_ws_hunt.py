"""Охота на ошибки: тихие необратимые действия и расхождения интерфейса с реальным состоянием."""
import re
import unittest
from pathlib import Path

from anonymizer import chat_api
from anonymizer.chats import ChatStore

from .helpers import Env

WEB = Path(__file__).resolve().parent.parent / "anonymizer" / "web" / "index.html"


class KeepOriginalsConfirmTests(unittest.TestCase):
    def test_turning_off_keep_originals_is_confirmed_in_the_page(self):
        """Снятие галочки стирает сохранённые оригиналы сразу: страница обязана спросить, если они есть."""
        html = WEB.read_text(encoding="utf-8")
        handler = html[html.index('$("#chat-keep").onchange'):]
        handler = handler[:handler.index("async function deleteChat")]
        self.assertIn("await ask(", handler)
        self.assertRegex(handler, r"roles\.orig")
        self.assertIn("danger: true", handler)

    def test_public_chat_exposes_stored_original_role(self):
        """Страница считает оригиналы по `files[].roles.orig`: поле должно доходить до неё."""
        env = Env()
        try:
            store = ChatStore(env.base / "chats", env.key)
            chat = store.create("t", keep_originals=True)
            record = store.add_file(chat["id"], "a.txt", "TEXT")
            store.save_blob(chat["id"], record["id"], "orig", b"secret")
            public = chat_api.public(store.get(chat["id"]))
            self.assertIn("orig", public["files"][0]["roles"])
            store.set_keep_originals(chat["id"], False)
            public = chat_api.public(store.get(chat["id"]))
            self.assertNotIn("orig", public["files"][0]["roles"])
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
