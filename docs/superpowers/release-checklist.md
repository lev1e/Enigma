# Release checklist and signing plan (W8, 13.10)

Labels: [M] measured this session on the Mac, [S] static reading of files, [U] unverified (needs Windows or the owner).

## 1. Build chain audit (static + Mac)

| Check | Result |
|---|---|
| Third-party imports in `anonymizer/*.py` vs spec | Imports found: PIL, cryptography, docx, fitz, lxml, openpyxl, pptx, pymorphy3, webview, clr (Windows only). All are in `requirements.txt`; the spec collects fitz, cryptography, pymorphy3, `dawg2_python`, webview, pythonnet, clr_loader. `lxml`, `PIL`, `docx`, `openpyxl`, `pptx` rely on PyInstaller's built-in hooks, which are fine for these packages. [S] |
| Data files | Spec bundles `pymorphy3_dicts_ru`, `anonymizer/web`, `anonymizer/addin_web`, `anonymizer/ocr_helpers`. `ocr_helpers` holds only Swift sources (macOS); harmless but dead weight on Windows. [S] |
| Office.js vendor files | `anonymizer/addin_web/vendor/` is gitignored and fetched by `tools/fetch_office_js.py` (needs the network: npm registry). `build_windows.ps1` and the workflow both run it before tests. [S] Fresh checkout WITHOUT it: `--selfcheck` fails on `addin_https_page` [M, reproduced in a clean worktree]; with it: 7 of 7 checks pass, exit 0 [M, main checkout, source run, not frozen]. Source of the "red" selfcheck in any new worktree. |
| `--selfcheck` entrypoint | `main.py` -> `desktop.main()` -> `selfcheck(report)`; writes JSON because the exe has no console. [S] It does not exercise OCR, DPAPI, WebView2 launch of a window, or the installer. |
| Windows OCR path | `ocr.WindowsProvider` runs `Windows.Media.Ocr` through `powershell` (WinRT script written to a temp file); Tesseract is a fallback only if `tesseract` is on PATH or `ANONYMIZER_TESSERACT` is set; nothing is bundled. Needs the Russian and English OCR language features installed in Windows. [S] [U] |
| Version strings | 2.3.0: `anonymizer/__init__.py` is the source; pyproject reads it dynamically, version_info is generated, workflow and installer use it and check tag agreement. Source/version tests passed on 15.10. [M/S] |
| Installer | Inno Setup per-user (`PrivilegesRequired=lowest`, no admin), x64 only, WebView2 bootstrapper bundled when downloaded, add-in install/uninstall through `--install-addin` / `--uninstall-addin`. The bootstrapper is downloaded without a hash check. [S] |
| macOS | Release script preflights Natasha and Office.js before removing artifacts; frozen selfcheck loads the NER model. Final rebuild/validation pending the sequential verification chain. Apple Silicon, ad hoc signed. [S] |

## 2. Release gates (all must hold on the release commit; record the numbers)

| Gate | How | Pass condition | Last known number |
|---|---|---|---|
| G1 Unit suite | `.venv312/bin/python run_tests.py` on a quiet tree | OK, 0 failures, 0 errors | Final sanitized tree: Ran 1808, OK, 410.705 s; 15 skips (13 private-case tests absent from publishable copy, 2 opt-in heavy performance). Original private-case checks recorded separately in status-2026-10-15.md |
| G2 Text quality gate | `tools/eval_text.py` on text_corpus_v1, v2, en | ALL PASS on each | 14.10 `quality_gate --full` PASS: v1 678/679 fp2, v2 111/111 fp0, EN 798/800 fp1, noise 0, images leaked 0 restore 16/16, pinned real leaked 0/626, triage FP 28 |
| G3 Real-document eval | `tools/eval_real.py run --jobs 2` (ru and en) | injected leaked = 0, refusals listed, restore equal not below the previous release | 14.10 RU 116 rows leaked 0, EN 131 rows leaked 0; restore=False: 5 RU PDFs and pdf_en_manifesto (listed in status-2026-10-14.md) |
| G4 Images | `tools/eval_images.py` plus eval_real subset for scans | leaked values in produced files = 0; refused files listed | ws-img2: eval_images 16 cases leaked 0, restore exact 15/16; scan subset 90 cases, 87 with 0 leaks (3 others are csv/log) |
| G5 E2E once, alone | `tools/e2e_window.py` (opens real windows; alone and last; owner notified first) | all checks pass | Final 15.10: 178/178, first run, restart restoration OK; no screenshots or retry |
| G6 Selfcheck | frozen `Anonymizer.exe --selfcheck` | exit 0, 8 of 8 (including ner_model) | not run on Windows [U] |
| G7 Windows verification | `windows-verification.md` filled by a person | no open failure in sections A-H | not run [U] |
| G8 SECURITY review | Review image policy, outbound guard, key storage, add-in listeners and logs | Claims match implementation; outbound leak count 0 on tested corpora | D2 review is in SECURITY.md. AI wired; 15.10 targeted fake-provider E2E: 88 requests, 0 gold/original leaks. Per-message guard consent ordering fixed and regression-tested. Real providers remain unverified. |
| G9 Dependencies | `pip list` vs `requirements.txt` pins; known-vulnerability check by the owner (needs network) | pinned, no known critical issues | not run |
| G10 Version | Source version, generated metadata, installer, workflow, README and release notes | all agree | 2.3.0; single-source version tests verified in the unit suite |
| G11 Release notes | Known limits (README) reviewed against section 4 | text matches the measured numbers | draft in README |
| G12 NER bundle (natasha) and vendor dir | After a Windows build: run `Anonymizer.exe --selfcheck`, then anonymize a Russian text with "Иван Петров встретил Джо Байдена" with `ner_candidates` on; check `python -c` equivalent: `ner.available()` is True inside the frozen app (log line `NER (natasha) недоступен` must be absent). Check folder growth: expect +60-70 MB, installer +25-35 MB [estimate, unmeasured]. Spec must not exclude numpy. The whole `anonymizer/web` folder, including `web/vendor/` (marked, DOMPurify, highlight.js, MANIFEST.json, licenses/), must be in the PyInstaller datas, and `THIRD_PARTY_NOTICES.md` must ship; check that the markdown preview works in the frozen app. Training-data licence statement (Lenta.ru/news corpora behind slovnet_ner_news_v1 and navec_news_v1) must be confirmed by the owner before release | frozen app finds names; feature off silently = FAIL of this gate, not of the product | macOS frozen: 8/8 selfchecks including NER; ZIP contains weights, Office.js, vendor hashes/licenses and notices. Windows execution remains unverified |

Never write "100%" except for a literal gate result and name the gate.

## 3. Installer and signing plan (no purchases made)

Today: unsigned `Anonymizer.exe` and installer. Windows shows SmartScreen ("Windows protected your PC") and some antivirus tools flag unsigned PyInstaller one-file executables; a corporate user may be blocked outright. PyInstaller one-file also unpacks to a temp folder at every start (slower start, a typical antivirus trigger).

| Option | Cost (check current prices) | What the owner supplies | Effect |
|---|---|---|---|
| 0. Stay unsigned | 0 | nothing | SmartScreen warning on every new download; instruct users: More info -> Run anyway. Provide SHA256SUMS.txt (now generated by the build script). |
| 1. Azure Trusted Signing (Microsoft) | monthly subscription | Azure account, identity validation of an organization or individual (availability depends on country; check eligibility), service principal | Good SmartScreen reputation quickly, signing from CI possible |
| 2. OV code-signing certificate from a CA | yearly | Legal entity or individual identity documents, hardware token or cloud HSM (required by CA rules since 2023) | Signed, reputation builds over time |
| 3. EV code-signing certificate | higher yearly | Registered company, verification call, hardware token | Immediate SmartScreen trust (historically; verify current policy) |
| 4. SignPath Foundation (free for open-source) | 0 | Public open-source repository | Only if the project becomes public; the repo is currently private by decision |

Technical steps once a certificate exists: sign `dist\Anonymizer.exe` BEFORE building the installer (so the installer embeds the signed exe), then sign the installer with `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256`, always with a timestamp. In Inno Setup use `SignTool=` and `SignedUninstaller=yes`. PyInstaller: `upx=False` is already set (UPX increases antivirus flags). Consider a one-folder build inside the installer to avoid per-start unpacking; that needs a spec change (W7 owns the spec; request in requests-w8.md).

Also needed for any public release: the macOS side needs an Apple Developer ID (99 USD per year) for notarization; update signing key backup (`~/.anonymizer-release/update-signing.pem`) must exist in two places; license review for the bundled WebView2 bootstrapper redistribution (Microsoft allows it under the Evergreen distribution terms; owner confirms) and Office.js (license file shipped under `vendor/LICENSE-office-js.md`).

## 4. Release steps

1. Branch from main; bump `__version__`, `pyproject.toml`, `version_info.txt` (filevers tuple and 2 strings), workflow names, README title.
2. Run gates G1-G4, G9, G10 on the Mac. Record numbers in `queue.md`.
3. Push tag `v<version>`; workflow `Windows build` builds, self-checks, builds the installer, creates a GitHub Release.
4. Download artifacts on a clean Windows machine; run `windows-verification.md` (G6, G7). Do not publish before this passes.
5. G5 (e2e alone) on the final Mac commit, G8 (SECURITY review).
6. macOS: `tools/release_mac.py` per `docs/MAC_RELEASE.md`.
7. Publish release notes with the Known limits text.
