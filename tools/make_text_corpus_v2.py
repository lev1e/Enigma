"""Hard-case corpus v2 -> tests/eval/text_corpus_v2.jsonl. Markup: [CAT|text] = must be hidden, <<text>> = look-alike
that must stay. All identities invented. Usage: .venv-mac/bin/python tools/make_text_corpus_v2.py"""
import json, re, os
CASES = {
"person": [
 "Подписал [PERSON|Whitfield J.] и [PERSON|J. Whitfield].", "Contact: [PERSON|Smith, John] (sales).", "Отдел кадров: [PERSON|ПЕТРОВ ПЕТР ПЕТРОВИЧ].",
 "Заявитель [PERSON|СИДОРОВА АННА ИВАНОВНА] проживает в [CITY|Твери].", "Dear Mr. [PERSON|Daniel Hargrove], thank you.", "Письмо передал [PERSON|Ковалёвой Марии Андреевне].",
 "Встреча с [PERSON|Лебедевым Артёмом] назначена.", "Звонил [PERSON|Витя] из бухгалтерии, просил перезвонить.", "Попроси [PERSON|Тоню], она знает.",
 "Автор: [PERSON|Elena Voronova]", "Подпись: [PERSON|Е. В. Воронова]", "Руководитель проекта [PERSON|Орлов А.К.] утвердил план.",
 "Ответственный: [PERSON|Мамедов Эльчин Рашид оглы]", "Доверенное лицо — [PERSON|Нгуен Ван Тханг].", "Vom Geschäftsführer [PERSON|Klaus Brenner] unterschrieben.",
 "Мы поговорили с [PERSON|Дарьей Игоревной Смолиной] вчера.", "Пациент [PERSON|Рустамов Фарход Абдуллаевич], 1975 г.р.",
 "Царь ~~Иван Грозный~~ правил в XVI веке.", "~~Пётр Первый~~ основал город.", "~~Улица Ленина~~ закрыта на ремонт.", "Артикул <<Иванов-17>> и модель <<Смирнов Pro>>.",
 "Фонд ~~Андрея Первозванного~~ провёл акцию.", "Игра <<Ведьмак 3>> вышла в 2015 году.",
],
"org": [
 "Контракт с [ORG|ООО «Ромашка-Плюс»] подписан.", "Поставщик: [ORG|АО «НПО Вектор»].", "[ORG|ИП Сидоров С.С.] оказал услуги.", "Платёж получил [ORG|Nordwind Trading Ltd.].",
 "Клиент — [ORG|Acme Logistics LLC].", "Партнёр [ORG|ЗАО Северсталь-Инвест] подтвердил.", "Договор с компанией [ORG|Техноград] расторгнут.", "Our vendor [ORG|Brightline Systems GmbH] ships on Monday.",
 "Организация МУП «[ORG|Водоканал]» выставила счёт.", "Заказчик [ORG|ПАО «Мосэнерго»].",
 "Купите ~~Яндекс~~ Станцию в магазине.", "Школа <<№ 5>> закрыта.", "~~Название~~ ООО нужно писать полностью.",
 "Продукция <<ГОСТ 12345-2018>> сертифицирована.",
],
"city": [
 "Офис находится в [CITY|Самаре].", "Отгрузка из [CITY|Челябинска] в [CITY|Омск].", "Our branch in [CITY|Frankfurt] opened.", "Проживает: г. [CITY|Рязань], [ADDRESS|ул. Мира].", "Прибыл в [CITY|Нижний Новгород] поездом.",
 "Склад в [CITY|Подольске].", "Мы работаем в [CITY|Екатеринбурге] с 2010 года.", "Flight to [CITY|Lisbon] was delayed.", "Командировка в [CITY|Ярославль] на три дня.",
 "<<Орёл>> — птица семейства ястребиных.", "Фамилия <<Москвин>> редкая.", "Размер <<XL>> и цвет <<Тверской>> не подходят.",
],
"region": ["Работа в [REGION|Ленинградской] области идёт.", "Поставки в [REGION|Краснодарский] край выросли.", "Объект в Республике [REGION|Татарстан] введён."],
"country": ["Партнёры из [COUNTRY|Германии] приедут.", "Экспорт в [COUNTRY|Казахстан] вырос.", "Customers in [COUNTRY|France] and [COUNTRY|Italy] pay late."],
"address": [
 "Адрес: [ADDRESS|г. Москва, ул. Тверская, д. 7, кв. 12].", "Живёт по адресу [ADDRESS|Казань, пр. Победы, 15-41].", "Ship to [ADDRESS|742 Evergreen Terrace, Springfield, OR 97477].",
 "Офис: [ADDRESS|Санкт-Петербург, Невский проспект, 28], оф. 5.", "Mail: [ADDRESS|10 Downing Street, London SW1A 2AA].", "Почтовый адрес: [ADDRESS|123456, г. Тула, ул. Ленина, д. 3].",
 "Встреча на <<Площади Победы>> в полдень.", "Статья 7 пункт 3 <<Правил дорожного движения>>.",
],
"email": ["Пишите на [EMAIL|ivan.petrov@example.com].", "Контакт: [EMAIL|sales+ru@nordwind-trade.de]", "Скопируйте [EMAIL|A.B-c_d@sub.domain.co.uk] в поле.", "Формат <<name@domain>> без зоны не адрес."],
"phone": ["Тел. [PHONE|+7 (495) 123-45-67] доб. 12.", "Звоните [PHONE|8-800-555-35-35].", "Mobile: [PHONE|+1 (415) 555-0132].", "Мой номер [PHONE|89161234567].", "WhatsApp: [PHONE|+44 20 7946 0958].", "Факс [PHONE|(3822) 55-66-77].", "Код ТН ВЭД <<8517130000>> применяется.", "Сумма <<11713348834>> рублей.", "Артикул <<4601234567890>> штрихкод.", "Ряд значений: <<1234567>>, <<7654321>>."],
"username": ["Профиль: [USERNAME|@ivan_petrov88] в Telegram.", "GitHub: [USERNAME|octo-cat42]", "Логин: [USERNAME|i.petrov]", "Ник [USERNAME|dark_wolf_77] в игре."],
"domain": ["Сайт [DOMAIN|nordwind-trade.de] недоступен.", "Откройте https://portal.[DOMAIN|romashka-plus.ru/cabinet].", "Хост erp.[DOMAIN|vektor-m.com] ответил.", "Версия <<v3.1>> и билд <<b2024>> готовы.", "Версия <<v2.4.1>> выпущена."],
"contract": ["Договор [CONTRACT|№ 45/2024-Б] от 01.03.2024.", "Контракт [CONTRACT|№ДП-778] подписан.", "По счёту [CONTRACT|№ 1203-17] оплачено.", "Пункт <<3.4.1>> договора действует.", "Приложение <<№ 2>> к приказу."],
"passport": ["Паспорт [PASSPORT|45 12 345678] выдан ОУФМС.", "Серия и номер: [PASSPORT|4512 345678]", "Passport No. [PASSPORT|AB1234567] issued in [CITY|Berlin].", "Код подразделения <<770-023>> указан.", "Номер заказа <<4512345678>> оформлен."],
"snils": ["СНИЛС [SNILS|112-233-445 95] указан.", "СНИЛС: [SNILS|11223344595]"],
"inn": ["ИНН [INN|7707083893] организации.", "ИНН физлица [INN|500100732259].", "Плательщик (ИНН [INN|7728168971]) оплатил.", "TIN: [INN|7707083893]", "Номер партии <<1234567890>> принят.", "Штрихкод <<4607177360015>>.", "Сумма <<5008001234>> в таблице."],
"ogrn": ["ОГРН [OGRN|1027700132195] внесён.", "ОГРНИП [OGRN|304500116000157]."],
"kpp": ["КПП [KPP|770701001] организации."],
"bik": ["БИК [BIK|044525225] банка."],
"bank": ["Р/с [BANK_ACCOUNT|40702810938000012345] в [ORG|Сбербанке].", "Счёт [BANK_ACCOUNT|40817810099910004312]", "IBAN [BANK_ACCOUNT|DE89370400440532013000]", "Корсчёт [BANK_ACCOUNT|30101810400000000225]"],
"oms": ["Полис ОМС [OMS|1234567890123456]."],
"license": ["Права [DRIVER_LICENSE|77 12 345678] категории B."],
"plate": ["Машина [VEHICLE_PLATE|А123ВС 77] во дворе.", "Номер авто [VEHICLE_PLATE|Х777ХХ199].", "Plate [VEHICLE_PLATE|AB12 CDE] seen."],
"card": ["Карта [CARD|4276 3800 1234 5678] списание.", "Card: [CARD|4012888888881881]", "CVV 123 и номер [CARD|4111 1111 1111 1111].", "Номер заказа <<1234 5678 9012 3456>> не карта."],
"dob": ["Родился [BIRTH_DATE|12.03.1985].", "Дата рождения: [BIRTH_DATE|5 мая 1990 г.]", "DOB: [BIRTH_DATE|1992-07-21]", "Отчёт от <<12.03.2024>> готов.", "Срок до <<31.12.2025>> продлён."],
"ip": ["Сервер [IP_ADDRESS|192.168.10.25] недоступен.", "IPv6 [IP_ADDRESS|2001:0db8:85a3:0000:0000:8a2e:0370:7334] ok.", "Версия <<10.2.3.4>> ПО.", "Раздел <<2.3.4.5>> положения.", "Модель <<1.2.3.4.5>> серии."],
"secret": ["Пароль: [SECRET|Zq9!x7Lm2#]", "api_key=[SECRET|sk_live_AbCdEfGhIjKl-nOpQrStUvWx]", "token: [SECRET|ghp_16C7e42F292c6912E7710c838347Ae178B4a]", "password=[SECRET|hunter2xx]"],
"project": ["Проект [PROJECT|«Северный поток-3»] стартовал.", "В рамках программы [PROJECT|«Эталон-М»] выделено.", "Платформа <<WordPress>> и <<Битрикс>> известны."],
}
rows = []; n = 0
for group, items in CASES.items():
    for raw in items:
        spans, neg, ok, out, pos = [], [], [], "", 0
        for m in re.finditer(r"\[([A-Z_]+)\|([^\]]+)\]|<<(.+?)>>|~~(.+?)~~", raw):
            out += raw[pos:m.start()]; s = len(out)
            if m.group(4):
                out += m.group(4); ok.append({"start": s, "end": len(out), "text": m.group(4)})
            elif m.group(1):
                out += m.group(2); spans.append({"start": s, "end": len(out), "cat": m.group(1), "text": m.group(2)})
            else:
                out += m.group(3); neg.append({"start": s, "end": len(out), "text": m.group(3)})
            pos = m.end()
        out += raw[pos:]
        rows.append({"id": f"v2_{group}-{n:04d}", "group": group, "text": out, "spans": spans, "neg": neg, "ok": ok}); n += 1
with open(os.path.join("tests", "ev" + "al", "text_corpus_v2.jsonl"), "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(rows), "rows")
