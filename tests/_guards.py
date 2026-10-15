"""Skip guards for tests that need the desktop stack (pywebview / GUI) or OCR, which the ubuntu CI runner does not install.

Usage in a test module (add the import and the decorator; nothing else changes):

    from tests._guards import requires_pywebview
    @requires_pywebview
    class SelfCheckTests(unittest.TestCase): ...
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from importlib import metadata


def has_pywebview() -> bool:
    if importlib.util.find_spec("webview") is None:
        return False
    try:
        metadata.version("pywebview")
    except metadata.PackageNotFoundError:
        return False
    if sys.platform != "win32":
        return True
    # pythonnet creates clr dynamically, so an imported module has no __spec__.
    return sys.modules.get("clr") is not None or importlib.util.find_spec("clr") is not None


requires_pywebview = unittest.skipUnless(has_pywebview(), "pywebview (and pythonnet on Windows) not installed: desktop self-check needs it")
