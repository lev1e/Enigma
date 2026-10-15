"""Необязательный источник кандидатов в имена людей: русская NER-модель natasha (slovnet).

Только для списка проверки (REVIEW): модель никогда не заменяет текст сама. Что взято из отчёта
docs/superpowers/ner-experiment.md, раздел 7:
  * только метка PERSON, достоверность не ниже MIN_CONF (апостериорная вероятность тега по прямому-обратному
    проходу CRF, минимум по токенам фрагмента);
  * таблицы, CSV, разметка и короткие «кодовые» фрагменты пропускаются;
  * длинный текст режется на куски по CHUNK символов (память около 0,5 ГБ вместо 2 ГБ);
  * принятое имя превращается в литерал: отмечаются ВСЕ вхождения этой строки в тексте, а не одно предложение.

Если natasha не установлена или не загрузилась, функции молча возвращают пустой список (признак выключен).
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import OrderedDict
from typing import Callable

MIN_CONF = 0.7
CHUNK = 20_000
AUTO_CONF = 0.9                    # полное имя с такой достоверностью и выше скрывается само (W7b: точность на выборке ниже)
MAX_TEXT = 50_000_000              # S8B: жёсткий предел безопасности (fail-soft с заметкой), раньше 400 000 пропускало тихо
OVERLAP = 400                      # перекрытие окон при жёстком разрезе (без точки/перевода строки): имя не режется
MIN_TEXT = 12                      # короче — это почти всегда ячейка или метка, а не фраза
_CACHE_MAX = 256

_lock = threading.Lock()
_model = None                      # None — ещё не пробовали; False — недоступна
_cache: OrderedDict[str, tuple[tuple[int, int, float], ...]] = OrderedDict()
_piece_cache: OrderedDict[bytes, tuple[tuple[int, int, float], ...]] = OrderedDict()   # окно -> спаны (повторяющиеся строки таблиц)
_PIECE_CACHE_MAX = 64
_notes: list[str] = []             # видимые заметки задания: сервис забирает их через take_notes()
_CAPWORD = re.compile(r"[А-ЯЁ][а-яё]|[А-ЯЁ]\.")      # без такого слова _clean не примет ни один фрагмент окна

_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT_OR_CYR = re.compile(r"[^\W\d_]")
_MARKUP = re.compile(r"<[a-zA-Z/!][^>]*>|\{\{|\}\}|\[\[|\]\]|\|\s*\w+\s*=|^#{1,6} |```|\\\w+\{", re.M)
# S9G: разметка вырезается пробелами по месту (смещения те же); целиком документ отвергается, только если почти вся разметка.
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_LINK_FILE = re.compile(r"\[\[\s*(?:Файл|File|Image|Изображение|Категория|Category|Служебная|Special):[^\n]*", re.I)
_LINK_HEAD = re.compile(r"\[\[[^\[\]|\n]*\|")                    # [[цель|  — цель ссылки не проза, подпись остаётся
_BRACKETS = re.compile(r"\[\[|\]\]|\{\{|\}\}")
_URL = re.compile(r"(?:https?://|ftp://|www\.)[^\s<>\]\)\"']+", re.I)
_TAG = re.compile(r"<[a-zA-Z/!][^>]*>")
_PARAM = re.compile(r"^[ \t]*\|[ \t]*[\w\- ]{1,40}?[ \t]*=", re.M)
_TEX = re.compile(r"\\\w+\{")
MARKUP_MAX_SHARE = 0.75     # S9G: доля вырезанных непробельных знаков выше этой — документ разметка/код, модель не запускается
MARKUP_MIN_TEXT = 2000      # короткий кусок с разметкой (ячейка, фрагмент тега) по-прежнему отвергается целиком
TEMPLATE_MAX = 30_000       # шаблон {{...}} длиннее — режем только скобки, не содержимое
_mask_memo: OrderedDict[tuple[int, int], tuple[str, float]] = OrderedDict()
_LOG = logging.getLogger("anonymizer.ner")
_STOP = frozenset(w.casefold() for w in (
    "Что", "Как", "Где", "Кто", "Это", "См", "Оп", "Пир", "Ге", "Доктор", "Министр", "Министром", "Президент", "Президента", "Президентом",
    "Директор", "Директора", "Мэр", "Мэром", "Мэра", "Губернатор", "Губернатора", "Профессор", "Профессора", "Академик", "Академика",
    "Генерал", "Полковник", "Коллежский", "Стих", "Свидетель", "Заявитель", "Истец", "Ответчик", "Господин", "Госпожа", "Товарищ", "Святой"))
_LABEL = re.compile(r"[A-Za-z]+\d+")
_ADJ_END = ("ический", "ическая", "ическое", "ические", "ённое", "емое", "ное", "ная", "ные", "ных", "ьная", "ьное", "тельная", "ственные")
_NAME_INITIAL = re.compile(r"^[А-ЯЁ]\.$")
_NAME_TOKEN = re.compile(r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ]?[а-яё]+)*\.?$|^[А-ЯЁ]\.$")


def available() -> bool:
    return _load() is not False


def installed() -> bool:
    """Дёшево, без загрузки модели: можно ли вообще ждать работы нейросети (для окна настроек)."""
    if _model is False:
        return False
    import importlib.util
    return importlib.util.find_spec("natasha") is not None


def _load():
    """Модель создаётся один раз; любой сбой импорта или загрузки отключает признак до перезапуска."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            import numpy as np
            from natasha import NewsEmbedding, NewsNERTagger
            tagger = NewsNERTagger(NewsEmbedding())
            infer = tagger.infer
            state = {"probs": []}
            per_ids = np.array([i for i, t in enumerate(infer.decoder.tags_vocab.items) if "PER" in str(t)], dtype="int64")
            has_per = lambda seq: bool(np.isin(seq, per_ids).any())     # noqa: E731

            def process(inputs):
                for inp in inputs:
                    pred = infer.model(inp.word_id, inp.shape_id, inp.pad_mask)
                    em = np.asarray(pred, dtype="float64")
                    trans = np.asarray(infer.model.head.crf.transitions.array, dtype="float64")
                    mask = np.asarray(~inp.pad_mask)
                    for b, seq in enumerate(_decode(infer.model.head.crf.transitions.array, pred, mask)):
                        n = int(mask[b].sum())
                        # S8B: вероятности нужны только фрагментам PER; в окне без PER проход вперёд-назад не нужен
                        state["probs"].append(_marginals(em[b, :n], trans, seq) if has_per(seq) else [])
                        yield seq

            object.__setattr__(infer, "process", process)
            _model = (tagger, state)
        except Exception as ex:         # noqa: BLE001 — модуль необязательный, падать из-за него нельзя
            _model = False
            _LOG.warning("NER (natasha) недоступен, работают только правила: %s: %s", type(ex).__name__, str(ex)[:120])
    return _model


def _decode(trans, emissions, mask):
    """Витерби для батча из одной последовательности: те же сложения и argmax, что в slovnet CRF.decode (теги совпадают
    бит в бит), но без np.indices на каждом шаге."""
    import numpy as np
    batch, seq_len, k = emissions.shape
    em = emissions.swapaxes(1, 0)
    mk = mask.swapaxes(1, 0)
    tr = trans
    history = []
    score = em[0]
    cols = np.arange(k)
    rows = np.arange(batch)[:, None]
    for i in range(1, seq_len):
        sc = score.reshape(batch, k, 1) + tr + em[i].reshape(batch, 1, k)
        idx = sc.argmax(-2)
        sc = sc[rows, idx, cols]
        score = np.where(mk[i].reshape(batch, 1), sc, score)
        history.append(idx)
    sizes = mk.sum(0) - 1
    out = []
    for b in range(batch):
        best = score[b].argmax()
        tags = [best]
        for idx in reversed(history[:sizes[b]]):
            best = idx[b][best]
            tags.append(best)
        tags.reverse()
        out.append(np.array(tags))
    return out


def _marginals(em, trans, seq):
    """Вероятность выбранного тега в каждой позиции (прямой-обратный проход по CRF).
    S8B: прямой и обратный проходы идут в одном цикле на стеке (2, k, k): арифметика та же (logsumexp, те же слагаемые),
    шагов Python вдвое меньше, буферы выделены один раз."""
    import numpy as np
    n, k = em.shape
    if n == 0:
        return []
    al = np.empty((n, k))
    be = np.zeros((n, k))
    al[0] = em[0]
    t2 = np.stack([trans, trans.T])                    # [0]: [пред, тек]; [1]: [след, тек]
    p = np.empty((2, k))
    p[0] = em[0]
    p[1] = em[n - 1]                                   # em[n-1] + be[n-1], be[n-1] = 0
    x = np.empty((2, k, k))
    m = np.empty((2, 1, k))
    r = np.empty((2, k))
    e = np.zeros((2, k))
    for t in range(n - 1):
        np.add(p[:, :, None], t2, out=x)
        np.max(x, axis=1, keepdims=True, out=m)
        np.subtract(x, m, out=x)
        np.exp(x, out=x)
        np.sum(x, axis=1, out=r)
        np.log(r, out=r)
        np.add(r, m[:, 0, :], out=r)                   # r[0] = lse по предыдущему, r[1] = be[n-2-t]
        be[n - 2 - t] = r[1]
        e[0] = em[t + 1]
        e[1] = em[n - 2 - t]
        np.add(r, e, out=p)
        al[t + 1] = p[0]
    z = np.log(np.exp(al[-1] - al[-1].max()).sum()) + al[-1].max()
    idx = np.arange(n)
    sq = np.asarray(seq)[:n]
    return np.exp(al[idx, sq] + be[idx, sq] - z).tolist()


def _blank(chars: list[str], a: int, b: int) -> None:
    for i in range(a, b):
        if not chars[i].isspace():
            chars[i] = " "


def _templates(text: str):
    """Спаны {{...}} с учётом вложенности (линейный проход по скобкам); непарные скобки пропускаются."""
    stack: list[int] = []
    for m in re.finditer(r"\{\{|\}\}", text):
        if m.group() == "{{":
            stack.append(m.start())
        elif stack:
            a = stack.pop()
            if not stack:
                yield a, m.end()


def _mask_markup(text: str) -> tuple[str, float]:
    """(текст той же длины, где разметка заменена пробелами; доля вырезанных непробельных знаков)."""
    key = (len(text), hash(text))
    hit = _mask_memo.get(key)
    if hit is not None:
        return hit
    chars = list(text)
    for m in _FENCE.finditer(text):
        _blank(chars, m.start(), m.end())
    for a, b in _templates(text):
        if b - a <= TEMPLATE_MAX:
            _blank(chars, a, b)
    for rx in (_LINK_FILE, _LINK_HEAD, _URL, _TAG, _PARAM, _TEX, _BRACKETS):
        for m in rx.finditer(text):
            _blank(chars, m.start(), m.end())
    masked = "".join(chars)
    total = sum(1 for c in text if not c.isspace())
    cut = sum(1 for a, b in zip(text, masked) if a != b and not a.isspace())
    out = (masked, cut / total if total else 1.0)
    _mask_memo[key] = out
    if len(_mask_memo) > 2:
        _mask_memo.popitem(last=False)
    return out


def working_text(text: str) -> str:
    """Текст для модели: без изменений, если разметки в начале нет; иначе та же строка с вырезанной разметкой."""
    if _MARKUP.search(text[:4000]):
        return _mask_markup(text)[0]
    return text


def eligible(text: str) -> bool:
    """Годится ли текст для модели: русская проза, не таблица, не разметка, не короткий код."""
    if len(text) < MIN_TEXT:
        return False
    letters = cyr = 0                  # S8B: счёт по кускам, без списка букв (50 МБ текста — гигабайты строк)
    for i in range(0, len(text), 1_000_000):
        part = text[i:i + 1_000_000]
        letters += len(_LAT_OR_CYR.findall(part))
        cyr += len(_CYR.findall(part))
    if not letters:
        return False
    if cyr < 0.5 * letters:
        return False
    head = text[:4000]
    lines = [ln for ln in head.split("\n") if ln.strip()] or [head]
    if sum(1 for ln in lines if ln.count("\t") >= 1 or ln.count(";") >= 2 or ln.count(",") >= 4 and len(ln) < 80) * 2 > len(lines):
        return False                                     # строки-таблицы и CSV
    if _MARKUP.search(head) and (len(text) < MARKUP_MIN_TEXT or _mask_markup(text)[1] > MARKUP_MAX_SHARE):
        return False                                     # S9G: разметка/код целиком; проза с вкраплениями шаблонов проходит
    if len(text) < 40 and (" " not in text.strip() or sum(not c.isalnum() and not c.isspace() for c in text) > len(text) // 5):
        return False                                     # короткий кодоподобный фрагмент
    return True


def _chunks(text: str):
    """Окна для модели: (начало, конец, своё_начало, своё_конец). Окно «владеет» фрагментами, чьё начало лежит в
    [своё_начало, своё_конец). Разрез по концу предложения/строки — без перекрытия (как раньше). Если границы
    предложения нет, режем по пробелу, а следующее окно начинается на OVERLAP раньше: имя на границе целиком видно
    в одном из окон, дубли в перекрытии отсекаются правилом владения."""
    n = len(text)
    a = 0
    own_a = 0
    while a < n:
        b = min(n, a + CHUNK)
        own_b = b
        nxt = b
        if b < n:
            cut = max(text.rfind("\n", a, b), text.rfind(". ", a, b))
            if cut > a + CHUNK // 2:
                b = cut + 1
                own_b = nxt = b
            else:
                ws = max(text.rfind(" ", a + CHUNK // 2, b), text.rfind("\n", a + CHUNK // 2, b))
                if ws > a:
                    b = ws
                nxt = max(a + 1, b - OVERLAP)
                own_b = b - OVERLAP // 2
        yield a, b, own_a, own_b if b < n else n
        a = nxt
        own_a = own_b


def _viable(piece: str) -> bool:
    """Окно, где нет ни одного слова с заглавной кириллической буквы, не даст ни одного принятого имени (см. _clean)."""
    return _CAPWORD.search(piece) is not None


def _run_piece(tagger, state, piece: str) -> tuple[tuple[int, int, float], ...] | None:
    """Спаны PER окна в локальных смещениях; None — сбой модели."""
    from bisect import bisect_left
    from slovnet.markup import BIOMarkup
    from slovnet.token import tokenize
    toks = list(tokenize(piece))
    if not toks:
        return ()
    infer = tagger.infer
    with _lock:
        state["probs"] = []
        try:
            inputs = infer.encoder([[t.text for t in toks]])
            preds = infer.decoder(infer.process(inputs))
            tags = next(iter(preds))
            spans = BIOMarkup.from_tuples(zip([t.text for t in toks], tags)).to_span(piece).spans
        except Exception:               # noqa: BLE001
            return None
        probs = state["probs"][0] if state["probs"] else []
    starts = [t.start for t in toks]
    out = []
    for sp in spans:
        if sp.type != "PER":
            continue
        i = bisect_left(starts, sp.start)
        idx = []
        while i < len(toks) and toks[i].stop <= sp.stop:
            idx.append(i)
            i += 1
        conf = min((probs[j] for j in idx if j < len(probs)), default=0.0)
        out.append((sp.start, sp.stop, round(conf, 3)))
    return tuple(out)


def _raw_spans(text: str) -> tuple[tuple[int, int, float], ...]:
    loaded = _load()
    if loaded is False:
        return ()
    tagger, state = loaded
    out: list[tuple[int, int, float]] = []
    for a, b, own_a, own_b in _chunks(text):
        piece = text[a:b]
        if not piece.strip() or not _viable(piece):
            continue
        key = hashlib.blake2b(piece.encode("utf-8", "surrogatepass"), digest_size=16).digest()   # ключ — хэш: память не растёт с размером окна
        hit = _piece_cache.get(key)
        if hit is not None:
            _piece_cache.move_to_end(key)
        else:
            hit = _run_piece(tagger, state, piece)
            if hit is None:
                return ()
            _piece_cache[key] = hit
            if len(_piece_cache) > _PIECE_CACHE_MAX:
                _piece_cache.popitem(last=False)
        for s_, e_, c_ in hit:
            if own_a <= a + s_ < own_b:
                out.append((a + s_, a + e_, c_))
    return tuple(out)


def take_notes() -> list[str]:
    """Заметки для задания (видимые пользователю); забираются один раз."""
    with _lock:
        got = list(_notes)
        _notes.clear()
    return got


def _note(msg: str) -> None:
    with _lock:
        if msg in _notes:
            return                  # одна запись в журнал на заметку, а не на каждый вызов
        _notes.append(msg)
    _LOG.warning(msg)


def _clean(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Обрезать знаки по краям и отбросить фрагмент, где слово не похоже на имя (не с заглавной, цифры, разметка)."""
    frag = text[start:end]
    stripped = frag.strip(" \t\r\n,;:()[]«»\"'—–-")
    if not stripped:
        return None
    start += frag.index(stripped)
    end = start + len(stripped)
    words = text[start:end].split()
    if not 1 <= len(words) <= 4:
        return None
    if not all(_NAME_TOKEN.match(w) for w in words):
        return None
    if all(len(w.rstrip(".")) < 2 for w in words):
        return None
    return start, end


def person_spans(text: str, min_conf: float = MIN_CONF) -> list[tuple[int, int, float]]:
    """Все вхождения принятых имён: (начало, конец, достоверность). Пусто, если модель недоступна или текст не подходит."""
    if len(text) > MAX_TEXT:
        _note(f"Поиск имён по модели NER пропущен: фрагмент {len(text) // 1_000_000} МБ больше предела {MAX_TEXT // 1_000_000} МБ; имена найдены только правилами.")
        return []
    if not eligible(text):
        return []
    if _load() is False:
        _note("Модель NER (natasha) недоступна: имена найдены только правилами.")
        return []
    orig = text
    text = working_text(orig)           # S9G: разметка вырезана пробелами, смещения прежние
    hit = _cache.get(text) if len(text) < 4000 else None
    raw = hit if hit is not None else _raw_spans(text)
    if hit is None and len(text) < 4000:
        _cache[text] = raw
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    accepted: dict[str, float] = {}
    for s, e, c in raw:
        if c < min_conf:
            continue
        fixed = _clean(text, s, e)
        if fixed:
            lit = text[fixed[0]:fixed[1]]
            accepted[lit] = max(accepted.get(lit, 0.0), c)
    out: list[tuple[int, int, float]] = []
    for lit, conf in accepted.items():
        for m in re.finditer(r"(?<![\w])" + re.escape(lit) + r"(?![\w])", text):
            if text is not orig and orig[m.start():m.end()] != lit:
                continue                # внутри имени была вырезанная разметка
            out.append((m.start(), m.end(), conf))
    return sorted(out)


def _word_ok(w: str) -> bool:
    core = w.rstrip(".")
    return len(core) >= 3 and w.casefold().strip(".") not in _STOP and not _LABEL.search(w)


def is_full_name(lit: str) -> bool:
    """Полное имя: либо два слова и больше (Имя Фамилия, Фамилия Имя Отчество), либо инициалы и фамилия. Роль и должность в начале — нет."""
    words = lit.split()
    full = [w for w in words if not _NAME_INITIAL.match(w)]
    if not full or not all(_word_ok(w) for w in full):
        return False
    return len(full) >= 2 or (len(full) == 1 and len(words) > len(full) and len(full[0]) >= 4)


def lone_ok(lit: str) -> bool:
    """Одиночное слово остаётся в списке проверки, если не похоже на стоп-слово, прилагательное с дефисом или метку."""
    w = lit.strip()
    if not _word_ok(w) and " " not in w:
        return False
    if "-" in w and any(part[:1].islower() for part in w.split("-")):
        return False
    return not _LABEL.search(w) and not (len(w) > 7 and w.casefold().endswith(_ADJ_END))


def decide(lit: str, conf: float) -> str | None:
    """'auto' — скрыть само, 'review' — в список проверки, None — отбросить."""
    if is_full_name(lit):
        return "auto" if conf >= AUTO_CONF else "review"
    return "review" if lone_ok(lit) else None


REASON_AUTO = "Полное имя по модели NER"
REASON_REVIEW = "Имя по модели NER"
REASON_BOTH = "Имя по модели NER, подтверждено правилами"
REASON_LEARNED = "Имя по модели NER, найдено в документе"

_memo: OrderedDict[tuple[int, int], list[tuple[int, int, float]]] = OrderedDict()


def spans_cached(text: str) -> list[tuple[int, int, float]]:
    """person_spans с памятью на последние тексты: harvest() и scan() одного и того же текста гоняют модель один раз."""
    key = (len(text), hash(text))
    hit = _memo.get(key)
    if hit is None:
        hit = person_spans(text)
        _memo[key] = hit
        if len(_memo) > 6:
            _memo.popitem(last=False)
    return hit


def learnable_names(text: str) -> list[str]:
    """Полные имена с высокой достоверностью: их заводят в запись о людях, как найденные правилами (разные падежи, фамилия, инициалы)."""
    seen: dict[str, None] = {}
    for s, e, c in spans_cached(text):
        lit = text[s:e]
        if c >= AUTO_CONF and decide(lit, c) == "auto":
            seen.setdefault(lit, None)
    return list(seen)


def review_candidates(text: str, make: Callable[..., object], priority: int, auto: bool = True) -> list[tuple[int, object]]:
    """Кандидаты в формате детектора: [(приоритет, Finding)]. make(start, end, conf, auto) -> Finding.
    Полное имя с высокой достоверностью помечается auto=True; одиночные слова остаются в списке проверки."""
    out = []
    for s, e, c in spans_cached(text):
        verdict = decide(text[s:e], c)
        if verdict is None:
            continue
        out.append((priority, make(s, e, c, auto and verdict == "auto")))
    return out
