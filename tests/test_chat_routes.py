"""Маршруты чатов: окно программы (HTTP, ключ сеанса) и add-in (HTTPS, токен панели) отдают одни и те же."""
import http.client
import json
import ssl
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

from anonymizer import certs
from anonymizer.addin import create_addin_server
from anonymizer.webapp import create_server

from .helpers import Env

TEXT_A = "Договор подписал Пётр Сидоров. Позвонить Петру Сидорову. Пётр Сидоров согласен."
TEXT_B = "Письмо для Анна Кузнецова."


class RoutesMixin:
    """Общий набор проверок; подкласс задаёт `call(method, path, body=None, json_body=None)`."""

    def jcall(self, method, path, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        status, headers, data = self.call(method, path, body, {"Content-Type": "application/json"})
        try:
            return status, json.loads(data.decode("utf-8")) if data else {}
        except ValueError:
            return status, data

    def anonymize(self, name, text, chat_id=None, options=None):
        """Возвращает завершённое задание; подкласс задаёт `start_anonymize`."""
        return self.finish(self.start_anonymize(name, text.encode("utf-8"), chat_id, options or {}))

    def restore_bytes(self, name, data):
        """Возвращённый файл (байты) для обезличенного `data`."""
        return self.finish_restore(name, data)

    # -- сценарии -------------------------------------------------------------

    def test_list_create_rename_delete(self):
        status, chat = self.jcall("POST", "/api/chats", {"title": "Кейс"})
        self.assertEqual(status, 200)
        self.assertEqual(chat["title"], "Кейс")
        self.assertEqual(chat["files"], [])
        status, listing = self.jcall("GET", "/api/chats")
        self.assertEqual([c["id"] for c in listing["items"]], [chat["id"]])
        status, renamed = self.jcall("POST", f"/api/chats/{chat['id']}", {"title": "Новый кейс", "keep_originals": True})
        self.assertEqual((renamed["title"], renamed["keep_originals"]), ("Новый кейс", True))
        status, _ = self.jcall("DELETE", f"/api/chats/{chat['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(self.jcall("GET", f"/api/chats/{chat['id']}")[0], 404)
        self.assertEqual(self.jcall("GET", "/api/chats")[1]["items"], [])

    def test_job_without_chat_id_still_works_and_reports_its_chat(self):
        job = self.anonymize("a.txt", TEXT_A)
        self.assertEqual(job["state"], "done")
        status, chat = self.jcall("GET", f"/api/chats/{job['chat']}")
        self.assertEqual(status, 200)
        self.assertEqual(len(chat["files"]), 1)
        self.assertTrue(chat["table"])

    def test_job_with_chat_id_goes_into_that_chat(self):
        _, chat = self.jcall("POST", "/api/chats", {"title": "Кейс"})
        job = self.anonymize("a.txt", TEXT_A, chat_id=chat["id"])
        self.assertEqual(job["chat"], chat["id"])
        self.anonymize("b.txt", TEXT_B, chat_id=chat["id"])
        _, full = self.jcall("GET", f"/api/chats/{chat['id']}")
        self.assertEqual(len(full["files"]), 2)
        self.assertEqual([s["kind"] for s in full["steps"]], ["anonymize", "anonymize"])

    def test_internal_fields_are_not_leaked(self):
        job = self.anonymize("a.txt", TEXT_A)
        _, chat = self.jcall("GET", f"/api/chats/{job['chat']}")
        self.assertNotIn("tokens", chat["files"][0])

    def test_download_version_and_open(self):
        job = self.anonymize("a.txt", TEXT_A)
        _, chat = self.jcall("GET", f"/api/chats/{job['chat']}")
        record = chat["files"][0]
        status, headers, data = self.call("GET", f"/api/chats/{chat['id']}/files/{record['id']}/anon")
        self.assertEqual(status, 200)
        self.assertNotIn("Сидоров".encode(), data)
        self.assertIn("attachment", {k.lower(): v for k, v in headers.items()}["content-disposition"])
        self.assertEqual(self.call("GET", f"/api/chats/{chat['id']}/files/{record['id']}/restored")[0], 404)
        self.assertEqual(self.call("GET", f"/api/chats/{chat['id']}/files/{record['id']}/bogus")[0], 404)
        opened = []
        self.app.opener = opened.append
        status, _ = self.jcall("POST", f"/api/chats/{chat['id']}/files/{record['id']}/anon/open", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0].read_bytes(), data)
        self.assertEqual(self.jcall("POST", f"/api/chats/{chat['id']}/files/{record['id']}/restored/open", {})[0], 404)

    def test_delete_erases_files_and_keeps_vault_labels(self):
        job = self.anonymize("a.txt", TEXT_A)
        chat_id = job["chat"]
        entities = dict(self.env.vault.entities)
        self.assertTrue(list((self.env.base / "chats" / chat_id).glob("*.anon.bin")))
        self.jcall("DELETE", f"/api/chats/{chat_id}")
        self.assertFalse((self.env.base / "chats" / chat_id).exists())
        self.assertEqual(self.env.vault.entities, entities)

    # -- правки соответствий --------------------------------------------------

    def person_row(self, chat_id):
        _, chat = self.jcall("GET", f"/api/chats/{chat_id}")
        return next(r for r in chat["table"] if r["kind"] == "PERSON")

    def chat_anon_bytes(self, chat_id):
        _, chat = self.jcall("GET", f"/api/chats/{chat_id}")
        _, _, data = self.call("GET", f"/api/chats/{chat_id}/files/{chat['files'][0]['id']}/anon")
        return data

    def test_edit_value_changes_restore_of_an_old_file(self):
        job = self.anonymize("a.txt", TEXT_A)
        row = self.person_row(job["chat"])
        _, anon = self.jcall("GET", f"/api/chats/{job['chat']}")
        record = anon["files"][0]
        _, _, anon_bytes = self.call("GET", f"/api/chats/{job['chat']}/files/{record['id']}/anon")
        status, result = self.jcall("POST", f"/api/chats/{job['chat']}/entities/{row['base']}",
                                    {"action": "edit", "variant": 1, "value": "Пётр Сидоров-Ларин"})
        self.assertEqual(status, 200, result)
        self.assertTrue(any(v["value"] == "Пётр Сидоров-Ларин" for r in result["table"] for v in r["variants"]))
        restored = self.restore_bytes("anon.txt", anon_bytes)
        self.assertIn("Сидоров-Ларин", restored.decode("utf-8"))
        _, chat = self.jcall("GET", f"/api/chats/{job['chat']}")
        edits = [s for s in chat["steps"] if s["kind"] == "edit"]      # возврат без номера чата тоже попадает в этот чат
        self.assertEqual(edits[-1]["action"], "edit")
        self.assertNotIn("Ларин", json.dumps(chat["steps"], ensure_ascii=False))

    def test_merge_split_keep_hide_forget(self):
        job = self.anonymize("a.txt", TEXT_A + " " + TEXT_B)
        chat_id = job["chat"]
        _, chat = self.jcall("GET", f"/api/chats/{chat_id}")
        persons = [r for r in chat["table"] if r["kind"] == "PERSON"]
        self.assertGreaterEqual(len(persons), 2)
        first, second = persons[0], persons[1]
        status, result = self.jcall("POST", f"/api/chats/{chat_id}/entities/{second['base']}",
                                    {"action": "merge", "into": first["base"]})
        self.assertEqual(status, 200, result)
        self.assertEqual(self.env.vault.describe(second["base"])["base"], first["base"])
        status, result = self.jcall("POST", f"/api/chats/{chat_id}/entities/{first['base']}",
                                    {"action": "split", "variant": len(self.env.vault.describe(first["base"])["variants"])})
        self.assertEqual(status, 200, result)
        self.assertTrue(result["new_base"])
        status, _ = self.jcall("POST", f"/api/chats/{chat_id}/entities/{first['base']}", {"action": "keep", "variant": 1})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.app.chats.terms(chat_id)["keep_terms"]), 1)      # решение живёт в чате,
        self.assertEqual(self.env.vault.prefs.get("keep_terms", []), [])           # общие настройки не тронуты
        status, _ = self.jcall("POST", f"/api/chats/{chat_id}/entities/{first['base']}", {"action": "hide", "term": "Секретное слово"})
        self.assertIn("Секретное слово", self.app.chats.terms(chat_id)["hide_terms"])
        self.assertNotIn("Секретное слово", self.env.vault.prefs.get("hide_terms", []))
        status, result = self.jcall("POST", f"/api/chats/{chat_id}/entities/{first['base']}", {"action": "forget"})
        self.assertEqual(status, 200)
        _, chat = self.jcall("GET", f"/api/chats/{chat_id}")
        self.assertEqual([s["action"] for s in chat["steps"] if s["kind"] == "edit"], ["merge", "split", "keep", "hide", "forget"])

    def test_undo_edit_keep_merge_split_keep_old_files_valid(self):
        """Отмена правки не меняет смысл выданной метки: старый файл возвращается дословно до, после правки и после отмены."""
        job = self.anonymize("a.txt", TEXT_A + " " + TEXT_B)
        chat_id = job["chat"]
        anon_bytes = self.chat_anon_bytes(chat_id)
        original = self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8")
        _, chat = self.jcall("GET", f"/api/chats/{chat_id}")
        persons = [r for r in chat["table"] if r["kind"] == "PERSON"]
        first, second = persons[0], persons[1]
        url = lambda base: f"/api/chats/{chat_id}/entities/{base}"
        # значение: правка, затем отмена возвращает исходное значение
        _, done = self.jcall("POST", url(first["base"]), {"action": "edit", "variant": 1, "value": "Другое Имя"})
        self.assertIsNone(done["undo"]["previous"])
        self.assertIn("Другое Имя", self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8"))
        status, _ = self.jcall("POST", url(first["base"]), {"action": "undo", **done["undo"]})
        self.assertEqual(status, 200)
        self.assertEqual(self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8"), original)
        # слово не скрывать: отмена убирает его из списка
        _, done = self.jcall("POST", url(first["base"]), {"action": "keep", "variant": 1})
        self.assertEqual(len(self.app.chats.terms(chat_id)["keep_terms"]), 1)
        self.jcall("POST", url(first["base"]), {"action": "undo", **done["undo"]})
        self.assertEqual(self.app.chats.terms(chat_id)["keep_terms"], [])
        # слияние и разделение
        _, merged = self.jcall("POST", url(second["base"]), {"action": "merge", "into": first["base"]})
        self.assertEqual(self.env.vault.describe(second["base"])["base"], first["base"])
        self.assertEqual(self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8"), original)
        status, _ = self.jcall("POST", url(second["base"]), {"action": "undo", **merged["undo"]})
        self.assertEqual(status, 200)
        self.assertEqual(self.env.vault.describe(second["base"])["base"], second["base"])
        self.assertEqual(self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8"), original)
        variants = len(self.env.vault.describe(first["base"])["variants"])
        if variants > 1:
            _, split = self.jcall("POST", url(first["base"]), {"action": "split", "variant": variants})
            self.assertEqual(self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8"), original)
            status, _ = self.jcall("POST", url(first["base"]), {"action": "undo", **split["undo"]})
            self.assertEqual(status, 200)
            self.assertEqual(self.restore_bytes("a-anon.txt", anon_bytes).decode("utf-8"), original)
        # забыть метку отменить нельзя
        status, _ = self.jcall("POST", url(first["base"]), {"action": "undo", "of": "forget"})
        self.assertEqual(status, 400)
        _, chat = self.jcall("GET", f"/api/chats/{chat_id}")
        self.assertIn("undo", [s["action"] for s in chat["steps"] if s["kind"] == "edit"])

    def test_entity_edit_errors(self):
        job = self.anonymize("a.txt", TEXT_A)
        chat_id = job["chat"]
        base = self.person_row(chat_id)["base"]
        for body, expected in (({"action": "bogus"}, 400), ({"action": "edit", "variant": 1, "value": " "}, 400),
                               ({"action": "edit", "variant": 99, "value": "x"}, 400), ({"action": "merge", "into": base}, 400),
                               ({"action": "merge", "into": "Name99"}, 400)):
            self.assertEqual(self.jcall("POST", f"/api/chats/{chat_id}/entities/{base}", body)[0], expected, body)
        self.assertEqual(self.jcall("POST", f"/api/chats/{chat_id}/entities/Name99", {"action": "forget"})[0], 404)
        self.assertEqual(self.jcall("POST", f"/api/chats/{chat_id}/entities/{base}%2F..", {"action": "forget"})[0], 404)

    # -- применить правки -----------------------------------------------------

    def test_apply_refuses_without_originals(self):
        self.env.vault.set_prefs(keep_originals=False)
        job = self.anonymize("a.txt", TEXT_A)
        status, result = self.jcall("POST", f"/api/chats/{job['chat']}/apply", {})
        self.assertEqual(status, 400)
        self.assertIn("Хранить оригиналы", result["error"])

    def test_apply_reruns_stored_originals_and_replaces_the_versions(self):
        _, chat = self.jcall("POST", "/api/chats", {"title": "Кейс", "keep_originals": True})
        job = self.anonymize("a.txt", TEXT_A, chat_id=chat["id"])
        self.env.vault.add_term("hide_terms", "согласен")
        status, started = self.jcall("POST", f"/api/chats/{chat['id']}/apply", {})
        self.assertEqual(status, 200, started)
        self.app.runners[started["job"]].join(30)
        self.assertEqual(self.app.job_public(started["job"])["state"], "done")
        _, full = self.jcall("GET", f"/api/chats/{chat['id']}")
        self.assertEqual(len(full["files"]), 1)                  # версия заменена, дубля нет
        _, _, anon = self.call("GET", f"/api/chats/{chat['id']}/files/{full['files'][0]['id']}/anon")
        self.assertNotIn("согласен".encode(), anon)
        self.assertEqual([s["kind"] for s in full["steps"]], ["anonymize", "anonymize"])

    def test_routes_need_auth(self):
        status, _, _ = self.call("GET", "/api/chats", auth=False)
        self.assertEqual(status, 403)
        status, _, _ = self.call("DELETE", "/api/chats/abcdef", auth=False)
        self.assertEqual(status, 403)


class WindowRoutesTests(RoutesMixin, unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.server, self.app = create_server(self.env.vault, self.env.base / "work")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.cleanup_open()
        self.env.close()

    def call(self, method, path, body=None, headers=None, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        head = {"Host": f"127.0.0.1:{self.port}"}
        if auth:
            head.update({"Cookie": f"anon_t={self.app.token}", "X-Requested-With": "anonymizer"})
        head.update(headers or {})
        conn.request(method, path, body=body, headers=head)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def upload(self, name, data):
        status, _, body = self.call("POST", "/api/upload", data, {"X-Filename": urllib.parse.quote(name)})
        self.assertEqual(status, 200, body)
        return json.loads(body)["id"]

    def finish(self, started):
        for _ in range(300):
            _, info = self.jcall("GET", f"/api/jobs/{started}")
            if info["state"] != "running":
                return info
            time.sleep(0.05)
        self.fail("задание не завершилось")

    def start_anonymize(self, name, data, chat_id, options):
        body = {"files": [self.upload(name, data)], "options": options}
        if chat_id:
            body["chat_id"] = chat_id
        status, started = self.jcall("POST", "/api/anonymize", body)
        self.assertEqual(status, 200, started)
        return started["job"]

    def finish_restore(self, name, data):
        _, started = self.jcall("POST", "/api/restore", {"files": [self.upload(name, data)]})
        done = self.finish(started["job"])
        return self.call("GET", f"/api/download/{done['id']}/0")[2]

    def test_unknown_chat_id_is_404(self):
        upload = self.upload("a.txt", TEXT_A.encode("utf-8"))
        status, _ = self.jcall("POST", "/api/anonymize", {"files": [upload], "chat_id": "nosuchchat1"})
        self.assertEqual(status, 404)


class AddinRoutesTests(RoutesMixin, unittest.TestCase):
    """Те же маршруты в add-in: страница чата открывается из панели Office во всплывающем окне.
    Задания в панели идут своими маршрутами `/api/addin/*`, поэтому здесь они запускаются через App."""

    def setUp(self):
        self.env = Env()
        from anonymizer.webapp import App
        self.app = App(self.env.vault, self.env.base / "work", "tok")
        self.dir = self.env.base / "addin"
        self.files = certs.ensure_certs(self.dir, self.env.key)
        self.server, self.api = create_addin_server(self.app, port=0, files=self.files, directory=self.dir, key=self.env.key)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ctx = ssl.create_default_context(cafile=str(self.files.ca_cert))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.cleanup_open()
        self.env.close()

    def call(self, method, path, body=None, headers=None, auth=True):
        conn = http.client.HTTPSConnection("localhost", self.port, context=self.ctx, timeout=30)
        head = {"Host": f"localhost:{self.port}"}
        if auth:
            head.update({"X-Requested-With": "anonymizer", "X-Addin-Token": self.api.token})
        head.update(headers or {})
        conn.request(method, path, body=body, headers=head)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def finish(self, job_id):
        self.app.runners[job_id].join(30)
        return self.app.job_public(job_id)

    def start_anonymize(self, name, data, chat_id, options):
        upload = self.app.add_upload(name, data)["id"]
        return self.app.start_job("anonymize", [upload], options, chat_id=chat_id)

    def finish_restore(self, name, data):
        upload = self.app.add_upload(name, data)["id"]
        job_id = self.app.start_job("restore", [upload], {})
        self.finish(job_id)
        return Path(self.app.service.jobs[job_id].files[0].out_path).read_bytes()


if __name__ == "__main__":
    unittest.main()
