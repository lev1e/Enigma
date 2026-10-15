# Publication — 2026-10-15

This report supersedes earlier publication checkpoints. The owner explicitly authorized publishing the sanitized repository to https://github.com/lev1e/Enigma and requested builds without another full test run.

- Release: https://github.com/lev1e/Enigma/releases/tag/v2.3.0. Published macOS Apple Silicon DMG and ZIP, Windows x64 portable executable and installer, update feed, and checksums.
- Release source: sanitized commit 6362334b4439dc3a66085ced4234e8cf6c3c64c5. Original Git history was not published.
- macOS was rebuilt with the approved Enigma logo. Package resources, update signature, checksums, and DMG integrity were verified.
- Windows build run 38780585779 completed compilation, frozen selfcheck, installer creation, and artifact upload. Unit tests, OCR preparation, and installed-program smoke were intentionally skipped at the owner's request. The release step collided with the already published Mac release; Windows artifacts were subsequently uploaded manually. The workflow now supports adding assets to an existing release.
- The final Linux suite was not rerun after OCR dependency fixes: the owner stopped further full test runs. Earlier verification results remain documented in status-2026-10-15.md.
- Approved light and dark logo assets are used in the desktop interface, Office pane, repository documentation, and application packaging. Native application icons use the approved light tile. No GitHub social preview was requested.
- Real Office integration, real AI credentials, Windows installation/OCR/DPAPI, and macOS Keychain still require validation on the corresponding systems. Intel Mac and mobile application packages are not provided. Licensing decisions recorded in earlier reports remain open.
