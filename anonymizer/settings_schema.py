"""Единая схема настроек: одна таблица на экран настроек, хранилище, чаты и движок.

Каждый пункт здесь связан с реальным поведением (поле `Settings`, правило хранения или режим обработки файла);
пункты, которых в движке нет, сюда не добавляются. Экран настроек рисуется из этой таблицы, поэтому он не может
показать то, чего нет в движке, и не может забыть то, что есть.

Порядок значений: явный параметр запуска > настройка чата > общая настройка > значение по умолчанию.
Защищённые виды данных (пароли и ключи, карты и счета, паспорта, СНИЛС) нельзя выключить ни в чате, ни в запуске.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Виды, которые выключить нельзя: утечка этих данных необратима. Переключателей для них нет.
PROTECTED_KINDS = frozenset({"SECRET", "CARD", "BANK_ACCOUNT", "PASSPORT", "NATIONAL_ID", "SNILS", "DRIVER_LICENSE", "OMS"})


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    kind: str                   # bool | choice | list | int
    default: object
    section: str                # general | categories | words | files | storage
    label: str
    hint: str
    example: str = ""
    scope: str = "chat"         # chat — можно переопределить в чате; global — только общие настройки
    advanced: bool = False
    kinds: tuple[str, ...] = ()  # для переключателей категорий: какие виды данных (tokens.KINDS) выключаются
    choices: tuple[tuple[object, str], ...] = ()
    group: str = ""             # подзаголовок внутри раздела


SECTIONS = (
    ("general", "Общие"),
    ("categories", "Что скрывать"),
    ("words", "Скрытие слов"),
    ("files", "Файлы"),
    ("storage", "Хранение и приватность"),
    ("office", "Word, Excel, PowerPoint"),
    ("about", "О программе"),
)


# Виды данных, сгруппированные для экрана настроек. (код, название, пояснение, пример, редкий ли)
# Защищённые виды (PROTECTED_KINDS) показываются строками без переключателя: выключить их нельзя.
KIND_GROUPS: tuple[tuple[str, str, str, tuple[tuple[str, str, str, str, bool], ...]], ...] = (
    ("people", "Люди", "Имена и даты рождения.", (
        ("PERSON", "Имена людей", "Имена, фамилии, отчества в любых падежах и инициалы.", "Иванов И.И. → Name1", False),
        ("BIRTH_DATE", "Даты рождения", "Даты рядом со словами «родился», «дата рождения».", "12.03.1985 → Birthdate1", False),
    )),
    ("orgs", "Организации", "Компании, проекты и коммерческие условия.", (
        ("ORG", "Компании", "Названия с ООО, АО и без них.", "ООО «Ромашка» → Company1", False),
        ("PROJECT", "Проекты и объекты", "Если программа их узнаёт по контексту.", "проект «Орион» → Project1", False),
        ("BUSINESS", "Коммерческие данные", "Строки про выручку, себестоимость, маржу, KPI, бонусы и зарплату целиком. По умолчанию выключено: может скрыть нужное для задачи.",
         "Выручка за год 4 млн руб. → Biz1", False),
    )),
    ("requisites", "Реквизиты организаций", "Налоговые и банковские реквизиты.", (
        ("INN", "ИНН", "Идентификационный номер налогоплательщика.", "7707083893 → Inn1", False),
        ("KPP", "КПП", "Код причины постановки на учёт.", "770701001 → Kpp1", False),
        ("OGRN", "ОГРН", "Основной государственный регистрационный номер.", "1027700132195 → Ogrn1", False),
        ("BIK", "БИК", "Банковский идентификационный код.", "044525225 → Bik1", False),
        ("BANK_ACCOUNT", "Расчётный счёт", "Банковские счета.", "40702810… → Account1", False),
        ("CONTRACT", "Номера договоров", "Номера договоров и документов.", "Договор № 45/2024 → Contract1", False),
    )),
    ("documents", "Личные документы", "Удостоверения, полисы и прочие персональные данные.", (
        ("PASSPORT", "Паспорт", "Серия и номер, кем и когда выдан.", "4510 123456 → Passport1", False),
        ("SNILS", "СНИЛС", "Страховой номер.", "123-456-789 01 → Snils1", False),
        ("NATIONAL_ID", "Национальный ID", "SSN и ITIN (США), SIN (Канада), NI number (Великобритания).", "SSN 437-86-6666 → NationalId1", False),
        ("DRIVER_LICENSE", "Водительское удостоверение", "Серия и номер.", "99 01 123456 → License1", False),
        ("OMS", "Полис ОМС", "Номер полиса.", "→ Oms1", False),
        ("VEHICLE_PLATE", "Госномера", "Номера автомобилей.", "А123ВС 77 → Plate1", True),
        ("MEDICAL_ID", "Медицинские номера", "Номера медицинских карт и историй болезни.", "MRN: 00482913 → Medical1", True),
        ("DEVICE_ID", "Идентификаторы устройств", "IMEI и MAC-адреса.", "IMEI: 358099497424747 → Device1", True),
        ("COMPENSATION", "Оплата труда", "Суммы после слов «оклад», «зарплата», «премия»; сами слова остаются.", "оклад 150 000 → Pay1", True),
        ("PII", "Прочие персональные данные", "Остальные найденные персональные данные.", "", True),
    )),
    ("places", "Места", "Каждый вид скрывается отдельно.", (
        ("COUNTRY", "Страны", "Вместе со странами скрываются слова от них: «китайский», «в Армении».", "Китай → Country1", False),
        ("REGION", "Регионы", "Области, края, республики и макрорегионы: «Азия», «Ближний Восток».", "Татарстан → Region1", False),
        ("CITY", "Города", "Города и населённые пункты.", "г. Казань → City1", False),
        ("ADDRESS", "Адреса", "Улицы и адреса целиком.", "ул. Мира, 5 → Address1", False),
    )),
    ("contacts", "Контакты", "Способы связаться с человеком или компанией.", (
        ("EMAIL", "Email", "Адреса электронной почты целиком.", "ivan@firma.ru → email1@example.com", False),
        ("PHONE", "Телефоны", "Любые форматы записи телефонных номеров.", "+7 495 123-45-67 → Phone1", False),
        ("DOMAIN", "Сайты и домены", "Адреса сайтов, домены, в том числе русские (пример.рф).", "firma.ru → Domain1", False),
        ("USERNAME", "Аккаунты", "Имена пользователей в мессенджерах и сетях.", "@ivanov → Handle1", False),
        ("IP_ADDRESS", "IP-адреса", "IPv4-адреса.", "10.0.0.5 → Ip1", True),
    )),
    ("finance", "Финансы и секреты", "Утечка этих данных необратима, поэтому они скрываются всегда.", (
        ("CARD", "Банковские карты", "Номера карт.", "4276 3800 1234 5675 → Card1", False),
        ("SECRET", "Пароли и ключи", "Пароли, токены, ключи доступа.", "password=… → Secret1", False),
    )),
)
KIND_LABELS = {code: label for _, _, _, items in KIND_GROUPS for code, label, *_ in items}
# Вид данных выключается переключателем с этим именем; для стран это прежняя настройка `countries`.
def kind_key(code: str) -> str:
    return {"COUNTRY": "countries", "BUSINESS": "business_confidential"}.get(code, f"hide_kind_{code}")


# Прежние крупные переключатели → виды, которые они выключали. Старые значения переносятся на новые ключи.
LEGACY_KEYS: dict[str, tuple[str, ...]] = {
    "hide_names": ("PERSON",), "hide_orgs": ("ORG", "PROJECT"), "hide_places": ("CITY", "REGION", "ADDRESS"),
    "hide_emails": ("EMAIL",), "hide_phones": ("PHONE",), "hide_domains": ("DOMAIN",), "hide_usernames": ("USERNAME",),
    "hide_ips": ("IP_ADDRESS",), "hide_birthdates": ("BIRTH_DATE",), "hide_tax_ids": ("INN", "OGRN", "KPP", "BIK"),
    "hide_contracts": ("CONTRACT",), "hide_plates": ("VEHICLE_PLATE",), "hide_other_pii": ("PII",),
}


def _kind_options() -> list[Option]:
    out = []
    for _, group_label, _, items in KIND_GROUPS:
        for code, label, hint, example, advanced in items:
            if code in PROTECTED_KINDS or code == "BUSINESS":     # коммерческие данные включает прежний `business_confidential`
                continue
            out.append(Option(kind_key(code), "bool", code != "BUSINESS", "categories", "Скрывать страны" if code == "COUNTRY" else label, hint, example, "chat", advanced,
                              (code,), group=group_label))
    return out


OPTIONS: tuple[Option, ...] = (
    # -- общие -----------------------------------------------------------------
    Option("theme", "choice", 0, "general", "Тема оформления", "Следовать теме компьютера или выбрать светлую или тёмную вручную. Значок программы меняется вместе с темой.",
           scope="global", group="Внешний вид", choices=((0, "Как в системе"), (1, "Светлая"), (2, "Тёмная"))),
    Option("strict", "bool", False, "general", "Скрывать и сомнительные слова",
           "Аббревиатуры и иностранные слова, которые могут оказаться названиями. Могут скрыться и обычные термины.",
           "Альфа-Групп, Ромашка", group="Распознавание"),
    Option("learn_names", "bool", True, "general", "Узнавать имена по тексту документа",
           "Полное ФИО в одном месте помогает найти «Иванов И.И.» и «Ивану» в другом.", "Иванов Иван Петрович → Иванов И.П.",
           advanced=True, group="Распознавание"),
    Option("ner_candidates", "bool", True, "general", "Искать незнакомые имена нейросетью (русский)",
           "Локальная модель (без интернета) находит русские имена, которых нет в справочниках. Полные имена скрываются сами, одиночные фамилии попадают в список проверки. Без установленной модели не действует: в отчёте появится пометка, обычный поиск продолжает работать.",
           "Свидетель Тарнов → предложено проверить", advanced=True, group="Распознавание"),
    Option("business_confidential", "bool", False, "categories", "Коммерческие данные",
           "Строки про выручку, себестоимость, маржу, KPI, бонусы и зарплату целиком. По умолчанию выключено: может скрыть нужное для задачи.",
           "Выручка за год 4 млн руб. → Biz1", group="Организации"),
    Option("neutral_names", "bool", True, "general", "Нейтральные названия файлов",
           "Имя результата не раскрывает содержимое; исходное имя хранится для возврата.", "Договор_Ромашка.docx → Файл1 (обезличено).docx",
           group="Замена"),
    # -- категории: по одному переключателю на вид данных, собираются из KIND_GROUPS ------------
    *_kind_options(),
    # -- списки слов (отдельный экран) -------------------------------------------
    Option("hide_terms", "list", [], "words", "Всегда скрывать", "По одному в строке: проекты, клиенты, внутренние названия.",
           "Проект «Орион»"),
    Option("keep_terms", "list", [], "words", "Никогда не скрывать", "По одному в строке: слова, ошибочно принятые за имена. "
           "Слово оставляет открытым только его самого; чтобы не скрывать полное имя, впишите его целиком. "
           "На пароли, карты, счета и паспорта это не действует.", "Альфа"),
    # -- файлы -------------------------------------------------------------------
    Option("numbers", "bool", False, "files", "Заменять числа в Excel", "Даты и годы не меняются; результаты формул очищаются.",
           "1 250 000 → 4 871 392", group="Excel"),
    Option("finance_numbers", "bool", False, "files", "Скрывать суммы в Excel (масштабирование)",
           "Суммы в финансовой модели умножаются на один секретный коэффициент, формулы остаются рабочими, возврат восстанавливает настоящие числа. "
           "Скрываются величины, но не соотношения: если известна одна настоящая сумма, коэффициент можно вычислить.",
           "1 250 000 → 872 311", group="Финансы и числа"),
    Option("finance_scale_per_sheet", "bool", False, "files", "Свой коэффициент для каждого листа",
           "Только если формулы не ссылаются на суммы другого листа. Сложнее вычислить коэффициент по одной известной сумме.",
           group="Финансы и числа", advanced=True),
    Option("finance_text_amounts", "bool", False, "files", "Суммы в тексте ячеек и примечаний",
           "«1,2 млн ₽», «$4.5M» в подписях, примечаниях и заголовках диаграмм заменяются тем же коэффициентом.",
           "1,2 млн ₽ → 0,85 млн ₽", group="Финансы и числа", advanced=True),
    Option("finance_on_formula_conflict", "choice", "exclude", "files", "Если формулу нельзя сохранить рабочей",
           "Например, произведение двух сумм или сумма плюс число. «Оставить видимыми» не маскирует суммы, от которых зависит формула, и предупреждает; "
           "«Не выдавать файл» отказывается его обезличивать.", scope="global", group="Финансы и числа", advanced=True,
           choices=(("exclude", "Оставить суммы видимыми и предупредить"), ("block", "Не выдавать файл"))),
    Option("scrub_metadata", "bool", True, "files", "Очищать свойства файла",
           "Автор, организация и название из свойств документа, миниатюры и встроенные предпросмотры.", "Автор: Иванов И. → Meta1",
           group="Все форматы"),
    Option("image_mode", "choice", "replace", "files", "Картинки и сканы",
           "По умолчанию каждая картинка заменяется целиком меткой Image1, Image2 и так далее, а оригинал хранится зашифрованным и возвращается при восстановлении: "
           "лица, подписи, печати, рукописный текст и снимки экрана распознать надёжно нельзя. Режим «Закрасить текст» оставляет картинку и закрашивает прочитанные данные; "
           "это менее безопасный режим без гарантии: логотип и всё нераспознанное остаются видимыми, просмотрите результат сами.",
           group="Все форматы",
           choices=(("replace", "Заменять картинку целиком"), ("redact_text", "Закрасить текст, картинку оставить (менее безопасно)"))),
    Option("ocr_images", "bool", True, "files", "Скрывать данные на изображениях (режим «Закрасить текст»)",
           "Действует только в режиме «Закрасить текст, оставить картинку»: текст на картинках распознаётся и закрашивается. Оригинал картинки хранится зашифрованным для возврата.",
           group="Все форматы"),
    Option("image_brand_policy", "choice", "paint", "files", "Логотипы и названия на картинках",
           "Крупный текст на картинке, похожий на название компании или логотип, но не опознанный как данные: закрасить, только предупредить или не искать. "
           "Закрашенное название получает метку Company и возвращается при восстановлении.",
           scope="global", group="Все форматы",
           choices=(("paint", "Закрашивать"), ("warn", "Только предупреждать"), ("off", "Не искать"))),
    Option("inspect_embedded", "bool", True, "files", "Проверять вложенные файлы",
           "Если внутри документа есть другой файл, программа предупредит, что он не обезличен.", group="Все форматы", advanced=True),
    # -- хранение ----------------------------------------------------------------
    Option("keep_originals", "bool", True, "storage", "Хранить оригиналы в новых чатах",
           "Зашифрованы ключом этого компьютера. Нужны, чтобы пересобрать файл после правок в таблице замен.", scope="global"),
    Option("retention_days", "choice", 180, "storage", "Срок хранения соответствий", "После срока соответствия удаляются, файлы вернуть уже нельзя.",
           scope="global", choices=((30, "30 дней"), (90, "90 дней"), (180, "180 дней"), (365, "1 год"), (0, "Пока не очищу"))),
    Option("restored_retention_days", "choice", 30, "storage", "Срок хранения возвращённых файлов",
           "Возвращённые файлы содержат настоящие данные, поэтому срок короче.", scope="global",
           choices=((7, "7 дней"), (30, "30 дней"), (90, "90 дней"), (0, "Пока не удалю"))),
    Option("retain_secrets_for_restore", "bool", False, "storage", "Сохранять пароли и ключи для возврата",
           "По умолчанию пароли и ключи заменяются без возможности вернуть. Если включить, они хранятся в зашифрованном хранилище.",
           scope="global", advanced=True),
)

BY_KEY = {o.key: o for o in OPTIONS}
CHAT_BOOLS = tuple(o.key for o in OPTIONS if o.kind == "bool" and o.scope == "chat")
CHAT_LISTS = ("hide_terms", "keep_terms")
CATEGORY_KEYS = tuple(o.key for o in OPTIONS if o.kinds)
# Эти значения живут в Settings под тем же именем; остальные (категории) превращаются в disabled_kinds.
SETTINGS_BOOLS = ("finance_numbers", "finance_scale_per_sheet", "finance_text_amounts",
                  "finance_on_formula_conflict", "numbers", "strict", "countries", "neutral_names", "learn_names", "ner_candidates", "business_confidential",
                  "scrub_metadata", "inspect_embedded", "image_mode", "ocr_images", "image_brand_policy", "retain_secrets_for_restore")


PRESETS: dict[str, dict] = {
    "recommended": {"label": "Рекомендуемый", "hint": "Сбалансированный режим: скрывается всё распознанное, спорные слова остаются.",
                    "values": {o.key: o.default for o in OPTIONS if o.scope == "chat" and o.kind == "bool"}},
    "maximum": {"label": "Максимальная приватность", "hint": "Скрывается всё, что программа умеет находить, включая сомнительные слова, числа Excel и коммерческие данные. "
                "Оригиналы не хранятся, соответствия живут 30 дней.",
                "values": {**{o.key: True for o in OPTIONS if o.scope == "chat" and o.kind == "bool"},
                           "keep_originals": False, "retention_days": 30, "restored_retention_days": 7}},
}


def defaults() -> dict:
    return {o.key: (list(o.default) if o.kind == "list" else o.default) for o in OPTIONS}


def coerce(option: Option, value):
    """Приводит значение к типу пункта; неверное значение — ValueError."""
    if option.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"«{option.label}»: ожидается включено или выключено")
    if option.kind == "list":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"«{option.label}»: ожидается список")
        return list(dict.fromkeys(str(t).strip() for t in value if str(t).strip()))
    if option.kind == "choice":
        allowed = [c[0] for c in option.choices]
        if isinstance(value, bool) or value not in allowed:
            raise ValueError(f"«{option.label}»: недопустимое значение")
        return value
    if option.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"«{option.label}»: ожидается число")
        return value
    raise ValueError(option.key)


def validate_patch(patch: dict, scope: str = "global") -> dict:
    """Проверяет набор изменений. Неизвестные пункты и пункты не того уровня отвергаются, а не молча пропускаются."""
    clean = {}
    for key, value in expand_legacy(patch).items():
        option = BY_KEY.get(key)
        if option is None:
            continue                    # служебные ключи страницы (ширина панелей и т. п.) проверяет вызывающий
        if scope == "chat" and option.scope != "chat":
            raise ValueError(f"«{option.label}» меняется только в общих настройках")
        if value is None and scope == "chat":
            clean[key] = None           # сброс переопределения
            continue
        clean[key] = coerce(option, value)
    return clean


def reconcile_lists(hide: list[str], keep: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Слово не может быть в обоих списках: «всегда скрывать» сильнее. Возвращает (hide, keep, снятые из keep)."""
    hidden = {t.casefold() for t in hide}
    dropped = [t for t in keep if t.casefold() in hidden]
    return hide, [t for t in keep if t.casefold() not in hidden], dropped


def expand_legacy(values: dict) -> dict:
    """Прежние крупные переключатели (`hide_places`, `hide_tax_ids` ...) превращаются в переключатели видов.
    Явно заданное значение вида сильнее перенесённого."""
    if not any(k in values for k in LEGACY_KEYS):
        return values
    out = {k: v for k, v in values.items() if k not in LEGACY_KEYS}
    for legacy, codes in LEGACY_KEYS.items():
        if legacy in values:
            for code in codes:
                out.setdefault(kind_key(code), values[legacy])
    return out


def disabled_kinds(values: dict) -> tuple[str, ...]:
    """Виды данных, выключенные переключателями. Защищённые виды сюда не попадают никогда."""
    values = expand_legacy(values)
    off: list[str] = []
    for option in OPTIONS:
        if option.kinds and values.get(option.key) is False:
            off.extend(k for k in option.kinds if k not in PROTECTED_KINDS)
    return tuple(dict.fromkeys(off))


def resolve(prefs: dict, chat: dict | None = None, run: dict | None = None) -> dict:
    """Итоговые значения: запуск > чат > общие настройки > умолчания. Списки слов объединяются на всех уровнях."""
    base = defaults()
    out = dict(base)
    prefs = expand_legacy(prefs or {})
    for source in (prefs, chat and expand_legacy(chat) or {}, run and expand_legacy(run) or {}):
        for key, value in source.items():
            option = BY_KEY.get(key)
            if option is None or value is None:
                continue
            if option.kind == "list":
                out[key] = list(dict.fromkeys([*out[key], *coerce(option, value)]))
            elif source is prefs or option.scope == "chat":
                try:
                    out[key] = coerce(option, value)
                except ValueError:
                    pass                # испорченное значение в хранилище не должно ронять обработку
    # Решения чата сильнее общих списков: слово, оставленное в чате, не скрывается там, даже если оно в общем «Всегда скрывать».
    decided = (run or {}).get("term_decisions") or {}
    for mine, opposite in (("keep_terms", "hide_terms"), ("hide_terms", "keep_terms")):
        taken = {str(t).casefold() for t in decided.get(mine) or []}
        if taken:
            out[opposite] = [t for t in out[opposite] if t.casefold() not in taken]
    out["hide_terms"], out["keep_terms"], _ = reconcile_lists(out["hide_terms"], out["keep_terms"])
    return out


def public_schema() -> dict:
    return {
        "sections": [{"id": s, "label": l} for s, l in SECTIONS],
        "options": [{"key": o.key, "type": o.kind, "default": o.default, "section": o.section, "label": o.label,
                     "hint": o.hint, "example": o.example, "scope": o.scope, "advanced": o.advanced, "group": o.group,
                     "choices": [[v, t] for v, t in o.choices]} for o in OPTIONS],
        "groups": [{"id": gid, "label": label, "hint": hint,
                    "items": [{"code": code, "key": None if code in PROTECTED_KINDS else kind_key(code), "label": klabel, "hint": khint,
                               "example": example, "locked": code in PROTECTED_KINDS, "advanced": advanced}
                              for code, klabel, khint, example, advanced in items]}
                   for gid, label, hint, items in KIND_GROUPS],
        "presets": {k: {"label": v["label"], "hint": v["hint"]} for k, v in PRESETS.items()},
        "locked": [{"label": "Пароли и ключи", "hint": "Всегда заменяются. Выключить нельзя."},
                   {"label": "Карты, банковские счета, паспорта, СНИЛС, водительские удостоверения, полисы",
                    "hint": "Всегда заменяются. Список «Никогда не скрывать» на них не действует."}],
    }
