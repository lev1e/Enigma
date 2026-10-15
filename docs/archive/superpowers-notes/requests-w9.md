# Requests from W9 (outside ownership)

1. `transform_ooxml` (formats.py, OOXML owner): macros/signature branch still writes an unchanged copy via `safe_copy`. The service now discards it (`service._anonymize_one` checks `result.integrity["macros"]` and BLOCKED), but `scan_ooxml` returns `MACRO_OFFICE` REVIEW_REQUIRED for the same file. Better to return BLOCKED without copying.
2. If ODF/RTF native support is approved: `restore.py` needs `restore_odf` (token substitution over content.xml/styles.xml/meta.xml, stripping the vault marker), `verify.check_openable` needs an ODF branch, `service.py` dispatch tables need an `ODF` kind. W9 can write `anonymizer/odf.py` and tests first.
3. `tests.test_desktop.SelfCheckTests.test_selfcheck_reports_every_component_and_exits_zero` fails in this worktree: check `addin_https_page` is False (not touched by W9; likely environment/certs). Verify on a quiet main.
4. `tests/test_ws_w9.py::test_supported_set_is_exactly_the_documented_one` pins the supported extension set; any worker adding a format must update it.
