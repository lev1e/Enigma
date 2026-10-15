# Windows verification checklist (UNVERIFIED until a human runs it)

Status (updated 14.10, shift 7): nothing in this file has been run on Windows; ALL rows below are UNVERIFIED and cannot be done on the Mac. No Windows machine was available; Windows OCR, DPAPI, WebView2, the installer and the Office add-in are only statically audited (see release-checklist.md section 1). Fill the "Result" column and commit the filled copy.

Test machine: a clean Windows 10 22H2 or Windows 11 x64 account (VM is fine), desktop Office (Word, Excel, PowerPoint 2016+ or Microsoft 365), no Python installed. Run the whole list twice if possible: once on Windows 10 without WebView2 (checks the bootstrapper), once on Windows 11.

Test data: use only synthetic files from `tests/` or files you make up. Never use real customer files.

| # | Step | Expected | Result |
|---|---|---|---|
| **A. Build (machine with Python 3.12 x64, Inno Setup 6)** | | | |
| A1 | `powershell -ExecutionPolicy Bypass -File build_windows.ps1` | Finishes without a red error; prints the self-check JSON with `"ok": true` and all 7 checks true (`page_resource`, `morphology_dictionary`, `window_component`, `server_and_page`, `addin_https_page`, `helper_and_window_client`, `anonymize_and_restore`); `"frozen": true`; creates `dist\Anonymizer.exe`, `dist\Anonymizer-Setup-<version>.exe`, `dist\SHA256SUMS.txt` | |
| A2 | Note the unit result printed by `run_tests.py` | `OK`, count equals the number in release-checklist.md gate G1 (skips only for private `case/` files) | |
| A3 | Right-click `dist\Anonymizer.exe` -> Properties -> Details | File version, product version equal `__version__`; company and name are filled | |
| A4 | Size of `Anonymizer.exe` | Write the number down (no baseline exists; a jump of more than 30% between releases needs a reason) | |
| **B. Portable run (no install)** | | | |
| B1 | Copy only `Anonymizer.exe` to a new folder and double-click | Window opens in under 15 s on first start (self-extraction); no console; no Python error dialog | |
| B2 | `Anonymizer.exe --selfcheck %TEMP%\sc.json` then open the file | `"ok": true`; `window_component` true | |
| B3 | Start a second copy | The existing window comes forward; no second background process (Task Manager shows one helper) | |
| **C. Installer** | | | |
| C1 | Run `Anonymizer-Setup-<version>.exe` (no admin prompt expected: per-user install) | Installs to `%LOCALAPPDATA%\Programs\Anonymizer`; Start menu entry; optional desktop icon only if ticked | |
| C2 | SmartScreen / Defender behaviour on the unsigned installer | Record exactly what appears ("Windows protected your PC" is expected while unsigned, see signing plan) | |
| C3 | On a machine without WebView2 (Windows 10 only): install with internet | WebView2 bootstrapper runs; app window opens afterwards | |
| C4 | Same without internet | Installer shows the message that WebView2 is missing; app starts only after it is installed; app does not open a browser | |
| C5 | Task "Подключить к Word, Excel и PowerPoint" ticked | A certificate confirmation dialog for `localhost` appears; after Yes the install ends without error | |
| **D. Formats (each: Anonymize, Save as, Restore, Save as)** | | | |
| D1 | `.docx`, `.xlsx`, `.pptx` with names, email, phone, INN, a table, a header | Output opens in Word/Excel/PowerPoint without a repair prompt; values replaced by labels; restore gives a file that opens and equals the original text | |
| D2 | `.pdf` with text | Output PDF has no selectable original text (select all and copy, paste into Notepad); restore report lists the labels returned | |
| D3 | `.txt .csv .md .json .xml .html .log .yaml` | Values replaced; restore is byte-equal for plain text | |
| D4 | Several files at once, and a folder with subfolders | Same person gets the same label in all files; output folder named `... (обезличено)`; restore of the folder returns names | |
| D5 | `.doc`, `.xls`, a password-protected `.docx`, a macro `.docm` | Each is refused with a reason and an instruction; no output file | |
| D6 | Long path (more than 200 characters), Cyrillic file name, file open in Excel at the same time | Clear message or success; no crash; no half-written output | |
| **E. Images and OCR (Windows.Media.Ocr)** | | | |
| E1 | Settings -> Windows Settings -> Time and language -> Language: check that Russian and English have the "Optical character recognition" feature | Both installed. Record the state. If missing, the OCR path should say so, not silently skip | |
| E2 | Anonymize a `.png` and a `.jpg` containing a name and a phone (default mode) | Whole image replaced by a placeholder; restore returns the identical image (compare SHA256 with `Get-FileHash`) | |
| E3 | Switch to "redact text, keep image" mode, use a scan with a name, an INN and an email | Text is covered; open the output and try to read the values by eye at 100% and 300% zoom; independent OCR (e.g. Snipping Tool "Text actions") finds none | |
| E4 | Scanned PDF (image-only) in both modes | Same as E2/E3; if OCR language missing the result is a refusal or warning, never a clean "OK" | |
| E5 | `.tiff` and `.webp` | Refused with a message (unsupported, by design in this version) | |
| E6 | Time a 5-page scanned PDF | Record seconds; compare with the Mac figures in release-checklist.md (no Windows baseline exists) | |
| E7 | Windows OCR is called through PowerShell: run with PowerShell constrained language mode or with a Group Policy blocking PowerShell (corporate machine) | Clear refusal; no crash | |
| **F. Office add-in** | | | |
| F1 | Open Word; Home tab | One button "Anonymizer" with the logo. If not visible: Insert -> Add-ins -> My Add-ins -> Shared folder / Anonymizer | |
| F2 | Click the button; pane opens with no certificate or blank-page error | Pane shows "Обезличить документ" / "Вернуть данные" | |
| F3 | Anonymize the open document, then Restore | Text replaced in place; restore returns it; pane reports no mismatches; "Откатить к исходному" works | |
| F4 | Repeat in Excel (multiple sheets, formulas) and PowerPoint (notes, several slides) | Same; formulas intact; no lost slides | |
| F5 | Close the main window; the pane still works | Window hides to background; pane still answers | |
| F6 | Sign out and in, or reboot | Helper starts automatically (autostart) at normal priority; button works without opening the app first | |
| F7 | Firewall prompt on first run | Record whether Windows asks; the service listens on 127.0.0.1 only (`netstat -ano | findstr 127.0.0.1`, no 0.0.0.0 listener owned by Anonymizer) | |
| **G. Key storage (DPAPI)** | | | |
| G1 | Anonymize a file; look in the data folder (`%APPDATA%` or `%LOCALAPPDATA%` Anonymizer; path is in Settings) | Vault file exists and is not readable as text; device key file starts with `DPAPI1:` | |
| G2 | Copy the data folder to another user account / machine and start the app there | Vault does not open; a clear message says the key is protected by Windows; no crash and no silent new empty vault that overwrites the old one | |
| G3 | Settings -> Save backup with a password; clear the vault; load the backup | Vault restored; a file anonymized earlier restores correctly | |
| **H. Uninstall** | | | |
| H1 | Settings -> Apps -> Anonymizer -> Uninstall | Add-in manifest unregistered (button gone from Word after restart); autostart entry removed; process stopped; install folder removed | |
| H2 | Check what remains | Vault and data folder: record whether they stay (should stay, so user data is not lost silently; document the choice). Trusted `localhost` certificate: record whether it is removed from "Trusted Root Certification Authorities" (`certmgr.msc`, current user) | |
| H3 | Reinstall | Old vault opens; restore of an earlier file works | |

| **I. Natasha (Russian name model) in the frozen build = release gate G12** | | | |
| I1 | After A1, open the build log or the self-check JSON | No line "NER (natasha) недоступен"; if the self-check has an NER entry it is true | |
| I2 | Anonymize a Russian text file containing "Иван Петров встретил Джо Байдена. Спросите Сидорова." with default settings | Both full names become Name labels; no job note about the missing model; Settings shows the natasha switch ON | |
| I3 | Same text with the switch OFF in Settings | Output differs only by names the rules alone miss; no crash | |
| I4 | Folder size of `dist` / installed app and installer size | Write both numbers down; expected +60-70 MB folder, +25-35 MB installer (estimate, unmeasured) | |
| I5 | Delete or rename the model files inside the install folder (copy, do not touch the original) and anonymize again | Visible note that the name model is unavailable; rules still work; nothing is silently skipped | |
| I6 | Owner statement on the training-data licence of `slovnet_ner_news_v1` / `navec_news_v1` (news corpora) | Written yes/no before any public release (UNVERIFIED, legal) | |
| **J. Refusals and image modes (spot checks)** | | | |
| J1 | `.rtf`, `.odt`, `.ods`, `.odp`, `.ppt`, `.doc`, `.xls` | Each refused with a reason and the instruction to save as .docx/.xlsx/.pptx; no output file | |
| J2 | Image mode "redact text, keep image" on a scan with a logo | Output shows the kept-pixels warning in the app and in the Office pane; logo kept, text painted over | |
| J3 | Default image mode | Whole image replaced; warning text about image modes visible in Settings | |
| **L. File chat: composer and preview panel (S10-S12)** | | | |
| L1 | Open a chat with files; look at the bottom of the chat | A message line is always visible (no top-right "ИИ-чат" button); Enter sends, Shift+Enter inserts a newline; with no provider configured, Enter keeps the text and says the AI is not set up | |
| L2 | Open the preview panel on a .txt, .md, .docx, .xlsx (several sheets), .pptx, .pdf, .png result | Each shows in the panel; xlsx has sheet tabs (arrow keys switch); md shows no clickable links and no images; labels highlighted in the anonymized tab | |
| L3 | Open the "Исходный" tab | Banner says it contains real data and stays on this computer | |
| L4 | Resize the panel with the mouse and with the keyboard (Tab to the separator, Left/Right, Home/End, Enter) | Width changes and is remembered after restart | |
| L5 | Window 390 px wide equivalent (narrow the window) | Panel becomes an overlay; Tab stays inside it; Escape closes it | |
| L6 | With a real or local AI provider (UNVERIFIED so far, fake provider only): ask to change a .txt result | A new version appears with a "новая версия" marker; the original and earlier versions stay; for .docx the answer is text only | |
| L7 | Run Process Monitor / a firewall log during L2-L4 | No connection other than 127.0.0.1 | |
| L8 | Frozen build contains `anonymizer\web\vendor\` (marked, purify, highlight, MANIFEST.json) and `THIRD_PARTY_NOTICES.md` is shipped | Files present; markdown preview works inside the frozen app | |
| **K. Order of the real run (about 2 hours)** | | | |
| K1 | A (build) -> I1 (natasha present) -> B -> C -> D -> E -> F -> G -> J -> I2-I5 -> H (uninstall last) | One filled copy of this file committed | |

Record failures with: step number, screenshot, `%TEMP%\sc.json`, `setup log` (installer writes one because of `SetupLogging=yes`, in `%TEMP%\Setup Log *.txt`).
