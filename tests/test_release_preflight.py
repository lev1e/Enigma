"""An incomplete build environment must leave existing release artifacts intact."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import release_mac


class ReleasePreflight(unittest.TestCase):
    def test_missing_ner_stops_before_build_or_artifact_deletion(self):
        with mock.patch("anonymizer.ner.available", return_value=False), \
                mock.patch.object(release_mac.shutil, "rmtree") as remove, \
                mock.patch.object(release_mac, "run") as run:
            with self.assertRaisesRegex(SystemExit, "natasha"):
                release_mac.build(Path("unused.app"))
            remove.assert_not_called()
            run.assert_not_called()

    def test_missing_office_js_stops_before_artifact_deletion(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(release_mac, "ROOT", Path(tmp)), \
                mock.patch("anonymizer.ner.available", return_value=True), \
                mock.patch.object(release_mac.shutil, "rmtree") as remove, \
                mock.patch.object(release_mac, "run") as run:
            with self.assertRaisesRegex(SystemExit, "Office.js"):
                release_mac.build(Path("unused.app"))
            remove.assert_not_called()
            run.assert_not_called()
