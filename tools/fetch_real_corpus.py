"""Fetch / verify the real-document corpus (tests/eval/real_manifest.json).

  python tools/fetch_real_corpus.py            download what is missing, verify SHA-256 of everything
  python tools/fetch_real_corpus.py --build    resolve SOURCES (licence/URL from the source API), download, rewrite the manifest

Only legally reusable files (public domain, CC0, CC-BY(-SA), Apache-2.0/MIT repos). Each file lives in its own directory
tests/eval/real/<id>/ (git-ignored: the manifest + this script are the versioned artifact). Downloads are never executed or
unpacked here. Files over MAX_BYTES are skipped. Remote content may legitimately change: a hash mismatch is reported, not
silently accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "tests" / "eval" / "real"
MANIFEST = ROOT / "tests" / "eval" / "real_manifest.json"
UA = {"User-Agent": "AnonymizerEvalBot/1.0 (levon.projob@gmail.com) test-corpus fetch"}
MAX_BYTES = 4_500_000
OK_LICENCE = re.compile(r"public domain|cc0|cc by|cc-by|no restrictions|pd", re.I)

# (id, kind, ref, fmt, lang, traits)   kind: commons (File title) | url (licence given) | gh (apache/poi path) | wiki (wikipedia article)
SOURCES: list[dict] = []


def src(id, kind, ref, fmt, lang, traits="", licence=""):
    SOURCES.append(dict(id=id, kind=kind, ref=ref, fmt=fmt, lang=lang, traits=traits, licence=licence))


# PDF: Russian legal texts (public domain / CC0 on Commons), English papers (CC-BY, two columns), forms, scans
src("pdf_ru_ukaz1843", "commons", "Указ Президента России от 06.11.1993 № 1843.pdf", "pdf", "ru", "text")
src("pdf_ru_pp962", "commons", "Постановление Правительства России от 10.09.2015 № 962.pdf", "pdf", "ru", "text")
src("pdf_ru_pp877", "commons", "Постановление Правительства РФ от 14.05.2022 № 877.pdf", "pdf", "ru", "text")
src("pdf_ru_pp1300", "commons", "Постановление Правительства РФ от 1 ноября 2018 года №1300.pdf", "pdf", "ru", "text")
src("pdf_ru_scan_pp", "commons", "Скан-образ постановления правительства России.pdf", "pdf", "ru", "scanned")
src("pdf_en_ioannidis", "commons", "Ioannidis (2005) Why Most Published Research Findings Are False.pdf", "pdf", "en", "multi-column")
src("pdf_en_manifesto", "commons", "A manifesto for reproducible science.pdf", "pdf", "en", "multi-column")
src("pdf_en_topicpages", "commons", "Topic Pages - PLoS Computational Biology Meets Wikipedia.pdf", "pdf", "en", "multi-column")
src("pdf_en_hiros", "commons", "Aid alignment for global health research – the role of HIROs.pdf", "pdf", "en", "multi-column")
src("pdf_en_1040a_2015", "commons", "Form 1040a, 2015.pdf", "pdf", "en", "form")
src("pdf_en_w2_2012", "commons", "Form W-2, 2012.pdf", "pdf", "en", "form")
src("pdf_en_1040a_2011", "commons", "Form 1040a, 2011.pdf", "pdf", "en", "form")
src("pdf_nl_consent", "commons", "Consent Form Wiki-Wetenschappers Maastricht University.pdf", "pdf", "nl", "form")
# Images: scans of Russian prints (public domain on Commons)
src("img_ru_ao1926", "commons", "Акционерные общества и товарищества (1926).png", "png", "ru", "scan")
src("img_ru_sud1926", "commons", "Третейские суды (1926).png", "png", "ru", "scan")
src("img_ru_volga1915", "commons", "Волжский день 19 апреля 1915 года страница 1.jpg", "jpg", "ru", "scan,newspaper")
src("img_ru_kharkov1989", "commons", "Евтушенко Харьков Результаты выборов 14 мая 1989.jpg", "jpg", "ru", "scan")
src("img_ru_voplenko", "commons", "Voplenko N N - General theory of law - title page.png", "png", "ru", "scan")
# Wikipedia HTML (CC BY-SA 4.0)
for _id, _lang, _title in [("html_ru_cheb", "ru", "Чебурашка"), ("html_ru_tver", "ru", "Тверь"), ("html_en_csv", "en", "Comma-separated_values"),
                           ("html_en_ocr", "en", "Optical_character_recognition")]:
    src(_id, "wiki", f"{_lang}:{_title}", "html", _lang, "article", "CC BY-SA 4.0")
# CSV (open-data repos, ODC-PDDL / CC0)
src("csv_en_countries", "url", "https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv", "csv", "en", "open-data", "ODC-PDDL-1.0")
src("csv_en_cars", "url", "https://raw.githubusercontent.com/vega/vega-datasets/main/data/cars.csv", "csv", "en", "open-data", "BSD-3-Clause")
src("csv_en_gapminder", "url", "https://raw.githubusercontent.com/datasets/gdp/main/data/gdp.csv", "csv", "en", "open-data", "ODC-PDDL-1.0")
src("csv_ru_wikidata", "url", "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(
    'SELECT ?c ?cLabel ?pop WHERE { ?c wdt:P31 wd:Q515; wdt:P17 wd:Q159; wdt:P1082 ?pop. FILTER(?pop>150000) '
    'SERVICE wikibase:label { bd:serviceParam wikibase:language "ru". } } LIMIT 80'), "json", "ru", "wikidata snapshot", "CC0-1.0")
# Office: Apache POI test-data (Apache-2.0), python-pptx / python-docx test files (MIT)

# ---- expansion (session 10): auto-searched Commons scans/contracts/invoices, more Office samples, Wikipedia (html/txt/md), Wikidata (csv/tsv/json/xml),
# ---- permissive GitHub text files (md/yaml/ini/xml/json/txt), US-government public-domain PDFs.
JUNK = re.compile(r"treaty|convention|verdrag|trait|pact|constitution|statut|accord|protocol on|charter|vertrag|tratado|convenzione|договор о|декларац", re.I)
SEARCHES = [("договор аренды", "pdf", "ru", "contract"), ("счёт на оплату", "pdf", "ru", "invoice"), ("резюме", "pdf", "ru", "resume"), ("заявление", "pdf", "ru", "form"),
            ("приказ", "pdf", "ru", "order"), ("протокол заседания", "pdf", "ru", "minutes"), ("судебное решение", "pdf", "ru", "ruling"), ("справка", "pdf", "ru", "certificate"),
            ("паспорт СССР образец", "jpg", "ru", "scan,doc"), ("удостоверение", "jpg", "ru", "scan,doc"), ("рукописное письмо", "jpg", "ru", "scan,handwriting"),
            ("письмо 19", "png", "ru", "scan,letter"), ("анкета", "jpg", "ru", "scan,form"), ("архивная справка", "jpg", "ru", "scan,archive"),
            ("invoice", "pdf", "en", "invoice"), ("lease agreement", "pdf", "en", "contract"), ("court opinion", "pdf", "en", "ruling"), ("affidavit", "pdf", "en", "form"),
            ("curriculum vitae", "pdf", "en", "resume"), ("meeting minutes", "pdf", "en", "minutes"), ("bank statement", "pdf", "en", "statement"), ("purchase order", "pdf", "en", "invoice"),
            ("census form", "jpg", "en", "scan,form"), ("receipt", "jpg", "en", "scan,receipt"), ("letter 19", "jpg", "en", "scan,letter"), ("passport sample", "jpg", "en", "scan,doc"),
            ("screenshot text", "png", "en", "screenshot"), ("screenshot email", "png", "en", "screenshot"), ("скриншот", "png", "ru", "screenshot"), ("memo", "tiff", "en", "scan"),
            ("form pdf fillable", "pdf", "en", "form"), ("annual report", "pdf", "en", "report"), ("договор", "pdf", "ru", "contract"), ("отчёт", "pdf", "ru", "report")]
for _q, _ft, _lang, _tr in SEARCHES:
    src("search:" + _q + "|" + _ft, "search", _q, _ft, _lang, _tr)
for _id, _lang, _title, _tr in [("ru_putin", "ru", "Путин,_Владимир_Владимирович", "bio"), ("ru_gazprom", "ru", "Газпром", "company"), ("ru_pushkin", "ru", "Пушкин,_Александр_Сергеевич", "bio"),
                                ("ru_sber", "ru", "Сбербанк", "company"), ("ru_moscow", "ru", "Москва", "article"), ("en_musk", "en", "Elon_Musk", "bio"), ("en_apple", "en", "Apple_Inc.", "company"),
                                ("en_curie", "en", "Marie_Curie", "bio"), ("en_lincoln", "en", "Abraham_Lincoln", "bio"), ("en_ibm", "en", "IBM", "company")]:
    src("html_" + _id, "wiki", f"{_lang}:{_title}", "html", _lang, _tr, "CC BY-SA 4.0")
    src("txt_" + _id, "wikitxt", f"{_lang}:{_title}", "txt", _lang, _tr, "CC BY-SA 4.0")
    if _id.endswith(("putin", "gazprom", "musk", "apple")):
        src("md_" + _id, "wikimd", f"{_lang}:{_title}", "md", _lang, _tr, "CC BY-SA 4.0")
_WD = ('SELECT ?p ?pLabel ?birth ?placeLabel WHERE {{ ?p wdt:P31 wd:Q5; wdt:P106 wd:{occ}; wdt:P27 wd:{ctry}; wdt:P569 ?birth. OPTIONAL {{ ?p wdt:P19 ?place. }} '
       'FILTER(YEAR(?birth)>1900) SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang},en". }} }} LIMIT 300')
for _id, _occ, _ctry, _lang in [("ru_writers", "Q36180", "Q159", "ru"), ("ru_politicians", "Q82955", "Q159", "ru"), ("en_scientists", "Q901", "Q30", "en"), ("en_actors", "Q33999", "Q30", "en")]:
    _q = urllib.parse.quote(_WD.format(occ=_occ, ctry=_ctry, lang=_lang))
    for _fmt, _acc in (("csv", "text/csv"), ("tsv", "text/tab-separated-values"), ("json", "application/sparql-results+json"), ("xml", "application/sparql-results+xml")):
        if _fmt == "csv" or _id in ("ru_writers", "en_scientists"):
            src(f"wd_{_id}_{_fmt}", "url", "https://query.wikidata.org/sparql?query=" + _q, _fmt, _lang, "wikidata people names+birthdates+places", "CC0-1.0")
            SOURCES[-1]["accept"] = _acc
GH = "https://raw.githubusercontent.com/"
# Office: direct raw.githubusercontent.com paths (no GitHub API / jsDelivr listing). Apache POI test-data = Apache-2.0; python-docx, python-pptx, docx(dolanmiu),
# calamine = MIT; XlsxWriter = BSD-2-Clause.
_POI = "apache/poi/trunk/test-data/"
OFFICE: list[tuple[str, str, str, str]] = []                       # (id, path under raw root, fmt, licence)
for _n in ["SampleDoc", "headerFooter", "TestDocument", "FancyFoot", "table_footnotes", "HeaderFooterUnicode", "ComplexNumberedLists", "bookmarks", "comment", "footnotes",
           "headerPic", "Tika-792"]:
    OFFICE.append((f"off_docx_poi_{_n.lower()}", f"{_POI}document/{_n}.docx", "docx", "Apache-2.0"))
for _n in ["tbl-cell-access", "txt-font-props", "blk-paras-and-tables"]:
    OFFICE.append((f"off_docx_pydocx_{_n}", f"python-openxml/python-docx/master/features/steps/test_files/{_n}.docx", "docx", "MIT"))
OFFICE.append(("off_docx_pydocx_test", "python-openxml/python-docx/master/tests/test_files/test.docx", "docx", "MIT"))
OFFICE.append(("off_docx_dolanmiu_template", "dolanmiu/docx/master/demo/assets/simple-template.docx", "docx", "MIT"))
for _n in ["SampleSS", "WithChart", "SimpleWithComments", "comments", "WithTable", "WithMoreVariousData", "NewStyleConditionalFormattings", "Tables", "ExcelTables", "tableStyle",
           "NumberFormatTests"]:
    OFFICE.append((f"off_xlsx_poi_{_n.lower()}", f"{_POI}spreadsheet/{_n}.xlsx", "xlsx", "Apache-2.0"))
# finance-style / feature-rich Excel-saved workbooks from the same Apache-2.0 repo (budget, shared formulas, conditional formats, validations, hidden
# sheets, multi-sheet refs, chart sheet); see docs/superpowers/finance-corpus.md. Not confidential: public test files.
for _n in ["simple-monthly-budget", "shared_formulas", "conditional_formatting_cell_is", "DataValidations-49244", "TwoSheetsOneHidden", "55906-MultiSheetRefs",
           "WithChartSheet", "61060-conditional-number-formatting", "simple-table-named-range", "55406_Conditional_formatting_sample"]:
    OFFICE.append((f"off_xlsx_poi_{_n.lower()}", f"{_POI}spreadsheet/{_n}.xlsx", "xlsx", "Apache-2.0"))
for _n in ["issues", "pivots", "merge_cells", "richtext-namespaced"]:
    OFFICE.append((f"off_xlsx_calamine_{_n}", f"tafia/calamine/master/tests/{_n}.xlsx", "xlsx", "MIT"))
for _n in ["chart_bar01", "comment01"]:
    OFFICE.append((f"off_xlsx_xlsxwriter_{_n}", f"jmcnamara/XlsxWriter/main/xlsxwriter/test/comparison/xlsx_files/{_n}.xlsx", "xlsx", "BSD-2-Clause"))
for _n in ["SampleShow", "layouts", "table_test", "shapes", "bar-chart", "sample", "present1", "WithMaster"]:
    OFFICE.append((f"off_pptx_poi_{_n.lower()}", f"{_POI}slideshow/{_n}.pptx", "pptx", "Apache-2.0"))
for _n in ["txt-text", "tbl-cell", "shp-picture", "sld-notes"]:
    OFFICE.append((f"off_pptx_pypptx_{_n}", f"scanny/python-pptx/master/features/steps/test_files/{_n}.pptx", "pptx", "MIT"))
for _id, _path, _fmt, _lic in OFFICE:
    src(_id, "url", GH + _path, _fmt, "en", "office sample (" + _lic + " test file)", _lic)
for _id, _path, _fmt, _lic in [("django_authors", "django/django/main/AUTHORS", "txt", "BSD-3-Clause"), ("requests_authors", "psf/requests/main/AUTHORS.rst", "txt", "Apache-2.0"),
                               ("flask_changes", "pallets/flask/main/CHANGES.rst", "txt", "BSD-3-Clause"), ("express_readme", "expressjs/express/master/Readme.md", "md", "MIT"),
                               ("express_history", "expressjs/express/master/History.md", "md", "MIT"), ("requests_readme", "psf/requests/main/README.md", "md", "Apache-2.0"),
                               ("requests_hist", "psf/requests/main/HISTORY.md", "md", "Apache-2.0"), ("numpy_readme", "numpy/numpy/main/README.md", "md", "BSD-3-Clause"),
                               ("lang_pom", "apache/commons-lang/master/pom.xml", "xml", "Apache-2.0"), ("io_pom", "apache/commons-io/master/pom.xml", "xml", "Apache-2.0"),
                               ("codec_pom", "apache/commons-codec/master/pom.xml", "xml", "Apache-2.0"), ("pkg_json", "expressjs/express/master/package.json", "json", "MIT"),
                               ("lodash_pkg", "lodash/lodash/main/package.json", "json", "MIT"), ("tox_ini", "pallets/flask/main/tox.ini", "ini", "BSD-3-Clause"),
                               ("setup_cfg", "psf/requests/main/setup.cfg", "ini", "Apache-2.0"), ("precommit_yaml", "pallets/flask/main/.pre-commit-config.yaml", "yaml", "BSD-3-Clause"),
                               ("owners_yml", "kubernetes/kubernetes/master/OWNERS_ALIASES", "yml", "Apache-2.0"), ("rtd_yml", "pallets/flask/main/.readthedocs.yaml", "yaml", "BSD-3-Clause"),
                               ("cpython_acks", "python/cpython/main/Misc/ACKS", "txt", "PSF-2.0"), ("curl_thanks", "curl/curl/master/docs/THANKS", "txt", "curl"),
                               ("node_authors", "nodejs/node/main/AUTHORS", "txt", "MIT"), ("react_readme", "facebook/react/main/README.md", "md", "MIT"),
                               ("kube_contrib", "kubernetes/kubernetes/master/CONTRIBUTING.md", "md", "Apache-2.0")]:
    src("gh_" + _id, "url", GH + _path, _fmt, "en", "github permissive file", _lic)
for _id, _url in [("fw9", "https://www.irs.gov/pub/irs-pdf/fw9.pdf"), ("fw4", "https://www.irs.gov/pub/irs-pdf/fw4.pdf"), ("f1040", "https://www.irs.gov/pub/irs-pdf/f1040.pdf"),
                  ("f1099msc", "https://www.irs.gov/pub/irs-pdf/f1099msc.pdf"), ("fss4", "https://www.irs.gov/pub/irs-pdf/fss4.pdf"), ("f8821", "https://www.irs.gov/pub/irs-pdf/f8821.pdf"),
                  ("f2848", "https://www.irs.gov/pub/irs-pdf/f2848.pdf"), ("f4506", "https://www.irs.gov/pub/irs-pdf/f4506.pdf"), ("fw8ben", "https://www.irs.gov/pub/irs-pdf/fw8ben.pdf"),
                  ("f1098", "https://www.irs.gov/pub/irs-pdf/f1098.pdf"), ("f941", "https://www.irs.gov/pub/irs-pdf/f941.pdf"), ("fw7", "https://www.irs.gov/pub/irs-pdf/fw7.pdf"),
                  ("sc_opinion1", "https://www.supremecourt.gov/opinions/23pdf/22-451_7m58.pdf"), ("sc_opinion2", "https://www.supremecourt.gov/opinions/22pdf/21-476_k536.pdf"),
                  ("sc_opinion3", "https://www.supremecourt.gov/opinions/21pdf/20-1530_n758.pdf"), ("sc_opinion4", "https://www.supremecourt.gov/opinions/20pdf/19-1392_6j37.pdf")]:
    src("gov_" + _id, "url", _url, "pdf", "en", "us-government form/opinion" + (",form" if _id[0] == "f" else ",ruling"), "US-Gov-PD")


def http(url: str, accept: str | None = None) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **({"Accept": accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(MAX_BYTES + 1)


def commons_info(title: str) -> dict:
    p = {"action": "query", "format": "json", "titles": "File:" + title, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
         "iiextmetadatafilter": "LicenseShortName"}
    d = json.loads(http("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p)))
    page = next(iter(d["query"]["pages"].values()))
    ii = page["imageinfo"][0]
    return {"url": ii["url"].split("?")[0], "size": ii["size"], "licence": ii["extmetadata"]["LicenseShortName"]["value"]}


_POI = None


def gh_pick(spec: str) -> tuple[str, str]:
    folder, ext, idx = spec.split(":")
    global _POI
    if _POI is None:                                     # one unauthenticated listing via jsDelivr (the GitHub API rate limit is 60/h)
        flat = json.loads(http("https://data.jsdelivr.com/v1/package/gh/apache/poi@trunk/flat"))["files"]
        _POI = [f for f in flat if f["name"].startswith("/test-data/")]
    files = sorted((f for f in _POI if f["name"].startswith(f"/test-data/{folder}/") and f["name"].lower().endswith("." + ext) and "/" not in f["name"][len(folder) + 12:]
                    and 8_000 < f["size"] < 1_500_000), key=lambda f: f["name"])
    step = max(1, len(files) // 12)
    f = files[min(int(idx) * step, len(files) - 1)]
    return "https://cdn.jsdelivr.net/gh/apache/poi@trunk" + f["name"], f["name"].rsplit("/", 1)[-1]


def resolve(s: dict) -> tuple[str, str, str]:
    """-> (url, filename, licence)"""
    if s["kind"] == "commons":
        info = commons_info(s["ref"])
        if not OK_LICENCE.search(info["licence"]):
            raise ValueError(f"licence not acceptable: {info['licence']}")
        return info["url"], Path(urllib.parse.unquote(info["url"])).name, info["licence"]
    if s["kind"] == "gh":
        url, name = gh_pick(s["ref"])
        return url, name, s["licence"]
    if s["kind"] in ("wikitxt", "wikimd"):
        lang, title = s["ref"].split(":", 1)
        if s["kind"] == "wikitxt":
            u = f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&format=json&redirects=1&titles={urllib.parse.quote(title)}"
        else:
            u = f"https://{lang}.wikipedia.org/w/index.php?action=raw&title={urllib.parse.quote(title)}"
        return u, title + "." + s["fmt"], s["licence"]
    if s["kind"] == "wiki":
        lang, title = s["ref"].split(":", 1)
        return f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{urllib.parse.quote(title)}", title + ".html", s["licence"]
    ext = s["fmt"]
    return s["ref"], s["id"] + "." + ext, s["licence"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expand_searches(sources: list[dict]) -> list[dict]:
    """Commons full-text searches -> concrete files (licence + size checked here and again in resolve())."""
    out, seen = [], set()
    for s in sources:
        if s["kind"] != "search":
            out.append(s)
            continue
        p = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{s['ref']} filetype:{s['fmt']}", "gsrnamespace": 6, "gsrlimit": 30,
             "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiextmetadatafilter": "LicenseShortName"}
        try:
            pages = json.loads(http("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p)))["query"]["pages"].values()
        except Exception:                                                  # noqa: BLE001
            continue
        k = 0
        for pg in sorted(pages, key=lambda x: x.get("index", 0)):
            title = pg["title"][5:]
            ii = pg["imageinfo"][0]
            lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
            if title in seen or JUNK.search(title) or not OK_LICENCE.search(lic) or ii["size"] > MAX_BYTES or ii["size"] < 20_000:
                continue
            seen.add(title)
            k += 1
            out.append(dict(id=f"cm_{s['fmt']}_{s['lang']}_{len(seen):03d}", kind="commons", ref=title, fmt=s["fmt"], lang=s["lang"], traits=s["traits"], licence=""))
            if k >= 2:
                break
    return out


POI_DIR = {"docx": "document", "xlsx": "spreadsheet", "pptx": "slideshow"}


def adopt_poi(have: set[str]) -> list[dict]:
    """Rebuild manifest rows for Apache POI files already on disk (tests/eval/real/poi_*/): id, path, fmt, sha256 come from the disk, URL is the
    canonical raw.githubusercontent.com path of the file name in POI's test-data folder."""
    rows = []
    for d in sorted(REAL.glob("poi_*")):
        files = [p for p in d.iterdir() if p.is_file()]
        if d.name in have or len(files) != 1:
            continue
        f = files[0]
        ext = f.suffix.lstrip(".").lower()
        if ext not in POI_DIR:
            continue
        data = f.read_bytes()
        rows.append({"id": d.name, "path": f"{d.name}/{f.name}", "fmt": ext, "lang": "en", "traits": "apache-poi test-data",
                     "url": f"{GH}{_POI}{POI_DIR[ext]}/{f.name}", "licence": "Apache-2.0", "size": len(data), "sha256": sha(data), "kind": "url", "accept": ""})
    return rows


def build(missing: bool = False) -> int:
    """missing=True keeps the existing manifest and only fetches sources whose id is not in it yet (no search re-expansion)."""
    entries, skipped = [], []
    have = {}
    if missing and MANIFEST.exists():
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
        have = {e["id"] for e in entries}
        entries += adopt_poi(have)
        have = {e["id"] for e in entries}
    for s in (SOURCES if missing else expand_searches(SOURCES)):
        if s["id"] in have or s["kind"] == "search":
            continue
        try:
            url, name, licence = resolve(s)
            data = http(url, "text/html" if s["kind"] == "wiki" else s.get("accept"))
            if s["kind"] == "wikitxt":
                data = "\n\n".join(pg.get("extract", "") for pg in json.loads(data)["query"]["pages"].values()).encode("utf-8")
            if len(data) > MAX_BYTES:
                skipped.append((s["id"], "over 4.5 MB"))
                continue
            d = REAL / s["id"]
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_bytes(data)
            entries.append({"id": s["id"], "path": f"{s['id']}/{name}", "fmt": s["fmt"], "lang": s["lang"], "traits": s["traits"],
                            "url": url, "licence": licence, "size": len(data), "sha256": sha(data), "kind": s["kind"], "accept": s.get("accept", "")})
        except Exception as ex:                                           # noqa: BLE001
            skipped.append((s["id"], f"{type(ex).__name__}: {str(ex)[:80]}"))
    MANIFEST.write_text(json.dumps({"version": 1, "files": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest: {len(entries)} files, skipped {len(skipped)}")
    for i, why in skipped:
        print("  skipped", i, why)
    return 0


def verify() -> int:
    bad = 0
    for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]:
        path = REAL / e["path"]
        if not path.exists():
            data = http(e["url"], "text/html" if e["kind"] == "wiki" else (e.get("accept") or None)) if "kind" in e else http(e["url"], "text/html" if e["fmt"] == "html" else None)
            if e.get("kind") == "wikitxt":
                data = "\n\n".join(pg.get("extract", "") for pg in json.loads(data)["query"]["pages"].values()).encode("utf-8")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if sha(path.read_bytes()) != e["sha256"]:
            bad += 1
            print("HASH MISMATCH", e["id"])
    print("verified" if not bad else f"{bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--missing", action="store_true", help="with --build: only fetch sources not yet in the manifest")
    a = ap.parse_args()
    sys.exit(build(a.missing) if (a.build or a.missing) else verify())
