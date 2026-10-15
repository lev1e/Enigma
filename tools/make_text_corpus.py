"""Synthetic labelled corpus v1 for the Anonymizer detector. All identities invented. Output: corpus_v1.jsonl
Each line: {"id","group","text","spans":[{"start","end","cat","text"}],"neg":[{"start","end","text"}]}
spans = sensitive (must be hidden), neg = harmless look-alikes (must NOT be hidden)."""
import json, random, re, sys
R = random.Random(20261008)
OUT = sys.argv[1] if len(sys.argv) > 1 else "corpus_v1.jsonl"

# ---------- checksum generators ----------
def inn10():
    d = [R.randint(1, 9)] + [R.randint(0, 9) for _ in range(8)]
    w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    d.append(sum(a * b for a, b in zip(d, w)) % 11 % 10)
    return "".join(map(str, d))
def inn12():
    d = [R.randint(1, 9)] + [R.randint(0, 9) for _ in range(9)]
    w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]; w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    d.append(sum(a * b for a, b in zip(d, w1)) % 11 % 10)
    d.append(sum(a * b for a, b in zip(d, w2)) % 11 % 10)
    return "".join(map(str, d))
def snils():
    d = [R.randint(0, 9) for _ in range(9)]
    while d[:3] == d[3:6] == d[6:9] or sum(d) == 0: d = [R.randint(0, 9) for _ in range(9)]
    s = sum((9 - i) * x for i, x in enumerate(d))
    c = s % 101 if s % 101 < 100 else 0
    c = 0 if c in (100, 101) else c
    return "".join(map(str, d)), "%02d" % c
def luhn(prefix, n=16):
    d = [int(x) for x in prefix] + [R.randint(0, 9) for _ in range(n - len(prefix) - 1)]
    t = 0
    for i, x in enumerate(reversed(d)):
        if i % 2 == 0:
            x *= 2
            if x > 9: x -= 9
        t += x
    d.append((10 - t % 10) % 10)
    return "".join(map(str, d))
def ogrn():
    b = "1" + "".join(str(R.randint(0, 9)) for _ in range(11)); return b + str(int(b) % 11 % 10)
def ogrnip():
    b = "3" + "".join(str(R.randint(0, 9)) for _ in range(13)); return b + str(int(b) % 13 % 10)
def digits(n): return "".join(str(R.randint(0, 9)) for _ in range(n))
def hexs(n): return "".join(R.choice("0123456789abcdef") for _ in range(n))
def alnum(n): return "".join(R.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# ---------- declension ----------
CASES = ["nom", "gen", "dat", "acc", "ins", "prep"]
def dec_name(w, kind):
    """kind: m/f given name | ms/fs surname (-ов etc.) | mp/fp patronymic. Returns 6 forms."""
    if kind == "mp":
        s = w[:-2] if w.endswith("ич") else w
        return [w, w + "а", w + "у", w + "а", w + "ем", w + "е"]
    if kind == "fp":
        b = w[:-1]; return [w, b + "ы", b + "е", b + "у", b + "ой", b + "е"]
    if kind == "ms":
        if w.endswith(("ов", "ев", "ин", "ын", "ёв")):
            return [w, w + "а", w + "у", w + "а", w + "ым", w + "е"]
        if w.endswith("ский") or w.endswith("цкий"):
            b = w[:-2]; return [w, b + "ого", b + "ому", b + "ого", b + "им", b + "ом"]
        if w.endswith("ой"):
            b = w[:-2]; return [w, b + "ого", b + "ому", b + "ого", b + "ым", b + "ом"]
        if w.endswith("ий"):
            b = w[:-2]; return [w, b + "ого", b + "ому", b + "ого", b + "им", b + "ом"]
        if w.endswith("ич"): return [w, w + "а", w + "у", w + "а", w + "ем", w + "е"]
        return [w] * 6
    if kind == "fs":
        if w.endswith(("ова", "ева", "ина", "ына", "ёва")):
            b = w[:-1]; return [w, b + "ой", b + "ой", b + "у", b + "ой", b + "ой"]
        if w.endswith("ская") or w.endswith("цкая"):
            b = w[:-2]; return [w, b + "ой", b + "ой", b + "ую", b + "ой", b + "ой"]
        return [w] * 6
    if kind == "m":
        if w.endswith("ей"): b = w[:-2]; return [w, b + "ея", b + "ею", b + "ея", b + "еем", b + "ее"]
        if w.endswith("ий"): b = w[:-2]; return [w, b + "ия", b + "ию", b + "ия", b + "ием", b + "ии"]
        if w.endswith("ь"): b = w[:-1]; return [w, b + "я", b + "ю", b + "я", b + "ем", b + "е"]
        if w.endswith("а"): b = w[:-1]; return [w, b + "ы", b + "е", b + "у", b + "ой", b + "е"]
        if w.endswith("й"): b = w[:-1]; return [w, b + "я", b + "ю", b + "я", b + "ем", b + "е"]
        return [w, w + "а", w + "у", w + "а", w + "ом", w + "е"]
    if kind == "f":
        if w.endswith("ия"): b = w[:-2]; return [w, b + "ии", b + "ии", b + "ию", b + "ией", b + "ии"]
        if w.endswith("ья"): b = w[:-1]; return [w, b + "и", b + "е", b + "ю", b + "ей", b + "е"]
        if w.endswith("я"): b = w[:-1]; return [w, b + "и", b + "е", b + "ю", b + "ей", b + "е"]
        if w.endswith("а"): b = w[:-1]; return [w, b + "ы", b + "е", b + "у", b + "ой", b + "е"]
        return [w, w + "и", w + "и", w, w + "ью", w + "и"]
    raise ValueError(kind)

# (surname, given, patronymic, sex)
M = [("Кузнецов", "Андрей", "Сергеевич"), ("Морозов", "Дмитрий", "Олегович"), ("Лебедев", "Игорь", "Николаевич"),
     ("Новиков", "Алексей", "Павлович"), ("Зайцев", "Михаил", "Юрьевич"), ("Крылов", "Владимир", "Иванович"),
     ("Тихомиров", "Артём", "Валерьевич"), ("Ильин", "Роман", "Андреевич"), ("Достоевский", "Станислав", "Борисович"),
     ("Заславский", "Евгений", "Львович"), ("Толстой", "Кирилл", "Матвеевич"), ("Макаров", "Денис", "Аркадьевич"),
     ("Фёдоров", "Григорий", "Петрович"), ("Беляев", "Максим", "Эдуардович"), ("Гришин", "Леонид", "Васильевич"),
     ("Черных", "Антон", "Геннадьевич"), ("Бондаренко", "Виктор", "Степанович"), ("Саркисян", "Арсен", "Рубенович"),
     ("Соловьёв", "Тимур", "Ринатович"), ("Орлов", "Константин", "Анатольевич")]
F = [("Морозова", "Анна", "Сергеевна"), ("Лебедева", "Мария", "Олеговна"), ("Новикова", "Елена", "Павловна"),
     ("Крылова", "Ольга", "Ивановна"), ("Ильина", "Татьяна", "Андреевна"), ("Заславская", "Наталья", "Львовна"),
     ("Макарова", "Екатерина", "Аркадьевна"), ("Беляева", "Ирина", "Эдуардовна"), ("Гришина", "Светлана", "Васильевна"),
     ("Черных", "Юлия", "Геннадьевна"), ("Бондаренко", "Оксана", "Степановна"), ("Тихомирова", "Дарья", "Валерьевна"),
     ("Кузнецова", "Алла", "Николаевна"), ("Зайцева", "Софья", "Юрьевна"), ("Фёдорова", "Лидия", "Петровна")]
def fio_forms(p, sex):
    s, g, o = p
    S = dec_name(s, "ms" if sex == "m" else "fs"); G = dec_name(g, sex); O = dec_name(o, "mp" if sex == "m" else "fp")
    return [(S[i], G[i], O[i]) for i in range(6)]

SPANS = []  # filled per item
class B:
    def __init__(self): self.t = ""; self.sp = []; self.neg = []
    def a(self, s, cat=None, neg=False):
        if cat: self.sp.append({"start": len(self.t), "end": len(self.t) + len(s), "cat": cat, "text": s})
        elif neg: self.neg.append({"start": len(self.t), "end": len(self.t) + len(s), "text": s})
        self.t += s; return self
    def __call__(self, *parts):
        for p in parts:
            if isinstance(p, str): self.a(p)
            else:
                s, c = p[0], p[1]
                if c == "NEG": self.a(s, neg=True)
                else: self.a(s, c)
        return self
ITEMS = []
def add(group, b):
    ITEMS.append({"id": f"{group}-{len(ITEMS):04d}", "group": group, "text": b.t, "spans": b.sp, "neg": b.neg})
def sent(group, *parts): add(group, B()(*parts))

# ================= PERSON: declension cases =================
frames = [  # (frame text parts with CASE marker idx, case index)
    ("", 0, " подписал акт приёмки."), ("Договор заключил ", 0, " лично."), ("Письмо от ", 1, " получено вчера."),
    ("Мы направили документы ", 2, " по почте."), ("Встретился с ", 4, " на прошлой неделе."),
    ("Вопрос обсуждали с ", 4, " и юристом."), ("Рассказали о ", 5, " в приказе."),
    ("Я видел ", 3, " в офисе."), ("Нет данных о ", 5, " в реестре."), ("Передайте ", 2, " мои слова.")]
people = [(p, "m") for p in M] + [(p, "f") for p in F]
for k in range(70):
    p, sex = people[k % len(people)]
    fr = frames[k % len(frames)]
    form = fio_forms(p, sex)[fr[1]]
    style = k % 5
    if style == 0: nm = " ".join(form)                    # ФИО
    elif style == 1: nm = f"{form[0]} {form[1]}"          # Фамилия Имя
    elif style == 2: nm = f"{form[1]} {form[0]}"          # Имя Фамилия
    elif style == 3: nm = f"{form[0]} {form[1][0]}.{form[2][0]}."  # Иванов И.И.
    else: nm = f"{form[1][0]}.{form[2][0]}. {form[0]}"    # И.И. Иванов
    sent("person_case", fr[0], (nm, "PERSON"), fr[2])
# single surname after known full name (coreference)
for k in range(20):
    p, sex = people[(k * 3) % len(people)]
    f0 = fio_forms(p, sex)
    sent("person_coref", "Директор ", (" ".join(f0[0]), "PERSON"), " утвердил план. Позже ", (f0[2][0], "PERSON"), " отозвал приказ.")
# titles/honorifics
for t in ["Господин", "Г-н", "Уважаемый", "Тов."]:
    p = M[R.randrange(len(M))]; sent("person_title", t + " ", (f"{p[0]} {p[1]}", "PERSON"), ", просим Вас подтвердить встречу.")
sent("person_title", "Уважаемая ", ("Анна Сергеевна", "PERSON"), ", направляем Вам счёт.")
sent("person_title", "Уважаемый ", ("Андрей Сергеевич", "PERSON"), "!")
sent("person_title", "Д-р ", ("Левицкий", "PERSON"), " прочитал доклад.")
# ALL CAPS
for p in [M[0], M[3], F[2], F[7], M[8]]:
    sent("person_caps", "ПОДПИСАНО: ", (" ".join(p).upper(), "PERSON"), "\nДата: см. ниже.")
sent("person_caps", "FROM: ", ("IVAN PETROV", "PERSON"), " TO: ", ("MARIA SMITH", "PERSON"))
# transliteration & English
for nm in ["Ivan Kuznetsov", "Aleksey Novikov", "Sergei Morozov", "Maria Lebedeva", "Dmitry Zaytsev", "John Whitfield", "Emma Carlisle",
           "Robert Hargreave", "Olivia Thornbury", "Michael Brandt", "Sofia Marchetti", "Yuri Kovalenko"]:
    sent("person_en", "Please contact ", (nm, "PERSON"), " regarding the invoice.")
for nm in ["Mr. Peter Holloway", "Dr. Karen Ashworth", "Ms. Laura Fenwick"]:
    sent("person_en", (nm, "PERSON"), " will chair the meeting.")
for nm in ["Hans Müller", "Pierre Dubois", "Giovanni Rossi"]:
    sent("person_en", "Signed by ", (nm, "PERSON"), ", Managing Director.")
for nm in ["Kuznetsov A.S.", "A. S. Kuznetsov", "J. Whitfield", "Smith, John"]:
    sent("person_en", "Reviewed by ", (nm, "PERSON"), " on Monday.")
# nicknames / diminutives (full given-only names are ambiguous; label PERSON)
for nm in ["Саша", "Серёга", "Лёха", "Ваня", "Катя", "Димон"]:
    sent("person_nick", "Позвони ", (nm, "PERSON"), " и узнай, когда будет готово.")
# names in quotes / inline
sent("person_quote", "Он сказал: «", ("Иван Петров", "PERSON"), " подписал договор вчера».")
sent("person_quote", 'Клиент "', ("Сергей Макаров", "PERSON"), '" просил перезвонить.')
sent("person_quote", "Заявитель — ", ("Крылова Ольга Ивановна", "PERSON"), ", паспорт предъявлен.")
sent("person_list", "Участники: ", ("Морозов Д.О.", "PERSON"), ", ", ("Лебедева М.О.", "PERSON"), ", ", ("Новиков А.П.", "PERSON"), ".")
sent("person_list", "Присутствовали:\n1. ", ("Зайцев Михаил Юрьевич", "PERSON"), "\n2. ", ("Тихомирова Дарья Валерьевна", "PERSON"), "\n")
sent("person_hyphen", ("Петрова-Водкина Анна", "PERSON"), " и ", ("Салтыков-Щедрин Илья", "PERSON"), " подали заявки.")
sent("person_hyphen", ("Мария Ли-Смит", "PERSON"), " выступила с докладом.")
sent("person_ya", ("Ёлкин Пётр Ильич", "PERSON"), " и ", ("Щукина Юлия Эдуардовна", "PERSON"), " присутствовали.")
sent("person_ya", "Работник: ", ("Оглы Рашид Эльдар", "PERSON"), ".")
# role + name in tables
sent("person_tab", "ФИО\tДолжность\n", ("Кузнецов Андрей Сергеевич", "PERSON"), "\tбухгалтер\n", ("Морозова Анна Сергеевна", "PERSON"), "\tменеджер\n")

# ================= PHONE =================
pf = ["+7 (913) 555-12-34", "8 913 555 12 34", "89135551234", "+79135551234", "8-913-555-12-34", "913-555-12-34", "(913) 555-12-34",
      "+7 913 555 1234", "7 (913) 5551234", "+7.913.555.12.34", "+44 20 7946 0958", "+1 (415) 555-0132", "(495) 123-45-67",
      "8 (495) 123-45-67", "+49 30 123456", "+380 44 123 45 67", "8 800 555-35-35", "+7(913)555-12-34", "+7-913-555-12-34", "8(913)5551234",
      "+7 495 123 45 67", "8 (383) 210-45-67"]
frames_ph = ["Тел.: {}", "Звоните по номеру {}", "Мой номер {}", "Phone: {}", "Call me at {}", "контакт: {}, добавочный 12", "Моб. {}", "WhatsApp {}", "Факс: {}"]
for i, ph in enumerate(pf):
    fr = frames_ph[i % len(frames_ph)]
    b = B(); pre, post = fr.split("{}"); b(pre, (ph, "PHONE"), post, ".")
    add("phone", b)
sent("phone_unlab", "Пишите на почту или набирайте ", ("8 913 555 12 34", "PHONE"), " после 18:00.")
sent("phone_ctx", "Тел. ", ("+7 (913) 555-12-34", "PHONE"), " Иванов Иван")  # trailing-space bug probe
sent("phone_ctx", "Тел ", ("+7 (913) 555-12-34", "PHONE"), " ", ("Иванов Иван Петрович", "PERSON"), "")
sent("phone_ctx", "Тел: ", ("8 913 555 12 34", "PHONE"), " (рабочий), ", ("8 913 555 12 35", "PHONE"), " (домашний)")

# ================= EMAIL =================
em = ["ivan.petrov@gmail.com", "i.petrov@romashka.ru", "иван@почта.рф", "user+tag@sub.example.co.uk", "a_b-c@mail.ru", "IVAN.PETROV@MAIL.RU",
      "info@tehnopark-alfa.ru", "o.kuznetsova@corp.nordlicht.de", "m.lebedeva@yandex.ru", "sales@brightwave.io", "первый.отдел@компания.рф", "d.morozov@xn--80aswg.xn--p1ai"]
for i, e in enumerate(em):
    sent("email", ["Пишите на ", "E-mail: ", "email — ", "Отправьте копию ", "Contact: ", "mailto:"][i % 6], (e, "EMAIL"), [".", ", спасибо.", "\n", "", " today.", ""][i % 6])
sent("email_hdr", "From: ", ("Ivan Petrov", "PERSON"), " <", ("ivan.petrov@gmail.com", "EMAIL"), ">\nTo: ", ("Maria Smith", "PERSON"), " <", ("m.smith@example.org", "EMAIL"), ">\n")

# ================= URL / DOMAIN / USERNAME =================
for u, c in [("https://romashka.ru/cabinet?user=123", "DOMAIN"), ("www.tehnopark-alfa.ru", "DOMAIN"), ("https://crm.nordlicht-handel.de/login", "DOMAIN"),
             ("brightwave.io", "DOMAIN"), ("https://портал.рф/вход", "DOMAIN"), ("http://intranet.vektor-m.com", "DOMAIN")]:
    sent("url", "Ссылка: ", (u, c), " (внутренний ресурс).")
for h in ["@ivan_petrov", "@kuznetsov_a", "@maria.lebedeva"]:
    sent("username", "Telegram: ", (h, "USERNAME"), ".")
sent("username", "Логин: ", ("ipetrov", "USERNAME"), ", пароль выдан отдельно.")
sent("username", "Profile: linkedin.com/in/", ("ivan-petrov-4821", "USERNAME"))

# ================= IP =================
for ip in ["192.168.1.15", "10.20.30.40", "172.16.254.1", "8.8.8.8", "203.0.113.77"]:
    sent("ip", "Доступ с адреса ", (ip, "IP_ADDRESS"), " зафиксирован.")
for ip in ["2001:db8::1", "fe80::1ff:fe23:4567:890a", "2001:0db8:85a3:0000:0000:8a2e:0370:7334", "::1"]:
    sent("ip6", "Source IP ", (ip, "IP_ADDRESS"), " blocked.")
sent("ip_neg", "Версия сборки ", ("2.10.3.1", "NEG"), " и ", ("v1.4.2.9", "NEG"), " выпущены.")
sent("ip_neg", "Раздел ", ("1.2.3.4", "NEG"), " Положения о закупках.")

# ================= IDs =================
for i in range(8):
    sent("inn_org", ["ИНН ", "ИНН: ", "ИНН/КПП ", "ИНН контрагента — "][i % 4], (inn10(), "INN_ORG"), [" ", ".", ", ", ";"][i % 4] + "расчёт.")
for i in range(8):
    sent("inn_person", ["ИНН ", "ИНН физлица: ", "ИНН "][i % 3], (inn12(), "INN_PERSON"), ".")
for i in range(6):
    sent("inn_unlabeled", "Контрагент (", (inn10(), "INN_ORG"), ") оплатил счёт.")
for i in range(4):
    sent("inn_unlabeled", "В таблице указан ", (inn12(), "INN_PERSON"), " без подписи.")
for i in range(4):
    sent("kpp", "ИНН ", (inn10(), "INN_ORG"), " КПП ", ("77" + digits(2) + "01001", "KPP"), ".")
for i in range(4):
    sent("ogrn", "ОГРН ", (ogrn(), "OGRN"), ", зарегистрирован давно.")
for i in range(3):
    sent("ogrn", "ОГРНИП ", (ogrnip(), "OGRN"), ".")
for i in range(6):
    n, c = snils(); fmt = i % 3
    s = f"{n[:3]}-{n[3:6]}-{n[6:]} {c}" if fmt == 0 else (f"{n}{c}" if fmt == 1 else f"{n[:3]} {n[3:6]} {n[6:]} {c}")
    sent("snils", ["СНИЛС ", "СНИЛС: ", "страховой номер "][i % 3], (s, "SNILS"), ".")
for i, f in enumerate(["45 12 345678", "4512 345678", "4512345678", "45 12 №345678"]):
    sent("passport", ["Паспорт ", "паспорт серия/номер ", "Паспорт РФ: ", "Документ, удостоверяющий личность: паспорт "][i % 4], (f, "PASSPORT"), ", выдан ОВД района.")
sent("passport", "серия ", ("4512", "PASSPORT"), " № ", ("345678", "PASSPORT"), ", выдан 12.03.2015")
for i, f in enumerate(["77 12 345678", "7712 345678", "50 21 987654"]):
    sent("driver", "Водительское удостоверение ", (f, "DRIVER_LICENSE"), " действительно.")
for i in range(3):
    d = digits(16); sent("oms", "Полис ОМС ", (d[:4] + " " + d[4:8] + " " + d[8:12] + " " + d[12:], "OMS"), ".")
for i in range(3):
    sent("oms", "ОМС № ", (digits(16), "OMS"), ".")
for i in range(6):
    sent("bank", ["р/с ", "Расчётный счёт: ", "Р/с №", "счёт "][i % 4], (("40702810" + digits(12)), "BANK_ACCOUNT"), " в банке.")
for i in range(3):
    sent("bank", "к/с ", ("30101810" + digits(12), "BANK_ACCOUNT"), ", БИК ", ("04" + digits(7), "BIK"), ".")
for i in range(3):
    sent("bik", "БИК ", ("04" + digits(7), "BIK"), ".")
for pre in ["4276", "5536", "4111", "5100", "2200", "4000"]:
    c = luhn(pre); sent("card", "Карта ", (" ".join(c[i:i + 4] for i in range(0, 16, 4)), "CARD"), ", срок 12/28.")
for pre in ["4276", "5536"]:
    sent("card", "Номер карты: ", (luhn(pre), "CARD"), ".")
sent("card", "Card ", ("4111-1111-1111-1111", "CARD"), " charged.")
for iban in ["DE89 3704 0044 0532 0130 00", "GB29 NWBK 6016 1331 9268 19", "FR14 2004 1010 0505 0001 3M02 606", "DE44500105175407324931"]:
    sent("iban", "IBAN: ", (iban, "BANK_ACCOUNT"), " (SEPA).")
sent("crypto", "BTC: ", ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "SECRET"), ".")
sent("crypto", "Wallet ", ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "SECRET"), " received funds.")
sent("crypto", "ETH ", ("0x" + hexs(40), "SECRET"), " is mine.")
sent("secret", "api_key=", ("sk-live-" + alnum(32), "SECRET"), "")
sent("secret", "Authorization: Bearer ", ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYmMxMjMifQ." + alnum(43), "SECRET"), "")
sent("secret", "export AWS_ACCESS_KEY_ID=", ("AKIA" + "".join(R.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for _ in range(16)), "SECRET"), "")
sent("secret", "token: ", ("ghp_" + alnum(36), "SECRET"), "")
sent("secret", "пароль: ", ("Qw3rty!9xZ", "SECRET"), "")
sent("secret", "password=", ("Hunter2!x", "SECRET"), "&user=admin")
sent("secret", "Пароль от почты — ", ("Tr0ub4dor&3", "SECRET"), ", никому не говорите.")
sent("secret", "secret_key = '", (hexs(40), "SECRET"), "'")
sent("secret", "-----BEGIN RSA PRIVATE KEY-----\n", ("MIIEowIBAAKCAQEA" + alnum(60), "SECRET"), "\n-----END RSA PRIVATE KEY-----")
sent("secret", "pwd: ", ("Zq8!mLp2", "SECRET"), "")
# ================= DOB / PLATE / CONTRACT =================
for s in ["12.05.1985", "03.03.1990", "1 февраля 1975", "1990-03-03"]:
    sent("dob", ["Дата рождения: ", "родился ", "д.р. ", "DOB: "][["12.05.1985", "03.03.1990", "1 февраля 1975", "1990-03-03"].index(s)], (s, "BIRTH_DATE"), ".")
sent("dob", "Дата рождения: ", ("12 марта 1988 г.", "BIRTH_DATE"), "")
for pl in ["А123ВС 77", "к456мр178", "Е001КХ 199", "М777ММ 50"]:
    sent("plate", "Автомобиль с госномером ", (pl, "VEHICLE_PLATE"), " припаркован.")
for c in ["45/2023-К", "ДГ-2023/118", "2023-0451-Д", "У-17/09"]:
    sent("contract", "Договор № ", (c, "CONTRACT"), " от 12.05.2023 заключён.")
sent("contract_neg", "Договор от ", ("12.05.2023", "NEG"), " на сумму ", ("1 250 000,00 руб.", "NEG"), " действует до ", ("31.12.2026", "NEG"), ".")
# ================= ORG =================
orgs = ["ООО «Технопарк-Альфа»", 'ООО "Вектор-М"', "АО «Тихая Гавань»", "ЗАО «Северная Звезда»", "ПАО «Альфастрой»", "ИП Белов Игорь Олегович",
        "ОАО «Мостотрест-Сибирь»", "НКО «Фонд Рассвет»", "ООО Ромашка", "ООО «Лотос и партнёры»", "АО Нордлихт-Рус",
        "Nordlicht Handels GmbH", "Brightwave Solutions LLC", "Kestrel Dynamics Ltd.", "Harbor & Finch Inc.", "Delta Systems S.A.", "Kuznetsov Consulting LLP"]
fr_org = ["Договор с {} заключён.", "Поставщик — {}.", "Счёт выставлен {}", "Мы работаем с {} с 2019 года.", "Client: {}", "Подрядчик {} выполнил работы.",
          "Платёж в пользу {} получен.", "Письмо от {} пришло вчера."]
for i, o in enumerate(orgs):
    fr = fr_org[i % len(fr_org)]; pre, post = fr.split("{}")
    sent("org", pre, (o, "ORG"), post)
sent("org_ip", "ИП ", ("Белов И.О.", "ORG"), " получил оплату.")
sent("org_abbr", "Мы подписали контракт с ", ("Альфа-Групп", "ORG"), " вчера.")
sent("org_neg", "Сбербанк и ", ("Яндекс", "ORG"), " вышли на рынок.")  # public companies: ambiguous, report
# ================= GEO =================
geo = [("г. Новосибирск, ул. Кирова, д. 12, кв. 45", "ADDRESS"), ("Москва, Тверская ул., 7", "ADDRESS"), ("Санкт-Петербург, Невский пр-т, 28", "ADDRESS"),
       ("420111, г. Казань, ул. Баумана, д.5", "ADDRESS"), ("пос. Заречный, ул. Лесная, 3", "ADDRESS"), ("221B Baker Street, London", "ADDRESS"),
       ("1600 Example Ave, Springfield, IL 62704", "ADDRESS"), ("г. Екатеринбург, пр. Ленина, д. 50, оф. 301", "ADDRESS"), ("Краснодарский край, ст. Васюринская", "ADDRESS")]
for a, c in geo:
    sent("address", "Адрес: ", (a, c), ".")
for city in ["Новосибирск", "Омск", "Воронеж", "Томск", "Самара", "Саратов", "Тюмень", "Красноярск"]:
    sent("city", "Офис находится в г. ", (city, "CITY"), ".")
for city in ["Новосибирске", "Томске", "Омске"]:
    sent("city", "Сотрудник работает в ", (city, "CITY"), " с 2020 года.")
for city in ["Berlin", "Manchester", "Hamburg"]:
    sent("city_en", "Our office is in ", (city, "CITY"), ".")
# ================= DISTRACTORS =================
neg_sents = [
    ["Орёл", "NEG"], ]
def neg(*parts): sent("neg", *parts)
neg(("Орёл", "NEG"), " — гордая птица, а не имя.")
neg("На гербе изображён ", ("орёл", "NEG"), ".")
neg("К праздничному столу подали ", ("гусь", "NEG"), " с яблоками.")
neg(("Любовь", "NEG"), " — это сильное чувство.")
neg("Фильм «", ("Любовь", "NEG"), " и голуби» показали вчера.")
neg("Борьба за ", ("мир", "NEG"), " продолжается; ", ("Мира", "NEG"), " не будет без диалога.")
neg("Он жил на проспекте ", ("Мира", "NEG"), ".")  # street => ADDRESS arguably; counted as ambiguous
neg("Площадь ", ("Победы", "NEG"), " закрыта.")
neg("Мы изучали эпоху ", ("Петра", "NEG"), " Великого на уроке истории.")
neg("Артикул ", ("AB-4521-X", "NEG"), ", партия ", ("L-2023-09", "NEG"), ".")
neg("Заказ № ", ("4521-8890-12", "NEG"), " отправлен.")
neg("ISBN ", ("978-5-17-123456-7", "NEG"), ".")
neg("Версия ", ("3.14.2", "NEG"), " вышла в ", ("2025", "NEG"), " году.")
neg("Сумма ", ("12 345,67", "NEG"), " руб., НДС ", ("20%", "NEG"), ".")
neg("Температура ", ("-15", "NEG"), " градусов, давление ", ("760", "NEG"), " мм.")
neg("Страница ", ("1234", "NEG"), " из ", ("5678", "NEG"), ".")
neg("Модель ", ("iPhone 15 Pro", "NEG"), " и ", ("Galaxy S24", "NEG"), " в наличии.")
neg("Сайт на платформе ", ("WordPress", "NEG"), " с темой ", ("Astra", "NEG"), ".")
neg("Совещание в понедельник в ", ("10:30", "NEG"), ", кабинет ", ("205", "NEG"), ".")
neg("Код ТН ВЭД ", ("8517130000", "NEG"), ".")
neg("Номер отслеживания ", ("RA123456789RU", "NEG"), ".")
neg("Kodak и Nokia — известные бренды.")
neg("Постановление от ", ("15.03.2022", "NEG"), " № ", ("123-ФЗ", "NEG"), " действует.")
neg("Рис ", ("12", "NEG"), ", таблица ", ("3.4", "NEG"), ", раздел ", ("2.1.5", "NEG"), ".")
neg("Принято решение о повышении цены на ", ("5", "NEG"), " процентов.")
neg("Генеральный директор принял решение. Бухгалтер подготовил отчёт. Юрист проверил договор.")
neg("The quick brown fox jumps over the lazy dog. Invoice due in 30 days.")
neg("Уважаемые коллеги, напоминаем о сроках сдачи отчётности.")
neg("Дедлайн: ", ("1 ноября", "NEG"), ". Пятница, ", ("13", "NEG"), " число.")
neg("Ссылка на закон: статья ", ("228.1", "NEG"), " УК РФ, часть ", ("2", "NEG"), ".")
neg("Координаты: ", ("55.7558", "NEG"), ", ", ("37.6173", "NEG"), ".")
neg("Хэш коммита ", ("a1b2c3d", "NEG"), " слит в ветку main.")
neg("Файл ", ("report_final_v2.xlsx", "NEG"), " загружен.")
neg("Квартал: ", ("Q3 2026", "NEG"), ", выручка выросла.")
neg("Мария, Анна и Пётр — типичные русские имена (общий перечень).")  # ambiguous: bare given names
neg("Мир, труд, май. Роза, Вера, Надежда, Любовь — слова-имена.")
neg("Встреча в кафе «", ("Пётр", "NEG"), "» на углу.")
neg("Гражданин Российской Федерации вправе обжаловать решение.")
neg("Победа, Заря, Север, Восток — названия кинотеатров.")
neg("В Москве, Санкт-Петербурге и Казани проходят чемпионаты.")  # cities: sensitive by product setting -> labelled as CITY? mark only as note
neg("Оплата по реквизитам, указанным в приложении №", ("1", "NEG"), ".")
# ================= MIXED PARAGRAPHS =================
def para(i):
    p, sex = people[(i * 7) % len(people)]; f0 = fio_forms(p, sex)
    s, g, o = p
    org = orgs[i % 11]; ph = pf[i % 14]; e = em[i % 10]
    n10 = inn10(); card = luhn("4276")
    city = ["Новосибирск", "Омск", "Томск", "Самара"][i % 4]
    b = B()
    b("Протокол встречи. ", (org, "ORG"), " в лице директора ", (" ".join(f0[1]), "PERSON"), " (ИНН ", (n10, "INN_ORG"), ") передал ",
      (" ".join(f0[2]), "PERSON"), " документы. Контакты: ", (ph, "PHONE"), ", ", (e, "EMAIL"), ". Офис — г. ", (city, "CITY"),
      ". Карта для оплаты ", (" ".join(card[i:i + 4] for i in range(0, 16, 4)), "CARD"), ". Версия отчёта ", ("4.2.1", "NEG"), ", сумма ", ("150 000 руб.", "NEG"), ".")
    add("mixed", b)
for i in range(30): para(i)
def para_en(i):
    nm = ["John Whitfield", "Emma Carlisle", "Robert Hargreave", "Olivia Thornbury"][i % 4]
    b = B(); n = ["Brightwave Solutions LLC", "Kestrel Dynamics Ltd.", "Nordlicht Handels GmbH"][i % 3]
    b("Dear ", (nm, "PERSON"), ", the invoice from ", (n, "ORG"), " is attached. Reach me at ", ("+1 (415) 555-0132", "PHONE"), " or ",
      (f"{nm.split()[0].lower()}@example.org", "EMAIL"), ". Build ", ("2.10.3", "NEG"), " shipped ", ("2026-03-01", "NEG"), ".")
    add("mixed_en", b)
for i in range(12): para_en(i)
# mixed ru/en transliteration inside Russian text
for nm, tr in [("Иван Кузнецов", "Ivan Kuznetsov"), ("Мария Лебедева", "Maria Lebedeva")]:
    sent("translit", "Контакт: ", (nm, "PERSON"), " (", (tr, "PERSON"), ")")
# lines of structured text
sent("csvline", "id,name,phone\n1,", ("Кузнецов Андрей Сергеевич", "PERSON"), ",", ("+7 (913) 555-12-34", "PHONE"), "\n")
sent("jsonline", '{"name": "', ("Лебедева Мария Олеговна", "PERSON"), '", "email": "', ("m.lebedeva@yandex.ru", "EMAIL"), '"}')
sent("logline", "2026-10-08 12:00:01 INFO user=", ("ipetrov", "USERNAME"), " ip=", ("192.168.1.15", "IP_ADDRESS"), " login ok")
# ================= write =================
with open(OUT, "w", encoding="utf-8") as f:
    for it in ITEMS: f.write(json.dumps(it, ensure_ascii=False) + "\n")
print(len(ITEMS), "items", sum(len(i["spans"]) for i in ITEMS), "sensitive spans", sum(len(i["neg"]) for i in ITEMS), "neg spans")
