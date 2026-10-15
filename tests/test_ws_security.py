"""Безопасность сервиса и add-in: исходники не лежат на диске, токен не раздаётся, остатки не переживают срок."""
import json
import os
import time
import unittest

from anonymizer.service import JobCancelled, Service, Upload

from .helpers import Env

TEXT = "Согласовано Мария Иванова, m.ivanova@example.org"


def files_under(path):
    return [p for p in path.rglob("*") if p.is_file()] if path.exists() else []


class OriginalsNotLeftOnDisk(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def inputs(self):
        work = self.env.service.workdir
        return [p for p in files_under(work) if p.relative_to(work).parts[1:2] == ("in",)]

    def test_inputs_removed_after_success(self):
        job = self.env.anonymize(("a.txt", TEXT))
        self.assertEqual(job.state, "done")
        self.assertEqual(self.inputs(), [])
        self.assertTrue(files_under(job.dir / "out"))

    def test_inputs_removed_after_restore(self):
        job = self.env.anonymize(("a.txt", TEXT))
        restored = self.env.restore(self.env.as_upload(job))
        self.assertEqual(restored.state, "done")
        self.assertEqual(self.inputs(), [])

    def test_inputs_removed_after_cancel(self):
        job = self.env.service.new_job("anonymize", {})
        job.cancel = True
        with self.assertRaises(JobCancelled):
            self.env.service.anonymize([Upload("a.txt", TEXT.encode())], {}, None, job=job)
        self.assertEqual(self.inputs(), [])

    def test_inputs_removed_after_failure(self):
        job = self.env.service.new_job("anonymize", {})
        original = self.env.service._pass

        def boom(*a, **k):
            raise RuntimeError("boom")
        self.env.service._pass = boom
        with self.assertRaises(RuntimeError):
            self.env.service.anonymize([Upload("a.txt", TEXT.encode())], {}, None, job=job)
        self.env.service._pass = original
        self.assertEqual(self.inputs(), [])

    def test_rerun_keeps_working_without_files_on_disk(self):
        job = self.env.anonymize(("a.txt", TEXT))
        again = self.env.service.rerun(job.id, {}, {})
        self.assertEqual(again.state, "done")
        self.assertEqual(self.inputs(), [])

    def test_stale_inputs_swept_on_start(self):
        work = self.env.base / "work"
        stale = work / "deadbeef0000" / "in" / "0"
        stale.mkdir(parents=True)
        (stale / "secret.txt").write_text(TEXT)
        old = time.time() - 3600
        os.utime(stale.parent, (old, old))
        Service(self.env.vault, work)
        self.assertFalse((work / "deadbeef0000" / "in").exists())


if __name__ == "__main__":
    unittest.main()


class RetentionPurgesFileNames(unittest.TestCase):
    def test_old_original_names_and_history_files_are_purged(self):
        env = Env(retention_days=30)
        try:
            job = env.anonymize(("Иванов Мария Отчет.txt", TEXT))
            number = next(iter(env.vault.file_names))
            self.assertEqual(env.vault.file_names[number], "Иванов Мария Отчет.txt")
            old = time.time() - 40 * 86400
            env.vault.file_times[number] = old
            for entry in env.vault.history:
                entry["time"] = old
            env.vault.dirty = True
            env.vault.commit()
            again = env.reopen()
            self.assertEqual(again.vault.file_names, {})
            self.assertTrue(all(not e.get("files") for e in again.vault.history))
            self.assertNotIn("Иванов Мария", repr(again.vault._payload()))
            again.close()
        finally:
            env.close()

    def test_recent_names_survive(self):
        env = Env(retention_days=30)
        try:
            env.anonymize(("Отчет.txt", TEXT))
            again = env.reopen()
            self.assertEqual(list(again.vault.file_names.values()), ["Отчет.txt"])
        finally:
            env.close()


class VerifyDocumentLeaks(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def book(self, name, text, defined=None):
        from openpyxl import Workbook
        from openpyxl.workbook.defined_name import DefinedName
        wb = Workbook()
        wb.active["A1"] = text
        if defined:
            wb.defined_names["Client"] = DefinedName("Client", attr_text=defined)
        path = self.dir / name
        wb.save(path)
        return path

    def test_defined_name_leak_is_reported(self):
        from anonymizer.addin import verify_document
        expected = self.book("e.xlsx", "Name1")
        actual = self.book("a.xlsx", "Name1", defined='"Мария Иванова"')
        verdict = verify_document(expected, actual, ["Мария Иванова"])
        self.assertFalse(verdict["ok"], verdict)
        self.assertIn("leak", [p["code"] for p in verdict["problems"]])

    def test_lone_surname_leak_is_reported(self):
        from anonymizer.addin import verify_document
        expected = self.book("e.xlsx", "Согласовано Name1")
        actual = self.book("a.xlsx", "Согласовано Name1 Иванова")
        verdict = verify_document(expected, actual, ["Мария Иванова"])
        self.assertFalse(verdict["ok"], verdict)

    def test_clean_document_is_still_ok(self):
        from anonymizer.addin import verify_document
        expected = self.book("e.xlsx", "Согласовано Name1")
        actual = self.book("a.xlsx", "Согласовано Name1")
        self.assertTrue(verify_document(expected, actual, ["Мария Иванова"])["ok"])

    def test_kept_word_present_in_expected_is_not_a_leak(self):
        from anonymizer.addin import verify_document
        expected = self.book("e.xlsx", "Name1 Иванова")        # «Иванова» оставлена по решению человека
        actual = self.book("a.xlsx", "Name1 Иванова")
        self.assertTrue(verify_document(expected, actual, ["Мария Иванова"])["ok"])


class RerunKeepsState(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_vault_edit_after_job_survives_rerun(self):
        job = self.env.anonymize(("a.txt", TEXT))
        base = next(b for b, e in self.env.vault.entities.items() if e["kind"] == "PERSON")
        self.env.vault.entities[base]["spellings"].append("Мариечка Иванова")      # правка человека после задания
        self.env.vault.dirty = True
        self.env.service.rerun(job.id, {}, {})
        self.assertIn("Мариечка Иванова", self.env.vault.entities[base]["spellings"])

    def test_unchanged_vault_still_rolls_back_wasted_tokens(self):
        job = self.env.anonymize(("a.txt", TEXT))
        before = dict(self.env.vault.counters)
        again = self.env.service.rerun(job.id, {}, {})
        self.assertEqual(again.state, "done")
        self.assertEqual(self.env.vault.counters, before)

    def test_removed_chat_setting_is_not_carried_into_rerun(self):
        job = self.env.service.new_job("anonymize", {"strict": True, "hide_terms": ["Секрет"], "numbers": False})
        self.env.service.anonymize([Upload("a.txt", TEXT.encode())], {"strict": True, "hide_terms": ["Секрет"], "numbers": False}, None, job=job)
        again = self.env.service.rerun(job.id, {"numbers": True}, {})
        self.assertNotIn("strict", again.options)
        self.assertNotIn("Секрет", again.options.get("hide_terms") or [])
        self.assertEqual(again.options["numbers"], True)

    def test_overrides_accumulate_across_reruns(self):
        job = self.env.anonymize(("a.txt", TEXT))
        second = self.env.service.rerun(job.id, {}, {"слово": "hide"})
        third = self.env.service.rerun(second.id, {}, {"другое": "keep"})
        self.assertEqual(third.options["overrides"], {"слово": "hide", "другое": "keep"})


class CrossVaultCsv(unittest.TestCase):
    CSV = "ФИО,Почта\nМария Иванова,m.ivanova@example.org\n"

    def test_csv_round_trip_is_exact_and_foreign_vault_is_refused(self):
        env, other = Env(), Env()
        try:
            job = env.anonymize(("t.csv", self.CSV))
            out = env.output_bytes(job).decode("utf-8")
            self.assertNotIn("Иванова", out)
            self.assertEqual(env.output_bytes(env.restore(env.as_upload(job))).decode("utf-8"), self.CSV)
            foreign = other.restore(env.as_upload(job))
            self.assertEqual(foreign.files[0].status, "error")
            self.assertIn("другим хранилищем", " ".join(m["text"] for m in foreign.files[0].messages))
        finally:
            env.close()
            other.close()

    def test_csv_without_marker_restores_as_before(self):
        env = Env()
        try:
            job = env.anonymize(("t.csv", self.CSV))
            plain = "".join(ch for ch in env.output_bytes(job).decode("utf-8") if not 0xE0000 <= ord(ch) <= 0xE007F)
            restored = env.restore(("t (обезличено).csv", plain.encode("utf-8")))
            self.assertEqual(env.output_bytes(restored).decode("utf-8"), self.CSV)
        finally:
            env.close()


class ArchiveSafety(unittest.TestCase):
    def test_zip_bomb_is_refused_before_processing(self):
        import io
        import zipfile
        from anonymizer import service as svc
        env = Env()
        old = svc.MAX_UNPACKED_BYTES
        try:
            svc.MAX_UNPACKED_BYTES = 50_000
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("[Content_Types].xml", "<Types/>")
                z.writestr("word/document.xml", b"\0" * 5_000_000)      # сжимается в несколько КБ
            self.assertLess(len(buffer.getvalue()), 50_000)
            job = env.anonymize(("bomb.docx", buffer.getvalue()))
            self.assertEqual(job.files[0].status, "error")
            self.assertIn("слишком велик", " ".join(m["text"] for m in job.files[0].messages))
            info = env.service.peek(Upload("bomb.docx", buffer.getvalue()))
            self.assertFalse(info["supported"])
        finally:
            svc.MAX_UNPACKED_BYTES = old
            env.close()

    def test_project_paths_cannot_escape_the_target_folder(self):
        from anonymizer.folders import _record_layout
        env = Env()
        try:
            chat = {"files": [{"id": "1", "roles": {"anon": {}, "restored": {}}, "name": name} for name in (
                "../../evil/x.txt", "a/../../b.txt", "..\\..\\c.txt", "/abs/olute/d.txt", "C:\\Windows\\e.txt", "..")]}
            for role in ("anon", "restored"):
                for _, dirs, name in _record_layout(env.vault, chat, role):
                    for part in (*dirs, name):
                        self.assertNotIn("..", part.replace("...", ""), (role, dirs, name))
                        self.assertFalse(set(part) & set("/\\:"), (role, dirs, name))
                        self.assertNotEqual(part, "", (role, dirs, name))
        finally:
            env.close()


from .test_addin import AddinCase


class AddinTokenBinding(AddinCase):
    def test_page_without_pane_key_gets_no_token(self):
        for path in ("/addin/taskpane.html", "/addin/taskpane.html?k=wrong", "/addin/taskpane.html?k="):
            status, _, data = self.call("GET", path, auth=False)
            self.assertEqual(status, 403, path)
            self.assertNotIn(self.api.token.encode(), data)

    def test_page_with_pane_key_carries_token(self):
        status, _, data = self.call("GET", self.pane_url(), auth=False)
        self.assertEqual(status, 200)
        self.assertIn(self.api.token.encode(), data)

    def test_manifest_points_to_keyed_url_and_refresh_rewrites_it(self):
        from anonymizer import addin_install
        manifest = addin_install.render_manifest()
        self.assertEqual(manifest.count("taskpane.html?k="), 2)
        self.assertNotIn("{PANE_KEY}", manifest)

    def test_addin_rerun_with_wrong_types_is_400(self):
        for payload in ({"job": ["x"]}, {"job": 5}, {"job": "zzz", "options": "no"}, {"job": "zzz", "overrides": 7}):
            status, _, _ = self.call("POST", "/api/addin/rerun", json.dumps(payload).encode())
            self.assertEqual(status, 400, payload)

    def test_concurrent_addin_jobs_do_not_mix_documents(self):
        import urllib.parse
        from concurrent.futures import ThreadPoolExecutor
        from .helpers import docx_bytes, docx_text
        people = ["Смирнов Алексей Петрович", "Кузнецова Ольга Игоревна", "Орлов Дмитрий Сергеевич", "Волкова Анна Павловна"]

        def run(person):
            data = docx_bytes([f"Договор подписал {person}."])
            status, started = self.json("POST", "/api/addin/anonymize", data, {
                "X-Filename": urllib.parse.quote(f"{person.split()[0]}.docx"), "X-Options": "%7B%7D"})
            assert status == 200, started
            for _ in range(600):
                _, job = self.json("GET", f"/api/addin/jobs/{started['job']}")
                if job["state"] != "running":
                    return person, started["job"], job
                time.sleep(.1)
            return person, started["job"], {"state": "timeout"}
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(run, people))
        outputs = {}
        for person, job_id, job in results:
            self.assertEqual(job["state"], "done", (person, job))
            outputs[person] = docx_text(self.result(job_id))
        for person, text in outputs.items():
            for other in people:
                for word in other.split()[:2]:
                    self.assertNotIn(word, text, f"{word} в результате для {person}")
        self.assertEqual(len(self.api.meta), 4)

    def test_addin_bomb_is_refused(self):
        import io
        import zipfile
        from anonymizer import service as svc
        old = svc.MAX_UNPACKED_BYTES
        svc.MAX_UNPACKED_BYTES = 50_000
        try:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("word/document.xml", b"\0" * 5_000_000)
            status, _, _ = self.call("POST", "/api/addin/anonymize", buffer.getvalue(), {"X-Filename": "b.docx"})
            self.assertEqual(status, 400)
        finally:
            svc.MAX_UNPACKED_BYTES = old

    def test_addin_negative_content_length_is_400(self):
        status, _, _ = self.call("POST", "/api/addin/rerun", b"", {"Content-Length": "-1"})
        self.assertEqual(status, 400)


class BadRequestBodies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from anonymizer.webapp import create_server
        cls.env = Env()
        cls.server, cls.app = create_server(cls.env.vault, cls.env.base / "work")
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.env.close()

    def raw(self, path, body, length=None):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}", "Cookie": f"anon_t={self.app.token}", "X-Requested-With": "anonymizer"}
        connection.putrequest("POST", path, skip_host=True)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.putheader("Content-Length", str(len(body) if length is None else length))
        connection.endheaders(body)
        status = connection.getresponse().status
        connection.close()
        return status

    def test_negative_content_length_is_400(self):
        self.assertEqual(self.raw("/api/rerun", b"", length=-5), 400)

    def test_garbage_content_length_is_400(self):
        self.assertEqual(self.raw("/api/rerun", b"", length="abc"), 400)

    def test_rerun_with_wrong_types_is_400(self):
        import json
        for payload in ({"job": ["x"]}, {"job": 5}, {"job": "zzz", "options": "no"}, {"job": "zzz", "overrides": [1]},
                        {"job": "zzz", "overrides": {"a": 3}}, {"job": {"a": 1}}):
            self.assertEqual(self.raw("/api/rerun", json.dumps(payload).encode()), 400, payload)
