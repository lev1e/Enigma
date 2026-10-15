"""English-language detection rules: people, organisations, postal addresses, birth dates, bare passport numbers.

The Russian side of the product is driven by morphology; English has no inflection, so recall here comes from
(a) strong cues (label, honorific, middle initial, «Surname, Given», e-mail display name, salutation/signature),
(b) a given-name / surname lexicon (en_names_data, generated offline) and
(c) organisation nouns (Holdings, Capital, Partners, University ...) and legal forms.
Everything is regex + small Python filters; detectors.py / entities.py only plug the results in.
"""
from __future__ import annotations

import re

from .en_names_data import GIVEN as _GIVEN0, SURNAMES
from .names_data import ENGLISH_GIVEN_NAMES

GIVEN = frozenset(_GIVEN0) | frozenset(ENGLISH_GIVEN_NAMES.split()) | {"Grace", "Joy", "Hope", "Faith", "Frank", "Oliver", "Victor", "Hugh", "Rose", "Daisy", "Violet"} | frozenset(
    "Bob Bill Jimmy Mike Tom Tommy Tony Dan Rick Dick Nick Pete Sam Sammy Ben Joey Beth Katie Maggie Meg Peggy Sue Susie Jenny Jen Patty Ted Teddy Freddie Ed Hank Harry Gerry Barry Abby Lizzie Molly Sally Kenny Ronnie Jeff Josh Zack Zach Tina Gina Mick Robbie Ollie Timmy Tess Frankie".split())

_L = "A-ZÀ-ÖØ-Þ"
_l = "a-zà-öø-ÿ"
# One capitalised name word: Whitfield, McDonald, O'Brien, Smith-Jones, Lindqvist
NW = rf"(?:[ODL][’'](?=[{_L}]))?[{_L}][{_l}]+(?:[{_L}][{_l}]+)?(?:[-'’](?:[ODL][’'](?=[{_L}]))?[{_L}][{_l}]+)*"
INIT = rf"[{_L}]\."
POSS = r"(?:['’]s)?"
TAIL = r"(?![\w'’-])"

HONORIFICS = ("Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|Sir|Dame|Lord|Lady|Rev|Reverend|Fr|Hon|Judge|Justice|Capt|Captain|Sgt|Lt|Col|Gen|"
              "Sen|Gov|Mme|Mlle|Herr|Frau|Mister|Madam|Madame|Senor|Senora|Sr|Sra")

# Words that make a capitalised pair NOT a person (sections, doc parts, org/place nouns, generic business words).
_NOT_NAME = frozenset(w.lower() for w in """
inc ltd llc llp box bag corp corporation company co bank university college institute school group project department office team committee
council agency authority association foundation society services service systems solutions limited trust fund hospital clinic hotel
restaurant street avenue road park square city county state republic kingdom union federation version section chapter table figure
page appendix agreement contract policy report plan guide manual form number data api sdk app web server client customer user admin
account support sales marketing finance legal article item part exhibit schedule annex step phase level class type option module
unit block room floor suite building tower centre center plaza lane drive court way place terrace boulevard highway bridge station
airport harbor harbour port island river lake mountain valley beach church temple mosque museum library gallery theatre theater
stadium arena market mall store shop cafe bar pub grill kitchen studio lab labs laboratory academy hall house home inn lodge resort
spa gym club league cup award prize medal order act code law rule rules terms privacy notice statement summary overview introduction
conclusion background scope purpose definitions interpretation general special annual monthly weekly daily quarterly net gross total
subtotal balance amount price cost fee tax rate discount invoice receipt payment order delivery shipping billing address phone email
mobile tel fax date time year month week day today tomorrow yesterday monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december period box bureau holdings capital partners dynamics logistics
technologies technology industries enterprises ventures associates consulting international global worldwide national press media
networks energy pharmaceuticals motors airlines realty properties insurance brothers management advisors securities electronics
software analytics robotics interactive engineering construction foods publishing hotel hotels resorts bancorp financial
""".split())

# Words that start a sentence / label and must not be swallowed into a name or organisation.
_LEAD_STOP = frozenset(w.lower() for w in """
the a an our your their his her its my this that these those at to from with for by of in on and or but if as per via re fwd fw cc bcc
contact please dear hi hello hey thanks thank regards sincerely best kind warm pay send invoice bill ship sold billed attn attention
client customer company employer supplier vendor buyer seller landlord tenant between name organization organisation firm agency
signed prepared reviewed approved submitted issued verified written sent checked witness applicant patient owner holder cardholder
signatory claimant defendant plaintiff beneficiary borrower lender payee payer recipient sender director manager president
see note notes also new old first second third next last each every all any some no not yes now then when where while who whom
whose which what why how here there email phone tel fax mobile address date born birth dob passport ssn tax id number
visit call write ask meet welcome introducing announcing about regarding concerning following attached enclosed
""".split())

# Business / generic words: an organisation made only of these is a department or a section, not a company.
_GENERIC = frozenset(w.lower() for w in """
tech technical support customer customers project product products management marketing sales human resources research development
quality business executive steering working advisory review finance financial legal operations engineering security information
technology data digital service services national international global general public private first second third new old north south
east west central united american british european asian african pacific atlantic board advisory strategic corporate commercial
retail wholesale consumer industrial professional medical health healthcare education student students staff user users member
members family social community city state county federal royal imperial local regional annual quarterly steering focus age blood
risk compliance audit internal external senior junior chief technical content creative design brand media press public
""".split())

# Organisation nouns that end a company name.
ORG_NOUNS = ("Holdings Holding Capital Partners Partnership Group Labs Lab Laboratories Logistics Dynamics Systems Technologies Technology "
             "Solutions Industries Enterprises Ventures Associates Consulting Consultants Services Bank Bancorp Trust Foundation Institute "
             "University College Society Agency Studios Studio Media Networks Energy Pharmaceuticals Pharma Motors Airlines Airways Realty "
             "Properties Insurance Assurance Brothers Bros Company Corporation Management Advisors Advisers Securities Electronics Software "
             "Analytics Robotics Interactive Engineering Construction Foods Brewing Brewery Publishing Press Hospital Clinic Hotels Resorts "
             "Financial Therapeutics Biosciences Biotech Sciences Semiconductors Instruments Materials Chemicals Mining Resources Petroleum "
             "Shipping Transport Transportation Aviation Aerospace Defense Defence Automotive Fabrics Apparel Cosmetics Pictures Entertainment "
             "Productions Games Gaming Telecom Communications Wireless Mobile Cloud Security Innovations Works Workshop Collective "
             "Cooperative Co-op Syndicate Alliance Institute Academy Clinic Pharmacy Dental Veterinary Surgery Hospice Orchestra Gallery").split()
LEGAL_FORMS_EN = ("Inc.", "Inc", "Incorporated", "Ltd.", "Ltd", "Limited", "LLC", "L.L.C.", "LLP", "LP", "PLC", "Plc", "plc", "Corp.", "Corp",
                  "Co.", "GmbH", "AG", "S.A.", "SA", "N.V.", "NV", "B.V.", "BV", "Pty", "Pte", "Oy", "AB", "SpA", "S.p.A.", "Sarl", "SARL")
_NOUN_SET = frozenset(n.lower() for n in ORG_NOUNS)
_LEGAL_SET = frozenset(f.lower().rstrip(".") for f in LEGAL_FORMS_EN)
_PREFIX_NOUNS = frozenset("bank university college institute foundation society association church museum hospital school academy trust fund club".split())


def _is_given(word: str) -> bool:
    if "-" in word and all(len(x) > 1 for x in word.split("-")):
        return all(x.title() in GIVEN for x in word.split("-"))                    # Anna-Marie, Jean-Paul
    return word.title() in GIVEN or word in GIVEN


def _bad_word(w: str) -> bool:
    return w.lower().rstrip(".") in _NOT_NAME


def en_person_ok(value: str) -> bool:
    """Final sanity filter on an English person candidate (any rule)."""
    words = re.findall(rf"[{_L}{_l}][{_L}{_l}'’-]*", value)
    if not words:
        return False
    big = [w for w in words if len(w) > 1]
    if not big:
        return False
    if any(_bad_word(w) for w in big):
        return False
    if len(big) >= 2 and big[0].lower() in _LEAD_STOP:
        return False
    return True


# ----------------------------------------------------------------------------------------------------------------- people
def _two_ok(v: str) -> bool:
    w = [x for x in re.findall(rf"[{_L}{_l}][{_L}{_l}'’-]*", v) if len(x) > 1]
    return len(w) >= 2 and en_person_ok(v)


def _triple_ok(v: str) -> bool:
    w = re.findall(rf"[{_L}{_l}][{_L}{_l}'’-]*", v)
    if len(w) < 2 or w[0].lower() in _LEAD_STOP or any(_bad_word(x) for x in w if len(x) > 1):
        return False
    return not (len(w[0]) == 2 and w[0].isupper() and w[0] == "US")


def _pair_ok(v: str) -> bool:
    """Bare «Given Surname» (no cue): the first word must be a known given name, the second an ordinary-looking surname."""
    w = v.split()
    if len(w) != 2 or not en_person_ok(v):
        return False
    first, second = w
    if first.lower() in _LEAD_STOP or second.lower() in _LEAD_STOP or second.lower() in _GENERIC or first.lower() in _GENERIC:
        return False
    if _is_given(first) and len(second) >= 3:
        return not _is_given(second) or second in SURNAMES
    return first.lower() not in _GENERIC and second in SURNAMES and len(first) >= 3 and first.title() not in SURNAMES


def _comma_ok(v: str) -> bool:
    m = re.match(rf"({NW}),\s+({NW})", v)
    if not m or not en_person_ok(v):
        return False
    sur, giv = m.groups()
    if sur.lower() in _LEAD_STOP or giv.lower() in _LEAD_STOP or sur.lower() in _GENERIC:
        return False
    return _is_given(giv) and not _is_given(sur) or (_is_given(giv) and sur in SURNAMES)


def _single_ok(v: str) -> bool:
    """A lone word after a salutation: only a known given name."""
    return " " in v.strip() and en_person_ok(v) or (_is_given(v.strip()) and en_person_ok(v))


NAME_FULL = rf"{NW}(?:\s+{INIT}){{0,2}}\s+{NW}"                       # John A. Whitfield, John Whitfield
NAME_REV = rf"{NW},\s+{NW}(?:\s+{INIT})?"                              # Whitfield, John A.
CAPS = rf"(?:[ODL][’'](?=[{_L}]))?[{_L}]{{2,}}(?:[-'’][{_L}]{{2,}})*"
LABELS = (r"applicant|(?:full |first |last |sur|given |legal |contact |patient |employee |customer |client |tenant |owner |payer |payee )?name|"
          r"patient|client|customer|employee|owner|holder|cardholder|account holder|contact(?: person)?|signatory|claimant|defendant|plaintiff|"
          r"tenant|landlord|beneficiary|borrower|buyer|seller|author|witness|spouse|guardian|director|manager|president|attention|attn|insured|"
          r"payee|payer|recipient|sender|from|to|cc|bcc|reply-to|speaker|speakers|presenter|attendee|attendees|participants?|present|chair|chairperson|"
          r"organi[sz]er|host|assignee|reporter|requested by|requester|submitted for|prepared for|prepared by|reviewed by|approved by|signed by|"
          r"issued to|issued by|sold to|bill to|billed to|ship to|shipped to|deliver to|paid to|paid by|care of|c/o|in favou?r of|on behalf of|"
          r"represented by|nominee|trustee|executor|administrator|attorney|lawyer|supervisor|"
          r"physician|doctor|nurse|teacher|manager|engineer|developer|designer|analyst|consultant|accountant|auditor|inspector|"
          r"officer|secretary|treasurer|founder|ceo|cfo|cto|coo|vp|referee|emergency contact|next of kin|primary contact|"
          r"point of contact|poc|account manager|sales rep|representative|rep")

PERSON_RULES: list[tuple[re.Pattern[str], float, str, object]] = []


def _add(pattern: str, conf: float, reason: str, validator=None, flags: int = 0) -> None:
    PERSON_RULES.append((re.compile(pattern, flags), conf, reason, validator))


# 1. «John A. Whitfield»: first name + middle initial + surname, anywhere.
_add(rf"(?<![\w.'’-])({NW}(?:\s+{INIT}){{1,2}}\s+{NW}){POSS}{TAIL}", .86, "Имя со средним инициалом", _triple_ok)
# 2. «Whitfield, John A.» / «Haverford, Oliver», anywhere, when the second word is a known given name.
_add(rf"(?<![\w.'’-])(?=({NW},\s+{NW}(?:\s+{INIT})?){TAIL})", .84, "Фамилия, имя", _comma_ok)
# 3. Label + name in any of the shapes (colon/dash required: a bare «to Mr» is not a label).
_add(rf"(?i:\b(?:{LABELS}))\s*[:\-–—]\s*\"?({NAME_FULL}|{NAME_REV}){POSS}\"?{TAIL}", .9, "Имя после подписи",
     lambda v: en_person_ok(v) and not _is_org_like(v))
# 4. Honorific + name (name may be a surname alone, upper case allowed).
_add(rf"(?<![\w.])(?:{HONORIFICS})\.?\s+({NW}(?:\s+{INIT}){{0,2}}(?:\s+{NW})?|{CAPS}(?:\s+{INIT}){{0,2}}(?:\s+{CAPS})?){POSS}{TAIL}", .9,
     "Имя после обращения", lambda v: en_person_ok(v) and not _is_org_like(v))
# 5. ALL CAPS after a label: APPLICANT: MARCUS A. LINDQVIST, SIGNED BY JANE DOE
_add(rf"(?i:\b(?:{LABELS}))\s*[:\-–—]\s*({CAPS}(?:\s+{INIT}){{0,2}}\s+{CAPS}|{CAPS},\s+{CAPS}(?:\s+{INIT})?){TAIL}", .88,
     "Имя капсом после подписи", lambda v: en_person_ok(v.title()) and not _is_org_like(v.title()))
# 6. Salutation / closing: «Dear Priya,», «Hi Marcus Lindqvist», «Regards, John Whitfield».
_add(rf"\b(?:Dear|Hi|Hello|Hey|Thanks|Thank you|Regards|Best regards|Kind regards|Warm regards|Sincerely|Cheers|Best|Yours sincerely|Yours truly|"
     rf"With thanks|Respectfully)\s*,?\s+(?:(?:{HONORIFICS})\.?\s+)?({NW}(?:\s+{INIT}){{0,2}}(?:\s+{NW})?){POSS}\b(?!['’-])", .88,
     "Имя в обращении или подписи", _single_ok)
# 7. Closing on its own line then the name on the next line.
_add(rf"(?im)^[ \t]*(?:best |kind |warm |best wishes|with )?(?:regards|sincerely|cheers|thanks|thank you|best wishes|yours (?:truly|sincerely|faithfully)|"
     rf"respectfully|with thanks|many thanks|all the best)[,.!]?[ \t]*\r?\n[ \t]*({NW}(?:\s+{INIT}){{0,2}}(?:[ \t]+{NW}){{0,2}})[ \t]*$", .88,
     "Имя в подписи под письмом", _single_ok)
# 8. E-mail display name: «Marcus Lindqvist <marcus@x.com>» / «"Lindqvist, Marcus" <...>»
_add(rf"(?<![\w.'’-])\"?({NAME_FULL}|{NAME_REV})\"?[ \t]*[<(]\s*[\w.+-]+@[\w-]+(?:\.[\w-]+)+\s*[>)]", .92, "Имя перед адресом почты",
     lambda v: en_person_ok(v))
# 8b. ALL CAPS «Given SURNAME» with a known given name, anywhere («send to REBECCA ABERNATHY at ...»).
_add(rf"(?<![\w.'’-])({CAPS}[ \t]+{CAPS}){POSS}{TAIL}", .8, "Имя капсом (словарь имён)", lambda v: _pair_ok(v.title()) and len(v.split()[0]) >= 3)
# 8c. Initials first: «J. Whitfield», «J.R. Whitfield», «F.S. McAllister» (also at the start of a line / after «Then»).
_add(rf"(?<![\w.'’-])((?:{INIT}[ \t]?){{1,3}}{NW}){POSS}{TAIL}", .84, "Инициалы и фамилия",
     lambda v: not re.match(r"(?:U\.?S\.?A?|U\.?K\.?|E\.?U\.?|U\.?N\.?|D\.?C\.?)\s", v + ' ') and en_person_ok(v) and v.split()[-1].lower() not in _LEAD_STOP and v.split()[-1].lower() not in _GENERIC and len(v.split()[-1]) >= 3)
# 9. Bare «Given Surname» with a known given name.
_add(rf"(?<![\w.'’-])(?=({NW}[ \t]+{NW}){POSS}{TAIL})", .8, "Имя и фамилия (словарь имён)", _pair_ok)


def _is_org_like(v: str) -> bool:
    words = v.replace(",", " ").split()
    return bool(words) and (words[-1].lower().rstrip(".") in _NOUN_SET or words[-1].lower().rstrip(".") in _LEGAL_SET)


# ----------------------------------------------------------------------------------------------------------- organisations
_WORD = re.compile(r"\S+")
_BRAND = re.compile(rf"^[{_L}][\w'’&.-]*$")


def _clean(tok: str) -> tuple[str, str]:
    """Strip surrounding punctuation from a token: -> (core, trailing punctuation that ends a run)."""
    core = tok.strip("()[]\"“”«»,;:")
    brk = ""
    if tok.endswith((",", ";", ":", ")", ".")) and not core.endswith("."):
        brk = tok[-1]
    elif tok.endswith(".") and core.lower().rstrip(".") not in _LEGAL_SET and core.lower() not in ("co.",):
        core = core.rstrip(".")
        brk = "."
    return core, brk


def _brand_word(w: str) -> bool:
    return bool(_BRAND.match(w)) and w.lower() not in _LEAD_STOP and w.lower() not in _NOT_NAME and w.lower() not in _GENERIC \
        and not w.isdigit()


_HEADING_WORDS = frozenset("""errors reminders terms conditions notes tips instructions questions answers rules rights responsibilities
definitions requirements deductions credits exceptions changes updates warnings tools resources procedures policies penalties
interest fees taxes payments filing deadlines examples exemptions limits limitations disclosures acknowledgments""".split())


def org_spans(text: str) -> list[tuple[int, int, str, str]]:
    """-> [(start, end, name, reason)] English organisation names."""
    out: list[tuple[int, int, str, str]] = []
    for line in re.finditer(r"[^\n]+", text):
        s0 = line.start()
        ltext = line.group()
        cached = _ORG_LINE_CACHE.get(ltext) if len(ltext) <= 400 else None
        if cached is None:
            cached = _org_line_spans(ltext)
            if len(ltext) <= 400:
                if len(_ORG_LINE_CACHE) >= 20000:
                    _ORG_LINE_CACHE.clear()
                _ORG_LINE_CACHE[ltext] = cached
        out.extend((a + s0, b + s0, v, r) for a, b, v, r in cached)
    return _org_rest(text, out)


_ORG_LINE_CACHE: dict[str, list] = {}


def _org_line_spans(text: str) -> list[tuple[int, int, str, str]]:
    """The per-line part of org_spans: a pure function of the line text (cached by org_spans)."""
    out: list[tuple[int, int, str, str]] = []
    if True:
        s0 = 0
        toks = [(m.start() + s0, m.end() + s0, m.group()) for m in _WORD.finditer(text)]
        n = len(toks)
        cleaned = [_clean(t[2]) for t in toks]
        for i in range(n):
            core, brk = cleaned[i]
            low = core.lower().rstrip(".")
            if not (low in _NOUN_SET and core[:1].isupper()):
                continue
            # words before the noun, capitalised, joined by spaces only (a comma/period before breaks the run)
            j = i
            parts = 0
            while j > 0 and parts < 4:
                pc, pb = cleaned[j - 1]
                if pb or not pc:
                    break
                if pc == "&" or (pc.lower() in ("of", "and", "for", "the") and j - 2 >= 0 and cleaned[j - 2][0][:1].isupper()):
                    j -= 1
                    continue
                if not _BRAND.match(pc):
                    break
                j -= 1
                parts += 1
            # trim leading stop words and generic leading words
            while j < i and (cleaned[j][0].lower() in _LEAD_STOP or cleaned[j][0] in ("&", "and", "of", "for", "the")):
                j += 1
            # «Delacroix, Grace» + перенос строки + «Quillfeather Labs»: имя после запятой принадлежит человеку, а не названию.
            if j > 0 and cleaned[j - 1][1] and i - j >= 2 and cleaned[j][0].title() in GIVEN and cleaned[j - 1][0][:1].isupper():
                j += 1
            if j >= i:
                continue
            names = [cleaned[k][0] for k in range(j, i)]
            if not any(_brand_word(w) for w in names):
                continue
            # a single leading generic/ordinary word + known given name pair is a person-ish thing; skip «John Group»
            end_i = i
            # absorb a legal form directly after the noun: «Acme Holdings Ltd»
            if i + 1 < n and not brk and cleaned[i + 1][0].lower().rstrip(".") in _LEGAL_SET:
                end_i = i + 1
            st, en = toks[j][0], toks[end_i][1]
            val = text[st:en].rstrip(",;:)")
            if val.endswith(".") and val.rsplit(None, 1)[-1].lower().rstrip(".") not in _LEGAL_SET:
                val = val.rstrip(".")
            if val != text[st:en]:
                en = st + len(val)
            out.append((st, en, val, "Организация: название с родовым словом"))
    return out


def _org_rest(text: str, out: list) -> list:
    # «Bank of America», «University of Oxford»
    for m in re.finditer(rf"(?<![\w'’-])((?:{'|'.join(w.title() for w in _PREFIX_NOUNS)})\s+of\s+(?:the\s+)?{NW}(?:\s+{NW}){{0,2}})", text):
        v = m.group(1)
        words = v.split()
        if any(w.lower() in _LEAD_STOP for w in words[2:] if w[:1].isupper()):
            continue
        out.append((m.start(1), m.end(1), v, "Организация: «X of Y»"))
    # «Smith & Wesson», «Procter & Gamble», «Jones & Sons», «Baker and Sons»
    for m in re.finditer(rf"(?<![\w'’&-])({NW}\s+(?:&|and)\s+(?:Sons|Daughters|Associates|Partners|Co\.?|Company|Brothers|Bros\.?|Son)|{NW}\s+&\s+{NW}(?:\s+(?:LLP|LLC|Co\.?|Partners|Associates))?)(?![\w'’-])", text):
        v = m.group(1)
        w = re.split(r"\s+", v)
        if len(w[0]) < 3 or w[0].lower() in _LEAD_STOP or (len(w) >= 3 and len(w[2]) < 3):
            continue
        # form headings («Errors & Reminders», «Terms & Conditions») are not organisations
        if w[0].lower() in _HEADING_WORDS and w[-1].lower() in _HEADING_WORDS:
            continue
        out.append((m.start(1), m.end(1), v, "Организация: «X & Y»"))
    # label cues: «Company: Orchard Lane», «Employer: Halcyon», «Bill to: ...»
    cue = re.compile(
        rf"(?i:\b(?:company|company name|employer|employer name|organi[sz]ation|firm|supplier|vendor|buyer|seller|lessor|lessee|licensor|licensee|"
        rf"contractor|subcontractor|merchant|sponsor|insurer|lender|counterparty|institution|business name|account name|customer company|"
        rf"client company|affiliation|issuing authority|bill to|billed to|ship to|sold to|payee|payer))\s*[:\-–—]\s*"
        rf"([{_L}][\w&'’.-]*(?:[ \t]+(?:[{_L}][\w&'’.-]*|&|of|and)){{0,4}})")
    for m in cue.finditer(text):
        v = m.group(1).rstrip(" .,;:")
        words = v.split()
        if _likely_person_phrase(words):
            continue
        if not any(_brand_word(w) for w in words) or len(words) > 5:
            continue
        out.append((m.start(1), m.start(1) + len(v), v, "Организация после подписи"))
    # employment verbs: «works for Orchard Lane», «joined Halcyon»
    cue2 = re.compile(
        rf"\b(?i:works? (?:for|at)|worked (?:for|at)|working (?:for|at)|employed (?:by|at)|joined|consultant (?:at|for)|(?:engineer|manager|director|"
        rf"analyst|associate|partner|intern|lawyer|attorney|accountant|nurse|teacher|professor) (?:at|for)|(?:CEO|CFO|CTO|founder|president|"
        rf"chairman|owner) of|on behalf of|a customer of|a client of)\s+((?:[{_L}][\w&'’-]*)(?:[ \t]+(?:[{_L}][\w&'’-]*|&)){{0,3}})(?![\w'’-])")
    for m in cue2.finditer(text):
        words = m.group(1).split()
        # trim trailing words that are clearly the next clause
        while words and (words[-1].lower() in _LEAD_STOP or words[-1].lower() in _NOT_NAME and len(words) > 1 and words[-1].lower() not in _NOUN_SET):
            words.pop()
        if not words or _likely_person_phrase(words) or not any(_brand_word(w) for w in words):
            continue
        if len(words) == 1 and (words[0].lower() in _GENERIC or len(words[0]) < 4 or _is_given(words[0])):
            continue
        v = " ".join(words)
        out.append((m.start(1), m.start(1) + len(v), v, "Организация после «works for / joined»"))
    # legal forms with a single leading name: «Acme Ltd», «Globex Corp.» (the LATIN_LEGAL_TRAILING rule does this too; only when a comma)
    return out


def _likely_person_phrase(words: list[str]) -> bool:
    if not words:
        return False
    if len(words) in (2, 3) and _is_given(words[0]) and all(w[:1].isupper() or re.fullmatch(INIT, w) for w in words):
        return True
    return len(words) == 1 and _is_given(words[0]) and words[0] not in ("Bank",)


# ----------------------------------------------------------------------------------------------------------------- birth dates
_MON = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
_DATE = (rf"(?:\d{{1,2}}[./-]\d{{1,2}}[./-](?:19|20)\d{{2}}|(?:19|20)\d{{2}}[./-]\d{{1,2}}[./-]\d{{1,2}}|\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2}}(?!\d)|"
         rf"{_MON}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{{2}}|\d{{1,2}}(?:st|nd|rd|th)?(?:\s+of)?\s+{_MON},?\s+(?:19|20)\d{{2}}|"
         rf"(?:19|20)\d{{2}},?\s+{_MON}\s+\d{{1,2}}(?!\d))")
_BIRTH_LABEL = (r"(?:date\s+of\s+birth|birth\s*-?\s*date|birthday|d\.?\s?o\.?\s?b\.?|born(?:\s+on)?|b\.|birth\s+date\s*\(dd/mm/yyyy\)|"
                r"year\s+and\s+date\s+of\s+birth)")
BIRTH_RULES = (
    re.compile(rf"(?i)(?<![\w.]){_BIRTH_LABEL}(?![\w])\)?[^\n\d.;]{{0,30}}?({_DATE})"),
    # «(born in Springfield on March 14, 1985)»: place between «born» and the date
    re.compile(rf"(?i)\bborn\s+(?:in|at)\s+[^\n\d.;]{{2,40}}?\s+(?:on\s+)?({_DATE})"),
)


# ------------------------------------------------------------------------------------------------------------------ passport
PASSPORT_RULES = (
    re.compile(r"(?i)\b(?:passport|travel\s+document|identity\s+document|id\s+document|document|doc\.?|pass\.?)\s*"
               r"(?:(?:no|number|num|nr|n°|#|№|id)\b\.?)?\s*(?:\([A-Za-z ]{2,12}\))?\s*(?:is\s+|was\s+)?[:#=\-–]?\s*"
               r"((?-i:(?<![\dA-Za-z])(?:\d{9}|[A-Z]{1,2}\d{6,8}|\d{3}\s\d{3}\s\d{3}|\d{8}|[A-Z0-9]{9}|[A-Z]{2}\s?\d{7})(?![\dA-Za-z])))"),
)


def passport_ok(match_text: str, value: str) -> bool:
    return any(c.isdigit() for c in value)


# ------------------------------------------------------------------------------------------------------------------ addresses
_SUFFIX = ("Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Terrace|Ter|Court|Ct|Way|Place|Pl|Square|Sq|Highway|Hwy|Parkway|Pkwy|"
           "Circle|Cir|Close|Crescent|Cres|Gardens|Gdns|Grove|Row|Walk|Mews|Alley|Trail|Trl|Plaza|Broadway|Pike|Path|Loop|Heights|Hill|Rise|"
           "Green|Passage|Wharf|Quay|Embankment|Esplanade|Promenade|Causeway|Bypass")
_ONEWORD = r"(?:Kingsway|Queensway|Broadway|The\s+Strand|The\s+Mall)"
_STATE = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|"
          "AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT|NSW|VIC|QLD|WA|SA|TAS|ACT|NT")
_ZIP = rf"(?:{_STATE})\.?\s+\d{{5}}(?:-\d{{4}})?|(?:{_STATE})\s+\d{{4}}|[A-Z]\d[A-Z]\s?\d[A-Z]\d|[A-Z]{{1,2}}\d[A-Z\d]?\s*\d[A-Z]{{2}}"
_STREETNAME = rf"(?:(?:\d{{1,3}}(?:st|nd|rd|th)|[NSEW]{{1,2}}\.?|North|South|East|West)\s+)?[{_L}][\w.'’&-]*(?:[ \t]+[{_L}][\w.'’&-]*){{0,3}}"
_UNIT = r"(?:,?[ \t]+(?:Apt|Apartment|Suite|Ste|Unit|Flat|Floor|Fl|Room|Rm|Bldg|Building|#)\.?[ \t]*[\w-]+)?"
_CITYPART = rf"(?:,[ \t]*[{_L}][{_l}]+(?:[ \t-][{_L}][{_l}]+){{0,2}})"
ADDRESS_RULES = (
    # 1450 Maple Avenue, Suite 12, Springfield, IL 62704  /  221B Baker Street, London NW1 6XE  /  12 Elm Rd
    re.compile(rf"(?<![\w.#-])\d{{1,5}}[A-Za-z]?(?:-\d{{1,5}})?[ \t]+(?:{_STREETNAME}[ \t]+(?:{_SUFFIX})|{_ONEWORD})\b\.?(?:[ \t]+(?:N|S|E|W|NE|NW|SE|SW)\b\.?)?{_UNIT}"
               rf"{_CITYPART}?(?:{_CITYPART})?(?:,[ \t]*(?:{_STATE})\b(?!\w|[ \t]+\d))?(?:,?[ \t]+(?:{_ZIP}))?"),
    # Flat 3, 12 Baker Street, ...
    re.compile(rf"(?<![\w.])(?:Flat|Apartment|Apt|Suite|Unit|Room)[ \t]+\w+,[ \t]*\d{{1,5}}[A-Za-z]?[ \t]+(?:{_STREETNAME}[ \t]+(?:{_SUFFIX})|{_ONEWORD})\b\.?{_CITYPART}?(?:,?[ \t]+(?:{_ZIP}))?"),
    # P.O. Box 4411, Springfield, IL 62704
    re.compile(rf"(?<![\w.])(?:P\.?\s?O\.?\s+Box|Post\s+Office\s+Box|PO\s+Box|Private\s+Bag)[ \t]+\d+{_CITYPART}?(?:,?[ \t]+(?:{_ZIP}))?"),
    # Springfield, IL 62704 / Leeds LS1 4AP after a comma
    re.compile(rf"(?<![\w.])[{_L}][{_l}]+(?:[ \t][{_L}][{_l}]+)?,[ \t]*(?:{_STATE})\.?[ \t]+\d{{5}}(?:-\d{{4}})?(?![\d\w])"),
    # a street without a number after a preposition: «on Fenwick Street», «at 5th Avenue»
    re.compile(rf"(?<![\w.])(?:on|at|near|along|off|to|from|via|into|opposite|behind)[ \t]+((?:\d{{1,3}}(?:st|nd|rd|th)|{NW})(?:[ \t]+{NW}){{0,2}}[ \t]+(?:Street|Avenue|Road|Boulevard|Lane|Drive|Terrace|Court|Way|Place|Square|Highway|Parkway|Close|Crescent|Gardens|Grove|Mews|Alley|Trail|Plaza))\b"),
    # label + postcode/zip: «Postcode: SW1A 2AA», «ZIP 62704»
    re.compile(r"(?i)\b(?:post\s?code|postal\s+code|zip(?:\s+code)?)\s*[:#]?\s*((?<![\w])(?:\d{5}(?:-\d{4})?|[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}|[A-Z]\d[A-Z]\s?\d[A-Z]\d)(?![\w]))"),
)
_ADDR_GROUPED = {4, 5}                    # rules whose address is group 1


def address_ok(value: str) -> bool:
    words = value.split()
    return bool(words) and not any(w.lower() in _LEAD_STOP and i == 0 and False for i, w in enumerate(words))


EN_PLACES = frozenset(w.lower() for w in """
alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho illinois indiana iowa kansas kentucky
louisiana maine maryland massachusetts michigan minnesota mississippi missouri montana nebraska nevada ohio oklahoma oregon pennsylvania
tennessee texas utah vermont virginia washington wisconsin wyoming ontario quebec alberta manitoba saskatchewan england scotland wales ireland
york london manchester birmingham leeds liverpool bristol sheffield newcastle nottingham leicester edinburgh glasgow cardiff belfast oxford
cambridge brighton halifax reading southampton portsmouth plymouth norwich derby coventry hull bradford sunderland aberdeen dundee swansea
dublin cork galway limerick springfield portland columbus dallas houston austin denver seattle boston chicago atlanta miami phoenix detroit
philadelphia baltimore memphis nashville orlando tampa charlotte raleigh richmond pittsburgh cleveland cincinnati milwaukee minneapolis
omaha tulsa wichita albuquerque tucson fresno sacramento oakland sandiego sanjose sanfrancisco losangeles lasvegas saltlake kansascity
toronto vancouver montreal ottawa calgary edmonton winnipeg halifax victoria regina saskatoon sydney melbourne brisbane perth adelaide
canberra hobart darwin auckland wellington christchurch dunedin hamilton tauranga paris berlin madrid rome vienna prague warsaw lisbon athens
amsterdam brussels zurich geneva stockholm oslo copenhagen helsinki moscow kyiv istanbul dubai singapore tokyo osaka seoul beijing shanghai
hongkong mumbai delhi bangalore cairo lagos nairobi johannesburg capetown mexico bogota lima santiago brasilia sydney
america europe asia africa oceania antarctica canada australia zealand germany france spain italy portugal netherlands belgium switzerland
sweden norway denmark finland poland russia ukraine turkey china japan korea india brazil argentina chile peru colombia egypt nigeria kenya
usa uk us eu un ussr
""".split())


def is_place_phrase(words: list[str]) -> bool:
    """«Halifax», «New York», «Salt Lake City»: every word is a known place word (so not a company)."""
    return bool(words) and all(w.lower().rstrip(".,") in EN_PLACES or w.lower() in ("new", "city", "salt", "lake", "san", "los", "las", "st", "saint", "fort", "port", "north", "south", "east", "west") for w in words)


# ----------------------------------------------------------------------------------------------------------- cities in free text
# A city is hidden only next to a locative cue («in Leeds», «from Austin to Denver», «City: Glasgow», «the Boston office»): a bare
# capitalised «Reading» or «Mobile» in prose is an ordinary word. Names that are also given names / ordinary words need a strong cue.
_CITY_LIST = """
New York|Los Angeles|San Francisco|San Diego|San Jose|San Antonio|Las Vegas|Salt Lake City|Kansas City|New Orleans|Oklahoma City|Santa Fe|Santa Monica|Palo Alto|Mountain View|St. Louis|Fort Worth|Fort Lauderdale|Virginia Beach|Long Beach|Corpus Christi|Baton Rouge|Little Rock|Des Moines|Grand Rapids|Colorado Springs|Cedar Rapids|Ann Arbor|Palm Springs|Jersey City|New Haven|Springfield|Portland|Columbus|Tulsa|Denver|Boston|Raleigh|Pittsburgh|Sacramento|Austin|Dallas|Houston|Seattle|Chicago|Atlanta|Miami|Phoenix|Detroit|Philadelphia|Baltimore|Memphis|Nashville|Orlando|Tampa|Charlotte|Richmond|Cleveland|Cincinnati|Milwaukee|Minneapolis|Omaha|Wichita|Albuquerque|Tucson|Fresno|Oakland|Honolulu|Anchorage|Boise|Spokane|Tacoma|Eugene|Reno|Madison|Lincoln|Louisville|Lexington|Buffalo|Rochester|Syracuse|Albany|Hartford|Providence|Newark|Trenton|Charleston|Savannah|Jacksonville|Birmingham|Montgomery|Jackson|Knoxville|Chattanooga|Greensboro|Durham|Norfolk|Arlington|Alexandria|Washington|Dayton|Toledo|Akron|Lansing|Indianapolis|Fargo|Billings|Cheyenne|Santa Barbara|Berkeley|Pasadena|Irvine|Anaheim|Riverside|Bakersfield|Stockton|Plano|Scottsdale|Tempe|Aurora|Boulder|Provo|Burlington|Concord|Manchester|Princeton|Cambridge|Worcester|Lowell|Stamford|Brooklyn|Manhattan
London|Liverpool|Bristol|Sheffield|Newcastle|Nottingham|Leicester|Edinburgh|Glasgow|Cardiff|Belfast|Oxford|Brighton|Southampton|Portsmouth|Plymouth|Norwich|Derby|Coventry|Sunderland|Aberdeen|Dundee|Swansea|Exeter|Bath|York|Chester|Lancaster|Canterbury|Winchester|Salisbury|Gloucester|Peterborough|Ipswich|Colchester|Chelmsford|Luton|Watford|Slough|Guildford|Maidstone|Reading|Swindon|Cheltenham|Bournemouth|Poole|Taunton|Truro|Carlisle|Preston|Blackpool|Bolton|Stockport|Salford|Wigan|Warrington|Huddersfield|Bradford|Wakefield|Doncaster|Rotherham|Hull|Middlesbrough|Stoke-on-Trent|Wolverhampton|Walsall|Telford|Shrewsbury|Northampton|Milton Keynes|Bedford|Stevenage|Crawley|Croydon|Bromley|Inverness|Stirling|Perth|Paisley|Newport|Wrexham|Londonderry|Lisburn|Dublin|Cork|Galway|Limerick|Waterford|Kilkenny|Leeds
Toronto|Vancouver|Montreal|Ottawa|Calgary|Edmonton|Winnipeg|Halifax|Victoria|Regina|Saskatoon|Quebec City|Hamilton|Mississauga|Kitchener|Fredericton|Moncton
Sydney|Melbourne|Brisbane|Adelaide|Canberra|Hobart|Darwin|Gold Coast|Geelong|Townsville|Cairns|Auckland|Wellington|Christchurch|Dunedin|Tauranga|Queenstown|Napier|Rotorua
Johannesburg|Cape Town|Durban|Pretoria|Nairobi|Lagos|Accra|Cairo|Mumbai|Delhi|Bangalore|Chennai|Kolkata|Hyderabad|Singapore|Hong Kong|Dubai|Paris|Berlin|Madrid|Rome|Vienna|Prague|Warsaw|Lisbon|Athens|Amsterdam|Brussels|Zurich|Geneva|Stockholm|Oslo|Copenhagen|Helsinki|Tokyo|Osaka|Seoul|Beijing|Shanghai|Frankfurt|Munich|Hamburg|Milan|Barcelona|Moscow|Kyiv|Istanbul|Mexico City|Bogota|Lima|Santiago|Buenos Aires|Sao Paulo|Rio de Janeiro
"""
EN_CITIES = frozenset(w.strip() for w in _CITY_LIST.replace("\n", "|").split("|") if w.strip())
_AMBIG_CITY = frozenset(w.lower() for w in ("Reading Hull Bath Madison Lincoln Jackson Victoria Charlotte Austin Dallas Aurora Concord Hamilton Newport Derby Lancaster Chester "
                                            "York Bangor Perth Paris Orlando Brooklyn Washington Lexington Arlington Alexandria Columbus Durham Nelson Montgomery Richmond "
                                            "Santiago Lima Jersey Cambridge Salem Wellington Florence").split())
_CITY_ALT = "|".join(sorted((re.escape(c).replace(r"\ ", r"\s+") for c in EN_CITIES), key=len, reverse=True))
_CITY_RE = rf"(?<![\w'’-])(?P<c>{_CITY_ALT})(?![\w'’-])"
_CUE_STRONG = (r"(?:in|from|near|around|outside|within|across|throughout|based\s+in|moved\s+to|relocat\w+\s+to|born\s+in|lives?\s+in|living\s+in|"
               r"resid\w+\s+in|located\s+in|office\s+in|offices\s+in|branch\s+in|warehouse\s+in|city\s+of)")
_CUE_WEAK = r"(?:to|at|via|toward|towards|visit(?:ing|ed)?|reach(?:ing|ed)?|between)"
_CITY_CUE = re.compile(rf"\b(?P<cue>{_CUE_STRONG}|{_CUE_WEAK})\s+(?:the\s+)?(?=[A-Z])", re.I)
_CITY_LABEL = re.compile(r"\b(?:city|town|location|residence|place\s+of\s+birth|birthplace|hometown|home\s+city|home\s+town|current\s+city|"
                         r"city\s+of\s+residence|offices?|branch(?:es)?|locations?|sites|cities|towns|stores|warehouses|venue|destination|origin|domicile|operations\s+in|presence\s+in|hubs?)\s*[:\-–—]\s*", re.I)
_CITY_OFFICE = re.compile(rf"{_CITY_RE}(?=\s+(?:office|branch|warehouse|store|factory|plant|campus|clinic|hospital|team|depot|studio|headquarters|HQ)\b)")
_CITY_CHAIN = re.compile(rf"\s*(?:,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|\s*/\s*|\s+to\s+|\s*&\s*){_CITY_RE}")
_CITY_ONE = re.compile(_CITY_RE)
_CITY_LOWER = frozenset(c.lower() for c in EN_CITIES)
_CITY_DATELINE = re.compile(r"(?m)^[ \t]*(?P<n>[A-Z][A-Z .'-]{2,30}?)[ \t]*(?:[—–·•|]|--|,[ \t]*[A-Z][\w.]*(?:[ \t]*\([A-Za-z]+\))?[ \t]*[—–-])")


def city_spans(text: str) -> list[tuple[int, int, str, str]]:
    """-> [(start, end, name, reason)] cities next to a locative cue (see EN_CITIES)."""
    out: list[tuple[int, int, str, str]] = []
    seen: set[int] = set()

    def take(m: re.Match[str], strong: bool) -> int:
        if m.start("c") not in seen and (strong or m.group("c").lower() not in _AMBIG_CITY):
            seen.add(m.start("c"))
            out.append((m.start("c"), m.end("c"), re.sub(r"\s+", " ", m.group("c")), "Город (англ. текст)"))
        return m.end("c")

    def chain(pos: int, strong: bool) -> None:
        while True:
            m = _CITY_CHAIN.match(text, pos)
            if not m:
                return
            pos = take(m, strong)

    for m in _CITY_CUE.finditer(text):
        strong = bool(re.fullmatch(_CUE_STRONG, m.group("cue"), re.I))
        c = _CITY_ONE.match(text, m.end())
        if c:
            take(c, strong)
            chain(c.end("c"), strong)
    for m in _CITY_LABEL.finditer(text):
        c = _CITY_ONE.match(text, m.end())
        if c:
            take(c, True)
            chain(c.end("c"), True)
    for m in _CITY_OFFICE.finditer(text):
        take(m, False)
    for m in _CITY_DATELINE.finditer(text):                                          # «LEEDS — The council ...», «BOSTON, Mass. (AP) —»
        name = m.group("n").title()
        if name.lower() in _CITY_LOWER and m.group("n").isupper():
            out.append((m.start("n"), m.end("n"), m.group("n"), "Город (англ. текст)"))
    out.sort()
    return out
