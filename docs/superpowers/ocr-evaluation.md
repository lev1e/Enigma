# OCR evaluation for the Anonymizer (scanned PDFs / images), 2026-10-08

Goal: an offline, CPU-only OCR returning word-level boxes plus text for Russian and English, so detected PII can be redacted by pixel. It must ship in a proprietary PyInstaller bundle on macOS arm64 and Windows.

Labels: **[M]** measured on this Mac (arm64, Python 3.12, throwaway venv). **[W]** verified on the web on 2026-10-08. **[I]** inferred or from memory, not verified.

## 1. Candidates

| Engine | Version [W] | Code / weights licence | Russian | Word boxes | Runtime weight |
|---|---|---|---|---|---|
| **Tesseract 5** | 5.5.1 installed [M]; tessdata_best/fast `rus` from official GitHub | Apache-2.0 / Apache-2.0 [W] | Yes, mature (`rus`) [M] | Native TSV, word level [M] | `rus` fast 3.7 MB, best 14.6 MB; `eng` fast 3.9 MB, best 14.7 MB [M]. Binary plus DLLs on Windows ~30-50 MB [I]. |
| **RapidOCR** (PaddleOCR PP-OCRv5 models via ONNX Runtime) | `rapidocr` 3.9.2 (current). Old `rapidocr-onnxruntime` 1.4.4 is capped at Python <3.13 and ships no Cyrillic. [W] | RapidOCR code Apache-2.0 (the `rapidocr-onnxruntime` metadata says so; the `rapidocr` PyPI licence field is empty, so check the repo LICENSE). PaddleOCR repo Apache-2.0 [W]; weights presumed Apache-2.0 like the repo [I]. | `eslav_PP-OCRv5_rec_mobile` (ru/be/uk/en) and `cyrillic_PP-OCRv5_rec_mobile` are in `default_models.yaml` [W]. Models are hosted on modelscope.cn. | Yes with `return_word_box=True`, tested [M] | det PP-OCRv6 small 9.9 MB + rec 7.9 MB [M]. onnxruntime 80 MB, opencv-headless 119 MB (trimmable) on macOS [M]. |
| **Apple Vision** (`VNRecognizeTextRequest`) | revision 3; `ru-RU` and `uk-UA` listed on this Mac [M] | OS API, no redistribution issue | Yes [M] | Per word via `boundingBox(for: range)` [M] | 0 MB bundled. macOS only, needs a Swift helper or pyobjc. |
| Windows.Media.Ocr | n/a, not tested (no Windows machine) | OS API | Only if the user has the OCR language pack installed (`Language.OCR~~~ru-RU~`, name unverified) [W/I]. Docs say the namespace needs package identity (MSIX) for desktop apps [W]. | Word level via `OcrWord.BoundingRect` [I] | 0 MB bundled. Pack availability is not under our control. |
| docTR | 1.1.0, Apache-2.0 [W] | Apache-2.0 | `vocabs.py` has Russian/Cyrillic vocabularies, but I found no official Cyrillic pretrained weights [W]. Not tested. | Yes | Needs torch or TF (large) [I] |
| EasyOCR | 1.7.2, Apache-2.0 [W] | Apache-2.0 | `ru` model exists [I] | Yes | Needs torch, hundreds of MB to ~1 GB bundled [I]. Not tested. |
| Surya | 0.22.1 [W] | **Code Apache-2.0; weights are a modified AI Pubs Open RAIL-M**: free for research, personal use and startups under $5M funding/revenue, otherwise a paid licence (datalab.to/pricing) [W] | Yes | Yes | Needs torch. **Flag: not usable for general commercial redistribution without a licence.** |

Packaging notes:
- Tesseract has no official Windows binary. Use the UB Mannheim build or compile it yourself, and bundle `tesseract.exe` with its DLLs and `tessdata`. On macOS use Homebrew's binary plus dylibs, or build static [I]. Calling the CLI as a subprocess avoids PyInstaller binary-hook problems; it also costs ~0.1-0.2 s process start per call [M, included in the timings below].
- RapidOCR needs `onnxruntime` (MIT) and `opencv-python-headless`, plus `numpy`, `shapely` and `pyclipper` [M, from pip]. PyInstaller handles these, but the onnxruntime native libs are big (33 MB dylib + 41 MB pybind module on macOS [M]). The model files **must be vendored**: RapidOCR downloads them from modelscope.cn at first use [M], which breaks offline use and the firewalled customers.
- **PP-OCRv6 default recognizer is not usable for Russian** [M]: with no language override, RapidOCR 3.9.2 got only Latin and digit strings right (40% hit rate, 0% on Cyrillic names).

## 2. Practical test (measured)

Corpus: 3 A4 PDFs made with PyMuPDF (Arial 11 pt, Times New Roman 10 pt, Arial 8 pt). Each has a contract paragraph, a 3x3 bordered table and a round "stamp". Each page was rendered at 150 and 300 dpi, clean (grayscale PNG) and degraded (2.5 degree skew, Gaussian noise, blur, JPEG q60). That is 12 images per engine.

Targets: "Иванов Иван Петрович" (x2), "ИНН 7707083893", "ivan.petrov@mail.ru" (x2), "+7 (495) 123-45-67" (x2), "СНИЛС 112-233-445 95", "Сидорова Анна Сергеевна" (x2). That is 10 instances per page, 30 per condition.

Ground truth comes from the PDF word boxes, with ink extents measured on the clean render and mapped through the skew transform. An instance counts as **redactable** when all three hold:
- the OCR words whose centres lie in the target region reproduce the target string with character recall of at least 0.95;
- those boxes cover at least 97% of the target's ink pixels;
- the box union is no more than 3 times the ink bbox.

| Engine (config) | clean 300 | clean 150 | skew+noise 300 | skew+noise 150 | s/page (mean of 12) |
|---|---|---|---|---|---|
| Tesseract 5.5.1, tessdata_fast, `rus+eng`, psm 3 | 100% | 100% | 97% | 87% | 0.41 |
| Tesseract, tessdata_best | 100% | 100% | 93% | 90% | 0.85 |
| RapidOCR 3.9.2, PP-OCRv6 det + cyrillic_PP-OCRv5 rec | 93% | 97% | 83% | 87% | 0.40 |
| RapidOCR, eslav_PP-OCRv5 rec | 83% | 87% | 73% | 83% | 0.42 |
| RapidOCR default (PP-OCRv6 rec) | 40% | 40% | 40% | 40% | 0.50 |
| Apple Vision rev 3, accurate, `ru-RU,en-US`, language correction off | 100% | 100% | 100% | 100% | 0.13 |

Notes on the numbers:
- Timings are wall clock per page (1240x1754 and 2480x3508 px) on an Apple Silicon laptop. Tesseract uses the default thread setting and includes process start. RapidOCR runs with the cls stage disabled, after warm-up. Cold model load for RapidOCR was about 3 s [M].
- Pooled per target type (all conditions), redactable %:
  - phone: Tesseract 96, RapidOCR cyrillic 100, Vision 100
  - e-mail: Tesseract 88-92, RapidOCR cyrillic 75, eslav 62, Vision 100
  - ИНН: Tesseract 100, RapidOCR 75, Vision 100
  - СНИЛС: Tesseract 100, RapidOCR cyrillic 92, eslav 67, Vision 100
  - names: Tesseract 96-100, RapidOCR 88-96, Vision 100
- RapidOCR failure modes seen [M]:
  - Latin/Cyrillic homoglyph mixing inside an e-mail ("реtrоv" with Cyrillic е and о).
  - Merged tokens such as "e-mail:ivan...".
  - A dropped hyphen or digit in the СНИЛС.
  - These are dangerous for regex-based PII detection downstream. They need NFKC plus a homoglyph fold on tokens that look like e-mail or digits, or fuzzy matching.
- Tesseract failure modes [M]:
  - A few e-mail and name boxes on the noisy 150 dpi skew set.
  - Its word boxes are tight and upright. On skewed pages (2.5 degrees) the box still covered at least 97% of the ink in 87-97% of cases. Pad the boxes by 2-3 px when painting.
- Vision's word boxes are loose: box area is 2-3 times the ink bbox on some strings. That is safe for redaction but can clip neighbouring text.
- Stamp text, handwriting, multi-column layouts, colour backgrounds and real scanner artefacts were **not** scored. The stamp and table were present on every page but only table-cell targets were counted.
- Sample size is small (3 pages, synthetic fonts, 30 instances per condition). Treat differences below roughly 10 points as noise. RapidOCR and Vision would probably widen their lead over Tesseract on real photographed or low-contrast scans [I], but I did not measure that.

## 3. Licence verdicts

- **Tesseract: OK** (Apache-2.0 code, Apache-2.0 tessdata). Keep the licence texts in the NOTICE file.
- **RapidOCR + PaddleOCR v5 weights: OK** by what I could verify (Apache-2.0 repos). The model files are hosted on modelscope.cn, so vendor them and record the source. Confirm the exact weight licence in the Paddle model card before shipping [I].
- **onnxruntime: MIT. OpenCV: Apache-2.0. EasyOCR: Apache-2.0. docTR: Apache-2.0.**
- **Surya: weights are NOT freely redistributable commercially** (modified AI Pubs Open RAIL-M, $5M cap). Exclude it.
- Apple Vision and Windows.Media.Ocr are OS services, so there is no redistribution question. Their behaviour does change with the OS version, which hurts reproducible audits.

## 4. Recommendation

**Use Tesseract 5 (`rus+eng`) as the one baseline OCR provider on both macOS and Windows.**
- It is the only candidate that passed the ranked requirements without a caveat:
  - Apache-2.0 for code and data.
  - Native word boxes.
  - Top-tier accuracy on the Russian/English strings in this test (100% clean, 87-97% degraded).
  - Small models (fast 7.6 MB for rus+eng).
  - Identical behaviour on both OSes.
- Apple Vision scored higher here and is cheaper at runtime, but it is macOS-only. A cross-platform product needs identical results for audits and tests.
- RapidOCR matched Tesseract's speed but was less accurate on e-mail and СНИЛС. Its homoglyph errors need a normalisation layer.

### Integration sketch

```python
@dataclass
class OcrWord: text: str; box: tuple[float, float, float, float]; conf: float   # px, top-left origin
@dataclass
class OcrPage: width: int; height: int; dpi: int; words: list[OcrWord]

class OcrProvider(Protocol):
    name: str
    def available(self) -> bool: ...
    def recognize(self, image: "np.ndarray|PIL.Image", dpi: int, langs=("rus", "eng")) -> OcrPage: ...
```

Pipeline:
1. Render with PyMuPDF at 300 dpi, or at 200 dpi for A4 speed. Extract embedded images at native resolution. Convert to grayscale and deskew only if the OCR confidence is low.
2. Call `provider.recognize()`.
3. Normalise the text: NFKC, Latin/Cyrillic homoglyph fold for e-mail/digit tokens, strip trailing punctuation. Map the matched span back to word boxes.
4. Paint boxes padded 2-3 px, then replace with placeholders. Keep the OCR text layer and mapping in the audit log.
5. Self-check after redaction: re-OCR the output page and fail the job if any detected entity is still read back.

Providers:
- `TesseractProvider`: subprocess `tesseract ... --dpi N -c tessedit_create_tsv=1 -l rus+eng --tessdata-dir <bundle>`; parse TSV level 5. Always set `--dpi`; without it Tesseract guessed 420 dpi on my PNGs [M]. Use `OMP_THREAD_LIMIT=1` and run pages in a process pool.
- `RapidOcrProvider`: optional second engine. Use cyrillic PP-OCRv5 rec with the PP-OCRv6 det, vendored under `models/`, with the download disabled.
- `AppleVisionProvider` (macOS only, optional): a small signed Swift helper (as in my `vis.swift` test) or pyobjc.
- `WindowsOcrProvider` (optional): only if the Russian OCR language pack is present.

Model bundling:
- Ship `rus.traineddata`, `eng.traineddata` (tessdata_fast, 7.6 MB total) and `osd`. Offer a "high accuracy" tessdata_best pack (about 30 MB) as a setting; in this test it did not beat fast.
- Bundle the `tesseract` binary per OS: `tesseract.exe` plus DLLs on Windows, a static or relocated build on macOS arm64 (the Homebrew binary links to Homebrew paths, so relocate or rebuild it). Verify the SHA-256 of every bundled file at startup.
- Never download at runtime; the app is fully offline.

Fallback order:
- Windows: Tesseract, then RapidOCR (only if the user enables the "enhanced" pack), then Windows.Media.Ocr if it is the only thing left.
- macOS: Tesseract by default; Apple Vision as a user-selectable "native" engine after it passes the same golden test set; then RapidOCR.
- A page runs a second engine only when the first returns an average word confidence below ~60 or finds no text on a page that clearly has image content. Never merge outputs silently; log which engine produced the redaction boxes.

Before releasing, build a golden set of 30-50 real scans (stamps, handwriting-adjacent text, photographed pages, low-contrast copies) and re-run this harness. That is the main gap in this evaluation.

## 5. Reproduction

Everything lives under `/private/tmp/claude-501/ocr-eval/`:
- `scripts/gen.py`: builds the PDFs and renders.
- `scripts/run.py`: runs all engines.
- `scripts/evalr.py`: computes the scores.
- `scripts/vis.swift`: the Apple Vision helper.
- `results.json`: raw word boxes and timings.

Nothing was installed into the repo venvs.
