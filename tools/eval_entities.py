"""Entity coverage probe (W11): kind x language x carrier matrix on synthetic values.

For every sample value (invented, checksum-valid where the kind has one) the value is embedded in a carrier
(prose, table row under a header, short header/footer line, URL, file name, comment) and the detector is asked
what it finds over the value. Result per cell: AUTO (replaced), REVIEW (flagged but not auto), MISS.

  python tools/eval_entities.py [--json out.json]

`supported` = the kind exists in tokens.KINDS or a detector rule claims it; the rest are candidates NOT yet detected,
measured here so the gap list in docs/superpowers/entity-coverage.md rests on numbers. Read-only: nothing in anonymizer/ is touched.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (kind label, lang, value, header word for the table carrier, prose template with {v})
S = [
    # ---- kinds the product claims (tokens.KINDS) ----
    ("PERSON", "ru", "Иванова Мария Петровна", "ФИО", "Заявление подписала {v} лично."),
    ("PERSON", "en", "Michael J. Peterson", "Name", "The letter was signed by {v} yesterday."),
    ("EMAIL", "ru", "m.ivanova@firma-demo.ru", "E-mail", "Пишите на {v} в рабочее время."),
    ("EMAIL", "en", "m.peterson@acme-demo.com", "Email", "Write to {v} for details."),
    ("PHONE", "ru", "+7 916 123-45-67", "Телефон", "Звоните по номеру {v} после десяти."),
    ("PHONE", "en", "+1 (415) 555-0142", "Phone", "Call me on {v} after ten."),
    ("INN", "ru", "7707083893", "ИНН", "ИНН организации {v}, прошу проверить."),
    ("INN", "ru", "500100732259", "ИНН", "ИНН физлица {v} указан в анкете."),
    ("SNILS", "ru", "112-233-445 95", "СНИЛС", "СНИЛС {v} приложен к заявлению."),
    ("PASSPORT", "ru", "4510 123456", "Паспорт", "Паспорт серии и номер {v} выдан в 2015 году."),
    ("PASSPORT", "en", "X1234567", "Passport", "Passport number {v} expires in 2030."),
    ("OGRN", "ru", "1027700132195", "ОГРН", "ОГРН {v} внесён в реестр."),
    ("KPP", "ru", "770701001", "КПП", "КПП {v} указан в реквизитах."),
    ("BIK", "ru", "044525225", "БИК", "БИК банка {v}."),
    ("BANK_ACCOUNT", "ru", "40702810938000012345", "Р/с", "Расчётный счёт {v} открыт в банке."),
    ("CARD", "en", "4276 3800 1234 5679", "Card", "Charge card {v} for the order."),
    ("CARD", "ru", "5536 9140 1234 5678", "Карта", "Оплата картой {v} прошла."),
    ("BIRTH_DATE", "ru", "14.03.1987", "Дата рождения", "Дата рождения: {v}, место рождения Тула."),
    ("BIRTH_DATE", "en", "March 14, 1987", "Date of birth", "Date of birth: {v}."),
    ("IP_ADDRESS", "en", "203.0.113.45", "IP", "Login from {v} at 10:42."),
    ("VEHICLE_PLATE", "ru", "А123ВС 77", "Госномер", "Автомобиль с госномером {v} стоял у входа."),
    ("DRIVER_LICENSE", "ru", "77 12 345678", "ВУ", "Водительское удостоверение {v} действительно."),
    ("OMS", "ru", "7745 8590 1234 5678", "Полис ОМС", "Полис ОМС {v} предъявлен в регистратуре."),
    ("ADDRESS", "ru", "г. Москва, ул. Лесная, д. 5, кв. 12", "Адрес", "Проживает по адресу {v}."),
    ("ADDRESS", "en", "221B Baker Street, London NW1 6XE", "Address", "Ship to {v} please."),
    ("ORG", "ru", "ООО «Ромашка Логистик»", "Организация", "Договор с {v} подписан."),
    ("ORG", "en", "Northwind Traders Ltd", "Company", "The contract with {v} was signed."),
    ("USERNAME", "en", "@mpeterson_88", "Telegram", "Contact me on {v} anytime."),
    ("DOMAIN", "en", "intranet.northwind-demo.com", "Site", "The portal lives at {v} for staff."),
    ("SECRET", "en", "sk_live_51HqXyZabcDEF1234567890", "API key", "api_key = {v}"),
    ("SECRET", "ru", "Qw3rty!Zx9", "Пароль", "Пароль: {v} (никому не сообщать)."),
    ("NATIONAL_ID", "en", "078-05-1120", "SSN", "SSN {v} on file."),
    ("NATIONAL_ID", "en", "QQ 12 34 56 C", "NI number", "National Insurance number {v}."),
    ("CONTRACT", "ru", "№ 45/2024-ДС", "Договор", "По договору {v} поставка выполнена."),
    # ---- candidates NOT in tokens.KINDS ----
    ("IBAN", "en", "GB82 WEST 1234 5698 7654 32", "IBAN", "Transfer to IBAN {v} today."),
    ("SWIFT", "en", "DEUTDEFF500", "SWIFT", "SWIFT code {v} for the wire."),
    ("VIN", "en", "1HGCM82633A004352", "VIN", "Vehicle VIN {v} registered in 2019."),
    ("VIN", "ru", "XTA210930Y2765432", "VIN", "VIN автомобиля {v} указан в ПТС."),
    ("CRYPTO_BTC", "en", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "Wallet", "Send BTC to {v} please."),
    ("CRYPTO_ETH", "en", "0x52908400098527886E0F7030069857D2E4169EE7", "Wallet", "ETH address {v} confirmed."),
    ("API_KEY_AWS", "en", "AKIAIOSFODNN7EXAMPLE", "Key", "aws key {v} leaked in the log."),
    ("API_KEY_GITHUB", "en", "ghp_16C7e42F292c6912E7710c838347Ae178B4a", "Token", "token {v} was committed."),
    ("JWT", "en", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "Auth", "Authorization: Bearer {v}"),
    ("GPS", "en", "55.751244, 37.618423", "Coordinates", "Meeting point at {v}, behind the station."),
    ("MAC", "en", "00:1A:2B:3C:4D:5E", "MAC", "Device MAC {v} joined the network."),
    ("IMEI", "en", "356938035643809", "IMEI", "Phone IMEI {v} was reported lost."),
    ("UK_NHS", "en", "943 476 5919", "NHS number", "NHS number {v} on the referral."),
    ("DE_STEUER_ID", "en", "86095742719", "Steuer-ID", "Steuer-ID {v} wurde angegeben."),
    ("US_EIN", "en", "12-3456789", "EIN", "Employer EIN {v} on the W-9."),
    ("US_DRIVER", "en", "D123-4567-8901", "License", "Driver license {v} was scanned."),
    ("BIRTH_DATE_ISO", "en", "1987-03-14", "DOB", "DOB {v} per the record."),
    ("BIRTH_DATE_WORDS", "ru", "14 марта 1987 года рождения", "Родился", "Сотрудник {v}, принят в 2012."),
    ("ROLE_TITLE", "ru", "главный бухгалтер Петрова А. В.", "Должность", "Отчёт подготовила {v}."),
    ("ROLE_TITLE", "en", "Chief Financial Officer Anna Whitfield", "Title", "Approved by {v} on Monday."),
    ("SIGNATURE_LINE", "ru", "_____________ / Сидоров И. И. /", "Подпись", "Директор {v}"),
    ("SIGNATURE_LINE", "en", "/s/ Robert A. Chen", "Signed", "Respectfully, {v}"),
    ("PHONE_NO_PLUS_RU", "ru", "8 (495) 123-45-67", "Тел.", "Приёмная: {v}."),
    ("KZ_IIN", "ru", "870314300123", "ИИН", "ИИН {v} указан в анкете."),
    ("UA_RNTRC", "ru", "3123456789", "РНУКПН", "РНУКПН {v} указан в декларации."),
    ("FAX_EXT", "en", "ext. 4417", "Ext", "Reach reception on {v}."),
    ("MEDICAL_RECORD", "en", "MRN 00482913", "MRN", "Patient {v} was admitted on Friday."),
    ("DIAGNOSIS_ICD", "ru", "диагноз J18.9 (пневмония)", "Диагноз", "У пациента {v}."),
    ("SALARY", "ru", "оклад 185 000 руб.", "Оклад", "Сотруднику установлен {v}."),
]
CARRIERS = {
    "prose": lambda h, t, v: t.format(v=v),
    "table": lambda h, t, v: f"№\t{h}\tДата\n1\t{v}\t01.02.2024\n2\tдругое значение\t03.02.2024\n",
    "header": lambda h, t, v: f"{h}: {v}",
    "url": lambda h, t, v: f"https://portal.example.org/profile?{h.lower().replace(' ', '_')}={v.replace(' ', '%20')}",
    "filename": lambda h, t, v: f"scan_{v.replace(' ', '_')}.pdf",
    "comment": lambda h, t, v: f"/* TODO: check {h} {v} before release */",
}
KNOWN_KINDS = {"PERSON", "EMAIL", "PHONE", "INN", "SNILS", "PASSPORT", "OGRN", "KPP", "BIK", "BANK_ACCOUNT", "CARD", "BIRTH_DATE", "IP_ADDRESS",
               "VEHICLE_PLATE", "DRIVER_LICENSE", "OMS", "ADDRESS", "ORG", "USERNAME", "DOMAIN", "SECRET", "NATIONAL_ID", "CONTRACT"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    from tests.helpers import Env
    env = Env()
    det = env.service.build_detector(env.service.settings_for({}))
    cells: dict = collections.defaultdict(lambda: collections.Counter())
    rows = []
    for kind, lang, value, header, tpl in S:
        for car, fn in CARRIERS.items():
            text = fn(header, tpl, value)
            pos = text.find(value if car != "url" else value.replace(" ", "%20"))
            if pos < 0:
                pos = text.find(value.replace(" ", "_"))
            end = pos + len(value) if pos >= 0 else len(text)
            try:
                det.harvest(text, "x.txt")
                fs = det.scan(text, "x.txt", "text")
            except Exception as ex:                                    # noqa: BLE001
                fs = []
                print("ERR", kind, car, ex, file=sys.stderr)
            ov = [f for f in fs if f.start < end and f.end > max(pos, 0)]
            core = value.replace(" ", "")
            covered = "".join(ch for i, ch in enumerate(text[max(pos, 0):end], max(pos, 0)) if any(f.start <= i < f.end and f.decision.value == "AUTO" for f in ov))
            if ov and any(f.decision.value == "AUTO" for f in ov) and len(covered.replace(" ", "")) >= 0.8 * len(core):
                res = "AUTO"
            elif ov:
                res = "REVIEW" if all(f.decision.value != "AUTO" for f in ov) else "PARTIAL"
            else:
                res = "MISS"
            cells[(kind, lang, car)][res] += 1
            rows.append({"kind": kind, "lang": lang, "carrier": car, "result": res, "found": [(f.category, f.decision.value) for f in ov][:3]})
    env.close()
    per_kind = collections.defaultdict(collections.Counter)
    per_car = collections.defaultdict(collections.Counter)
    for r in rows:
        per_kind[(r["kind"], r["lang"])][r["result"]] += 1
        per_car[r["carrier"]][r["result"]] += 1
    print(f"{'kind':<18}{'lang':<5}{'known':<6}{'AUTO':>5}{'PART':>5}{'REV':>5}{'MISS':>5}  recall(AUTO)")
    for (k, l), c in sorted(per_kind.items(), key=lambda x: (x[0][0] not in KNOWN_KINDS, x[0])):
        n = sum(c.values())
        print(f"{k:<18}{l:<5}{'yes' if k in KNOWN_KINDS else 'NO':<6}{c['AUTO']:>5}{c['PARTIAL']:>5}{c['REVIEW']:>5}{c['MISS']:>5}  {c['AUTO']}/{n} = {c['AUTO'] / n:.2f}")
    print("\nper carrier (all kinds):")
    for car, c in per_car.items():
        n = sum(c.values())
        kn = [r for r in rows if r["carrier"] == car and r["kind"] in KNOWN_KINDS]
        ka = sum(1 for r in kn if r["result"] == "AUTO")
        print(f"  {car:<9} AUTO {c['AUTO']}/{n}; known kinds only {ka}/{len(kn)} = {ka / max(1, len(kn)):.2f}")
    kn = [r for r in rows if r["kind"] in KNOWN_KINDS]
    un = [r for r in rows if r["kind"] not in KNOWN_KINDS]
    print(f"\nTOTAL known-kind cells {len(kn)}: AUTO {sum(r['result'] == 'AUTO' for r in kn)}; candidate-kind cells {len(un)}: AUTO {sum(r['result'] == 'AUTO' for r in un)}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
