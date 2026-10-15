"""English round 4 (real-corpus triage): code false positives, surname-first next to a company, csv/html carriers of injected values."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import Env


def scan(text):
    env = Env()
    d = env.service.build_detector(env.service.settings_for({}))
    d.harvest(text, "x.txt")
    return [(f.category, f.original.strip()) for f in d.scan(text, "x.txt", "text") if f.decision.value == "AUTO"]


def run_file(name, raw):
    env = Env()
    job = env.anonymize((name, raw))
    return Path(job.files[0].out_path).read_text(encoding="utf-8")


class CodeFalsePositives(unittest.TestCase):
    def test_python_decorators_are_not_handles(self):
        found = scan("Use @before_first_request or @with_appcontext here, and thank @blakeembrey.")
        self.assertEqual([v for c, v in found if c == "USERNAME"], ["@blakeembrey"])

    def test_zero_prefixed_number_is_not_phone(self):
        self.assertEqual([c for c, _ in scan("Offset +000000120 in the table, then +0000001200.") if c == "PHONE"], [])

    def test_as_is_is_not_legal_form(self):
        found = scan('Provided on an "AS IS" basis, the license says AS IS and nothing else.')
        self.assertEqual([v for c, v in found if c == "ORG"], [])

    def test_code_identifiers_are_not_domains_or_files(self):
        found = scan("Call app.route and flask.app, then org.apache.commons.io; read package.json, res.status(status).json and response.json.")
        self.assertEqual([c for c, _ in found if c in ("DOMAIN", "FILE")], [])

    def test_real_domain_still_found(self):
        self.assertIn(("DOMAIN", "mysite.io"), scan("Visit mysite.io for details."))


class SurnameFirst(unittest.TestCase):
    def test_surname_first_before_company_in_list(self):
        found = scan("SSN 547-83-1239; alt. contact Kowalczyk, John; Halcyon Dynamics, 147 Marchmont Avenue, Halifax")
        self.assertIn(("PERSON", "Kowalczyk, John"), found)
        self.assertNotIn(("ORG", "John"), found)


class Carriers(unittest.TestCase):
    def test_csv_free_text_row_in_country_column(self):
        rows = ["country,year,pop"] + [f"Country{i},2000,{i}00" for i in range(6)]
        rows.append('"Applicant: Thomas L. Whitfield, date of birth 10/07/1968","",""')
        rows += ["", "Name,Phone,Email,SSN,Passport,Address",
                 'Grace Underhill,+44 20 7335 6565,g.u@demo-mail.example.com,437-86-6666,604730109,"2270 Fenwick Street, Portland"']
        out = run_file("t.csv", ("\n".join(rows) + "\n").encode())
        for secret in ("Whitfield", "604730109", "437-86-6666"):
            self.assertNotIn(secret, out)

    def test_html_data_attribute_text(self):
        html = '<html><body><div data-owner="Ship to 2082 Larkspur Way, Springfield, contact Yuki E. Vandermeer +1-212-555-3517" hidden>x</div></body></html>'
        out = run_file("t.html", html.encode())
        for secret in ("Vandermeer", "555-3517", "Larkspur"):
            self.assertNotIn(secret, out)


if __name__ == "__main__":
    unittest.main()
