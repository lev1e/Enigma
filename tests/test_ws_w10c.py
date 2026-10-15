"""W10c: base64 заглушки в data:image не проходит через поиск данных, картинка в .md/.html возвращается байт в байт."""
from __future__ import annotations

import base64
import random
import unittest
from unittest import mock

from anonymizer import imagereplace
from tests.test_ws_w10 import W10Base, png_bytes


def uri_of(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


class TestDataUriExact(W10Base):
    def _roundtrip(self, name: str, body: str, b64: str):
        job, out = self.run_one(name, body.encode())
        self.assertNotIn(b64[100:160], out.read_text())
        self.assertIn(b64, self.restored(out, out.name).read_text())

    def test_secret_like_run_inside_placeholder(self):
        """Заглушка, чей base64 содержит строку, похожую на секрет, не портится и возвращается точно."""
        png = png_bytes(20)
        b64 = base64.b64encode(png).decode()
        real = imagereplace.placeholder_for

        def tainted(raw, label, ext=""):
            data = real(raw, label, ext)
            # хвост из высокоэнтропийных байтов: его base64 выглядит как токен-секрет (так бывает и у настоящих заглушек)
            return data + random.Random(5).randbytes(120)
        for name, body in (("n.md", f"# t\n\n![x]({uri_of(png)})\n"),
                           ("p.html", f'<p>hi</p><img src="{uri_of(png)}">')):
            with mock.patch.object(imagereplace, "placeholder_for", tainted):
                job, out = self.run_one(name, body.encode())
            self.assertIn(b64, self.restored(out, out.name).read_text())

    def test_repeated_md_and_html_exact(self):
        png = png_bytes(20)
        b64 = base64.b64encode(png).decode()
        for _ in range(60):
            self._roundtrip("n.md", f"# t\n\n![x]({uri_of(png)})\n", b64)
            self._roundtrip("p.html", f'<p>hi</p><img src="{uri_of(png)}">', b64)

    def test_helpers(self):
        t = 'a "data:image/png;base64,QUJD==" b'
        self.assertEqual(imagereplace.strip_data_uri_payloads(t), 'a "data:image/png;base64," b')
        (b, e), = imagereplace.data_uri_spans(t)
        self.assertEqual(t[b:e], "QUJD==")


if __name__ == "__main__":
    unittest.main()
