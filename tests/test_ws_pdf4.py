"""English PDF leaks from the real-corpus run: an email cut at a table cell edge kept its login (a surname)."""
from __future__ import annotations

import unittest
from pathlib import Path

import fitz

from anonymizer import pdftext
from tests.helpers import Env
from tests.pdf_probe import leaks, views


def make_pdf(rows: list[list[str]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    pdftext.put_text(page, (40, 60), "Contact sheet for the audit committee", 11)
    y = 100
    for row in rows:
        pdftext.put_text(page, (40, y), "   ".join(c[:28] for c in row), 8.5)
        y += 13
    return doc.tobytes()


class CutEmail(unittest.TestCase):
    def test_email_cut_at_cell_edge_is_removed(self):
        rows = [["Name", "Phone", "Email"],
                ["Oliver Abernathy", "+1-212-555-7753", "oliver.abernathy98@demo-mail.example.com"],
                ["Yuki Delacroix", "+44 20 7430 3923", "yuki.delacroix37@demo-mail.example.com"]]
        env = Env()
        try:
            job = env.anonymize(("t.pdf", make_pdf(rows)))
            out = Path(job.files[0].out_path).read_bytes()
        finally:
            env.close()
        self.assertEqual([], leaks(out, ["Abernathy", "abernathy98", "Oliver", "delacroix37"]))

    def test_plain_handles_stay(self):
        env = Env()
        try:
            doc = fitz.open(); page = doc.new_page()
            pdftext.put_text(page, (40, 60), "clone git@github and ping @maria for review of the draft", 11)
            job = env.anonymize(("t.pdf", doc.tobytes()))
            out = Path(job.files[0].out_path).read_bytes()
        finally:
            env.close()
        self.assertIn("git@github", views(out)["text"])


class PassportCarriers(unittest.TestCase):
    """Passports that only a column makes recognisable: headerless XML rows, tab table in a log."""

    def run_text(self, name: str, text: str) -> str:
        env = Env()
        try:
            job = env.anonymize((name, text.encode("utf-8")))
            return Path(job.files[0].out_path).read_text(encoding="utf-8")
        finally:
            env.close()

    def test_xml_attribute_rows(self):
        vals = ["723549216", "E92485238", "G28244149", "A24671720"]
        rows = "".join(f'<person f0="Person {i}" f4="{v}"><x>1</x></person>' for i, v in enumerate(vals))
        out = self.run_text("c.xml", f"<contacts>{rows}</contacts>")
        for v in vals:
            self.assertNotIn(v, out)

    def test_xml_leaf_rows(self):
        vals = ["723549216", "E92485238", "G28244149"]
        rows = "".join(f"<row><cell>Person {i}</cell><cell>{v}</cell></row>" for i, v in enumerate(vals))
        out = self.run_text("c.xml", f"<t>{rows}</t>")
        for v in vals:
            self.assertNotIn(v, out)

    def test_log_tab_table(self):
        lines = ["2026-10-03 10:25:01 INFO  Name\tPassport\tCity"] + [
            f"2026-10-0{i} 11:36:02 INFO  Person{i}\t{v}\tHalifax" for i, v in enumerate(["120239680", "G56779628"], 4)]
        out = self.run_text("a.log", "\n".join(lines) + "\n")
        self.assertNotIn("120239680", out)
        self.assertNotIn("G56779628", out)


class RestoreNoDoubleDraw(unittest.TestCase):
    def test_given_name_at_line_end_is_not_glued_into_company(self):
        lines = ["Registered to SSN 522-80-4218; alt. contact Delacroix, Thomas",
                 "Northwind Holdings, 1184 Larkspur Way, Dunedin",
                 "Wire to IBAN GB84NWBK80820542505234, attn Grace B. Vandermeer"]
        doc = fitz.open(); page = doc.new_page()
        for i, ln in enumerate(lines):
            pdftext.put_text(page, (40, 80 + i * 14), ln, 9)
        data = doc.tobytes()
        env = Env()
        try:
            job = env.anonymize(("t.pdf", data))
            rb = Path(env.restore(env.as_upload(job)).files[0].out_path).read_bytes()
        finally:
            env.close()
        count = lambda b: "".join(p.get_text() for p in fitz.open(stream=b, filetype="pdf")).lower().count("thomas")   # noqa: E731
        self.assertEqual(count(data), count(rb))


if __name__ == "__main__":
    unittest.main()
