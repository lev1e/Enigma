"""Папка как проект в чате: относительные пути, общие метки, сохранение папкой, пересборка, возврат папкой."""
import io
import shutil
import unittest
import zipfile
from pathlib import Path

from anonymizer import folders
from anonymizer.webapp import App

from .helpers import Env, docx_bytes, docx_text, pdf_bytes, pptx_bytes, xlsx_bytes

SECRET = "Смирнов Алексей Петрович"


def make_tree(base: Path) -> Path:
    src = base / "Клиент Ромашка"
    (src / "Договоры" / "2024").mkdir(parents=True)
    (src / "Отчёты и таблицы").mkdir()
    (src / "Договоры" / "Договор.docx").write_bytes(docx_bytes([f"Директор {SECRET}, ООО «Ромашка», г. Новосибирск."]))
    (src / "Договоры" / "2024" / "Договор.docx").write_bytes(docx_bytes([f"Подписал {SECRET}. Телефон +7 913 555-12-34."]))
    (src / "Отчёты и таблицы" / "Реестр.xlsx").write_bytes(xlsx_bytes({"A1": "ФИО", "A2": SECRET}))
    (src / "Отчёты и таблицы" / "Презентация.pptx").write_bytes(pptx_bytes([f"Руководитель {SECRET}"]))
    (src / "Отчёты и таблицы" / "Справка.pdf").write_bytes(pdf_bytes("Smirnov report"))
    (src / "заметка.txt").write_text(f"Звонил {SECRET}", encoding="utf-8")
    (src / "картинка.png").write_bytes(b"\x89PNG not really")
    (src / "~$Договор.docx").write_bytes(b"lock")
    return src


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.app = App(self.env.vault, self.env.base / "work", "tok")
        self.src = make_tree(self.env.base)

    def tearDown(self):
        self.app.cleanup_open()
        self.env.close()

    def project(self, kind="anonymize", source=None, chat_id=None, keep=None):
        if keep is not None:
            self.env.vault.prefs["keep_originals"] = keep
        info = self.app.add_folder(str(source or self.src), kind)
        job_id = self.app.start_project_job(kind, info["id"], {}, chat_id)
        self.app.runners[job_id].join(120)
        return self.app.job_public(job_id)

    def chat(self):
        listing = self.app.chats.listing()
        self.assertEqual(len(listing), 1)
        return self.app.chats.get(listing[0]["id"])


class ProjectTests(ProjectCase):
    def test_scan_reports_files_unsupported_and_project_ok(self):
        info = self.app.add_folder(str(self.src), "anonymize")
        self.assertEqual(info["files"], 6)
        self.assertTrue(info["project_ok"])
        self.assertEqual([s["path"] for s in info["skipped_items"]], ["картинка.png"])

    def test_project_goes_to_one_chat_with_relative_paths_and_shared_codes(self):
        job = self.project()
        self.assertEqual(job["state"], "done", job["error"])
        chat = self.chat()
        self.assertEqual(chat["project"]["root"], "Клиент Ромашка")
        self.assertEqual(chat["title"], "Клиент Ромашка")
        self.assertEqual(sorted(r["name"] for r in chat["files"]),
                         sorted(["Договоры/2024/Договор.docx", "Договоры/Договор.docx", "заметка.txt",
                                 "Отчёты и таблицы/Презентация.pptx", "Отчёты и таблицы/Реестр.xlsx", "Отчёты и таблицы/Справка.pdf"]))
        steps = [s for s in chat["steps"] if s["kind"] == "anonymize"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["project"]["unsupported_total"], 1)
        person = [set(r["tokens"]) for r in chat["files"] if r["name"].endswith((".docx", ".txt"))]
        self.assertTrue(set.intersection(*person), "один человек - одна метка во всех файлах")
        listing = self.app.chats.listing()[0]
        self.assertEqual(listing["project"], "Клиент Ромашка")

    def test_same_names_in_different_dirs_do_not_collide(self):
        self.project()
        chat = self.chat()
        docs = [r for r in chat["files"] if r["name"].endswith("Договор.docx")]
        self.assertEqual(len(docs), 2)
        blobs = {self.app.chats.read_blob(chat["id"], r["id"], "anon") for r in docs}
        self.assertEqual(len(blobs), 2)

    def test_save_project_recreates_structure_with_neutral_dirs_and_never_overwrites(self):
        self.project()
        chat = self.chat()
        target = self.env.base / "Куда сохранить" / "с пробелом"
        target.mkdir(parents=True)
        first = folders.write_project(self.app, chat["id"], "anon", target)
        second = folders.write_project(self.app, chat["id"], "anon", target)
        self.assertNotEqual(first["out"], second["out"])
        root = Path(first["out"])
        self.assertNotIn("Ромашка", str(root))
        files = [p for p in root.rglob("*") if p.is_file()]
        self.assertEqual(len(files), 6)
        for path in files:
            self.assertNotIn("Ромашка", str(path))
            if path.suffix == ".docx":
                self.assertNotIn("Смирнов", docx_text(path))
        self.assertEqual(len({p.parent for p in root.rglob("*.docx")}), 2)
        data, name = folders.project_zip(self.app, chat["id"], "anon")
        self.assertTrue(name.endswith(".zip") and zipfile.ZipFile(io.BytesIO(data)).namelist())

    def test_rebuild_keeps_paths_and_needs_originals(self):
        self.project(keep=True)
        chat = self.chat()
        self.assertTrue(all(r["roles"].get("orig") for r in chat["files"]))
        job_id = self.app.apply_chat(chat["id"], {})
        self.app.runners[job_id].join(120)
        after = self.chat()
        self.assertEqual(sorted(r["name"] for r in after["files"]), sorted(r["name"] for r in chat["files"]))

    def test_without_originals_rebuild_says_so(self):
        self.project(keep=False)
        chat = self.chat()
        self.assertFalse(any(r["roles"].get("orig") for r in chat["files"]))
        with self.assertRaises(ValueError) as caught:
            self.app.apply_chat(chat["id"], {})
        self.assertIn("оригиналы", str(caught.exception))

    def test_restore_returned_folder_matches_by_relative_path(self):
        self.project()
        chat = self.chat()
        returned = self.env.base / "Ответ ИИ"
        out = Path(folders.write_project(self.app, chat["id"], "anon", self.env.base)["out"])
        shutil.move(str(out), returned)
        job = self.project("restore", source=returned, chat_id=chat["id"])
        self.assertEqual(job["state"], "done", job["error"])
        after = self.chat()
        self.assertEqual(len(after["files"]), 6, "возврат заполняет записи проекта, а не плодит новые")
        self.assertTrue(all("restored" in r["roles"] for r in after["files"]))
        restored = self.app.chats.read_blob(after["id"], next(r["id"] for r in after["files"] if r["name"] == "Договоры/2024/Договор.docx"), "restored")
        self.assertIn("Смирнов", docx_text(restored))
        out_restored = Path(folders.write_project(self.app, chat["id"], "restored", self.env.base)["out"])
        self.assertTrue((out_restored / "Договоры" / "2024").is_dir())
        self.assertEqual(out_restored.name, "Клиент Ромашка (восстановлено)")

    def test_huge_folder_is_refused_with_plain_message(self):
        big = self.env.base / "Большая"
        big.mkdir()
        for i in range(folders.PROJECT_MAX_FILES + 1):
            (big / f"f{i}.txt").write_text("x", encoding="utf-8")
        info = self.app.add_folder(str(big), "anonymize")
        self.assertFalse(info["project_ok"])
        self.assertIn("не больше", info["project_note"])
        with self.assertRaises(ValueError):
            self.app.start_project_job("anonymize", info["id"], {})

    def test_empty_folder_is_refused(self):
        empty = self.env.base / "Пусто"
        empty.mkdir()
        (empty / "x.png").write_bytes(b"1")
        info = self.app.add_folder(str(empty), "anonymize")
        self.assertFalse(info["project_ok"])

    def test_cancel_stops_job_and_rolls_back_vault(self):
        info = self.app.add_folder(str(self.src), "anonymize")
        job_id = self.app.start_project_job("anonymize", info["id"], {})
        self.app.cancel_job(job_id)
        self.app.runners[job_id].join(60)
        job = self.app.job_public(job_id)
        if job["state"] == "failed":
            self.assertIn("Остановлено", job["error"])
            self.assertEqual(self.app.chats.listing(), [])

    def test_progress_counts_are_reported(self):
        job = self.project()
        self.assertEqual((job["processed"], job["total"]), (6, 6))


if __name__ == "__main__":
    unittest.main()
