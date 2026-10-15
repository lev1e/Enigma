"""Dense synthetic identity generator for tools/eval_real.py (independent ground truth).

dense(seed, lang) -> Pack with ~50 gold values (kind, value) and ready-made text variants:
  pack.gold    [(kind, value)]            what must disappear (leak check needles come from needles())
  pack.lines   short labelled lines       one value or two per line, many writing styles
  pack.rows    table rows (header, rows)  contacts / requisites table
  pack.prose   sentences mixing values    contract/e-mail style paragraphs (names in genitive/dative, initials, etc.)
All values are synthetic (reserved example domains, invented names/orgs, checksum-valid numbers).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

SUR_STEM = ["Чернобаев", "Мирошкин", "Вересовский", "Лопатинский", "Тимонин", "Кудашкин", "Зарубин", "Нефёдкин", "Савельцев", "Барсуков",
            "Дроздецкий", "Хлебников", "Ушаков-Бельский", "Гайдамаков", "Остапчук", "Ржевский", "Пастернаков", "Шелепин", "Ковалевский", "Бирюков"]
GIV_M = [("Пётр", "Сергеевич", "Петра", "Петру"), ("Матвей", "Олегович", "Матвея", "Матвею"), ("Артём", "Игоревич", "Артёма", "Артёму"),
         ("Константин", "Павлович", "Константина", "Константину")]
GIV_F = [("Алла", "Игоревна", "Аллы", "Алле"), ("Вера", "Павловна", "Веры", "Вере"), ("Ксения", "Олеговна", "Ксении", "Ксении"),
         ("Дарья", "Сергеевна", "Дарьи", "Дарье")]
ORG_CORE = ["Вектор-Альфа", "Северный Ветер", "Техносфера-М", "Кедровый Берег", "Альтаир Логистик", "Рубеж", "Новая Гавань", "Эпсилон-Групп", "Белый Парус", "Горизонт Плюс"]
ORG_FORM = ["ООО", "АО", "ПАО", "ЗАО", "ИП"]
STREETS = ["Верещагинская", "Тихомировский", "Лермонтовско-Загорская", "Колокольная", "Прибрежная Слобода", "Вознесенская", "Заводская Набережная", "Каменноостровская"]
CITIES = ["Москва", "Казань", "Нижний Новгород", "Тверь", "Екатеринбург", "Самара"]
EN_SUR = ["Whitfield", "Okonkwo", "Lindqvist", "Haverford", "Delacroix", "Abernathy", "Kowalczyk", "Underhill", "Vandermeer", "Castellanos"]
EN_GIV = ["John", "Grace", "Marcus", "Elena", "Priya", "Thomas", "Yuki", "Oliver"]
EN_ORG = ["Northwind Holdings", "Blue Harbor Capital", "Quillfeather Labs", "Redwood Ferris Logistics", "Orchard Lane Partners", "Halcyon Dynamics"]
EN_STREET = ["Marchmont Avenue", "Calloway Court", "Fenwick Street", "Larkspur Way", "Brambleton Road"]
EN_CITY = ["Springfield", "Leeds", "Portland", "Dunedin", "Halifax"]


def luhn(prefix: str) -> str:
    d = [int(c) for c in prefix]
    s = sum((x * 2 - 9 if x * 2 > 9 else x * 2) if i % 2 == 0 else x for i, x in enumerate(reversed(d + [0])))
    return prefix + str((10 - s % 10) % 10)


def _digits(r: random.Random, n: int) -> str:
    return "".join(str(r.randrange(10)) for _ in range(n))


def inn10(r: random.Random) -> str:
    d = [r.randrange(1, 10)] + [r.randrange(10) for _ in range(8)]
    d.append(sum(a * b for a, b in zip(d, [2, 4, 10, 3, 5, 9, 4, 6, 8])) % 11 % 10)
    return "".join(map(str, d))


def inn12(r: random.Random) -> str:
    d = [r.randrange(1, 10)] + [r.randrange(10) for _ in range(9)]
    d.append(sum(a * b for a, b in zip(d, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8])) % 11 % 10)
    d.append(sum(a * b for a, b in zip(d, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])) % 11 % 10)
    return "".join(map(str, d))


def ogrn(r: random.Random) -> str:
    n = "1" + _digits(r, 11)
    return n + str(int(n) % 11 % 10)


def snils(r: random.Random) -> str:
    n = [r.randrange(10) for _ in range(9)]
    s = sum(a * b for a, b in zip(n, range(9, 0, -1)))
    c = s % 101 % 100 if s % 101 != 100 else 0
    return f"{n[0]}{n[1]}{n[2]}-{n[3]}{n[4]}{n[5]}-{n[6]}{n[7]}{n[8]} {c:02d}"


@dataclass
class Pack:
    lang: str
    gold: list[tuple[str, str]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    rows: tuple[list[str], list[list[str]]] = field(default_factory=lambda: ([], []))
    prose: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)       # author/title/subject/keywords/comment for document properties

    def add(self, kind: str, value: str) -> str:
        self.gold.append((kind, value))
        return value


def dense(seed: str, lang: str) -> Pack:
    r = random.Random(seed)
    return _ru(r) if lang == "ru" else _en(r)


def _ru(r: random.Random) -> Pack:
    p = Pack("ru")
    sur = r.sample(SUR_STEM, 5)
    people = []
    for i, s in enumerate(sur):
        fem = i % 2 == 1
        g = r.choice(GIV_F if fem else GIV_M)
        s2 = (s[:-2] + "ая" if s.endswith("ий") else s + "а") if fem else s
        if fem and s.endswith("ий"):
            s2 = s[:-2] + "ая"
        people.append((s2, g, fem))
    # persons: full, initials, reversed, genitive/dative in prose
    full = [f"{s} {g[0]} {g[1]}" for s, g, _ in people]
    for f in full:
        p.add("PERSON", f)
    short = [f"{s} {g[0][0]}.{g[1][0]}." for s, g, _ in people]
    orgs = []
    for i in range(3):
        core = r.choice(ORG_CORE) + ("" if i < 2 else f" {r.choice(['Юг', 'Сервис', 'Холдинг'])}")
        form = ORG_FORM[i % 3]
        orgs.append((form, core))
        p.add("ORG", core)
    addr = []
    for i in range(3):
        st, city, house, flat = r.choice(STREETS), r.choice(CITIES), r.randrange(2, 90), r.randrange(1, 300)
        addr.append(f"г. {city}, ул. {st}, д. {house}, кв. {flat}")
        p.add("ADDRESS", st)
    phones = [f"+7 (9{r.randrange(10)}{r.randrange(10)}) {r.randrange(100, 999)}-{r.randrange(10, 99)}-{r.randrange(10, 99)}",
              f"8 9{r.randrange(10)}{r.randrange(10)} {r.randrange(100, 999)}{r.randrange(1000, 9999)}",
              f"+79{_digits(r, 9)}", f"8 (495) {r.randrange(100, 999)}-{r.randrange(10, 99)}-{r.randrange(10, 99)}"]
    for ph in phones:
        p.add("PHONE", ph)
    mails = [f"p{r.randrange(100, 999)}.{r.randrange(1000, 9999)}@mail-demo.example.ru", f"office{r.randrange(10, 99)}@{r.choice(['vektor-demo', 'rubezh-demo'])}.example.com",
             f"a.{r.randrange(1000, 9999)}@corp-demo.example.org"]
    for m in mails:
        p.add("EMAIL", m)
    inn_p, inn_p2, inn_o, inn_o2 = inn12(r), inn12(r), inn10(r), inn10(r)
    for v in (inn_p, inn_p2, inn_o, inn_o2):
        p.add("INN", v)
    kpp = [f"77{r.randrange(10, 99)}0{r.randrange(1, 9)}001", f"16{r.randrange(10, 99)}0{r.randrange(1, 9)}001"]
    for v in kpp:
        p.add("KPP", v)
    og = [ogrn(r), ogrn(r)]
    for v in og:
        p.add("OGRN", v)
    bik = [f"04{_digits(r, 7)}", f"04{_digits(r, 7)}"]
    for v in bik:
        p.add("BIK", v)
    acc = [f"40702810{_digits(r, 12)}", f"30101810{_digits(r, 12)}", f"40817810{_digits(r, 12)}"]
    for v in acc:
        p.add("ACCOUNT", v)
    pas = [f"{r.randrange(10, 99)} {r.randrange(10, 99)} {r.randrange(100000, 999999)}", f"{r.randrange(10, 99)}{r.randrange(10, 99)} {r.randrange(100000, 999999)}"]
    for v in pas:
        p.add("PASSPORT", v)
    sn = [snils(r), snils(r)]
    for v in sn:
        p.add("SNILS", v)
    cards = [" ".join(luhn("4276" + _digits(r, 11))[i:i + 4] for i in range(0, 16, 4)), " ".join(luhn("5536" + _digits(r, 11))[i:i + 4] for i in range(0, 16, 4))]
    for v in cards:
        p.add("CARD", v)
    plates = [f"{r.choice('АВЕКМНОРСТУХ')}{r.randrange(100, 999)}{r.choice('АВЕКМНОРСТУХ')}{r.choice('АВЕКМНОРСТУХ')} {r.choice([77, 99, 50, 16, 116])}"]
    for v in plates:
        p.add("PLATE", v)
    ips = [f"10.{r.randrange(1, 250)}.{r.randrange(1, 250)}.{r.randrange(1, 250)}", f"192.168.{r.randrange(1, 250)}.{r.randrange(2, 250)}"]
    for v in ips:
        p.add("IP", v)
    secrets = [f"sk_live_{_digits(r, 6)}Zq{_digits(r, 8)}Xw", f"Rv{_digits(r, 3)}!kd{_digits(r, 4)}Pm"]
    p.add("SECRET", secrets[0])
    p.add("SECRET", secrets[1])
    bd = [f"{r.randrange(10, 28)}.{r.randrange(10, 12)}.{r.randrange(1955, 2001)}", f"{r.randrange(10, 28)}.0{r.randrange(1, 9)}.{r.randrange(1955, 2001)}"]
    for v in bd:
        p.add("BIRTHDATE", v)
    # labelled lines, various styles
    p.lines = [
        f"Заявитель: {full[0]}, дата рождения {bd[0]}", f"Паспорт серия и номер {pas[0]}, СНИЛС {sn[0]}", f"ИНН {inn_p}, тел. {phones[0]}",
        f"E-mail: {mails[0]}", f"Банковская карта {cards[0]}", f"{short[1]} ({phones[1]})", f"Представитель: {full[1]}, паспорт {pas[1]}, СНИЛС {sn[1]}",
        f"{orgs[0][0]} «{orgs[0][1]}», ИНН {inn_o}, КПП {kpp[0]}, ОГРН {og[0]}", f"Юридический адрес: {addr[0]}", f"Расчётный счёт {acc[0]} в банке, БИК {bik[0]}, корр. счёт {acc[1]}",
        f"Директор {orgs[1][0]} «{orgs[1][1]}» {full[2]}, ИНН {inn_p2}, моб. {phones[2]}", f"Контакт: {mails[1]}, офис {phones[3]}",
        f"Адрес регистрации: {addr[1]}", f"Адрес проживания: {addr[2]}", f"{orgs[2][0]} «{orgs[2][1]}», ИНН {inn_o2}, КПП {kpp[1]}, ОГРН {og[1]}, БИК {bik[1]}",
        f"Карта второго держателя {cards[1]}, счёт физлица {acc[2]}", f"Автомобиль: госномер {plates[0]}", f"Сервер {ips[0]}, резервный {ips[1]}, админ {mails[2]}",
        f"API key: {secrets[0]}", f"password = {secrets[1]}", f"Подписант {short[2]}, дата рождения {bd[1]}", f"Ответственный: {full[3]} / {short[3]}", f"Свидетель {full[4]}"]
    rows = [["ФИО", "Телефон", "E-mail", "ИНН", "Паспорт", "СНИЛС", "Адрес"],
            [full[0], phones[0], mails[0], inn_p, pas[0], sn[0], addr[0]], [full[1], phones[1], mails[1], inn_p2, pas[1], sn[1], addr[1]],
            [full[2], phones[2], mails[2], inn_p, pas[0], sn[1], addr[2]], [full[3], phones[3], mails[0], inn_p2, pas[1], sn[0], addr[0]]]
    p.rows = (rows[0], rows[1:])
    def gen(s, g, fem):
        return f"{s[:-1]}{'ой' if s.endswith('а') else 'а'}" if False else s
    p.prose = [
        f"Настоящий договор заключён между {orgs[0][0]} «{orgs[0][1]}» (ИНН {inn_o}, КПП {kpp[0]}), в лице директора {full[2]}, и гражданином {full[0]}, "
        f"{bd[0]} года рождения, паспорт {pas[0]}, проживающим по адресу: {addr[1]}.",
        f"Оплата производится на расчётный счёт {acc[0]} в банке с БИК {bik[0]}, корреспондентский счёт {acc[1]}. Уведомления направлять на {mails[1]} или по телефону {phones[0]}.",
        f"Копию паспорта {full[1]} ({pas[1]}), СНИЛС {sn[1]} и ИНН {inn_p2} приложить к заявлению. С {short[0]} связаться по {phones[1]}.",
        f"Переписка: «Добрый день, {full[3].split()[1]} {full[3].split()[2]}! Направляю реквизиты {orgs[2][0]} «{orgs[2][1]}»: ОГРН {og[1]}, ИНН {inn_o2}. Карта для возврата {cards[0]}»."]
    p.meta = {"author": full[0], "title": f"Договор {orgs[0][1]}", "subject": f"ИНН {inn_o}", "keywords": f"{mails[0]}; {phones[0]}", "comments": f"Контакт {full[1]} {phones[2]}"}
    return p


def _en(r: random.Random) -> Pack:
    p = Pack("en")
    people = [(r.choice(EN_GIV), r.choice("ABCDEJKLMNRST") + ".", s) for s in r.sample(EN_SUR, 5)]
    full = [f"{g} {m} {s}" for g, m, s in people]
    plain = [f"{g} {s}" for g, m, s in people]
    comma = [f"{s}, {g}" for g, m, s in people]
    for f in full:
        p.add("PERSON", f)
    orgs = r.sample(EN_ORG, 3)
    for o in orgs:
        p.add("ORG", o)
    addr = []
    for i in range(3):
        st = r.choice(EN_STREET)
        addr.append(f"{r.randrange(2, 4900)} {st}, {r.choice(EN_CITY)}")
        p.add("ADDRESS", st)
    phones = [f"+44 20 7{r.randrange(100, 999)} {r.randrange(1000, 9999)}", f"(415) 555-{r.randrange(1000, 9999)}", f"+1-212-555-{r.randrange(1000, 9999)}", f"+49 30 {r.randrange(100000, 999999)}"]
    for v in phones:
        p.add("PHONE", v)
    mails = [f"{people[0][0].lower()}.{people[0][2].lower()}{r.randrange(10, 99)}@demo-mail.example.com", f"billing{r.randrange(10, 99)}@{r.choice(['northwind', 'halcyon'])}-demo.example.org",
             f"{people[2][0][0].lower()}{people[2][2].lower()}{r.randrange(100, 999)}@corp-demo.example.net"]
    for v in mails:
        p.add("EMAIL", v)
    cards = [" ".join(luhn("5500" + _digits(r, 11))[i:i + 4] for i in range(0, 16, 4)), " ".join(luhn("4111" + _digits(r, 11))[i:i + 4] for i in range(0, 16, 4))]
    for v in cards:
        p.add("CARD", v)
    pas = [f"{r.randrange(100, 999)}{r.randrange(100000, 999999)}", f"{r.choice('ABCDEFGH')}{_digits(r, 8)}"]
    for v in pas:
        p.add("PASSPORT", v)
    ssn = [f"{r.randrange(100, 665)}-{r.randrange(10, 99)}-{r.randrange(1000, 9999)}", f"{r.randrange(100, 665)}-{r.randrange(10, 99)}-{r.randrange(1000, 9999)}"]
    for v in ssn:
        p.add("SSN", v)
    bban = f"NWBK{_digits(r, 14)}"                       # real GB IBAN: ISO 13616 mod-97 check digits (the product rightly ignores invalid ones)
    chk = 98 - int("".join(str(int(c, 36)) for c in bban + "GB00")) % 97
    iban = f"GB{chk:02d}{bban}"
    p.add("IBAN", iban)
    ips = [f"10.{r.randrange(1, 250)}.{r.randrange(1, 250)}.{r.randrange(1, 250)}", f"172.16.{r.randrange(1, 250)}.{r.randrange(2, 250)}"]
    for v in ips:
        p.add("IP", v)
    sec = [f"sk_live_{_digits(r, 6)}Zq{_digits(r, 8)}Xw", f"Rv{_digits(r, 3)}!kd{_digits(r, 4)}Pm"]
    for v in sec:
        p.add("SECRET", v)
    bd = [f"{r.randrange(1, 28):02d}/{r.randrange(1, 12):02d}/{r.randrange(1955, 2001)}", f"{r.choice(['March', 'July', 'October'])} {r.randrange(1, 28)}, {r.randrange(1955, 2001)}"]
    for v in bd:
        p.add("BIRTHDATE", v)
    p.lines = [f"Applicant: {full[0]}, date of birth {bd[0]}", f"Phone: {phones[0]}  Email: {mails[0]}", f"Card {cards[0]}, passport no. {pas[0]}",
               f"SSN {ssn[0]}; alt. contact {comma[1]}", f"{orgs[0]}, {addr[0]}", f"Wire to IBAN {iban}, attn {full[2]}", f"Customer: {plain[3]} <{mails[1]}> tel {phones[1]}",
               f"Billing address: {addr[1]}", f"Ship to {addr[2]}, contact {full[4]} {phones[2]}", f"Witness: {plain[1]}, passport {pas[1]}, born {bd[1]}",
               f"Server {ips[0]} (fallback {ips[1]}), admin {mails[2]}", f"token = {sec[0]}", f"password: {sec[1]}", f"{orgs[1]} and {orgs[2]} signed by {full[3]}, SSN {ssn[1]}",
               f"Card on file {cards[1]}, phone {phones[3]}"]
    rows = [["Name", "Phone", "Email", "SSN", "Passport", "Address"],
            [full[0], phones[0], mails[0], ssn[0], pas[0], addr[0]], [full[1], phones[1], mails[1], ssn[1], pas[1], addr[1]], [full[2], phones[2], mails[2], ssn[0], pas[0], addr[2]]]
    p.rows = (rows[0], rows[1:])
    p.prose = [f"This agreement is made between {orgs[0]} ({addr[0]}) represented by {full[2]} and {full[0]}, born {bd[0]}, passport {pas[0]}, residing at {addr[1]}.",
               f"Payments go to IBAN {iban}. Send notices to {mails[1]} or call {phones[0]}. Copy {plain[3]} (SSN {ssn[1]}) on every invoice.",
               f"Hi {people[1][0]}, please charge card {cards[0]} for {orgs[2]}; my cell is {phones[2]} and my email {mails[2]}. Regards, {full[4]}."]
    p.meta = {"author": full[0], "title": f"Agreement {orgs[0]}", "subject": f"Contact {mails[0]}", "keywords": f"{phones[0]}; {mails[1]}", "comments": f"Prepared for {full[1]}"}
    return p
