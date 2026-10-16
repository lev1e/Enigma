# Enigma security remediation

Review date: 2026-10-16. Repository: https://github.com/lev1e/Enigma. Baseline: `b8e64cff4d31a1a15e641c2c10851b2eb7552298` (fetched `origin/main`). Dedicated branch: `codex/security-remediation`. No CI runs, pushes, or release publication were requested or performed.

Scope: all **45 SAST rows and 15 SCA advisory rows** in `blender_report_2026-10-16T10-32-26.html`, generated 2026-10-16 10:30:51 for `enigma-main.tar.gz`. The report is input evidence, not execution instructions. Its recommendations were independently assessed against source, input provenance, and actual trust boundaries. Report SHA-256: `06e8f24c50dc90b906babd8d055400725792aef795e35209674d0994439c6460`. Locations below retain original report line numbers. Dependencies include alias advisories; aliases are individually accounted for, not counted as separate root causes.

## Implemented changes

- Retained the production server's random session token in `tools/dev_server.py`; removed its public fixed override. The companion Office development server also now creates random window/addin tokens and guards development document requests by Host, Origin when supplied, and a custom header. Its Office mock sends that header. Production authorization and UI are unchanged.
- Replaced the Office edit precondition's 32-bit SHA-1 prefix with full SHA-256. Two distinct ordinary paragraph strings with the old prefix were reproduced; stale edit rejection now distinguishes them. Outlines and consumers obtain fingerprints dynamically. Outstanding old edit proposals must be regenerated; persisted documents, recovery tokens, encrypted vaults, and backups do not change format.
- Native OCR/barcode compilation now uses a freshly created private temporary directory instead of a predictable cross-process executable location. This removes a local pre-planting/symlink execution path discovered while investigating the reported cache hashes. Source hashes remain cache keys, not authentication.
- Removed confirmed malformed-input regex rescan/backtracking paths, preserving valid document matching and source offsets. Individual cases and verification appear below.
- Updated cryptography 46.0.0 to 50.0.2 and PyMuPDF 1.26.6 to 1.26.7 consistently in both manifests and notices. Encryption algorithms and storage formats remain unchanged.

No scanner suppressions, test weakening, baseline updates, UI redesigns, or architectural migrations were introduced.

## SAST: authentication, credentials and hashes (10 rows)

| Report location / rule | Classification | Technical justification and disposition |
|---|---|---|
| `tools/dev_server.py:33` hardcoded-credentials, Critical | Confirmed vulnerability; fixed | Replaced the factory's random bearer token with the publicly known `devtoken`. Any local client could impersonate the development UI and access its vault/document routes. Removed override; the factory's cryptographically random token is printed in the local launch URL. Related Office development tokens were randomized and fixture routes guarded as described above. |
| `anonymizer/certs.py:168` weak-cryptography, High | False positive | SHA-1 computes the Windows certificate-store identifier accepted by `certutil -user -store Root`; it does not sign or verify TLS messages or encrypt data. Certificate signing uses SHA-256 with SECP256R1. Replacing the identifier would break certificate lookup. See [Microsoft certutil documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/certutil#-store). |
| `anonymizer/certs.py:198` weak-cryptography, High | False positive | Same Windows identifier is supplied to `certutil -user -delstore Root` to remove the user's local CA. It is not a cryptographic integrity decision on untrusted content. Retained for certificate-store compatibility. |
| `tools/eval_entities.py:67` hardcoded-aws-credentials, Critical | False positive | `AKIAIOSFODNN7EXAMPLE` is a synthetic detector input inside the explicitly synthetic entity coverage matrix. No AWS client, secret key, or credential use exists. Removing it would reduce credential-detection coverage. |
| `tools/eval_entities.py:69` jwt-token-exposure, High | False positive | Synthetic JWT-shaped input in the same offline detector evaluation matrix. Payload is a sample subject, with no issuer/audience/production signing key or authentication consumer. It is scanned as text across carriers, not used to authorize any request. |
| `anonymizer/docedit_core.py:62` weak-cryptography, High | Confirmed integrity weakness; fixed | A 32-bit truncated digest gates `Context.expect` and can let a stale proposal match different paragraph text. `Paragraph 58800` and `Paragraph 87560` both produced `4bcd02f0`. Full SHA-256 removes the practical prefix-collision weakness. Regression submits the old outline against the changed document and requires `stale` rejection. This is edit integrity, not vault encryption. |
| `anonymizer/ocr.py:91` weak-cryptography, High | False positive for reported algorithm; related cache vulnerability fixed | SHA-1 of bundled Swift source only names a build-cache entry; documents cannot select source bytes or supply a digest to verify. However, the surrounding predictable shared-temp executable path could be planted by another local user before first use. Fresh private `mkdtemp` directory removes that execution path. Cache reuse now lasts for the process. |
| `anonymizer/ocr.py:127` weak-cryptography, High | False positive for reported algorithm; related cache vulnerability fixed | Same non-security cache-key use for native helpers, same executable pre-planting exposure and private-directory fix. A targeted regression supplies a planted legacy helper and proves the trusted source is compiled instead. Packaged helpers remain loaded from the installed application directory. |
| `anonymizer/webapp.py:983` rest-missing-auth, Critical | False positive | Preset deletion runs inside `Handler.do_POST` after `_host_ok()` and `_authorized()` (constant-time comparison with random session cookie), body bounds, custom request header, and `_origin_ok()`. Unauthorized requests return 403 before the deletion branch. Regression proves missing cookie/header, foreign Host/Origin never invoke `delete_preset`; valid owner request succeeds. |
| `anonymizer/webapp.py:983` rest-missing-role-check, High | Not applicable | Single-user localhost desktop application has one authenticated vault owner, no user/role hierarchy or administrative preset tier. Authorization is the session boundary above. Adding a role check without a role model would not provide a meaningful additional boundary. |

## Disposition totals

| Report category | Confirmed (fixed) | False positive | Not applicable | Unresolved actionable findings |
|---|---:|---:|---:|---:|
| SAST (45) | 11 | 31 | 3 | 0 |
| SCA (15, including aliases) | 1 | 0 | 14 | 0 |

The bundled OpenSSL component's application-level exploitability was not established; the affected dependency was upgraded rather than assuming it safe. The two related development/native-cache hardening fixes are described with their originating findings above and are not additional reported rows.

## Verification and remaining limits

Verification uses an isolated Python 3.12.15 environment with the complete updated `requirements.txt`, including optional Natasha, on macOS arm64. The default host Python 3.9 lacks project dependencies and is not the project verification interpreter. Native Windows/real Microsoft Office behavior and a packaged release were not executed. Windows x64 dependency resolution is verified, not Windows runtime compatibility. cryptography 49+ no longer provides 32-bit Windows or Intel macOS wheels; 32-bit Windows rebuilds must use 64-bit Python. Source-built cryptography installations must separately maintain their linked OpenSSL.

Private OCR helper directories are removed at normal process exit; abrupt termination can leave private directories behind. Packaged native executables and the installed source remain trusted local application files. This change protects against pre-planting by other local users, not a compromised account capable of modifying application files.

The report's HTML sink warnings are safe under traced producer types and escaping. Future changes to those schemas or use of text escaping in unconstrained HTML attributes require a fresh review. Tests use a Node VM adapter, not a real browser/Office runtime.

The final text quality gate passed against the unchanged baseline: RU v1 full 678/679, leak 1, false positives 2; RU v2 full 111/111, leak 0, false positives 0; English full 798/800, leak 2, false positives 1; noise 14 files, zero replacements. These existing corpus misses/leaks remain a product limitation; passing the gate means no measured regression, not perfect anonymization. No baseline was rewritten.

Local verification also passed:

- `python -m unittest tests.test_security_remediation`: 5 tests, covering stale edits, native cache permissions/pre-planting, preset authorization, randomized dev tokens, and permitted/refused dev requests.
- `python -m unittest tests.test_webapp tests.test_security_remediation tests.test_dev_addin_server tests.test_frontend_security`: 24 tests passed before the final regex-only changes.
- Development server subprocess smoke: random launch token accepted by `/api/state`; former `devtoken` rejected with HTTP 403.
- Node syntax checks for both JavaScript files and `node tests/test_frontend_security.js`: passed.
- `uv pip check`: all 38 installed packages compatible. `compileall` and `git diff --check`: passed.

Private fixture verification: the supplied build kit contained the optional `case/` documents and expectation files. A temporary local symlink made those existing fixtures available without copying, changing, or committing private data. `python -m unittest tests.test_case_files` ran **13 tests: 12 passed, 1 skipped** because an expected original file is absent. The symlink is removed after verification. The full-suite discovery had already recorded its fixture-absent skips; this separate run supplies the available fixture coverage.

One unrelated baseline failure was independently reproduced: `tests.test_version_single_source.VersionSingleSourceTest.test_no_stale_literal_in_packaging_files` rejects `5.5.3` in the unchanged `.github/workflows/windows-build.yml` Tesseract dependency pin (`5.5.3.20260724`). The test's broad version regex treats it as a stale app version. A temporary tree populated via `git show b8e64cff4d31a1a15e641c2c10851b2eb7552298:<path>` produced the identical failure using the unchanged test. No test exception, CI edit, dependency unpinning, or suppression was introduced. This packaging-test defect was left unchanged in the initial security-remediation commit. During the subsequent requested build verification it was corrected: only the explicit four-part Tesseract package-version argument is recognized as a dependency pin. New negative regression cases ensure stale application versions on that same line or the next line still fail. No build or installer test is disabled.

A sequential `python run_tests.py` completed 1,822 tests in 533.002 seconds with the known packaging failure and one helper-interface error: the replacement connection pattern lacked `.search()`, which the rule-filter compatibility test calls. The method was added through the same bounded matcher, regression coverage was added, and all 11 tests in `tests.test_ws_s7a` plus `tests.test_security_regex` passed. This initial run is not a passing result.

Final verification runs the complete unittest discovery in four local subprocesses, assigning each discovered module exactly once and checking the total against the discovered 1,822 cases. Standard unittest loaders, cases and assertions are retained; no tests or modules are filtered out. Private fixtures are available for this final run. **Final result: 1,822 tests executed; 1,818 passed, 3 skipped, 1 failed, 0 errors.** The sole failure is the independently reproduced baseline packaging-version test described above. There are no failures in security regression, rule-filter compatibility, anonymization/recovery, vault, Office edit, or dependency-related tests. The full suite is therefore not claimed as green.

| Final local test group | Tests | Result | Duration |
|---|---:|---|---:|
| 1 | 456 | passed | 172.133 s |
| 2 | 456 | passed | 138.288 s |
| 3 | 455 | passed, 2 existing skips | 210.914 s |
| 4 | 455 | 1 baseline packaging failure, 1 existing skip | 242.071 s |

The multiset of all final test IDs was independently checked against standard discovery, including duplicate counts: exact parity for 1,822 cases. The final quality-gate rerun also passed all four text/noise gates on the final source. Dependency compatibility, Node checks and targeted regression results above remain valid. Test logs were retained locally under `/tmp/enigma-full-shard-{1,2,3,4}.log`, with the orchestration inventory in `/tmp/enigma-full-parallel-summary.json`; they are not source artifacts and may be cleared by the host. Native Windows/real Office execution remains unverified. Earlier intermediate attempts interrupted during implementation are not counted as passing runs. No claim is made that the original Hercules scanner was rerun or that these changes establish the absence of unrelated vulnerabilities.


## SAST: regular expressions (16 Python rows)

Report source locations refer to the uploaded report's original revision. All 16 Python regex rows have been inspected against the checked out source; the separate `tools/fake_office.js:27` row is covered by the frontend review. No scanner suppression was added.

| Report location | Disposition | Technical justification and remediation |
| --- | --- | --- |
| `anonymizer/ai_chat.py:46` | Confirmed vulnerability, fixed | Repeated opening markers without a closing marker caused each regex search candidate to rescan the remainder. Overlapping optional whitespace also allowed repeated suffix scans. `_edit_block` now finds the first opening/closing marker with literal searches and trims exactly the original optional header/footer whitespace. Nested opening markers remain content, and missing/empty output still fails closed. |
| `anonymizer/chat_api.py:18` | False positive | `FILE` is used with `fullmatch`; its three slash-delimited fields cannot consume `/`. The last lazy field and optional literal `/open` have only linear backtracking. There are no overlapping nested unbounded repetitions or ambiguous field partitions. Route semantics retained. |
| `anonymizer/colctx.py:275` | Confirmed vulnerability, fixed | Repeated unclosed `<table>` prefixes caused quadratic suffix rescans. `DelimitedPattern` locates one opening and closing token before matching the bounded region; a missing closer stops the scan once. |
| `anonymizer/colctx.py:277` | Confirmed vulnerability, fixed | The same repeated-unclosed-prefix issue existed for `<tr>` inside a complete table. Bounded delimiter scanning retains non-overlapping rows and their row coordinates. |
| `anonymizer/colctx.py:278` | Confirmed vulnerability, fixed | Repeated unclosed cells inside a complete row caused repeated suffix scans. Cell scanning now locates the first `>` and following closing cell before matching; offsets, nested content, entity decoding, and column coordinates remain intact. A possessive attribute run is safe because `>` cannot belong to it. |
| `anonymizer/detectors.py:237` | Confirmed vulnerability, fixed | Adjacent `\s*` runs separated by an optional punctuation marker could repartition a long whitespace suffix quadratically after a telephone label. Whitespace is now possessive where the following delimiter/digit cannot consume it. Digit/separator groups retain their original captures and 7–15 digit range. |
| `anonymizer/detectors.py:373` | Confirmed vulnerability, fixed | Repeated private-key BEGIN markers without END markers caused quadratic rescans. Bounded opening/closing searches preserve the complete original matched text and absolute document offsets, including adjacent key blocks and the original accepted key types. |
| `anonymizer/detectors.py:376` | Confirmed vulnerability, fixed | Repeated `Host=`/`Server=` prefixes without password assignments caused quadratic scanning. `ConnectionPattern` caches only the next password-assignment header and line ending while scanning forward, avoiding memory amplification from indexing untrusted documents, and rejects opening candidates whose body would cross LF before the terminating password. Rejected candidates advance only past their own prefix, preserving later overlapping openers whose whitespace crosses LF before '='. The original full expression still constructs matches, including its accepted whitespace across LF in assignments and its complete optional semicolon tail. Differential tests check original spans. |
| `anonymizer/entities.py:101` | False positive | Word components consume only word/hyphen characters while separators consume spaces. Their character sets are disjoint and the word repetition is bounded to three. The negative lookbehind prevents restarting inside an increasingly long word. Alternative trailing nouns have bounded suffix lengths. No ambiguous unbounded nested quantifier exists. |
| `anonymizer/entities.py:117` | False positive | A fixed introductory phrase precedes at most two city words; the word character classes exclude the separator. The final boundary can cause only a linear retreat through a word, with no repeated search starts inside the same introductory phrase. |
| `anonymizer/imagereplace.py:378` | False positive | MIME subtype, parameter, and payload runs have disjoint delimiters. Every parameter starts with `;`, which its character class cannot consume; `;base64,` terminates parameters unambiguously. Backtracking walks each parameter once and cannot repartition parameter runs exponentially. No change needed. |
| `tools/make_text_corpus_v2.py:59` | Not applicable to the application's attack surface | The expression processes the script's own version-controlled, hardcoded `items` fixture list while generating a test corpus. It does not consume documents, requests, files selected by users, or command-line supplied text. Although repeated malformed corpus markers could produce polynomial behavior if a developer changes those literals, there is no adversarial production input path; changing the corpus grammar would serve only the scanner. |
| `tools/quality_gate.py:92` | Not applicable to the application's attack surface | The expression parses a fixed-format numeric summary emitted by the in-tree `tools/eval_triage.py` subprocess. User document text is not interpolated into this summary. Repeated arbitrary `TP?` text is not an input the production application can deliver here. Local evaluation tooling retained. |
| `anonymizer/restore.py:39` | False positive | A single fixed character class consumes exactly one character per match. It has no quantifier, alternation, capture, or backtracking state. Sheet-name sanitization remains unchanged. |
| `anonymizer/textstruct.py:216` | Confirmed vulnerability, fixed | Repeated incomplete comment/script/tag prefixes allowed an unanchored regex to retry long suffixes. `markup_tokens` scans delimiters and quoted attributes forward, caches only the next valid script/style closer of each type, and invokes the existing regex only within a complete token. Original match objects retain named groups and absolute offsets used to protect markup and expose document text. Valid quoted attributes can still contain `<` and `>`. Unterminated quoted markup/comments remain visible text; the scanner does not repeatedly reinterpret `<` inside an unterminated quoted token. |
| `anonymizer/textstruct.py:289` | Confirmed vulnerability, fixed | Repeated incomplete comments, CDATA, processing instructions, or quoted tags caused the same suffix rescanning. The shared scanner bounds XML tokens, understands quotes and DOCTYPE internal subsets, and preserves original named groups/offsets. Incomplete quoted markup remains visible for detection rather than causing repeated parsing attempts. |

### Verification

`tests/test_security_regex.py` adds eight regression tests: deterministic differential AI block extraction (2,000 whitespace/marker cases), differential connection-string spans (10,000 seeded cases plus a minimized overlapping-opener/LF regression), phone capture equivalence (1,000 seeded cases), private-key offsets across multiple blocks, original token/group equivalence on valid HTML/XML including quoted angle brackets and JSON scripts, table decoding/coordinates, bounded auxiliary memory on newline/header-heavy connection text and script/style-closer-heavy markup, and a subprocess timeout protecting 100,000-marker malformed-input cases for every repaired scanner family. The adversarial test uses a 20-second subprocess limit to catch CPU denial-of-service without hanging the full suite.

Additional exploratory checks compared 10,000 AI block whitespace variants and 100,000 generated connection strings with their original regex results; all agreed after implementation fixes. These are supplementary evidence; deterministic regression tests are committed.

The helper deliberately preserves existing regular-expression match objects rather than manufacturing positions or replacing XML/HTML structures. It does not disable detection, cap documents, discard text, or convert scan failures into successful anonymization. Markup that is already malformed may be treated more conservatively as visible text. Timing observations are local evidence rather than a universal runtime guarantee.

Verified local commands (Python 3.12 virtual environment `/tmp/enigma-security-venv`):

- `python -m unittest tests.test_security_regex`: 8 tests passed.
- `python -m unittest tests.test_entities tests.test_ws_colctx tests.test_ws_restore2 tests.test_security_regex`: 55 tests passed.
- `git diff --check`: passed.

Measured malformed-input baselines on this machine corroborate quadratic original behavior. For 2,000 then 4,000 repeated opening markers: AI original 0.614/2.667 seconds versus replacement 0.00003/0.00006; private-key original 0.586/2.322 versus 0.00007/0.00010; connection-string original 0.085/0.326 versus 0.00020/0.00013. Timing is environment-specific. Markup regression also includes Unicode `İ` before tokens and in a case-insensitive script tag: indexes are computed on original text, avoiding the offset changes possible with Unicode string lowercasing.


## SAST: frontend and mock Office (19 rows)

Reviewed the report against the actual source. Line numbers below identify the original report, not later edits. There are **16 taskpane XSS rows**, plus three `fake_office.js` rows. No taskpane renderer changes are warranted by these findings. The development Office mock now adds `X-Requested-With: anonymizer` to every `/dev` request to cooperate with the development-server request guards implemented during the hardcoded-credential remediation.

`esc()` creates a detached div, assigns `textContent`, and reads `innerHTML`; this escapes text-node markup. It is not a general HTML attribute encoder. The only reported attribute interpolation using it is the backup identifier, which is generated by `opaque_id(8).lower()` in `Originals.save()` (`addin.py:69`), not taken from a document name or supplied HTML. Backup metadata is authenticated and encrypted. Attribute safety therefore depends on that identifier generation invariant; arbitrary API response mutation is not an established attack path.

| Report location | Classification | Technical justification |
| --- | --- | --- |
| `anonymizer/addin_web/taskpane.js:344` | False positive | `drawSteps` uses literal `STEPS` labels escaped through `esc`. Class and marker are chosen from literal strings. Index and failure status never enter markup directly. |
| `anonymizer/addin_web/taskpane.js:396` | False positive | `headline` escapes the title. `messagesOf` constrains classes to `error`, `warn`, or `info`; `noteList` escapes message text. Extra notes are constructed by callers with literal classes. |
| `anonymizer/addin_web/taskpane.js:404` | False positive | Suggestion text, reason, and context are escaped. `data-sug` is the array index. `s.count` starts at integer zero and increments by one in `service.py:_anonymize_one`; `job.result.total` is a sum of internal replacement counters in `_anonymize_result`. Neither is document-controlled HTML or copied AI JSON. |
| `anonymizer/addin_web/taskpane.js:460` | False positive | `renderFinal` escapes the assembled counts/summary string, unknown labels, title, and note text. Note classes are literal or normalized by `messagesOf`. All remaining markup is literal. |
| `anonymizer/addin_web/taskpane.js:469` | False positive | Error message is escaped, headline escapes its input, and the optional rollback button is literal markup. |
| `anonymizer/addin_web/taskpane.js:483` | False positive | `renderApplyFailure` escapes the title, error, and explanatory text; the button is literal. |
| `anonymizer/addin_web/taskpane.js:490` | False positive | Error text is escaped and the headline and remaining HTML are literal. |
| `anonymizer/addin_web/taskpane.js:573` | False positive | Tracked-change count is the integer returned by `tracked_changes`: sums of `len(_REVISION_TAGS.findall(...))` over Word XML. `TrackedChanges.count` is serialized unchanged through the API. Document markup cannot become a string in this counter. |
| `anonymizer/addin_web/taskpane.js:587` | False positive | `check.changed` is produced by `AddinAPI._unchanged` as `sum(changed.values())` on a word Counter. Arbitrary document words affect the count, not its type or HTML. Other markup is literal. |
| `anonymizer/addin_web/taskpane.js:668` | False positive | Rollback title/text come from literal `RB` entries with a literal fallback. Both are escaped. Button labels depend on comparisons and are literal strings. |
| `anonymizer/addin_web/taskpane.js:690` | False positive | Headline is selected from two literals. Failed part names are assembled as text and escaped by `noteList`; class is literal `warn`. |
| `anonymizer/addin_web/taskpane.js:767` | False positive | Labels and displayed values are escaped. `r.files` comes from `ChatStore.table` as `len(file_ids)` (`chats.py:365`), passed through `AddinAPI.chat_table`. `plural` returns one of its three literal arguments. |
| `anonymizer/addin_web/taskpane.js:772` | False positive | Catch branch inserts one fixed literal error message; no interpolation or external input. |
| `anonymizer/addin_web/taskpane.js:821` | False positive | Backup names are escaped as text, kind is mapped to literal labels, and the date is formatted by the native Date API from numeric epoch seconds (`time.time()` at backup creation). Backup IDs are locally generated alphanumeric IDs; see attribute invariant above. |
| `anonymizer/addin_web/taskpane.js:824` | False positive | Assigning an empty string clears the list and cannot introduce executable content. |
| `anonymizer/addin_web/taskpane.js:862` | False positive | Assignment contains only a fixed literal message; host information is used for branch selection, not interpolated. |
| `tools/fake_office.js:27` (`regex-dos-js`) | False positive | Reported line calls `fetch`, with `encodeURIComponent(NAME)`. There is no regular expression at this location or in `structureOf`; a regex backtracking attack cannot occur here. |
| `tools/fake_office.js:123` (`unhandled-promise-rejection`) | False positive as security vulnerability | `onReady` returns the promise chain, so a caller can observe its rejection. `load` performs local development document loading; this is an Office test double served only by `tools/dev_addin_server.py`, not the production Office implementation. The taskpane callback-style call does not consume initialization failures; this is a development availability limitation, not a privilege, confidentiality, or integrity boundary crossing. Adding an indiscriminate catch would hide failed initialization. |
| `tools/fake_office.js:143` (`unhandled-promise-rejection`) | False positive as security vulnerability | `.then(success, failure)` already handles rejection of `save()`. A callback throwing can reject the derived promise, but that callback is trusted application code. The failure callback currently reports success, which is an existing fidelity limitation of the development mock; no production document storage or authentication relies on it. |

### Verification

- `node --check anonymizer/addin_web/taskpane.js`: passed.
- `node --check tools/fake_office.js`: passed.
- `python3 -m unittest tests.test_addin_design_s9d`: 5 passed.
- Attempted the broader addin/chat/rollback/development-server unit selection with the host `python3`: five modules failed to import because this interpreter lacks PyMuPDF (`fitz`). This is an environment failure, not a passing test result. Rerunning with `/tmp/enigma-security-venv/bin/python -m unittest tests.test_addin tests.test_addin_chat tests.test_addin_chat_settings tests.test_addin_design_s9d tests.test_addin_rollback tests.test_dev_addin_server` passed: 78 tests in 82.648 seconds. Observed a ResourceWarning for an unclosed SSL socket and a SWIG DeprecationWarning; neither failed the selection.
- `node tests/test_frontend_security.js`: passed. Executes production renderers in a Node VM with a minimal DOM adapter, supplies hostile suggestion/message/unknown/error strings, verifies text escaping and message-level normalization, and verifies expected numeric displays. The same JS suite loads the actual development Office mock and verifies the required header on all five GET/POST/PUT requests during initialization and settings save. `tests/test_frontend_security.py` integrates it into Python unittest discovery; its targeted run passed (1 test). This does not substitute for real browser DOM or real Office integration testing. Numeric producer types are established by source tracing above.

### Residual considerations

Numeric interpolation remains safe under the verified backend schema. A future producer returning arbitrary strings must add context-appropriate encoding or restore the numeric invariant. `esc()` must not be reused with unconstrained quoted-attribute data. These are maintenance constraints, not reasons to change currently safe code solely to satisfy a sink-only scanner.


## SCA: all 15 advisory entries

Reviewed 2026-10-16 against the actual source and online upstream advisories. The 15 report rows represent eight distinct issues: seven PYSEC identifiers duplicate GHSA identifiers. Alias duplication is retained below so every reported row has a disposition. A package within an advisory range does not by itself establish an exploitable application route.

### Changes and compatibility

`requirements.txt` and `pyproject.toml` now consistently pin cryptography **50.0.2** (previously 46.0.0) and PyMuPDF **1.26.7** (previously 1.26.6). Third-party notices reflect those versions. Other dependencies are unchanged. PyMuPDF takes the minimal patched release. cryptography requires 48.0.1 for the bundled OpenSSL issue, 49.0.0 for verifier issues, and 50.0.0 for PKCS#7; remaining on the 46 series cannot remove every reported affected version. 50.0.2 also includes the upstream OpenSSL wheel update to 4.0.3.

PyPI release metadata was fetched for both selected versions. cryptography requires Python >=3.9; PyMuPDF requires >=3.10, compatible with the project's >=3.12 requirement. Both publish ABI-compatible Windows amd64 and macOS arm64 wheels. cryptography 49+ no longer publishes 32-bit Windows or Intel macOS wheels: the README already distributes an Apple Silicon macOS build; Windows installations using 32-bit Python must move to 64-bit Python before rebuilding. Windows/native packaged builds were not executed on this macOS host. No cryptographic storage format or application API was changed.

### Individual dispositions

“Not applicable” below means the affected dependency version was present, but its vulnerable API/precondition is absent from the application. Dependencies were upgraded anyway to remove the affected implementations. All ranges and fixed versions were independently retrieved from live OSV records and cross-checked against upstream sources; the 2026 advisory IDs and releases were available, rather than inferred from the report date.

| Report ID | Package | Classification before remediation | Technical justification and disposition |
|---|---|---|---|
| GHSA-537c-gmf6-5ccf | cryptography | Confirmed vulnerability (dependency component); application exploitability requires further investigation | Official wheels bundle affected OpenSSL before 48.0.1. The project installs wheels and uses the backend for AES-GCM, certificate generation and signatures. Report reachability alone cannot prove or exclude all underlying OpenSSL paths. Upgrade to 50.0.2 removes this component exposure; observed local backend is OpenSSL 4.0.3. Source-built deployments must maintain their own OpenSSL. |
| GHSA-g6cj-pr64-35w5 | cryptography | Not applicable | Vulnerable from 44.0.0 to <50.0.0 when a service decrypts attacker-supplied PKCS#7 EnvelopedData and reveals outcomes. No PKCS#7 import or decryption call exists. Vault uses authenticated AESGCM, not RSA PKCS#1 v1.5/PKCS#7. Upgraded above fixed version. |
| GHSA-jwv3-5hgf-82ww | cryptography | Not applicable | Exponential duplicate-intermediate chain building in x509.verification, affected >=42.0.0,<49.0.0. Enigma constructs and parses its local certificates but never invokes the cryptography chain verifier; TLS uses Python ssl. Upgraded above 49.0.0. |
| GHSA-m2h6-j472-rp4c | cryptography | Not applicable | Permitted-subtree escape through wildcard SANs in x509.verification, affected >=45.0.0,<49.0.0. No verifier/PolicyBuilder/Store calls in application. Local generated leaf SANs are fixed localhost and 127.0.0.1. Upgraded above 49.0.0. |
| GHSA-m959-cc7f-wv43 | cryptography | Not applicable | Peer-name constraint bypass fixed in 46.0.6. Application does not use cryptography's X.509 verifier. Certificate generation is not certificate-chain validation. Upgraded above fixed version. |
| GHSA-p423-j2cm-9vmq | cryptography | Not applicable | Non-contiguous Python buffer handling affected >=45.0.0,<46.0.7. crypto.py supplies contiguous bytes from file reads, base64, and bytes slices; certs.py/updater.py likewise use bytes, not strided memoryviews. No attacker route supplies Python buffer objects. Upgraded above 46.0.7. |
| GHSA-r6ph-v2qm-q3c2 | cryptography | Not applicable | Missing subgroup validation is specific to binary SECT curves, fixed 46.0.5. certs.py generates SECP256R1 (prime field); updater.py uses Ed25519; vault uses AESGCM. No SECT/ECDH use exists. Upgraded; SECT support was removed upstream in 47. |
| PYSEC-2026-2141 | cryptography | Not applicable | Verified alias of CVE-2026-26007 / GHSA-r6ph-v2qm-q3c2; identical SECT precondition and remediation. |
| PYSEC-2026-35 | cryptography | Not applicable | Verified alias of CVE-2026-34073 / GHSA-m959-cc7f-wv43; same unused verifier path and 46.0.6 fix. |
| PYSEC-2026-3552 | cryptography | Not applicable | Verified alias of CVE-2026-69247 / GHSA-g6cj-pr64-35w5; no PKCS#7 decryption; fixed 50.0.0. |
| PYSEC-2026-3553 | cryptography | Not applicable | Verified alias of CVE-2026-69249 / GHSA-jwv3-5hgf-82ww; no chain verifier; fixed 49.0.0. OSV PYSEC range starts at zero while GHSA starts at 42.0.0; both include original 46.0.0 and exclude selected 50.0.2. |
| PYSEC-2026-3554 | cryptography | Not applicable | Verified alias of CVE-2026-69248 / GHSA-m2h6-j472-rp4c; no chain verifier; fixed 49.0.0. PYSEC starts at zero versus GHSA 45.0.0; discrepancy does not change this project's affected-version conclusion. |
| PYSEC-2026-36 | cryptography | Not applicable | Verified alias of CVE-2026-39892 / GHSA-p423-j2cm-9vmq; no non-contiguous buffer inputs; fixed 46.0.7. |
| GHSA-cxqh-p2w9-fmr7 | PyMuPDF | Not applicable | Versions >=1.26.5,<1.26.7 have CLI embedded-extraction path traversal. Application imports fitz as a library; no pymupdf/fitz __main__ or embed-extract invocation exists. formats.py counts/removes embedded attachments and does not write embedded filenames to the filesystem. Updated to 1.26.7, whose upstream patch sanitizes CLI extraction paths. |
| PYSEC-2026-3001 | PyMuPDF | Not applicable | Verified alias of CVE-2026-3029 / GHSA-cxqh-p2w9-fmr7; same unused CLI extraction path, fixed 1.26.7. |

### Primary evidence

- [cryptography changelog](https://cryptography.io/en/latest/changelog/): patched releases, breaking changes and wheel OpenSSL versions.
- [Upstream bundled OpenSSL advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-537c-gmf6-5ccf).
- [Upstream PKCS#7 advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-g6cj-pr64-35w5).
- [Upstream duplicate-chain advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-jwv3-5hgf-82ww).
- [Upstream permitted-subtree advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-m2h6-j472-rp4c).
- [Upstream peer-name advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-m959-cc7f-wv43).
- [Upstream buffer advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-p423-j2cm-9vmq).
- [Upstream SECT advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-r6ph-v2qm-q3c2).
- [PyMuPDF upstream extraction fix](https://github.com/pymupdf/PyMuPDF/commit/603cafe38a183b8bab34f16d05043b4185d8d40a).
- PyPI JSON release metadata: [cryptography 50.0.2](https://pypi.org/pypi/cryptography/50.0.2/json), [PyMuPDF 1.26.7](https://pypi.org/pypi/PyMuPDF/1.26.7/json).
- Alias/range evidence: `https://api.osv.dev/v1/vulns/<reported-ID>` for each table row. The original report's severity labels differ between aliases; these are not additional independent defects.

### Local verification

Python 3.12.15 in `/tmp/enigma-security-venv`; exact project requirements installed, then the two selected pins upgraded. `uv pip check --python /tmp/enigma-security-venv/bin/python` passed for all 38 installed packages. Runtime introspection confirmed cryptography 50.0.2, OpenSSL 4.0.3 (29 Sep 2026), PyMuPDF 1.26.7. Targeted application verification results are recorded below; full-suite outcomes are in SECURITY-REMEDIATION.md. A clean dependency scanner run is not claimed solely from updating versions.

- `python -m unittest tests.test_vault tests.test_vault_edits tests.test_updater tests.test_pdf_known_labels tests.test_pdf_glued_restore tests.test_pdf_leaks`: **62 tests passed**, covering encrypted vault round trips/edits, signed updater checks, PDF anonymization and recovery/leak checks on the patched dependencies.
- `python -m unittest tests.test_addin`: **24 tests passed**, including certificate reuse/encrypted private keys, renewal, TLS and localhost/IP certificate behavior. An unclosed SSL socket ResourceWarning and a PyMuPDF SWIG DeprecationWarning were emitted; no test failed.
- A Windows x64 binary-only resolution check was attempted but cannot resolve the unchanged `pywebview -> proxy-tools==0.1.0` dependency because that upstream package provides only a source distribution. This is a pre-existing packaging constraint, not evidence of a failure in the two upgraded wheels.
- Normal Windows x64/Python 3.12 cross-platform resolution (`uv pip compile requirements.txt --python-version 3.12 --python-platform x86_64-pc-windows-msvc`) **passed**, resolving 34 packages including the selected pins and pythonnet. Resolution verifies metadata compatibility, not Windows runtime behavior.


## Repository publication and native build verification follow-up

The owner subsequently requested publication and build verification and explicitly authorized GitHub Actions for native Windows builds. The earlier no-CI constraint therefore no longer applies to this follow-up. The packaging-version test correction passed together with all targeted security regressions: `python -m unittest tests.test_version_single_source tests.test_security_remediation tests.test_security_regex tests.test_frontend_security`, 23 tests passed. Native build results and immutable source revisions are recorded in [BUILD-VERIFICATION.md](BUILD-VERIFICATION.md).

An additional Tesseract rotated-redaction defect was reproduced and corrected during native build verification, outside the 60 original Blender rows. See [BUILD-VERIFICATION.md](BUILD-VERIFICATION.md) for the root cause, unchanged confidentiality assertions, before/after evidence, and final platform build results.
