"""NER-as-second-detector measurement (read-only on the product).

Stages (each writes JSON into --out, a directory OUTSIDE the repo):
  product   run in the product venv (.venv312/bin/python), cwd = repo root:
            collects units (labelled corpora + public real documents), runs the product detector, dumps findings.
  ner       run in the throwaway NER venv: natasha (ru), spaCy sm/md (en), dumps spans with confidence proxies.
  analyze   plain python: joins product + ner dumps, prints the tables used in docs/superpowers/ner-experiment.md.

The private case/ folder is never read. Real documents come from tests/eval/real (public sources, see real_manifest.json).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPORA = {"v1": ("tests/eval/text_corpus_v1.jsonl", "ru"), "v2": ("tests/eval/text_corpus_v2.jsonl", "ru"),
           "en": ("tests/eval/text_corpus_en.jsonl", "en")}
SOFT = {"PERSON", "ORG", "PROJECT", "CITY", "REGION", "COUNTRY", "ADDRESS"}
LEGAL = re.compile(r"\b(ООО|ОАО|ЗАО|АО|ПАО|ИП|НКО|LLC|Ltd|Inc|GmbH|LLP|S\.A|https?|www|mailto|и|ул|д|г|кв|оф|пр|пос|ст|край|Dr|Mr|Ms|Господин|Г|н|Уважаемый|Уважаемая|Тов|Д|р)\b", re.I)


# ---------------------------------------------------------------- product stage

# ---------------------------------------------------------------- novelty probe (names built from syllables, unlikely to be in any dictionary)
def probe_units():
    import random
    r = random.Random(11)
    out = []

    def add(lang, i, text, spans):
        out.append({"kind": "corpus", "set": "probe", "lang": lang, "id": f"{lang}{i}", "group": "probe", "text": text, "gold": spans, "neg": [], "ok": []})

    def mk(text, parts):
        spans, cur = [], text
        return cur

    def build(lang, tpl, ents, cat):
        for i, (full, key) in enumerate(ents):
            for j, t in enumerate(tpl):
                text = t.format(x=full)
                st = text.index(full)
                add(lang, f"{cat}{i}_{j}", text, [{"start": st, "end": st + len(full), "cat": cat, "text": full}])
    ru_f = ["Андрей", "Сергей", "Павел", "Игорь", "Олег", "Виктор", "Николай", "Максим"]
    ru_o = ["Петрович", "Иванович", "Сергеевич", "Андреевич", "Олегович", "Викторович"]
    ru_s1 = ["Тарн", "Кувш", "Жер", "Бельск", "Нехл", "Прот", "Зав", "Ляп", "Гун", "Сыр", "Остр", "Мерц", "Дроб", "Хвал", "Пегов", "Стрел"]
    ru_s2 = ["ов", "ин", "ский", "енко", "ук", "ев", "ич", "цов"]
    seen, ru_s = set(), []
    while len(ru_s) < 60:
        n = r.choice(ru_s1) + r.choice(ru_s2)
        if n not in seen:
            seen.add(n); ru_s.append(n)
    build("ru", ["Договор подписал директор {x} в присутствии свидетелей.", "Свидетель {x} подтвердил показания, данные ранее.", "{x}\tдиректор\tМосква", "С уважением,\n{x}", "Заявитель: {x}"],
          [(f"{r.choice(ru_f)} {r.choice(ru_o)} {s}", s) for s in ru_s[:30]] + [(s, s) for s in ru_s[30:]], "PERSON")
    ru_org = ["Тревилан", "Кордекс", "Ривалтех", "Номинекс", "Белтрон", "Астравиль", "Мелкотех", "Дарвинор", "Уралгрейн", "Сибфорст", "Ланкор", "Вельтмар"]
    build("ru", ["Контракт с компанией {x} продлён.", "Поставщик: {x}", "Реквизиты ООО «{x}» приведены ниже."], [(o, o) for o in ru_org], "ORG")
    ru_c = ["Ртищево", "Кологрив", "Усть-Кут", "Мезень", "Чердынь", "Каргополь", "Урюпинск", "Кимры", "Бежецк", "Тотьма", "Сольвычегодск", "Пошехонье", "Макарьев", "Солигалич", "Любим", "Вытегра", "Лальск", "Няндома", "Онега", "Мышкин"]
    build("ru", ["Родился в г. {x}.", "Отправлено из {x}, вчера.", "Место работы: {x}"], [(c, c) for c in ru_c], "CITY")
    en_f = ["Daniel", "Grace", "Oliver", "Megan", "Peter", "Laura", "Victor", "Hannah"]
    en_s1 = ["Bran", "Kel", "Dros", "Wen", "Thor", "Mar", "Quin", "Hal", "Pell", "Vard", "Lin", "Ost", "Fen", "Gar", "Cobb", "Rud"]
    en_s2 = ["ham", "wick", "ford", "son", "ley", "ton", "well", "berg", "stein", "man"]
    seen, en_s = set(), []
    while len(en_s) < 60:
        n = r.choice(en_s1) + r.choice(en_s2)
        if n not in seen:
            seen.add(n); en_s.append(n)
    build("en", ["The agreement was signed by director {x} in the presence of witnesses.", "Witness {x} confirmed the earlier statement.", "{x}\tDirector\tBoston", "Regards,\n{x}", "Applicant: {x}"],
          [(f"{r.choice(en_f)} {s}", s) for s in en_s[:30]] + [(s, s) for s in en_s[30:]], "PERSON")
    en_org = ["Brightwell Dynamics", "Corvane Systems", "Delmark Partners", "Halvorsen Freight", "Norquist Labs", "Tellivar Group", "Ostrand Holdings", "Penrovia Foods", "Kestrel Marrow Ltd", "Quillon Analytics", "Varnholt Capital", "Zeldarin Works"]
    build("en", ["Our contract with {x} was extended.", "Supplier: {x}", "Invoice issued by {x} Inc."], [(o, o) for o in en_org], "ORG")
    en_c = ["Wetumpka", "Tonopah", "Chillicothe", "Skowhegan", "Ashtabula", "Manitowoc", "Kutztown", "Ishpeming", "Wapakoneta", "Pocatello", "Shelbyville", "Opelousas", "Cullman", "Tupelo", "Ketchikan", "Alamogordo", "Wausau", "Ottumwa", "Hibbing", "Bemidji"]
    build("en", ["Born in {x}.", "Sent from {x}, yesterday.", "Office location: {x}"], [(c, c) for c in en_c], "CITY")
    return out

def real_texts(main_root: Path, limit_chars: int = 400_000):
    """Text-extractable real documents, via pdftotext / python-docx / openpyxl / python-pptx / plain read."""
    man = json.loads((ROOT / "tests/eval/real_manifest.json").read_text())["files"]
    base = main_root / "tests/eval/real"
    for f in man:
        p = base / f["id"] / Path(f["path"]).name
        if not p.exists():
            continue
        fmt, text = f["fmt"], None
        try:
            if fmt == "pdf":
                text = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
            elif fmt == "docx":
                from docx import Document
                d = Document(str(p))
                parts = [x.text for x in d.paragraphs]
                for t in d.tables:
                    for r in t.rows:
                        parts.append("\t".join(c.text for c in r.cells))
                text = "\n".join(parts)
            elif fmt == "xlsx":
                from openpyxl import load_workbook
                wb = load_workbook(str(p), read_only=True, data_only=True)
                rows = []
                for ws in wb.worksheets:
                    for r in ws.iter_rows(values_only=True):
                        rows.append("\t".join("" if v is None else str(v) for v in r))
                text = "\n".join(rows)
            elif fmt == "pptx":
                from pptx import Presentation
                pr = Presentation(str(p))
                parts = []
                for s in pr.slides:
                    for sh in s.shapes:
                        if sh.has_text_frame:
                            parts.append(sh.text_frame.text)
                text = "\n".join(parts)
            elif fmt in ("txt", "md", "csv", "tsv", "json", "yaml", "yml", "xml", "html"):
                text = p.read_text("utf-8", errors="replace")
                if fmt == "html":
                    text = re.sub(r"<[^>]+>", " ", text)
        except Exception as e:  # noqa: BLE001
            print("skip", f["id"], e, file=sys.stderr)
            continue
        if text and len(text.strip()) > 80:
            yield {"id": f["id"], "fmt": fmt, "lang": f["lang"], "traits": f["traits"], "text": text[:limit_chars]}


def stage_product(a):
    sys.path.insert(0, str(ROOT))
    from tests.helpers import Env
    env = Env()

    def detect(text):
        d = env.service.build_detector(env.service.settings_for({}))
        d.harvest(text, "x.txt")
        return [[f.category, f.start, f.end, f.decision.value, round(f.confidence, 3)] for f in d.scan(text, "x.txt", "text")]

    units = []
    if a.probe:
        units = probe_units()
        for u in units:
            u["find"] = detect(u["text"])
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "product.json").write_text(json.dumps(units, ensure_ascii=False))
        print("probe units", len(units))
        return
    for key, (path, lang) in CORPORA.items():
        for l in (ROOT / path).read_text().splitlines():
            it = json.loads(l)
            units.append({"kind": "corpus", "set": key, "lang": lang, "id": it["id"], "group": it["group"], "text": it["text"],
                          "gold": it["spans"], "neg": it.get("neg", []), "ok": it.get("ok", []), "find": detect(it["text"])})
    t0 = time.time()
    for r in real_texts(Path(a.main_root)):
        t1 = time.time()
        fs = detect(r["text"])
        units.append({"kind": "real", "set": r["fmt"], "lang": "ru" if r["lang"] == "ru" else "en", "id": r["id"], "group": r["traits"],
                      "text": r["text"], "gold": [], "neg": [], "ok": [], "find": fs, "t": round(time.time() - t1, 2)})
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "product.json").write_text(json.dumps(units, ensure_ascii=False))
    print("units", len(units), "real", sum(u["kind"] == "real" for u in units), "secs", round(time.time() - t0))


# ---------------------------------------------------------------- NER stage
def _rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6   # macOS: bytes


def crf_marginals(em, trans, seq):
    """Posterior probability of the decoded tag at each token (forward-backward over the slovnet CRF)."""
    import numpy as np

    def lse(x, axis):
        m = x.max(axis=axis, keepdims=True)
        return (m + np.log(np.exp(x - m).sum(axis=axis, keepdims=True))).squeeze(axis)
    n, k = em.shape
    if n == 0:
        return []
    al = np.zeros((n, k)); be = np.zeros((n, k))
    al[0] = em[0]
    for i in range(1, n):
        al[i] = lse(al[i - 1][:, None] + trans, 0) + em[i]
    for i in range(n - 2, -1, -1):
        be[i] = lse(trans + (em[i + 1] + be[i + 1])[None, :], 1)
    z = lse(al[-1], 0)
    return [float(np.exp(al[i, seq[i]] + be[i, seq[i]] - z)) for i in range(n)]


class Natasha:
    name = "natasha"
    langs = ("ru",)

    def __init__(self):
        from natasha import NewsEmbedding, NewsNERTagger
        self.tagger = NewsNERTagger(NewsEmbedding())
        self.infer = self.tagger.infer
        self.probs = []
        import numpy as np
        infer = self.infer

        def process(inputs):
            for inp in inputs:
                pred = infer.model(inp.word_id, inp.shape_id, inp.pad_mask)
                em = np.asarray(pred, dtype="float64")
                trans = np.asarray(infer.model.head.crf.transitions.array, dtype="float64")
                mask = np.asarray(~inp.pad_mask)
                tags = list(infer.model.head.crf.decode(pred, mask))
                for b_, seq in enumerate(tags):
                    n = int(mask[b_].sum())
                    self.probs.append(crf_marginals(em[b_, :n], trans, seq))
                    yield seq
        object.__setattr__(infer, "process", process)

    def __call__(self, text):
        from slovnet.token import tokenize
        self.probs = []
        spans = list(self.infer([text]))[0].spans if text.strip() else []
        toks = list(tokenize(text))
        probs = self.probs[0] if self.probs else []
        out = []
        for s in spans:
            idx = [i for i, t in enumerate(toks) if t.start >= s.start and t.stop <= s.stop]
            conf = min((probs[i] for i in idx if i < len(probs)), default=0.5)
            out.append({"label": {"PER": "PERSON", "ORG": "ORG", "LOC": "LOC"}.get(s.type, s.type), "start": s.start, "end": s.stop,
                        "conf": round(conf, 3)})
        return out


class Spacy:
    langs = ("en",)

    def __init__(self, model):
        import spacy
        self.name = model
        self.nlp = spacy.load(model)
        self.nlp.max_length = 3_000_000
        self.ner = self.nlp.get_pipe("ner")

    def __call__(self, text):
        doc = self.nlp.make_doc(text)
        for name, proc in self.nlp.pipeline:
            if name in ("tok2vec", "transformer"):
                doc = proc(doc)
        beams = self.ner.beam_parse([doc], beam_width=8, beam_density=0.0001)
        score = collections.defaultdict(float)
        for score_, ents in self.ner.moves.get_beam_parses(beams[0]):
            for s, e, lab in ents:
                score[(s, e, lab)] += score_
        # greedy parse gives the actual entities; beam mass gives the confidence proxy
        out = []
        for ent in self.nlp(text).ents:
            lab = {"PERSON": "PERSON", "ORG": "ORG", "GPE": "LOC", "LOC": "LOC", "FAC": "LOC"}.get(ent.label_)
            if lab is None:
                continue
            out.append({"label": lab, "start": ent.start_char, "end": ent.end_char, "conf": round(score.get((ent.start, ent.end, ent.label_), 0.0), 3)})
        return out


def stage_ner(a):
    units = json.loads((Path(a.out) / "product.json").read_text())
    models = [("natasha", Natasha), ("en_core_web_sm", lambda: Spacy("en_core_web_sm")), ("en_core_web_md", lambda: Spacy("en_core_web_md"))]
    cost = json.loads((Path(a.out) / "cost.json").read_text()) if (Path(a.out) / "cost.json").exists() else {}
    for name, ctor in models:
        if a.only and name not in a.only.split(","):
            continue
        t0 = time.time()
        m = ctor()
        cold = time.time() - t0
        res, tdoc, nchar = {}, 0.0, 0
        for u in units:
            if u["lang"] not in m.langs:
                continue
            t1 = time.time()
            res[u["id"] if u["kind"] == "real" else u["set"] + ":" + u["id"]] = m(u["text"])
            tdoc += time.time() - t1
            nchar += len(u["text"])
        cost[name] = {"cold_s": round(cold, 2), "run_s": round(tdoc, 1), "chars": nchar, "ms_per_1k_chars": round(1000 * tdoc / max(1, nchar / 1000), 1),
                      "peak_rss_mb": round(_rss_mb())}
        (Path(a.out) / f"ner_{name}.json").write_text(json.dumps(res, ensure_ascii=False))
        print(name, cost[name], flush=True)
        (Path(a.out) / "cost.json").write_text(json.dumps(cost, indent=1))
        del m
    (Path(a.out) / "cost.json").write_text(json.dumps(cost, indent=1))



# ---------------------------------------------------------------- analysis
COMPAT = {"PERSON": {"PERSON"}, "ORG": {"ORG"}, "PROJECT": {"ORG"}, "CITY": {"LOC"}, "REGION": {"LOC"}, "COUNTRY": {"LOC"}, "ADDRESS": {"LOC"}}
MODELS = ["natasha", "en_core_web_sm", "en_core_web_md"]
LANG_MODELS = {"ru": ["natasha"], "en": ["en_core_web_sm", "en_core_web_md"]}
TAUS = [0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99]


def ov(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def uncovered(text, st, en, ivs):
    sub = "".join(text[i] if not any(a <= i < b for a, b in ivs) else " " for i in range(st, en))
    return "".join(c for c in LEGAL.sub(" ", sub) if c.isalnum())


def text_type(u):
    t = u["text"]
    if u["kind"] == "real":
        return u["set"] + (":" + u["group"][:18] if u["set"] in ("pdf",) else "")
    if re.search(r"(?i)^(regards|best|sincerely|thanks|с уважением|подпись)|\n(regards|sincerely|best|с уважением)", t.strip()):
        return "signature"
    if "\t" in t or t.count("|") >= 2 or t.count(";") >= 3:
        return "table-row"
    if re.search(r"[<>{}=]", t) and len(t) < 200:
        return "code/markup"
    w = len(t.split())
    return "short-fragment(<6w)" if w < 6 else ("prose(>=12w)" if w >= 12 else "mid(6-11w)")


def load(out):
    out = Path(out)
    units = json.loads((out / "product.json").read_text())
    ner = {m: json.loads((out / f"ner_{m}.json").read_text()) for m in MODELS if (out / f"ner_{m}.json").exists()}
    return units, ner


def key(u):
    return u["id"] if u["kind"] == "real" else u["set"] + ":" + u["id"]


def stage_analyze(a):
    units, ner = load(a.out)
    rep = collections.defaultdict(dict)
    samples = collections.defaultdict(list)
    for lang, ms in LANG_MODELS.items():
        cu = [u for u in units if u["kind"] == "corpus" and u["lang"] == lang]
        for m in ms:
            if m not in ner:
                continue
            for tau in TAUS:
                per = collections.defaultdict(collections.Counter)
                for u in cu:
                    t = u["text"]
                    auto = [(f[1], f[2]) for f in u["find"] if f[3] == "AUTO"]
                    anyf = [(f[1], f[2]) for f in u["find"]]
                    nspans = [s for s in ner[m][key(u)] if s["conf"] >= tau]
                    for g in u["gold"]:
                        if g["cat"] not in SOFT:
                            continue
                        c = per[g["cat"]]
                        c["gold"] += 1
                        unc = uncovered(t, g["start"], g["end"], auto)
                        leaked = len(unc) >= 3
                        c["leak_prod"] += leaked
                        strict = [(s["start"], s["end"]) for s in nspans if s["label"] in COMPAT[g["cat"]]]
                        loose = [(s["start"], s["end"]) for s in nspans]
                        c["ner_full_strict"] += len(uncovered(t, g["start"], g["end"], strict)) < 3
                        c["ner_full_loose"] += len(uncovered(t, g["start"], g["end"], loose)) < 3
                        if leaked:
                            c["resc_strict"] += len(uncovered(t, g["start"], g["end"], auto + strict)) < 3
                            c["resc_loose"] += len(uncovered(t, g["start"], g["end"], auto + loose)) < 3
                    golds = [(g["start"], g["end"]) for g in u["gold"]] + [(o["start"], o["end"]) for o in u["ok"]]
                    negs = [(n["start"], n["end"]) for n in u["neg"]]
                    for s in nspans:
                        k = per["_ALL"]
                        k["ner_spans"] += 1
                        if any(ov(s["start"], s["end"], x, y) for x, y in golds):
                            # boundary / category disagreement with product on a gold-overlapping span
                            continue
                        if any(ov(s["start"], s["end"], x, y) for x, y in auto):
                            k["dup_with_product_nongold"] += 1
                            continue
                        k["extra_fp"] += 1
                        k["extra_fp_neg" if any(ov(s["start"], s["end"], x, y) for x, y in negs) else "extra_fp_unl"] += 1
                        if tau in (0.0, 0.9):
                            samples[(lang, m, tau)].append({"id": key(u), "label": s["label"], "conf": s["conf"], "span": t[s["start"]:s["end"]],
                                                            "ctx": t[max(0, s["start"] - 50):s["end"] + 50].replace("\n", " "), "group": u["group"]})
                rep[(lang, m)][tau] = {k: dict(v) for k, v in per.items()}
    # real documents: spans NER finds that the product replaced neither automatically nor as review
    real = {}
    for lang, ms in LANG_MODELS.items():
        ru = [u for u in units if u["kind"] == "real" and u["lang"] == lang]
        for m in ms:
            if m not in ner:
                continue
            for tau in (0.0, 0.5, 0.9, 0.99):
                c = collections.Counter()
                for u in ru:
                    fs = [(f[1], f[2]) for f in u["find"]]
                    chars = len(u["text"])
                    c["chars"] += chars
                    for s in ner[m].get(key(u), []):
                        if s["conf"] < tau:
                            continue
                        c["ner_" + s["label"]] += 1
                        if any(ov(s["start"], s["end"], x, y) for x, y in fs):
                            c["covered_by_product"] += 1
                        else:
                            c["new_" + s["label"]] += 1
                real[(lang, m, tau)] = dict(c)
                if tau in (0.0, 0.9):
                    pool = []
                    for u in ru:
                        fs = [(f[1], f[2]) for f in u["find"]]
                        for s in ner[m].get(key(u), []):
                            if s["conf"] >= tau and not any(ov(s["start"], s["end"], x, y) for x, y in fs):
                                pool.append({"id": key(u), "fmt": u["set"], "label": s["label"], "conf": s["conf"], "span": u["text"][s["start"]:s["end"]],
                                             "ctx": u["text"][max(0, s["start"] - 50):s["end"] + 50].replace("\n", " ")})
                    samples[("real", lang, m, tau)] = pool
    # slices by text type (corpus + real), tau=0.0
    sl = {}
    for lang, ms in LANG_MODELS.items():
        for m in ms:
            if m not in ner:
                continue
            d = collections.defaultdict(collections.Counter)
            for u in units:
                if u["lang"] != lang:
                    continue
                tt = text_type(u)
                auto = [(f[1], f[2]) for f in u["find"] if f[3] == "AUTO"]
                nsp = ner[m].get(key(u), [])
                for g in u["gold"]:
                    if g["cat"] in SOFT:
                        strict = [(s["start"], s["end"]) for s in nsp if s["label"] in COMPAT[g["cat"]]]
                        d[tt]["gold"] += 1
                        d[tt]["prod_leak"] += len(uncovered(u["text"], g["start"], g["end"], auto)) >= 3
                        d[tt]["ner_found"] += len(uncovered(u["text"], g["start"], g["end"], strict)) < 3
                golds = [(g["start"], g["end"]) for g in u["gold"]] + [(o["start"], o["end"]) for o in u["ok"]]
                for s in nsp:
                    d[tt]["ner_spans"] += 1
                    if not any(ov(s["start"], s["end"], x, y) for x, y in golds + auto) and u["kind"] == "corpus":
                        d[tt]["ner_extra_fp"] += 1
                    if u["kind"] == "real" and not any(ov(s["start"], s["end"], x, y) for x, y in [(f[1], f[2]) for f in u["find"]]):
                        d[tt]["ner_new_real"] += 1
            sl[(lang, m)] = {k: dict(v) for k, v in d.items()}
    # disagreements on corpus (product AUTO overlaps NER span, bounds or category differ)
    dis = {}
    for lang, ms in LANG_MODELS.items():
        for m in ms:
            if m not in ner:
                continue
            c = collections.Counter()
            ex = []
            for u in units:
                if u["kind"] != "corpus" or u["lang"] != lang:
                    continue
                for s in ner[m][key(u)]:
                    for f in u["find"]:
                        if f[3] == "AUTO" and ov(s["start"], s["end"], f[1], f[2]):
                            c["overlap"] += 1
                            same_b = (s["start"], s["end"]) == (f[1], f[2])
                            cat_ok = (f[0] in ("PERSON", "POSSIBLE_PERSON") and s["label"] == "PERSON") or (f[0] in ("ORG", "PROJECT") and s["label"] == "ORG") or (f[0] in ("CITY", "REGION", "COUNTRY", "ADDRESS") and s["label"] == "LOC")
                            c["same_bounds"] += same_b
                            c["cat_agree"] += cat_ok
                            if not same_b or not cat_ok:
                                c["disagree"] += 1
                                if len(ex) < 6:
                                    ex.append([u["text"][s["start"]:s["end"]], s["label"], u["text"][f[1]:f[2]], f[0]])
            dis[(lang, m)] = {"counts": dict(c), "examples": ex}
    res = {"by_lang_model_tau": {f"{k[0]}|{k[1]}": {str(t): v for t, v in d.items()} for k, d in rep.items()},
           "real": {"|".join(map(str, k)): v for k, v in real.items()},
           "slices": {"|".join(k): v for k, v in sl.items()}, "disagreements": {"|".join(k): v for k, v in dis.items()}}
    Path(a.out, "analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    Path(a.out, "samples.json").write_text(json.dumps({"|".join(map(str, k)): v for k, v in samples.items()}, ensure_ascii=False, indent=1))
    print("wrote analysis.json, samples.json")


# ---------------------------------------------------------------- one entity, one label
TEMPL = {"en": ["{x} attended the meeting on Tuesday.", "Please forward the file to {x} before noon.", "Regards,\n{x}", "Contact: {x}; tel on file."],
         "ru": ["{x} присутствовал на встрече во вторник.", "Пожалуйста, передайте файл: {x}, до обеда.", "С уважением,\n{x}", "Контакт: {x}; телефон в деле."]}


def stage_consistency(a):
    units, ner = load(a.out)
    import random
    rnd = random.Random(7)
    ents = {"ru": collections.defaultdict(set), "en": collections.defaultdict(set)}
    for u in units:
        if u["kind"] == "corpus":
            for g in u["gold"]:
                if g["cat"] in ("PERSON", "ORG", "CITY"):
                    ents[u["lang"]][g["cat"]].add(g["text"])
    models = {"ru": [Natasha()], "en": [Spacy("en_core_web_sm"), Spacy("en_core_web_md")]}
    want = {"PERSON": "PERSON", "ORG": "ORG", "CITY": "LOC"}
    out = {}
    for lang in ("ru", "en"):
        for m in models[lang]:
            res = collections.defaultdict(collections.Counter)
            for cat, S in ents[lang].items():
                S = sorted(S)
                rnd.shuffle(S)
                for x in S[:120]:
                    sts = []
                    for tpl in TEMPL[lang]:
                        text = tpl.format(x=x)
                        st = text.index(x)
                        hit = [s for s in m(text) if ov(s["start"], s["end"], st, st + len(x))]
                        if not hit:
                            sts.append("none")
                        elif len(hit) == 1 and (hit[0]["start"], hit[0]["end"]) == (st, st + len(x)) and hit[0]["label"] == want[cat]:
                            sts.append("exact")
                        else:
                            sts.append("other")
                    c = res[cat]
                    c["entities"] += 1
                    c["consistent"] += len(set(sts)) == 1
                    c["all_exact"] += set(sts) == {"exact"}
                    c["all_none"] += set(sts) == {"none"}
                    c["mixed"] += len(set(sts)) > 1
            out[f"{lang}|{m.name}"] = {k: dict(v) for k, v in res.items()}
            print(lang, m.name, out[f"{lang}|{m.name}"])
    Path(a.out, "consistency.json").write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["product", "ner", "analyze", "consistency"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--main-root", default=str(ROOT))
    a = ap.parse_args()
    {"product": stage_product, "ner": stage_ner, "analyze": stage_analyze, "consistency": stage_consistency}.get(a.stage, lambda a: None)(a)
