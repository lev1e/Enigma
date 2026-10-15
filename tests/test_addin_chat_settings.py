"""Add-in и настройки чата: порядок запуск > чат > общие, повтор не теряет чат, панель шлёт только изменённое."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import unittest

from anonymizer.addin import ADDIN_DIR
from tests.helpers import docx_bytes, docx_text
from tests.test_addin import AddinCase
from tests.test_review_fixes import run_job

TEXT = ["Пётр Сидоров приехал из Германии.", "Пётр Сидоров согласен. Дальше работаем по плану."]


class AddinChatSettings(AddinCase):
    def chat(self, **settings):
        chat = self.app.chats.create("Чат", keep_originals=True)
        if settings:
            self.app.chats.set_settings(chat["id"], settings)
        return chat["id"]

    def addin_run(self, chat_id, options=None, data=None):
        status, started = self.json("POST", "/api/addin/anonymize", data or docx_bytes(TEXT), {
            "X-Filename": "a.docx", "X-Chat": chat_id, "X-Options": json.dumps(options or {})})
        self.assertEqual(status, 200, started)
        return started, self.wait(started["job"])

    def wait(self, job_id):
        for _ in range(600):
            _, job = self.json("GET", f"/api/addin/jobs/{job_id}")
            if job["state"] != "running":
                return job
            time.sleep(0.1)
        self.fail("задание не завершилось")

    def rerun(self, job_id, overrides=None):
        status, again = self.json("POST", "/api/addin/rerun", json.dumps(
            {"job": job_id, "options": {}, "overrides": overrides or {}}).encode(), {"Content-Type": "application/json"})
        self.assertEqual(status, 200, again)
        return self.wait(again["job"])

    def test_addin_output_equals_standalone_output_with_chat_override(self):
        data = docx_bytes(TEXT)
        mine, theirs = self.chat(countries=False), self.chat(countries=False)
        run_job(self.app, "anonymize", [("a.docx", data)], chat_id=mine, options={})
        chat = self.app.chats.get(mine)
        standalone = self.app.chats.read_blob(mine, chat["files"][-1]["id"], "anon")
        _, job = self.addin_run(theirs)
        self.assertEqual(job["state"], "done", job)
        via_addin = self.result(job["id"])
        self.assertIn("Германи", docx_text(standalone))             # переопределение чата действует
        self.assertEqual(docx_text(via_addin), docx_text(standalone))
        self.assertNotIn("Сидоров", docx_text(via_addin))

    def test_panel_sends_only_changed_options_so_chat_override_survives(self):
        _, job = self.addin_run(self.chat(countries=False), options={})          # панель ничего не меняла
        self.assertIn("Германи", docx_text(self.result(job["id"])))
        _, job = self.addin_run(self.chat(countries=False), options={"countries": True})   # человек включил сам
        self.assertNotIn("Германи", docx_text(self.result(job["id"])))

    def test_doc_state_carries_chat_overrides_for_the_panel(self):
        chat_id = self.chat(countries=False, strict=True)
        status, state = self.json("GET", f"/api/addin/doc-state?chat={chat_id}")
        self.assertEqual(state["chat"]["settings"], {"countries": False, "strict": True})

    def test_rerun_keeps_chat_replaces_record_and_applies_current_chat_settings(self):
        chat_id = self.chat()
        _, job = self.addin_run(chat_id)
        name_token = re.search(r"Name\d+", docx_text(self.result(job["id"]))).group(0)
        self.app.chats.set_settings(chat_id, {"hide_terms": ["плану"]})          # правка чата после первого прогона
        new = self.rerun(job["id"])
        self.assertEqual(new["state"], "done", new)
        text = docx_text(self.result(new["id"]))
        self.assertNotIn("плану", text)                                           # настройки чата не потеряны
        self.assertIn(name_token, text)                                           # Name1 остаётся Name1
        self.assertEqual(new.get("chat"), chat_id)
        self.assertEqual(len(self.app.chats.get(chat_id)["files"]), 1)            # запись заменена, дубля нет

    def test_rerun_still_applies_override_set_at_first_run(self):
        _, job = self.addin_run(self.chat(countries=False))
        new = self.rerun(job["id"], {"плану": "hide"})
        text = docx_text(self.result(new["id"]))
        self.assertIn("Германи", text)
        self.assertNotIn("плану", text)


@unittest.skipUnless(shutil.which("node"), "нужен node")
class PanelScript(unittest.TestCase):
    source = (ADDIN_DIR / "taskpane.js").read_text(encoding="utf-8")

    def pick(self, values, baseline, touched):
        core = re.search(r"// <options-core>(.*?)// </options-core>", self.source, re.S).group(1)
        script = core + f"\nconsole.log(JSON.stringify(pickOptions({json.dumps(values)}, {json.dumps(baseline)}, {json.dumps(touched)})));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_nothing_touched_sends_nothing(self):
        self.assertEqual(self.pick({"numbers": True, "strict": False, "countries": True},
                                   {"numbers": True, "strict": False, "countries": False}, {}), {})

    def test_only_changed_touched_toggles_are_sent(self):
        got = self.pick({"numbers": True, "strict": True, "countries": False},
                        {"numbers": False, "strict": False, "countries": False}, {"strict": True, "countries": True})
        self.assertEqual(got, {"strict": True})

    def test_options_is_not_a_blind_dump_of_checkboxes(self):
        body = self.source.split("function options()")[1].split("\n}")[0]
        self.assertNotIn('numbers: $("#opt-numbers").checked', body)
        self.assertIn("pickOptions", body)


if __name__ == "__main__":
    unittest.main()
