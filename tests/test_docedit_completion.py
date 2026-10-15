"""Comment targets must remain live; deferred operations fail atomically."""
import unittest

from anonymizer import docedit
from .test_ws_p2a import by_text, make_docx, make_pptx, make_xlsx, zip_parts


class CommentTargetTests(unittest.TestCase):
    def test_comment_on_deleted_paragraph_rejects_entire_patch(self):
        for name, build, text in (("a.docx", make_docx, "Второй абзац"),
                                  ("a.pptx", make_pptx, "Третий абзац")):
            with self.subTest(name=name):
                data = build()
                element = by_text(docedit.outline(data, name), text)
                patch = {"ops": [
                    {"op": "delete", "at": element["addr"], "expect": element["fp"]},
                    {"op": "comment", "at": element["addr"], "text": "Review this"},
                ]}
                with self.assertRaises(docedit.PatchRejected) as raised:
                    docedit.apply_patch(data, name, patch)
                self.assertEqual(raised.exception.code, "gone")
                self.assertEqual(raised.exception.op_index, 1)
                self.assertEqual(by_text(docedit.outline(data, name), text)["fp"], element["fp"])

    def test_comment_on_live_element_preserves_every_document_part(self):
        for name, build, text in (("a.docx", make_docx, "Второй абзац"),
                                  ("a.pptx", make_pptx, "Третий абзац")):
            with self.subTest(name=name):
                data = build()
                element = by_text(docedit.outline(data, name), text)
                new, report = docedit.apply_patch(data, name, {"ops": [
                    {"op": "comment", "at": element["addr"], "text": "Review this"}]})
                self.assertEqual(zip_parts(new), zip_parts(data))
                self.assertEqual(report["changed_parts"], [])
                self.assertEqual(report["comments"], [{"at": element["addr"], "text": "Review this"}])

    def test_deferred_operations_reject_before_mutating_document(self):
        cases = (("a.pptx", make_pptx, ("distribute", "set_theme_color", "apply_style_to_all")),
                 ("a.xlsx", make_xlsx, ("cell_style", "conditional_formatting")))
        for name, build, operations in cases:
            data = build()
            for operation in operations:
                with self.subTest(name=name, operation=operation):
                    with self.assertRaises(docedit.PatchRejected) as raised:
                        docedit.apply_patch(data, name, {"ops": [{"op": operation}]})
                    self.assertEqual(raised.exception.code, "unknown_op")


if __name__ == "__main__":
    unittest.main()
