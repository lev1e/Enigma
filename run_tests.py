import unittest


if __name__ == "__main__":
    import sys
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    # top_level_dir делает тесты пакетом `tests`, иначе относительные импорты внутри них рвутся.
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
