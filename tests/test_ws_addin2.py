"""Охота 2, add-in: параллельные операции, удаление данных, ошибки без утечек, проверка результата, zip-контейнеры."""
import http.client
import io
import json
import socket
import time
import unittest
import urllib.parse
import zipfile
from pathlib import Path

from anonymizer import addin, restore, service as svc
from anonymizer.util import client_message
from anonymizer.addin import verify_document

from .helpers import docx_bytes, xlsx_bytes
from .test_addin import SECRET, AddinCase

TEXT = [f"Договор подписал {SECRET}.", f"Контакт: {SECRET}, телефон +7 495 123-45-67."]


class Base(AddinCase):
    def post(self, kind, name, data, options=None, chat=None):
        headers = {"X-Filename": urllib.parse.quote(name), "X-Options": urllib.parse.quote(json.dumps(options or {}))}
        if chat:
            headers["X-Chat"] = chat
        return self.json("POST", f"/api/addin/{kind}", data, headers)

    def wait(self, job_id, states=("running",)):
        for _ in range(600):
            status, job = self.json("GET", f"/api/addin/jobs/{job_id}")
            if job.get("state") not in states:
                return job
            time.sleep(0.1)
        self.fail("задание не завершилось")

    def done(self, name="a.docx", data=None):
        started, job = self.run_op("anonymize", name, data or docx_bytes(TEXT))
        self.assertEqual(job["state"], "done", job)
        return started, job

    def hold(self):
        """Задание, которое не заканчивается, пока тест не отпустит его."""
        import threading
        gate = threading.Event()
        original = self.app.service.anonymize

        def slow(*args, **kwargs):
            gate.wait(20)
            return original(*args, **kwargs)
        self.app.service.anonymize = slow
        self.addCleanup(gate.set)
        return gate


class Concurrency(Base):
    def test_second_start_on_same_document_is_refused(self):
        gate = self.hold()
        status, first = self.post("anonymize", "a.docx", docx_bytes(TEXT))
        self.assertEqual(status, 200)
        status, second = self.post("anonymize", "a.docx", docx_bytes(TEXT))                  # двойной щелчок
        self.assertEqual(status, 409, second)
        self.assertEqual(len(self.api.originals.listing()), 1)                               # вторая копия не создана
        gate.set()
        self.assertEqual(self.wait(first["job"])["state"], "done")

    def test_rerun_during_running_job_is_refused(self):
        _, job = self.done()
        gate = self.hold()
        status, started = self.post("anonymize", "b.docx", docx_bytes(TEXT))
        self.assertEqual(status, 200)
        status, body = self.json("POST", "/api/addin/rerun", json.dumps({"job": started["job"], "options": {}}).encode())
        self.assertEqual(status, 409, body)
        gate.set()
        self.wait(started["job"])

    def test_double_rerun_second_is_not_a_500(self):
        started, _ = self.done()
        payload = json.dumps({"job": started["job"], "options": {}, "overrides": {}}).encode()
        status1, first = self.json("POST", "/api/addin/rerun", payload)
        status2, second = self.json("POST", "/api/addin/rerun", payload)
        self.assertEqual(status1, 200, first)
        self.assertIn(status2, (404, 409))
        self.assertEqual(self.wait(first["job"])["state"], "done")

    def test_rerun_bad_types_are_400(self):
        for body in ({"job": 5}, {"job": ["x"]}, {"job": "x", "options": None}, {"job": "x", "options": []},
                     {"job": "x", "options": {}, "overrides": {"a": 1}}, {"job": {"a": 1}}):
            status, answer = self.json("POST", "/api/addin/rerun", json.dumps(body).encode())
            self.assertEqual(status, 400, (body, answer))
        for raw in (b"[1,2]", b"null", b"\"x\"", b"{bad"):
            status, answer = self.json("POST", "/api/addin/rerun", raw)
            self.assertEqual(status, 400, (raw, answer))

    def test_negative_and_garbage_content_length_are_400(self):
        for value in ("-5", "abc"):
            sock = socket.create_connection(("localhost", self.port))
            with self.ctx.wrap_socket(sock, server_hostname="localhost") as tls:
                tls.sendall((f"POST /api/addin/rerun HTTP/1.1\r\nHost: localhost:{self.port}\r\nX-Requested-With: anonymizer\r\n"
                             f"X-Addin-Token: {self.api.token}\r\nContent-Length: {value}\r\n\r\n").encode())
                reply = tls.recv(4096)
            self.assertTrue(reply.startswith(b"HTTP/1.0 400") or reply.startswith(b"HTTP/1.1 400"), reply[:40])

    def test_options_header_garbage_is_400(self):
        status, answer = self.json("POST", "/api/addin/anonymize", docx_bytes(TEXT), {
            "X-Filename": "a.docx", "X-Options": urllib.parse.quote("{bad json " + SECRET)})
        self.assertEqual(status, 400)
        self.assertNotIn("Смирнов", json.dumps(answer, ensure_ascii=False))


class ErrorsAndStatuses(Base):
    def test_failed_job_drops_the_backup_and_hides_internal_text(self):
        def boom(*args, **kwargs):
            raise RuntimeError("секрет в тексте исключения " + SECRET)
        self.app.service.anonymize = boom
        status, started = self.post("anonymize", "a.docx", docx_bytes(TEXT))
        job = self.wait(started["job"])
        self.assertEqual(job["state"], "failed")
        self.assertNotIn("Смирнов", json.dumps(job, ensure_ascii=False))
        self.assertFalse(job["has_backup"])
        self.assertEqual(self.api.originals.listing(), [])
        self.assertEqual(list(self.api.originals.dir.glob("*.bin")), [])

    def test_cancelled_job_is_failed_and_leaves_no_copy(self):
        gate = self.hold()
        status, started = self.post("anonymize", "a.docx", docx_bytes(TEXT))
        self.app.cancel_job(started["job"])
        gate.set()
        job = self.wait(started["job"])
        self.assertEqual(job["state"], "failed", job)
        self.assertIn("Остановлено", job["error"])
        self.assertEqual(self.api.originals.listing(), [])

    def test_client_message_hides_third_party_text(self):
        try:
            json.loads('{"a": ' + SECRET)
        except ValueError as exc:
            self.assertNotIn("Смирнов", client_message(exc))
        self.assertEqual(client_message(ValueError("Файл слишком большой.")), "Файл слишком большой.")
        self.assertEqual(client_message(KeyError("Чата нет")), "Чата нет")
        self.assertNotIn("Name1", client_message(KeyError("Name1")))

    def test_unreadable_json_body_does_not_echo(self):
        status, answer = self.json("POST", "/api/addin/rerun", ('{"job": "' + SECRET).encode())
        self.assertEqual(status, 400)
        self.assertNotIn("Смирнов", json.dumps(answer, ensure_ascii=False))


class DeletingData(Base):
    def test_chat_delete_removes_backup_and_job_artifacts(self):
        started, job = self.done()
        chat = job["chat"]
        self.assertTrue(chat)
        for _ in range(50):                                   # привязка копии к чату — при первом чтении готового задания
            status, state = self.json("GET", f"/api/addin/doc-state?chat={chat}")
            if state.get("chat", {}).get("has_backup"):
                break
            time.sleep(0.1)
        backup = started["backup"]
        self.assertIsNotNone(self.api.originals.meta(backup))
        job_dir = self.app.service.jobs[started["job"]].dir
        self.assertTrue(job_dir.exists())
        status, _ = self.json("DELETE", f"/api/chats/{chat}")
        self.assertEqual(status, 200)
        self.assertIsNone(self.api.originals.meta(backup))
        self.assertEqual(list(self.api.originals.dir.glob(f"{backup}*")), [])
        self.assertFalse(job_dir.exists())
        self.assertNotIn(started["job"], self.api.meta)
        status, _ = self.json("GET", f"/api/addin/backup/{backup}")
        self.assertEqual(status, 404)
        status, _ = self.json("GET", f"/api/addin/result/{started['job']}")
        self.assertEqual(status, 404)

    def test_discard_overwrites_before_unlinking(self):
        from anonymizer.chats import ChatStore
        calls = []
        original = ChatStore._shred
        ChatStore._shred = staticmethod(lambda p: (calls.append(Path(p).suffix), original(p))[1])
        try:
            started, _ = self.done()
            self.api.originals.discard(started["backup"])
        finally:
            ChatStore._shred = staticmethod(original)
        self.assertIn(".bin", calls)
        self.assertIn(".meta", calls)


class VaultAndRetention(unittest.TestCase):
    def test_edit_value_leaves_no_bak_with_the_previous_value(self):
        from .helpers import Env
        from .test_review_fixes import finish, make_app, run_job
        env = Env()
        self.addCleanup(env.close)
        app = make_app(env)
        self.addCleanup(app.cleanup_open)
        finish(app, run_job(app, "anonymize", [("a.txt", "Пётр Сидоров подписал договор.\n")]))
        vault = env.vault
        base = next(b for b, e in vault.entities.items() if e["kind"] == "PERSON")
        vault.edit_value(base, 1, "ПРЕЖНЕЕ-ЗНАЧЕНИЕ")
        vault.edit_value(base, 1, "НОВОЕ-ЗНАЧЕНИЕ")
        self.assertFalse(vault.path.with_suffix(".bak").exists())
        vault.save()                                            # обычное сохранение снова может держать копию
        vault.restore_edit(base, 1, "ПРЕЖНЕЕ-ЗНАЧЕНИЕ")
        self.assertFalse(vault.path.with_suffix(".bak").exists())

    def test_retention_purge_shreds_bak_and_applies_at_once(self):
        from .helpers import Env
        from .test_review_fixes import finish, make_app, run_job
        env = Env()
        self.addCleanup(env.close)
        app = make_app(env)
        self.addCleanup(app.cleanup_open)
        finish(app, run_job(app, "anonymize", [("a.txt", "Пётр Сидоров подписал договор.\n")]))
        vault = env.vault
        vault.dirty = True
        vault.save()
        vault.dirty = True
        vault.save()
        self.assertTrue(vault.path.with_suffix(".bak").exists())
        for entity in vault.entities.values():
            entity["used"] = time.time() - 40 * 86400
        vault.set_prefs(retention_days=30)
        self.assertFalse(any(e["kind"] == "PERSON" for e in vault.entities.values()))
        self.assertFalse(vault.path.with_suffix(".bak").exists())


def _xlsx_with_names(names):
    data = xlsx_bytes({"A1": "Итого", "B1": 5})
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename == "xl/workbook.xml":
                text = raw.decode("utf-8")
                defined = "<definedNames>" + "".join(f'<definedName name="{n}">Лист1!$A$1</definedName>' for n in names) + "</definedNames>"
                text = text.replace("</sheets>", "</sheets>" + defined, 1)
                raw = text.encode("utf-8")
            zout.writestr(info.filename, raw)
    return out.getvalue()


class VerifyDocument(unittest.TestCase):
    def check(self, tmp_path, expected_names, actual_names, replaced):
        expected, actual = tmp_path / "e.xlsx", tmp_path / "a.xlsx"
        expected.write_bytes(_xlsx_with_names(expected_names))
        actual.write_bytes(_xlsx_with_names(actual_names))
        return verify_document(expected, actual, replaced)

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def test_leak_in_defined_name_with_underscore_is_found(self):
        verdict = self.check(self.path, ["Name1_Report"], ["Смирнов_Алексей_Отчёт"], [SECRET])
        self.assertFalse(verdict["ok"], verdict)
        self.assertIn("leak", [p["code"] for p in verdict["problems"]])

    def test_lone_surname_in_inflected_form_is_found(self):
        verdict = self.check(self.path, ["Name1_Report"], ["Отчёт для Смирнова"], [SECRET])
        self.assertFalse(verdict["ok"], verdict)

    def test_clean_document_stays_ok(self):
        verdict = self.check(self.path, ["Name1_Report"], ["Name1_Report"], [SECRET])
        self.assertTrue(verdict["ok"], verdict)

    def test_word_kept_by_decision_is_not_a_leak(self):
        verdict = self.check(self.path, ["Смирнов_Отчёт"], ["Смирнов_Отчёт"], [SECRET])
        self.assertTrue(verdict["ok"], verdict)


class TempFilesOnErrorPaths(unittest.TestCase):
    def test_restore_ooxml_leaves_no_temp_file_after_corrupt_member(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.docx"
            raw = bytearray(docx_bytes(TEXT))
            src.write_bytes(bytes(raw))
            with zipfile.ZipFile(src) as z:
                info = z.getinfo("word/document.xml")
                offset = info.header_offset + 30 + len(info.filename.encode()) + 5
            raw[offset] ^= 0xFF                                     # портим сжатые данные: чтение даст ошибку
            src.write_bytes(bytes(raw))
            out = Path(tmp) / "out"
            out.mkdir()
            with self.assertRaises(Exception):
                restore.restore_ooxml(src, out / "r.docx", None)
            self.assertEqual(list(out.iterdir()), [])


class ZipContainers(Base):
    def test_unpacked_size_bomb_is_refused(self):
        original = svc.MAX_UNPACKED_BYTES
        svc.MAX_UNPACKED_BYTES = 200_000
        self.addCleanup(setattr, svc, "MAX_UNPACKED_BYTES", original)
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(TEXT))) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                zout.writestr(info.filename, zin.read(info.filename))
            zout.writestr("word/media/bomb.bin", b"\0" * 5_000_000)
        status, answer = self.post("anonymize", "bomb.docx", out.getvalue())
        self.assertEqual(status, 400, answer)
        self.assertIn("велик", answer["error"])

    def test_forged_central_directory_is_never_a_500_or_hang(self):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(TEXT))) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                zout.writestr(info.filename, zin.read(info.filename))
            zout.writestr("word/media/big.bin", b"A" * 3_000_000)
        raw = bytearray(out.getvalue())
        marker = b"word/media/big.bin"
        # central directory record: размер распакованного файла (смещение 24 от сигнатуры) занижен до 10 байт
        index = raw.rfind(b"PK\x01\x02", 0, len(raw))
        while index != -1 and raw[index + 46:index + 46 + len(marker)] != marker:
            index = raw.rfind(b"PK\x01\x02", 0, index)
        self.assertNotEqual(index, -1)
        raw[index + 24:index + 28] = (10).to_bytes(4, "little")
        started = time.time()
        status, answer = self.post("anonymize", "forged.docx", bytes(raw))
        if status == 200:
            job = self.wait(answer["job"])
            self.assertIn(job["state"], ("done", "failed"))
            self.assertNotIn("Traceback", json.dumps(job, ensure_ascii=False))
        else:
            self.assertEqual(status, 400, answer)
        self.assertLess(time.time() - started, 60)

    def test_garbage_after_zip_signature_is_400(self):
        status, answer = self.post("anonymize", "x.docx", b"PK\x03\x04" + b"\xff" * 400)
        self.assertEqual(status, 400, answer)

    def test_zip_slip_member_names_do_not_reach_the_result(self):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes(TEXT))) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                zout.writestr(info.filename, zin.read(info.filename))
            zout.writestr("../../evil.xml", b"<x/>")
            zout.writestr("/abs/evil.xml", b"<x/>")
        status, answer = self.post("anonymize", "slip.docx", out.getvalue())
        if status != 200:
            self.assertEqual(status, 400, answer)
            return
        job = self.wait(answer["job"])
        if job["state"] == "done":
            with zipfile.ZipFile(io.BytesIO(self.result(answer["job"]))) as z:
                for name in z.namelist():
                    self.assertFalse(name.startswith("/") or ".." in Path(name).parts, name)


class StaleDocument(Base):
    def test_unchanged_strict_rerun_and_rollback_guard(self):
        submitted = docx_bytes(TEXT)                                   # одни и те же байты: у docx_bytes каждый раз новые метки времени
        started, job = self.done(data=submitted)
        edited = docx_bytes(TEXT + ["Пользователь дописал новый абзац после обработки."])
        status, answer = self.json("POST", f"/api/addin/unchanged/{started['job']}?strict=1", edited)
        self.assertEqual(status, 409, answer)
        self.assertIn("изменился", answer["error"])
        status, answer = self.json("POST", f"/api/addin/unchanged/{started['job']}", edited)       # без strict: прежний ответ
        self.assertEqual((status, answer["same"]), (200, False))
        status, answer = self.json("POST", "/api/addin/rerun", json.dumps({"job": started["job"], "options": {}, "digest": "0" * 64}).encode())
        self.assertEqual(status, 409, answer)
        self.assertIn(started["job"], self.api.meta)                    # отказ ничего не сломал
        self.assertEqual(self.json("GET", f"/api/addin/jobs/{started['job']}")[1]["state"], "done")
        # подтверждённый отпечаток текущего документа пропускает повтор
        import hashlib
        status, answer = self.json("POST", "/api/addin/rerun", json.dumps({
            "job": started["job"], "options": {}, "digest": hashlib.sha256(submitted).hexdigest()}).encode())
        self.assertEqual(status, 200, answer)
        self.wait(answer["job"])

    def test_rollback_check_strict_on_edited_document(self):
        started, job = self.done()
        result = self.result(started["job"])
        self.json("POST", f"/api/addin/verify/{started['job']}", result)                   # запоминает отпечаток документа
        status, answer = self.json("POST", f"/api/addin/rollback-check/{started['backup']}?strict=1", result)
        self.assertEqual(status, 200, answer)
        edited = docx_bytes(["Совсем другой текст про погоду и огород в деревне."])
        status, answer = self.json("POST", f"/api/addin/rollback-check/{started['backup']}?strict=1", edited)
        self.assertEqual(status, 409, answer)


class PrefsParityAndWipe(Base):
    def test_set_prefs_reports_noop_and_does_not_write(self):
        vault = self.env.vault
        vault.set_prefs(strict=True)
        before = vault.path.read_bytes()
        stamp = vault.path.stat().st_mtime_ns
        self.assertFalse(vault.set_prefs(strict=True))
        self.assertEqual(vault.path.stat().st_mtime_ns, stamp)
        self.assertEqual(vault.path.read_bytes(), before)
        self.assertTrue(vault.set_prefs(strict=False))

    def test_clear_vault_removes_addin_originals_and_jobs(self):
        started, job = self.done()
        self.assertTrue(self.api.originals.listing())
        self.app.clear_vault()
        self.assertEqual(list(self.api.originals.dir.glob("*.bin")), [])
        self.assertEqual(list(self.api.originals.dir.glob("*.meta")), [])
        self.assertFalse(self.api.meta)
        self.assertNotIn(started["job"], self.app.service.jobs)


class OcrScriptDirs(unittest.TestCase):
    def test_dead_pid_dirs_are_swept(self):
        import tempfile
        from anonymizer import ocr
        dead = Path(tempfile.gettempdir()) / "anonymizer-ocr-999999991"
        dead.mkdir(exist_ok=True)
        (dead / "win_ocr.ps1").write_text("x")
        # Windows deliberately uses age, not os.kill(pid, 0), which can kill
        # another process there. An orphan older than one day must be swept.
        import os, time
        old = time.time() - 2 * 86400
        os.utime(dead, (old, old))
        ocr._sweep_script_dirs()
        self.assertFalse(dead.exists())


if __name__ == "__main__":
    unittest.main()
