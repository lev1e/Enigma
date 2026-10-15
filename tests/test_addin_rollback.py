"""Откат из панели привязан к документу: отпечаток содержимого после обезличивания, сверка перед откатом, срок копии."""
import unittest

from .helpers import docx_bytes
from .test_addin import AddinCase
from .test_addin_chat import OTHER, SECRET, PanelChatTests


class RollbackBindingTests(AddinCase):
    op = PanelChatTests.op
    doc = PanelChatTests.doc

    def anonymized(self, name="Договор.docx", text=SECRET, chat=None):
        started, job = self.op("anonymize", name, self.doc(text), chat=chat)
        self.assertEqual(job["state"], "done", job)
        return started, job, self.result(job["id"])

    def anonymized_doc(self, name, person, chat):
        data = docx_bytes([f"Письмо поставщику от {person}.", "Просим подтвердить сроки отгрузки партии и порядок оплаты по счёту.",
                           "Склад в Казани принимает товар по будням с девяти до шести."])
        started, job = self.op("anonymize", name, data, chat=chat)
        self.assertEqual(job["state"], "done", job)
        return started, job, self.result(job["id"])

    def verify(self, job, data):
        status, body = self.json("POST", f"/api/addin/verify/{job['id']}", data)
        self.assertEqual(status, 200, body)
        return body

    def check(self, backup, data):
        status, body = self.json("POST", f"/api/addin/rollback-check/{backup}", data)
        self.assertEqual(status, 200, body)
        return body

    def test_info_reports_backup_lifetime_in_days(self):
        status, info = self.json("GET", "/api/addin/info")
        self.assertEqual(info["backup_days"], 7)

    def test_unchanged_document_matches_its_own_backup(self):
        started, job, result = self.anonymized()
        self.verify(job, result)
        self.assertEqual(self.check(started["backup"], result)["status"], "same")

    def test_edited_document_is_reported_as_edited(self):
        base = docx_bytes([f"Директор {SECRET}."] + [f"Пункт {i}: поставщик обязуется передать товар партии номер {i} в срок и без замечаний."
                                                      for i in range(1, 15)])
        started, job = self.op("anonymize", "Договор.docx", base)
        result = self.result(job["id"])
        self.verify(job, result)
        edited = docx_bytes(self.paragraphs(result) + ["Дописано вручную после обезличивания."])
        self.assertEqual(self.check(started["backup"], edited)["status"], "edited")

    def test_another_document_never_matches(self):
        started, job, result = self.anonymized()
        self.verify(job, result)
        stranger = docx_bytes(["Совсем другой договор поставки.", "Склад находится в Казани, срок оплаты тридцать дней.",
                               "Стороны согласовали порядок приёмки и ответственность."])
        self.assertEqual(self.check(started["backup"], stranger)["status"], "other")

    def test_second_document_in_same_chat_cannot_use_first_backup(self):
        first_started, first_job, first_result = self.anonymized("Договор.docx", SECRET)
        self.verify(first_job, first_result)
        second_started, second_job, second_result = self.anonymized_doc("Письмо.docx", OTHER, chat=first_job["chat"])
        self.verify(second_job, second_result)
        self.assertEqual(self.check(first_started["backup"], second_result)["status"], "other")
        self.assertEqual(self.check(second_started["backup"], first_result)["status"], "other")
        self.assertEqual(self.check(second_started["backup"], second_result)["status"], "same")

    def test_without_verification_status_is_unknown(self):
        started, job, result = self.anonymized()
        self.assertEqual(self.check(started["backup"], result)["status"], "unknown")

    def test_missing_backup_is_404(self):
        status, _ = self.json("POST", "/api/addin/rollback-check/deadbeef12", b"x")
        self.assertEqual(status, 404)

    def paragraphs(self, data):
        from .helpers import docx_text
        return [p for p in docx_text(data).split("\n") if p.strip()]


if __name__ == "__main__":
    unittest.main()
