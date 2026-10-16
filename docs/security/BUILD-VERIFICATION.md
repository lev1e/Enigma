# Native build verification

The owner authorized publishing the remediation branch and native Windows verification through GitHub Actions with unit tests and installer smoke checks enabled. Existing release assets and tags are not replaced by these verification runs.

## Build preflight

The original packaging-version test incorrectly rejected the pinned Tesseract dependency version. It now masks only the explicit four-part `choco install tesseract --version=` argument; added negative cases prove stale application versions remain rejected even on the same line. The dependency remains pinned. All 23 targeted packaging and security tests passed locally on Python 3.12.15.

Windows builds use `publish=false` and `run_tests=true`; results are recorded after completion. Local macOS arm64 builds use the existing release build and frozen-selfcheck functions, including native helper compilation, ad hoc code signing and signature verification. No release-version bump or replacement of existing v2.3.0 artifacts is part of build verification.
