"""Фоновая программа и окно-клиент: окно работает с хранилищем только через неё."""
import json
import threading
import time
import unittest
from pathlib import Path

from anonymizer import helper
from anonymizer.webapp import create_server

from .helpers import Env, docx_bytes, docx_text, xlsx_bytes
from .test_desktop import FakeWindow
from anonymizer import desktop


class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.server, self.app = create_server(self.env.vault, self.env.base / "work")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.info = {"port": self.server.server_address[1], "token": self.app.token}
        self.client = helper.HelperClient(self.info, timeout=30)
        self.remote = helper.RemoteApp(self.client)
        self.window = FakeWindow()
        self.bridge = desktop.Bridge(self.remote, lambda: self.window)
        self.folder = self.env.base / "user"
        self.folder.mkdir()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.remote.cleanup()
        self.env.close()

    def write(self, name, data):
        path = self.folder / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def wait(self, job_id):
        for _ in range(600):
            job = self.client.json("GET", f"/api/jobs/{job_id}")
            if job["state"] != "running":
                return job
            time.sleep(0.1)
        self.fail("задание не завершилось")


class ClientTests(Base):
    def test_ping_needs_the_token(self):
        self.assertTrue(helper.ping(self.info))
        self.assertFalse(helper.ping({"port": self.info["port"], "token": "чужой"}))
        self.assertFalse(helper.ping(None))

    def test_window_picks_files_and_the_helper_reads_them(self):
        path = self.write("Договор.docx", docx_bytes(["Директор Смирнов Алексей Петрович."]))
        self.window.answers = [(path,)]
        picked = self.bridge.pick_files()
        info = picked["files"][0]["info"]
        self.assertTrue(info["supported"], picked)
        job = self.client.json("POST", "/api/anonymize", {"files": [info["id"]], "options": {}})
        done = self.wait(job["job"])
        self.assertEqual(done["state"], "done", done)

    def test_save_result_downloads_from_the_helper_and_writes_where_the_person_chose(self):
        path = self.write("Данные.xlsx", xlsx_bytes({"A1": "Пётр Сидоров"}))
        self.window.answers = [(path,)]
        info = self.bridge.pick_files()["files"][0]["info"]
        job = self.client.json("POST", "/api/anonymize", {"files": [info["id"]], "options": {}})["job"]
        self.wait(job)
        target = self.folder / "результат.xlsx"
        self.window.answers = [(str(target),)]
        result = self.bridge.save_result(job, 0)
        self.assertEqual(result["path"], str(target))
        self.assertNotIn("Сидоров".encode(), target.read_bytes())
        self.assertIn("(обезличено)", self.window.asked[-1]["name"])

    def test_save_chat_file_works_through_the_helper(self):
        # Окно ходит к хранилищу через RemoteApp: сохранение версии из чата раньше падало (нет materialize).
        path = self.write("Данные.xlsx", xlsx_bytes({"A1": "Пётр Сидоров"}))
        self.window.answers = [(path,)]
        info = self.bridge.pick_files()["files"][0]["info"]
        job = self.client.json("POST", "/api/anonymize", {"files": [info["id"]], "options": {}})["job"]
        done = self.wait(job)
        chat = self.client.json("GET", f"/api/chats/{done['chat']}")
        record = chat["files"][0]
        target = self.folder / "из-чата.xlsx"
        self.window.answers = [(str(target),)]
        result = self.bridge.save_chat_file(done["chat"], record["id"], "anon")
        self.assertEqual(result.get("path"), str(target), result)
        self.assertNotIn("Сидоров".encode(), target.read_bytes())
        self.assertIn("error", self.bridge.save_chat_file(done["chat"], record["id"], "restored"))

    def _run_job(self, *files):
        ids = []
        for name, data in files:
            self.window.answers = [(self.write(name, data),)]
            ids.append(self.bridge.pick_files()["files"][0]["info"]["id"])
        job = self.client.json("POST", "/api/anonymize", {"files": ids, "options": {}})["job"]
        self.wait(job)
        return job

    def test_save_all_writes_every_result_through_the_helper(self):
        job = self._run_job(("Один.xlsx", xlsx_bytes({"A1": "Пётр Сидоров"})), ("Два.docx", docx_bytes(["Директор Смирнов Алексей Петрович."])))
        target = self.env.base / "итог"
        target.mkdir()
        self.window.answers = [(str(target),)]
        result = self.bridge.save_all(job)
        self.assertEqual(sorted(result["saved"]), [0, 1], result)
        self.assertEqual(len(list(target.iterdir())), 2)
        self.assertEqual(result["folder"], str(target))

    def test_reveal_after_save_works_only_for_saved_paths(self):
        job = self._run_job(("Данные.xlsx", xlsx_bytes({"A1": "Пётр Сидоров"})))
        target = self.folder / "р.xlsx"
        self.window.answers = [(str(target),)]
        saved = self.bridge.save_result(job, 0)["path"]
        import subprocess
        calls = []
        original = subprocess.Popen
        subprocess.Popen = lambda *a, **k: calls.append(a)
        try:
            self.assertEqual(self.bridge.reveal(saved), {"ok": True})
            self.assertIn("error", self.bridge.reveal(str(self.folder / "чужой.txt")))
        finally:
            subprocess.Popen = original
        self.assertEqual(len(calls), 1)

    def test_save_text_does_not_need_the_helper(self):
        target = self.folder / "текст.md"
        self.window.answers = [(str(target),)]
        self.assertEqual(self.bridge.save_text("текст.md", "Привет")["path"], str(target))
        self.assertEqual(target.read_text("utf-8-sig"), "Привет")

    def test_quit_app_calls_the_callback(self):
        done = threading.Event()
        bridge = desktop.Bridge(self.remote, lambda: self.window, done.set)
        self.assertEqual(bridge.quit_app(), {"ok": True})
        self.assertTrue(done.wait(3))
        self.assertIn("error", self.bridge.quit_app())

    def test_remote_state_and_jobs_match_what_the_bridge_reads(self):
        self.assertIsInstance(self.remote.state(), dict)
        self.assertIsNone(self.remote.service.jobs.get("нет такого"))
        self.assertIsNone(self.remote.service.output_path("нет такого", 0))
        with self.assertRaises(KeyError):
            self.remote.materialize("нет", "нет", "anon")
        job = self._run_job(("Данные.xlsx", xlsx_bytes({"A1": "Пётр Сидоров"})))
        found = self.remote.service.jobs.get(job)
        self.assertEqual(len(found.files), 1)
        path, name = self.remote.service.output_path(job, 0)
        self.assertTrue(path.exists() and name.endswith(".xlsx"))

    def test_save_all_and_unknown_job_are_lines_not_exceptions(self):
        self.assertIn("error", self.bridge.save_result("нет такого", 0))
        self.assertIn("error", self.bridge.save_all("нет такого"))

    def test_unreadable_path_and_folder_report_one_line(self):
        self.window.answers = [(str(self.folder / "нет.docx"),)]
        picked = self.bridge.pick_files()
        self.assertIn("error", picked["files"][0])
        self.window.answers = [(str(self.folder / "нет такой папки"),)]
        self.assertIn("error", self.bridge.pick_folder("anonymize"))

    def test_folder_job_through_the_window_bridge(self):
        (self.folder / "Отчёты").mkdir()
        (self.folder / "Отчёты" / "а.docx").write_bytes(docx_bytes(["Директор Смирнов Алексей Петрович."]))
        self.window.answers = [(str(self.folder / "Отчёты"),)]
        picked = self.bridge.pick_folder("anonymize")
        self.assertEqual(picked["folder"]["files"], 1, picked)
        job = self.client.json("POST", "/api/folder/anonymize", {"folder": picked["folder"]["id"], "options": {}})["job"]
        done = self.wait(job)
        self.assertEqual(done["state"], "done", done)
        revealed = []
        import subprocess
        original = subprocess.Popen
        subprocess.Popen = lambda *a, **k: revealed.append(a)       # не открываем Finder в тесте
        try:
            self.assertEqual(self.bridge.reveal_folder(job), {"ok": True})
        finally:
            subprocess.Popen = original

    def test_backup_round_trip_goes_through_the_helper(self):
        target = self.folder / "копия.anonkeys"
        self.window.answers = [(str(target),)]
        self.assertEqual(self.bridge.export_backup("пароль-123")["path"], str(target))
        self.window.answers = [(str(target),)]
        self.assertEqual(self.bridge.pick_backup()["name"], "копия.anonkeys")
        result = self.bridge.import_backup("пароль-123")
        self.assertIn("state", result, result)
        self.window.answers = [(str(target),)]
        self.bridge.pick_backup()
        self.assertIn("error", self.bridge.import_backup("неверный"))


class WindowEventsTests(Base):
    def test_a_waiting_window_wakes_only_when_there_is_something_to_say(self):
        self.client.json("POST", "/api/window/open", {"id": "w1"})
        started = time.time()
        got = {}
        thread = threading.Thread(target=lambda: got.update(self.client.json("GET", "/api/window/wait?id=w1", timeout=30)))
        thread.start()
        time.sleep(0.5)
        self.assertTrue(thread.is_alive(), "пока тихо, запрос ждёт")
        self.client.json("POST", "/api/focus", {})
        thread.join(5)
        self.assertEqual(got.get("focus"), True)
        self.assertLess(time.time() - started, 5)

    def test_no_window_means_the_helper_launches_one(self):
        launched = []
        self.app.spawn_window = lambda tab=None: launched.append(tab)
        self.client.json("POST", "/api/focus", {})
        self.assertEqual(launched, [None])
        self.app.request_window("rest")
        self.assertEqual(launched, [None, "rest"])

    def test_closed_window_is_forgotten(self):
        self.client.json("POST", "/api/window/open", {"id": "w2"})
        self.assertEqual(self.app.live_windows(), ["w2"])
        self.client.json("POST", "/api/window/closed", {"id": "w2"})
        self.assertEqual(self.app.live_windows(), [])


class LifetimeTests(Base):
    def test_helper_without_windows_exits_after_the_grace_period_unless_pinned(self):
        started = time.time() - helper.STARTUP_GRACE_SECONDS - 1
        self.assertTrue(helper.should_exit(self.app, time.time(), started))
        self.app.keep_alive = True
        self.assertFalse(helper.should_exit(self.app, time.time(), started))

    def test_helper_waits_while_a_window_is_alive_and_after_quit_it_stops(self):
        self.app.register_window("w")
        started = time.time() - 1000
        self.assertFalse(helper.should_exit(self.app, time.time(), started))
        self.app.windows["w"] -= 1000                      # окно давно не отзывалось
        self.assertTrue(helper.should_exit(self.app, time.time(), started))
        self.app.keep_alive = True
        self.client.json("POST", "/api/quit", {})
        self.assertTrue(helper.should_exit(self.app, time.time(), time.time()))

    def test_fresh_helper_gives_the_window_time_to_appear(self):
        self.assertFalse(helper.should_exit(self.app, time.time(), time.time()))


class StartupTests(unittest.TestCase):
    def test_autostart_from_sources_only_when_asked(self):
        from anonymizer import addin_install
        self.assertIsNone(addin_install.launch_command())
        command = addin_install.launch_command(dev=True)
        self.assertEqual(command[-2:], ["--serve", "--background"])
        self.assertTrue(Path(command[1]).name == "main.py")

    def test_launch_args_point_at_main_when_not_frozen(self):
        args = helper.launch_args(helper.SERVE_FLAG)
        self.assertEqual(args[-1], "--serve")
        self.assertTrue(Path(args[1]).name == "main.py" and Path(args[1]).exists())

    def test_modes_are_chosen_by_flags(self):
        self.assertEqual(helper.SERVE_FLAG, "--serve")
        self.assertEqual(helper.BACKGROUND_FLAG, "--background")


class ReconnectTests(Base):
    def start_second(self):
        env = Env()
        server, app = create_server(env.vault, env.base / "work2")
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def stop():
            server.shutdown()
            server.server_close()
            env.close()
        self.addCleanup(stop)
        return {"port": server.server_address[1], "token": app.token}

    def patch_instance(self, holder):
        from unittest import mock
        patcher = mock.patch.object(helper, "read_instance", lambda: holder.get("info"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rebind_points_requests_at_the_new_server(self):
        second = self.start_second()
        self.server.shutdown()
        self.server.server_close()
        self.assertFalse(helper.ping(self.info))
        self.client.rebind(second)
        self.assertEqual((self.client.port, self.client.token), (second["port"], second["token"]))
        self.assertTrue(self.client.json("GET", "/api/ping").get("ok"))

    def test_reconnect_info_none_when_dead_and_new_info_when_alive(self):
        holder = {"info": {"port": 1, "token": "x"}}
        self.patch_instance(holder)
        self.assertIsNone(helper.reconnect_info(None, 1))
        holder["info"] = self.start_second()
        self.assertEqual(helper.reconnect_info(None, 3), holder["info"])

    def test_bridge_reconnect_navigates_to_new_url(self):
        holder = {"info": self.start_second()}
        self.patch_instance(holder)
        loaded = []
        self.window.load_url = loaded.append
        result = self.bridge.reconnect()
        self.assertEqual(result, {"ok": True})
        self.assertEqual(loaded, [helper.helper_url(holder["info"])])
        self.assertEqual(self.client.port, holder["info"]["port"])

    def test_bridge_reconnect_error_when_nothing_alive(self):
        from unittest import mock
        self.patch_instance({"info": None})
        self.window.load_url = lambda url: self.fail("must not navigate")
        with mock.patch.object(helper, "ensure_helper", side_effect=RuntimeError("dead")):
            result = self.bridge.reconnect()
        self.assertIn("error", result)
        self.assertIn("не отвечает", result["error"])

    def test_bridge_reconnect_without_client(self):
        bridge = desktop.Bridge(self.app, lambda: self.window)
        self.assertEqual(bridge.reconnect(), {"error": "Переподключение не нужно."})

    def test_follow_helper_rebinds_and_reloads_then_reports_loss(self):
        second = self.start_second()
        self.server.shutdown()
        self.server.server_close()
        holder = {"info": None}
        self.patch_instance(holder)
        events = []

        class Win:
            def evaluate_js(self, code):
                events.append(("js", code))

            def load_url(self, url):
                events.append(("load", url))
                state["closing"] = True
        state = {"closing": False}
        steps = []
        real_json = self.client.json
        self.client.json = lambda method, path, *a, **k: ({} if "/api/window/wait" in path else real_json(method, path, *a, **k))

        def fake_sleep(_):
            steps.append(1)
            if len(steps) == 2:
                holder["info"] = second          # фон появился
            if len(steps) == 3:
                state["closing"] = True
        old = (self.client.port, self.client.token)
        helper.follow_helper(self.client, Win(), "w1", state, sleep=fake_sleep)
        self.assertEqual(events[0], ("js", helper.LOST_CALLBACK))
        self.assertEqual(sum(1 for e in events if e[0] == "js"), 1)
        self.assertIn(("load", helper.helper_url(second)), events)
        self.assertNotEqual((self.client.port, self.client.token), old)


class TableThroughTheHelperTests(Base):
    """Таблица замен из окна: те же методы, что у App, но через фоновую программу."""

    def make_chat(self):
        self.window.answers = [(self.write("Данные.xlsx", xlsx_bytes({"A1": "Пётр Сидоров", "A2": "Анна Кузнецова"})),)]
        info = self.bridge.pick_files()["files"][0]["info"]
        job = self.client.json("POST", "/api/anonymize", {"files": [info["id"]], "options": {}})["job"]
        return self.wait(job)["chat"]

    def test_save_table_writes_xlsx_and_csv_where_the_person_chose(self):
        chat = self.make_chat()
        target = self.folder / "таблица.xlsx"
        self.window.answers = [(str(target),)]
        self.assertEqual(self.bridge.save_table(chat, "xlsx").get("path"), str(target))
        self.assertTrue(target.read_bytes().startswith(b"PK"))
        self.assertEqual(self.window.asked[-1]["name"], "замены.xlsx")
        csv_target = self.folder / "таблица.csv"
        self.window.answers = [(str(csv_target),)]
        self.assertEqual(self.bridge.save_table(chat, "csv").get("path"), str(csv_target))
        self.assertIn("Сидоров", csv_target.read_text("utf-8-sig"))
        self.window.answers = []
        self.assertEqual(self.bridge.save_table(chat, "csv"), {"cancelled": True})
        self.assertIn("error", self.bridge.save_table("nochat1234", "csv"))

    def test_pick_table_previews_through_the_helper_and_the_page_applies(self):
        chat = self.make_chat()
        table = self.client.json("GET", f"/api/chats/{chat}")["table"]
        code = next(v["token"] for r in table for v in r["variants"] if "Сидоров" in v["value"])
        path = self.write("правки.csv", f"Код;Значение\r\n{code};Другой Человек\r\n".encode("utf-8-sig"))
        self.window.answers = [(path,)]
        picked = self.bridge.pick_table(chat)
        self.assertEqual(picked["name"], "правки.csv")
        preview = picked["preview"]
        self.assertEqual(preview["restore_changes"], [f"{code}: значение изменится"])
        done = self.client.json("POST", f"/api/chats/{chat}/table/import", {"apply": True, "token": preview["token"]})
        self.assertEqual(done["applied"]["restore"], 1)
        self.assertEqual(done["undo"]["of"], "batch")
        bad = self.write("мусор.csv", b"a;b\n1;2\n")
        self.window.answers = [(bad,)]
        self.assertIn("error", self.bridge.pick_table(chat))
        self.window.answers = []
        self.assertEqual(self.bridge.pick_table(chat), {"cancelled": True})

    def test_remote_import_and_table_file_match_the_app(self):
        chat = self.make_chat()
        path = self.remote.table_file(chat, "csv")
        self.assertEqual(path.name, "замены.csv")
        self.assertEqual(path.read_bytes(), self.app.table_file(chat, "csv").read_bytes())
        preview = self.remote.import_table(chat, "т.csv", path.read_bytes())
        self.assertEqual((preview["ai_changes"], preview["restore_changes"], preview["unrecognized"]), ([], [], []))


if __name__ == "__main__":
    unittest.main()


class ProjectThroughTheHelperTests(Base):
    """Папка как проект чата: выбор, задание, остановка, сохранение папкой, возврат папкой - через фоновую программу."""

    def make_project(self):
        src = self.folder / "Клиент Ромашка"
        (src / "Договоры" / "2024").mkdir(parents=True)
        (src / "Договоры" / "Договор.docx").write_bytes(docx_bytes(["Директор Смирнов Алексей Петрович."]))
        (src / "Договоры" / "2024" / "Договор.docx").write_bytes(docx_bytes(["Подписал Смирнов Алексей Петрович."]))
        (src / "заметка.txt").write_text("Звонил Смирнов Алексей Петрович", encoding="utf-8")
        (src / "картинка.png").write_bytes(b"\x89PNG")
        self.window.answers = [(str(src),)]
        picked = self.bridge.pick_folder("anonymize")
        self.assertTrue(picked["folder"]["project_ok"], picked)
        job = self.client.json("POST", "/api/folder/project", {"folder": picked["folder"]["id"], "options": {}})["job"]
        done = self.wait(job)
        self.assertEqual(done["state"], "done", done)
        self.assertEqual((done["processed"], done["total"]), (3, 3))
        return done["chat"], src

    def test_pick_folder_describes_project_and_skipped(self):
        src = self.folder / "П"
        src.mkdir()
        (src / "а.txt").write_text("x", encoding="utf-8")
        (src / "б.png").write_bytes(b"1")
        self.window.answers = [(str(src),)]
        picked = self.bridge.pick_folder("anonymize")["folder"]
        self.assertEqual((picked["files"], picked["skipped"]), (1, 1))
        self.assertEqual(picked["skipped_items"][0]["path"], "б.png")

    def test_save_project_writes_structure_to_a_cyrillic_path_and_never_overwrites(self):
        chat, _ = self.make_project()
        parent = self.folder / "Мои проекты с пробелом"
        parent.mkdir()
        self.window.answers = [(str(parent),), (str(parent),)]
        first = self.bridge.save_project(chat, "anon")
        second = self.bridge.save_project(chat, "anon")
        self.assertEqual(first["files"], 3, first)
        self.assertNotEqual(first["path"], second["path"])
        root = Path(first["path"])
        self.assertNotIn("Ромашка", str(root))
        self.assertEqual(len(list(root.rglob("*.docx"))), 2)
        self.assertEqual(len({p.parent for p in root.rglob("*.docx")}), 2)

    def test_save_project_cancel_and_errors(self):
        chat, _ = self.make_project()
        self.window.answers = [()]
        self.assertEqual(self.bridge.save_project(chat, "anon"), {"cancelled": True})
        self.assertIn("error", self.bridge.save_project("nochat1234", "anon"))
        self.assertIn("error", self.bridge.save_project(chat, "restored"))      # пока ничего не возвращено

    def test_restore_project_folder_through_the_window(self):
        chat, src = self.make_project()
        out_parent = self.folder / "ответ"
        out_parent.mkdir()
        self.window.answers = [(str(out_parent),)]
        saved = self.bridge.save_project(chat, "anon")
        self.window.answers = [(saved["path"],)]
        picked = self.bridge.pick_folder("restore")["folder"]
        job = self.client.json("POST", "/api/folder/project", {"folder": picked["id"], "kind": "restore", "chat_id": chat})["job"]
        self.assertEqual(self.wait(job)["state"], "done")
        self.window.answers = [(str(out_parent),)]
        restored = self.bridge.save_project(chat, "restored")
        self.assertEqual(restored["files"], 3, restored)
        self.assertIn("Смирнов", docx_text(next(Path(restored["path"]).rglob("2024/*.docx"))))

    def test_cancel_endpoint_is_accepted(self):
        self.assertEqual(self.client.json("POST", "/api/cancel", {"job": "нет"}), {"ok": True})
