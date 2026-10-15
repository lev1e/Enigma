"""Правка docx / pptx / xlsx через ИИ-чат (P2B): контекст для модели, разбор ответа, проверка патча, сводка для карточек.

Модель получает компактный текст со структурой файла (адреса, отпечатки, роли) и коротко сформулированные правила. Отвечает ОДНИМ
JSON-патчем в блоке ```json. Патч проверяется движком `docedit` (apply_patch на копии), в файл ничего не пишется, пока пользователь не
нажал «Применить». Весь этот модуль работает только с байтами файла выбранной версии (обезличенной или исходной) и ничего не отправляет.
"""

from __future__ import annotations

import json
import re

from . import docedit
from .docedit import PatchRejected

OFFICE_EXTS = (".pptx", ".docx", ".xlsx")
MAX_SELECTED = 20
ADDR_RE = re.compile(r"[^\s\x00-\x1f]{1,120}")

# Слова про оформление и про содержимое: по ним выбирается, нужен ли модели настоящий текст (full) или только заглушки (stub).
DESIGN_RE = re.compile(r"(шрифт|цвет|размер|выровн|жирн|курсив|отступ|интервал|межстроч|сдвин|подвин|перемест|увелич|уменьш|"
                       r"ширин|высот|колонк|столбц|оформлен|стил[ьею]|макет|layout|формат|рамк|фон|красив|крупн|мельч|"
                       r"font|color|colour|size|align|bold|italic|style|margin|width|height|move|resize)", re.I)
TEXTY_RE = re.compile(r"(перепиш|сократ|исправ|поправ|замен|переформулир|переведи|добавь|допиш|удали|убери|текст|слов|фраз|"
                      r"заголовок на|напиш|дополни|значени|формул|комментар|rewrite|shorten|translate|replace|add|delete|text)", re.I)

STYLE_HELP = ("set_style{at,font?,size?,bold?,italic?,color?(\"#\" и 6 цифр hex),alignment?(left|center|right|justify),"
              "space_before?,space_after?,line_spacing?}")
FORMAT_OPS = {
    "pptx": ("replace_text{at,expect,text}; insert_paragraph{after,text}; delete{at,expect}; comment{at,text}; " + STYLE_HELP +
             "; move_shape{at,x,y} (pt); resize_shape{at,w,h} (pt); align{ats:[..],mode:left|center|right|top|middle|bottom,to?:slide|first}; "
             "set_layout{slide,layout} (номер макета из списка); col_width{at,col,width} (таблица)"),
    "docx": ("replace_text{at,expect,text}; insert_paragraph{after,text}; delete{at,expect}; comment{at,text}; " + STYLE_HELP +
             "; paragraph_style{at,style} (номер стиля из списка); col_width{at,col,width} (таблица, pt)"),
    "xlsx": ("replace_text{at,expect,text} (текстовая ячейка); set_cell{at,expect,value|formula}; comment{at,text}; "
             "number_format{at,format} (ячейка или диапазон ячеек, адрес с именем листа); col_width{at (адрес столбца или столбцов с именем листа),width}"),
}


def is_office(name: str) -> bool:
    return (name or "").lower().endswith(OFFICE_EXTS)


def fmt_of(name: str) -> str:
    return (name or "").lower().rsplit(".", 1)[-1]


def guess_mode(text: str) -> tuple[str, bool]:
    """(режим outline, нужен ли блок оформления). Только оформление без слов про содержимое: заглушки вместо текста, иначе полный текст."""
    design = bool(DESIGN_RE.search(text or ""))
    stub = design and not TEXTY_RE.search(text or "")
    return ("stub" if stub else "full"), design


def clean_selection(raw) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError("Некорректный список выделенных элементов")
    out = [x for x in dict.fromkeys(raw) if ADDR_RE.fullmatch(x)]
    if len(out) > MAX_SELECTED:
        raise ValueError(f"Выделено больше {MAX_SELECTED} элементов: оставьте самое нужное")
    return out


# ---- контекст для модели -------------------------------------------------------------------------------------

def _style_bits(st: dict) -> str:
    # font names are Latin words the outgoing guard would take for company names: the model is told sizes and flags only
    return ", ".join(f"{k}={v}" for k, v in (st or {}).items() if v not in (None, "", False) and k != "font")


def aliases(o: dict) -> dict:
    """Layout and paragraph-style names are Latin words the outgoing guard flags as possible company names, so the model sees
    numbers (`макет 2`, `стиль 5`) and answers with them; `unalias` turns them back into names before the patch is validated."""
    lay = {str(i + 1): l["name"] for i, l in enumerate(o.get("layouts") or [])}
    sty = {str(i + 1): n for i, n in enumerate((o.get("styles") or [])[:60])}
    return {"layout": lay, "style": sty}


def unalias(patch: dict, al: dict) -> dict:
    """Maps numbered layouts / styles in `set_layout` and `paragraph_style` ops back to names. Unknown numbers stay and fail validation."""
    out = []
    for op in patch.get("ops") or []:
        if isinstance(op, dict) and op.get("op") == "set_layout" and str(op.get("layout")) in al["layout"]:
            op = dict(op, layout=al["layout"][str(op["layout"])])
        elif isinstance(op, dict) and op.get("op") == "paragraph_style" and str(op.get("style")) in al["style"]:
            op = dict(op, style=al["style"][str(op["style"])])
        out.append(op)
    return dict(patch, ops=out)


def render_outline(o: dict, selected: list[str] | None = None, design: bool = False) -> str:
    """Структура файла как текст: контейнер, затем элементы `[адрес] fp=... роль: текст`."""
    fmt = o.get("format", "")
    lines = [f"ДОКУМЕНТ ({fmt}), режим текста: {'заглушки' if o.get('text_mode') == 'stub' else 'полный'}"]
    if o.get("slide_size"):
        lines.append(f"Слайд: {o['slide_size']['w']:g} x {o['slide_size']['h']:g} pt")
    if o.get("page"):
        lines.append(f"Страница: {o['page']['w']:g} x {o['page']['h']:g} pt")
    al = aliases(o)
    if al["layout"]:
        lines.append("Макеты (в операции пиши номер): " + ", ".join(f"макет {k}" for k in al["layout"]))
    if al["style"] and fmt == "docx":
        lines.append("Стили абзацев (в операции пиши номер): " + ", ".join(f"стиль {k}" for k in al["style"]))
    lay_no = {v: k for k, v in al["layout"].items()}
    for c in o["containers"]:
        head = f"[{c['addr']}] {c['kind']}" + (f" заголовок: {c['title']}" if c.get("title") and c["title"] != c["addr"] else "") + (f", макет {lay_no[c['layout']]}" if c.get("layout") in lay_no else "")
        lines.append(head + (f" (элементов скрыто: {c['omitted']})" if c.get("summary_only") else ""))
        for e in c["elements"]:
            if e["kind"] == "shape":
                geom = e.get("geom")
                extra = f" {geom['x']:g},{geom['y']:g} {geom['w']:g}x{geom['h']:g}" if design and geom else ""
                tail = "" if e.get("editable", True) else "  <не редактируется>"
                lines.append(f"  [{e['addr']}] фигура {e.get('type', '')}/{e.get('role', '')}{extra}{tail}")
                continue
            if not e.get("editable", True):
                lines.append(f"  [{e['addr']}] <{e.get('label') or e.get('reason') or 'объект'}: не редактируется>")
                continue
            st = _style_bits(e.get("style")) if design else ""
            text = (e.get("text") or "").replace("\n", " ")
            lines.append(f"  [{e['addr']}] fp={e.get('fp', '')} {e.get('role', '')}{(' {' + st + '}') if st else ''}: {text}")
    if selected:
        lines.append("ВЫДЕЛЕНО ПОЛЬЗОВАТЕЛЕМ: " + ", ".join(selected))
    return "\n".join(lines)


def build_context(data: bytes, name: str, text: str, selected: list[str]) -> tuple[str, dict]:
    """(текст контекста, служебные сведения). Бросает PatchRejected, если структуру нельзя разобрать или она слишком велика."""
    mode, design = guess_mode(text)
    o = docedit.outline(data, name, text=mode, selected=selected or None, neighbours=1)
    return render_outline(o, selected, design or mode == "stub"), {"mode": mode, "design": design,
                                                                  "elements": o.get("stats", {}).get("elements", 0)}


def system_prompt(fmt: str) -> str:
    return ("Ты редактируешь файл (" + fmt + ") по просьбе пользователя. Ниже в сообщении структура файла: у каждого элемента адрес в "
            "квадратных скобках и отпечаток fp. Ответь одним патчем в блоке ```json (слово json после трёх апострофов) и больше ничего "
            "в блоке. Формат: {\"v\":1,\"note\":\"кратко что сделано\",\"ops\":[...]}. Доступные операции: " + FORMAT_OPS.get(fmt, "") + ". "
            "Правила: меняй только элементы из структуры; адреса и отпечатки (expect) копируй точно как в структуре; "
            "метки вида Name1, Phone2 не изменяй и не придумывай новых, копируй их в текст как есть; не добавляй ничего, о чём не просили; "
            "если пользователь не просит менять файл или правка невозможна, не выдумывай, а ответь обычным текстом без блока. Пояснение для пользователя пиши вне блока json.")


# ---- ответ модели --------------------------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json|JSON)?[ \t]*\r?\n(.*?)```", re.S)


def extract_patch(raw: str) -> dict:
    """Один JSON-объект из ответа. Не найден или не разобран: ValueError с русской причиной."""
    blocks = [m.group(1).strip() for m in _FENCE.finditer(raw or "")]
    cand = next((b for b in blocks if b.startswith("{")), None)
    if cand is None and (raw or "").strip().startswith("{"):
        cand = raw.strip()
    if cand is None:
        raise ValueError("ИИ ответил в неверном формате. Правки не предложены.")
    try:
        patch = json.loads(cand)
    except ValueError:
        raise ValueError("ИИ ответил в неверном формате. Правки не предложены.") from None
    if not isinstance(patch, dict):
        raise ValueError("ИИ ответил в неверном формате. Правки не предложены.")
    return patch


def reason(exc: PatchRejected) -> str:
    where = f" (операция {exc.op_index + 1}" + (f", {exc.at}" if exc.at else "") + ")" if exc.op_index is not None else ""
    return "Правка не применена: " + exc.text.rstrip(".") + where + ". Файл остался прежним."


def check_secret_mask(patch: dict, mask: str) -> None:
    """В режиме исходных данных модель видела «[секрет удалён]» вместо пароля: подставлять эту маску в файл нельзя."""
    for i, op in enumerate(patch.get("ops") or []):
        if isinstance(op, dict) and any(isinstance(v, str) and mask in v for v in op.values()):
            raise PatchRejected("secret_mask", "В тексте правки осталась маска вместо пароля или ключа", i, str(op.get("at") or op.get("after") or ""))


def subset(patch: dict, indices) -> dict:
    """Патч из выбранных операций (по индексам исходного патча). Комментарии в файл не пишутся, поэтому в подмножество не входят."""
    ops = patch["ops"]
    chosen = list(range(len(ops))) if indices == "all" else sorted({int(i) for i in indices})
    if not chosen or any(i < 0 or i >= len(ops) for i in chosen):
        raise ValueError("Выберите правки из списка")
    picked = [ops[i] for i in chosen if ops[i].get("op") != "comment"]
    if not picked:
        raise ValueError("Это комментарий: в файл он не записывается")
    return {"v": 1, "note": str(patch.get("note", ""))[:300], "ops": picked}


def cards(base: bytes, new: bytes, patch: dict, name: str) -> dict:
    """Карточки «было -> стало» (русские), комментарии и адреса для подсветки в панели."""
    summ = docedit.diff_summary(base, new, patch, name)
    items = [{"index": it["index"], "op": it["op"], "at": it.get("at", ""), "text": it["text"],
              "was": it.get("was") if isinstance(it.get("was"), (str, type(None))) else None,
              "now": it.get("now") if isinstance(it.get("now"), (str, type(None))) else None,
              "comment": it["op"] == "comment"} for it in summ["items"]]
    return {"items": items, "hint": summ["preview_hint"], "note": str(patch.get("note", ""))[:300]}


def unalias_for(base: bytes, name: str, patch: dict) -> dict:
    """Номера макетов и стилей из ответа модели -> имена (по структуре той же версии файла)."""
    return unalias(patch, aliases(docedit.outline(base, name, text="stub")))


def validate(base: bytes, name: str, patch: dict, secret_mask: str | None = None) -> dict:
    """Проверка всего патча на копии: карточки по каждой операции. PatchRejected = ничего не предлагать."""
    if secret_mask:
        check_secret_mask(patch, secret_mask)
    new, _rep = docedit.apply_patch(base, name, patch)
    return cards(base, new, patch, name)
