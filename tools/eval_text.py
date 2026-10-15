"""Text detector evaluation on tests/eval/text_corpus_v1.jsonl (synthetic labelled spans).

Usage: .venv-mac/bin/python tools/eval_text.py [corpus.jsonl] [report.json]
Prints per-category recall / precision / leakage; writes FN/FP/partial detail.
"""
import sys, json, collections, re
sys.path.insert(0, ".")
from tests.helpers import Env

_E = Env()


def detect(text):
    d = _E.service.build_detector(_E.service.settings_for({}))
    d.harvest(text, "x.txt")
    return d.scan(text, "x.txt", "text")


SOFT = {"PERSON", "ORG", "PROJECT", "CITY", "REGION", "COUNTRY", "ADDRESS"}
ALL_KINDS = ["PERSON", "ORG", "PROJECT", "CITY", "REGION", "COUNTRY", "ADDRESS", "EMAIL", "PHONE", "USERNAME", "DOMAIN", "CONTRACT",
             "PASSPORT", "SNILS", "INN", "OGRN", "KPP", "BIK", "OMS", "DRIVER_LICENSE", "VEHICLE_PLATE", "CARD", "BANK_ACCOUNT",
             "BIRTH_DATE", "IP_ADDRESS", "SECRET", "PII"]


def gate_table(per):
    """PASS/FAIL per kind: recall and precision >= 0.98 for structured ids, >= 0.95 for names/orgs/places."""
    print("\nPER-KIND GATE (recall/precision; thr 0.95 names/orgs/places, 0.98 ids)")
    bad = []
    for c in ALL_KINDS:
        v = per.get(c, collections.Counter()); thr = 0.95 if c in SOFT else 0.98
        tp = v["full"] + v["partial"]
        rec = v["full"] / v["gold"] if v["gold"] else None
        prec = tp / (tp + v["fp"]) if tp + v["fp"] else None
        ok = (rec is None or rec >= thr) and (prec is None or prec >= thr)
        f = lambda x: "  n/a" if x is None else "%.3f" % x
        print(f"  {c:15} gold={v['gold']:4} recall={f(rec)} prec={f(prec)}  {'PASS' if ok else 'FAIL'}" + ("" if v["gold"] else "  (no gold: unmeasured)"))
        if not ok: bad.append(c)
    print("GATE:", "ALL PASS" if not bad else "FAIL " + ",".join(bad))


def main():
    global_ = None
    paths=(sys.argv[1] if len(sys.argv)>1 else 'tests/eval/text_corpus_v1.jsonl').split(',')
    corpus=[json.loads(l) for pth in paths for l in open(pth)]
    ALIAS={"INN_ORG":"INN","INN_PERSON":"INN"}
    def norm(c): return ALIAS.get(c,c)
    per=collections.defaultdict(lambda: collections.Counter())
    fn=[]; fp=[]; partial=[]; rows=[]
    LEGAL=re.compile(r"\b(ООО|ОАО|ЗАО|АО|ПАО|ИП|НКО|LLC|Ltd|Inc|GmbH|LLP|S\.A|https?|www|mailto|и|ул|д|г|кв|оф|пр|пос|ст|край|Dr|Mr|Ms|Господин|Г|н|Уважаемый|Уважаемая|Тов|Д|р)\b",re.I)
    def alnum_uncovered(span, auto):
        st,en=span["start"],span["end"]
        if span["cat"]=="DOMAIN":
            m=re.search(r"(?:https?://)?([^/?#\s]+)",span["text"]); st=span["start"]+m.start(1); en=span["start"]+m.end(1)
        unc="".join(span["text"][i-span["start"]] if not any(f.start<=i<f.end for f in auto) else " " for i in range(st,en))
        unc=LEGAL.sub(" ",unc)
        return "".join(ch for ch in unc if ch.isalnum())
    for it in corpus:
        fs=detect(it["text"])
        auto=[f for f in fs if f.decision.value=="AUTO"]
        rev=[f for f in fs if f.decision.value!="AUTO"]
        used=set()
        for sp in it["spans"]:
            c=norm(sp["cat"]); per[c]["gold"]+=1
            ov=[f for f in auto if f.start<sp["end"] and f.end>sp["start"]]
            for f in ov: used.add(id(f))
            unc=alnum_uncovered(sp,auto)
            if ov and not unc:
                per[c]["full"]+=1
                if any(norm(f.category)==c or (c=="PERSON" and f.category in("PERSON","POSSIBLE_PERSON")) for f in ov): per[c]["catok"]+=1
                else: per[c]["wrongcat"]+=1; partial.append(("WRONGCAT",it["id"],sp["text"],[(f.category,f.original) for f in ov]))
            elif ov:
                per[c]["partial"]+=1; partial.append(("PARTIAL",it["id"],sp["text"],unc,[(f.category,f.original) for f in ov]))
                if len(unc)>=3: per[c]["leak"]+=1
            else:
                per[c]["miss"]+=1; per[c]["leak"]+=1
                fn.append((it["id"],c,sp["text"],it["text"][:120],[(f.category,f.decision.value,f.original) for f in rev if f.start<sp["end"] and f.end>sp["start"]]))
        for f in auto:
            if id(f) in used: continue
            if any(f.start<o["end"] and f.end>o["start"] for o in it.get("ok",[])): continue      # tolerated hit (legit proper name, not gold)
            negov=[n for n in it["neg"] if f.start<n["end"] and f.end>n["start"]]
            fp.append((it["id"],f.category,f.original,"NEGSPAN" if negov else "nospan",it["text"][:100]))
            per[norm(f.category)]["fp"]+=1
        # also FP where finding overlaps gold but extends beyond (over-redaction of neighbours)
    tot=collections.Counter()
    print(f"{'cat':14}{'gold':>5}{'full':>5}{'part':>5}{'miss':>5}{'wrongcat':>9}{'leak':>5}{'fp':>4}  recall  prec  leak%")
    for c,v in sorted(per.items()):
        if not v["gold"] and not v["fp"]: continue
        tp=v["full"]+v["partial"]; 
        rec=v["full"]/v["gold"] if v["gold"] else float('nan')
        prec=tp/(tp+v["fp"]) if tp+v["fp"] else float('nan')
        print(f"{c:14}{v['gold']:5}{v['full']:5}{v['partial']:5}{v['miss']:5}{v['wrongcat']:9}{v['leak']:5}{v['fp']:4}  {rec:.2f}   {prec:.2f}  {100*v['leak']/max(1,v['gold']):.0f}")
        for k in v: tot[k]+=v[k]
    gate_table(per)
    print("TOTAL gold",tot["gold"],"full",tot["full"],"partial",tot["partial"],"miss",tot["miss"],"wrongcat",tot["wrongcat"],"leak",tot["leak"],"fp",tot["fp"])
    print("recall(full)=%.3f  leakage=%.3f  precision=%.3f"%(tot["full"]/tot["gold"],tot["leak"]/tot["gold"],(tot["full"]+tot["partial"])/max(1,tot["full"]+tot["partial"]+tot["fp"])))
    json.dump({"fn":fn,"fp":fp,"partial":partial},open((sys.argv[2] if len(sys.argv)>2 else '/tmp/eval_text_report.json'),"w"),ensure_ascii=False,indent=1)


if __name__ == "__main__":
    main()
