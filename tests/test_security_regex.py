"""Regression coverage for scanner findings on malformed, attacker supplied text."""
import random
import re
import subprocess
import sys
import tracemalloc
import unittest

from anonymizer.ai_chat import _edit_block
from anonymizer.bounded_regex import ConnectionPattern
from anonymizer.colctx import grids_from_html
from anonymizer.detectors import SECRET_RULES, PII_RULES
from anonymizer.textstruct import _HTML_TOKEN, _XML_TOKEN, _html_layout, _xml_layout
from anonymizer.bounded_regex import markup_tokens


class SecurityRegexTests(unittest.TestCase):
    def test_edit_block_preserves_original_extraction(self):
        original = re.compile(r"<<<ФАЙЛ>>>[ \t]*\r?\n?(.*?)\r?\n?[ \t]*<<<КОНЕЦ>>>", re.S)
        rng = random.Random(321)
        samples = ['', '<<<ФАЙЛ>>>missing', '<<<ФАЙЛ>>>a<<<ФАЙЛ>>>b<<<КОНЕЦ>>>']
        samples += ['<<<ФАЙЛ>>>' + ''.join(rng.choices(' \t\r\nxy', k=30)) + '<<<КОНЕЦ>>>' for _ in range(2000)]
        for text in samples:
            match = original.search(text)
            self.assertEqual(_edit_block(text), match[1] if match else None)

    def test_connection_matches_original_spans_including_newline_whitespace(self):
        bounded = ConnectionPattern()
        original = re.compile(bounded.pattern)
        text = "Server=Host\n=\tPwd=:"
        self.assertEqual([m.span() for m in bounded.finditer(text)], [(7, 19)])
        self.assertEqual(bounded.search(text).span(), (7, 19))
        self.assertIsNone(bounded.search("Host=database without password"))
        text = "Server=unused Host\n=database;Password=verysecret"
        self.assertEqual([m.span() for m in bounded.finditer(text)], [m.span() for m in original.finditer(text)])
        rng = random.Random(792)
        for _ in range(10000):
            text = ''.join(rng.choices(['Host=', 'Host', 'Server', 'Data Source', '=', 'Pwd=', 'Password =', 'x', ' ', '\n', '\t', ';', 'Server =', 'Data Source='], k=20))
            self.assertEqual([m.span() for m in original.finditer(text)], [m.span() for m in bounded.finditer(text)], text)

    def test_connection_scan_uses_bounded_auxiliary_memory(self):
        # Allocate the input before tracing: this checks scanner amplification,
        # rather than charging the unavoidable source text to the scanner.
        for text in ('\n' * 1000000, 'Pwd=x ' * 100000):
            tracemalloc.start()
            try:
                self.assertEqual(list(ConnectionPattern().finditer(text)), [])
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertLess(peak, 1000000)
        text = '</script></style>' * 100000
        tracemalloc.start()
        try:
            for _ in markup_tokens(text, _HTML_TOKEN):
                pass
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1000000)

    def test_phone_capture_semantics_are_preserved(self):
        rule = next(r for r in PII_RULES if 'telegram' in r.pattern.pattern)
        original = re.compile(rule.pattern.pattern.replace('*+', '*'))
        rng = random.Random(19)
        for _ in range(1000):
            number = ''.join(rng.choice('0123456789') + rng.choice(['', ' ', '-', '( )', '\t']) for _ in range(rng.randint(5, 17)))
            text = rng.choice(['тел', 'телефон', 'моб', 'whatsapp', 'telegram']) + rng.choice([' ', ': ', ' No. ', '\n\t']) + number
            self.assertEqual([(m.span(), m.group(1)) for m in original.finditer(text)], [(m.span(), m.group(1)) for m in rule.pattern.finditer(text)])

    def test_private_keys_keep_original_offsets_and_separate_blocks(self):
        rule = next(r for r in SECRET_RULES if r.reason == 'PRIVATE_KEY')
        text = 'before -----BEGIN RSA PRIVATE KEY-----\nx\n-----END RSA PRIVATE KEY----- between -----BEGIN PRIVATE KEY-----y-----END PRIVATE KEY-----'
        self.assertEqual([m.span() for m in re.finditer(rule.pattern.pattern, text)], [m.span() for m in rule.pattern.finditer(text)])

    def test_valid_markup_preserves_tokens_and_visibility(self):
        html = 'İ Σ ß <div title="x > y < z">Alice</div><!-- comment --><script type="application/json">{"name":"Alice"}</script><style>x > y</style><scrİpt>x</SCRIPT>'
        xml = '<?xml version="1.0"?><!DOCTYPE root [<!ELEMENT root ANY>]><root title="x > y < z"><![CDATA[Alice]]><!-- x --></root>'
        for text, pattern, xml_mode in [(html, _HTML_TOKEN, False), (xml, _XML_TOKEN, True)]:
            expected = [(m.span(), m.groupdict()) for m in pattern.finditer(text)]
            actual = [(m.span(), m.groupdict()) for m in markup_tokens(text, pattern, xml=xml_mode)]
            self.assertEqual(expected, actual)
        self.assertIn('Alice', _html_layout(html)[0])
        self.assertIn('Alice', _xml_layout(xml)[0])

    def test_table_grid_coordinates_and_decoding(self):
        self.assertEqual(grids_from_html('<table><tr><th>Name</th><th>ID</th></tr><tr><td>Alice &amp; Bob</td><td>123</td></tr></table>'), [[(0, 0, 'Name'), (1, 0, 'ID'), (0, 1, 'Alice & Bob'), (1, 1, '123')]])

    def test_long_malformed_inputs_finish_in_bounded_time(self):
        # A subprocess timeout prevents a regression from hanging the test suite.
        code = '''
from anonymizer.ai_chat import _edit_block
from anonymizer.colctx import grids_from_html
from anonymizer.detectors import SECRET_RULES, PII_RULES
from anonymizer.textstruct import _html_layout, _xml_layout
n = 100000
assert _edit_block('<<<ФАЙЛ>>>' * n) is None
assert _edit_block('<<<ФАЙЛ>>>' + ' ' * n + 'x<<<КОНЕЦ>>>') == 'x'
for tag in ('table', 'tr', 'td'):
    text = '<' + tag + '>'
    assert grids_from_html('<table><tr>' + text * n + '</tr></table>') == []
for reason, text in [('PRIVATE_KEY', '-----BEGIN PRIVATE KEY-----' * n), ('CONNECTION_STRING', 'Host=x ' * n + chr(10) + 'Pwd=x')]:
    rule = next(r for r in SECRET_RULES if r.reason == reason)
    assert list(rule.pattern.finditer(text)) == []
phone = next(r for r in PII_RULES if 'telegram' in r.pattern.pattern)
assert list(phone.pattern.finditer('тел' + ' ' * n)) == []
for text in ('<!--' * n, '<script>' * n, '<a title="' + '<x' * n):
    _html_layout(text)
for text in ('<!--' * n, '<![CDATA[' * n, '<root title="' + '<x' * n):
    _xml_layout(text)
'''
        subprocess.run([sys.executable, '-c', code], check=True, timeout=20)
