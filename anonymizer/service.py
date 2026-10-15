"""Сценарии продукта: обезличить файл, вернуть исходные данные, показать, что заменено.

Слой не знает про HTTP. Интерфейс получает из него готовые для показа результаты: статус каждого
файла, сообщения на русском языке, сводку по видам данных и список того, что стоит проверить.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import shutil
import threading
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import imagereplace
from . import refusals
from . import restore as rs
from . import settings_schema
from .detectors import STAGE_HOOK, Detector
from .formats import (TransformContext, classify, extract_text, read_vault_marker, replace_findings, scan_ooxml,
                      scan_pdf, scan_text_file, transform_image, transform_ooxml, transform_pdf, transform_text_file)
from .models import Decision, Settings
from .normalize import fold
from .tokens import EMAIL_TOKEN_RE, GROUP_LABELS, KINDS, TOKEN_RE, format_token, parse_match
from .vault import Vault
from . import verify

Progress = Callable[[float, str], None]

# Живой статус: только названия этапов, без найденных значений. Группа поиска -> что видит человек.
STAGE_TEXT = {
    "secrets": "Обезличиваю секреты и ключи доступа",
    "entities": "Обезличиваю организации и места",
    "names": "Обезличиваю ФИО",
    "pii": "Обезличиваю контакты и реквизиты (ИНН, счета, паспорта)",
    "business": "Обезличиваю коммерческие данные",
}
STAGE_DWELL = 0.4          # секунд: подпись этапа не мигает чаще, чем читается


class StageTracker:
    """Подпись текущего этапа задания. Пишет в job.stage из потока задания; значения данных сюда не попадают."""

    def __init__(self, job, total: int = 1):
        self.job, self.total, self.index, self.last = job, total, 0, 0.0

    def file(self, index: int) -> None:
        self.index = index

    def set(self, text: str, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self.last < STAGE_DWELL:
            return
        prefix = f"Файл {self.index + 1} из {self.total}: " if self.total > 1 else ""
        self.job.stage = prefix + text
        self.last = now

    def group(self, name: str) -> None:
        text = STAGE_TEXT.get(name)
        if text:
            self.set(text, force=False)

OUTPUT_TTL = 30 * 60            # файлы результата открытым текстом после записи в чат живут не дольше
DELIVERED_GRACE = 10 * 60       # а после того, как человек забрал все файлы, ещё столько (повторное нажатие «Сохранить»)
JOB_TTL = 6 * 3600              # всё остальное (и результат, не попавший в чат: он единственный)


def shred_tree(path: Path) -> None:
    """Затирает и удаляет файл или каталог: рабочие файлы содержат настоящие данные открытым текстом."""
    from .chats import ChatStore
    try:
        if path.is_dir() and not path.is_symlink():
            for item in path.rglob("*"):
                if item.is_file() and not item.is_symlink():
                    ChatStore._shred(item)
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            ChatStore._shred(path)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)

SUFFIX_ANON = " (обезличено)"
SUFFIX_RESTORED = " (восстановлено)"
# Нейтральное имя результата: «Файл3 (обезличено).docx». Номер ведёт хранилище, по нему возврат находит исходное имя.
NEUTRAL_STEM = "Файл"
NEUTRAL_NAME = re.compile(rf"^{NEUTRAL_STEM}(\d{{1,7}})(?!\d)")
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
CHAT_SCOPED = {o.key for o in settings_schema.OPTIONS if o.scope == "chat"}
KNOWLEDGE_KINDS = {"ORG", "PROJECT", "CITY", "REGION", "DOMAIN", "TERM"}

UNSUPPORTED_HELP = refusals.HELP

FORMAT_LABEL = {"TEXT": "Текст", "OOXML": "Office", "PDF": "PDF", "IMAGE": "Картинка"}

# Части файла, где нет содержимого документа: образцы и макеты слайдов, темы, свойства файла. Слово оттуда
# («Embedded OLE Servers», «Office Theme») не повод для подсказки: если оно есть в тексте, подсказка придёт оттуда,
# а решение пользователя всё равно применится к каждому вхождению.
NON_CONTENT_PARTS = ("slidemasters", "slidelayouts", "notesmasters", "handoutmasters", "docprops/", "/theme/",
                     "presprops.xml", "viewprops.xml", "tablestyles.xml", "/styles.xml", "fonttable.xml", "websettings.xml")
# Замещающий текст картинок и подсказки ссылок.
ALT_TEXT_MARKS = (":cNvPr:descr", ":cNvPr:title", ":docPr:descr", ":docPr:title", ":hyperlink:tooltip")
# Подсказок каждого вида не больше этого: сильные важнее, и слабые не должны вытеснять их из списка.
STRONG_LIMIT, WEAK_LIMIT = 200, 60
# Строгий режим: сколько раз можно повторить проход, скрывая подсказки предыдущего (после замены могут всплыть новые).
STRICT_PASSES = 2


def not_content(location: str) -> bool:
    part = location.split("::", 1)[0].lower()
    return any(mark in part for mark in NON_CONTENT_PARTS)


@dataclass
class Upload:
    name: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def head(self, count: int = 16) -> bytes:
        return self.data[:count]

    def write_to(self, path: Path) -> None:
        path.write_bytes(self.data)


class PathUpload:
    """Файл на диске, который читается только когда до него дошла очередь: папка на гигабайты не должна жить в памяти."""

    def __init__(self, name: str, source: Path):
        self.name = name
        self.source = source

    @property
    def size(self) -> int:
        return self.source.stat().st_size

    @property
    def data(self) -> bytes:
        return self.source.read_bytes()

    def head(self, count: int = 16) -> bytes:
        with open(self.source, "rb") as handle:
            return handle.read(count)

    def write_to(self, path: Path) -> None:
        shutil.copyfile(self.source, path)


@dataclass
class FileOutcome:
    name: str
    out_name: str = ""
    out_path: str = ""
    status: str = "ok"                     # ok | attention | error
    format: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    total: int = 0
    messages: list[dict] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)   # метки (основы), встретившиеся в этом файле; наружу не отдаётся

    def add(self, level: str, text: str) -> None:
        if not any(m["text"] == text for m in self.messages):
            self.messages.append({"level": level, "text": text})
        if level == "error":
            self.status = "error"
        elif level == "warn" and self.status == "ok":
            self.status = "attention"

    def public(self) -> dict:
        return {"name": self.name, "out_name": self.out_name, "status": self.status, "format": self.format,
                "counts": self.counts, "total": self.total, "messages": self.messages,
                "downloadable": bool(self.out_path) and self.status != "error"}


@dataclass
class Job:
    id: str
    kind: str
    dir: Path
    files: list[FileOutcome] = field(default_factory=list)
    state: str = "running"                 # running | done | failed
    percent: float = 0.0
    stage: str = ""
    result: dict = field(default_factory=dict)
    inputs: list[Upload] = field(default_factory=list)
    options: dict = field(default_factory=dict)
    snapshot: object = None
    folder: object = None                  # FolderContext, если задание — целая папка
    replaced: list = field(default_factory=list)   # все заменённые исходные значения: для проверки, что они не остались в файле
    created: float = field(default_factory=time.time)
    error: str = ""
    chat: str = ""                         # чат, в который записан результат (заполняется после задания)
    warning: str = ""                      # результат готов, но с оговоркой (например, не записался в чат)
    processed: int = 0                     # сколько файлов уже обработано (для строки «Обработано 37 из 200»)
    total: int = 0
    cancel: bool = False                   # человек нажал «Остановить»: задание прерывается между файлами
    vault_sig: str = ""                    # слепок хранилища сразу после задания: правки человека после него откатывать нельзя
    stage_tracker: object = None           # StageTracker: подписи этапов (только названия)
    project: object = None                 # {"root": имя папки, ...}, если файлы задания — проект в чате
    delivered: dict = field(default_factory=dict)   # номер файла → когда человек его скачал или сохранил


NER_UNAVAILABLE_NOTE = "Нейросеть для имён недоступна, работает обычный поиск"


class JobCancelled(Exception):
    """Задание остановлено человеком; хранилище откатывается к состоянию до задания."""


OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")

# Метка, которую модель испортила: пробел между основой и номером («Name 1») или две метки без разделителя («Name1Name2»).
_STEMS = "|".join(sorted((k.stem for k in KINDS if k.code != "EMAIL"), key=len, reverse=True))
SPACED_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9_])({_STEMS})[ \u00a0]+(\d{{1,7}})(?![\d.,A-Za-z_])")
GLUED_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9_])(?:(?:{_STEMS})\d{{1,7}}(?:_\d{{1,6}})?){{2,}}(?![A-Za-z0-9_])")


def container_problem(name: str, data: bytes) -> str:
    """Понятная причина, по которой Office-файл нельзя открыть, — до попытки его обработать."""
    suffix = Path(name).suffix.lower()
    if suffix in (".xlsx", ".docx", ".pptx"):
        if data.startswith(OLE_HEADER):
            return ("Файл защищён паролем или сохранён в старом формате. Снимите защиту в Excel, Word или PowerPoint "
                    "и загрузите его снова.")
        if not data.startswith(b"PK"):
            return "Файл повреждён: это не документ Office."
    if suffix == ".pdf" and not data.startswith(b"%PDF"):
        return "Файл повреждён: это не PDF."
    return ""


MAX_UNPACKED_BYTES = 1024 * 1024 * 1024


def unpacked_size_problem(path: Path | bytes, name: str = "") -> str:
    """Архив, который при распаковке занял бы гигабайты («бомба»), не открываем: он повесил бы компьютер.
    Принимает путь к файлу или его содержимое (тогда нужно имя)."""
    if isinstance(path, (bytes, bytearray)):
        suffix, source = Path(name).suffix.lower(), io.BytesIO(path)
    else:
        suffix, source = path.suffix.lower(), path
    if suffix not in (".xlsx", ".docx", ".pptx"):
        return ""
    try:
        with zipfile.ZipFile(source) as z:
            infos = z.infolist()
            total = sum(info.file_size for info in infos)
    except (zipfile.BadZipFile, ValueError, NotImplementedError, OSError):
        return "Файл повреждён: не удаётся прочитать содержимое."
    for info in infos:
        parts = info.filename.replace("\\", "/").split("/")
        if info.filename.startswith(("/", "\\")) or ".." in parts or (parts[0][1:2] == ":" and len(parts[0]) == 2):
            return "Файл повреждён: внутри архива недопустимые пути."
    if total > MAX_UNPACKED_BYTES:
        return "Файл слишком велик после распаковки (больше 1 ГБ) и не обрабатывается."
    return ""


def safe_name(name: str) -> str:
    # macOS отдаёт имена в разложенной форме («й» из двух знаков): ни Windows, ни поиск по тексту такого не ждут.
    base = re.split(r"[\\/]", unicodedata.normalize("NFC", name))[-1].strip().strip(".") or "file"
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base)
    stem, dot, ext = base.rpartition(".")
    # Linux limits a component in bytes, whereas macOS/Windows also impose
    # character limits. Leave room for output suffixes such as " (обезличено)".
    def clipped(value: str, chars: int, byte_limit: int) -> str:
        return value[:chars].encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore").rstrip()

    if dot and stem and 0 < len(ext) <= 10:
        suffix = f".{ext}"
        return clipped(stem, 150 - len(suffix), 200 - len(suffix.encode("utf-8"))) + suffix
    return clipped(base, 150, 200)


def split_ext(name: str) -> tuple[str, str]:
    path = Path(name)
    return path.stem, path.suffix


class Service:
    def __init__(self, vault: Vault, workdir: Path):
        self.vault = vault
        self.workdir = workdir
        workdir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self._commit_counter = 0
        self.cleanup()

    # -- рабочие каталоги -----------------------------------------------------

    def cleanup(self, older_than: float = JOB_TTL, inputs_older_than: float = 600,
                outputs_older_than: float = OUTPUT_TTL, delivered_grace: float = DELIVERED_GRACE) -> None:
        now = time.time()
        limit = now - older_than
        inputs_limit = now - inputs_older_than
        for child in list(self.workdir.iterdir()):
            try:
                job = self.jobs.get(child.name)
                if job is not None and job.state == "running":
                    continue                     # идущее задание не трогаем, как бы долго оно ни шло
                if child.stat().st_mtime < limit:
                    shred_tree(child)
                    continue
                # Исходные файлы открытым текстом живут только пока идёт задание: забытые после сбоя убираем сразу.
                source = child / "in"
                if source.is_dir() and source.stat().st_mtime < inputs_limit:
                    shred_tree(source)
                if job is not None:
                    self._expire_outputs(job, now, outputs_older_than, delivered_grace)
            except OSError:
                continue
        for job_id in [j for j, job in self.jobs.items() if job.created < limit and job.state != "running"]:
            self.jobs.pop(job_id, None)

    def _expire_outputs(self, job: Job, now: float, ttl: float, grace: float) -> None:
        """Результат записан в чат (там он зашифрован) → открытая копия в `out/` живёт недолго и затирается.
        Результат, который в чат не попал, остаётся до конца срока задания: другой копии у человека нет."""
        out = job.dir / "out"
        if job.state == "running" or not job.chat or not out.is_dir():
            return
        files = [i for i, o in enumerate(job.files) if o.out_path and o.status != "error"]
        due = out.stat().st_mtime + ttl < now
        if files and all(i in job.delivered for i in files):
            due = due or max(job.delivered[i] for i in files) + grace < now
        if not due:
            return
        shred_tree(out)
        for archive in job.dir.glob("*.zip"):
            shred_tree(archive)
        for outcome in job.files:
            outcome.out_path = ""

    def note_delivered(self, job_id: str, index: int | None = None) -> None:
        """Человек забрал файл результата (скачал или сохранил). `None` — все сразу."""
        job = self.jobs.get(job_id)
        if job is None:
            return
        now = time.time()
        for i in (range(len(job.files)) if index is None else [index]):
            job.delivered[i] = now

    @staticmethod
    def _discard_output(dst: Path | None) -> None:
        """Недописанный результат не оставляем на диске."""
        if dst is not None:
            try:
                dst.unlink()
            except OSError:
                pass

    def new_job(self, kind: str, options: dict | None = None) -> Job:
        from .util import opaque_id
        self.cleanup()          # фоновая программа живёт днями: чистка только при запуске оставляла бы файлы дольше срока
        job_id = opaque_id(6).lower()
        directory = self.workdir / job_id
        (directory / "in").mkdir(parents=True, exist_ok=True)
        (directory / "out").mkdir(parents=True, exist_ok=True)
        job = Job(job_id, kind, directory, options=options or {})
        self.jobs[job_id] = job
        return job

    @staticmethod
    def purge_inputs(job: Job) -> None:
        """Копии исходных файлов (открытый текст) больше не нужны: для повтора хранятся загрузки, а не файлы на диске."""
        shutil.rmtree(job.dir / "in", ignore_errors=True)

    def forget_job(self, job_id: str) -> None:
        job = self.jobs.pop(job_id, None)
        if job:
            shred_tree(job.dir)

    # -- предпросмотр ---------------------------------------------------------

    def peek(self, upload: Upload) -> dict:
        """Что за файл: поддерживается ли, не обезличен ли он уже. Ничего не меняет."""
        name = safe_name(upload.name)
        path = self.workdir / "peek" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(upload.data)
        try:
            kind = classify(path)
            info = {"name": name, "size": len(upload.data), "format": FORMAT_LABEL.get(kind, ""),
                    "supported": kind in FORMAT_LABEL, "note": "", "tokens": 0}
            if kind not in FORMAT_LABEL:
                info["note"] = refusals.help_for_path(path)
                return info
            problem = container_problem(name, upload.data) or unpacked_size_problem(upload.data, name)
            if problem:
                info["supported"], info["note"] = False, problem
                return info
            try:
                text = extract_text(path)
            except Exception:
                info["note"] = "Файл не удалось прочитать: возможно, он повреждён или защищён паролем."
                info["supported"] = False
                return info
            known = 0
            for regex, email in ((TOKEN_RE, False), (EMAIL_TOKEN_RE, True)):
                for m in regex.finditer(text):
                    kind_, number, variant = parse_match(m, email=email)
                    if self.vault.lookup(kind_, number, variant).status in ("ok", "variant_missing"):
                        known += 1
            info["tokens"] = known
            return info
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    # -- обезличивание --------------------------------------------------------

    def settings_for(self, options: dict) -> Settings:
        """Порядок: явный параметр запуска (в нём уже настройки чата) > общие настройки > умолчания схемы."""
        values = settings_schema.resolve(self.vault.prefs, None, options)
        return Settings(suggest=True, disabled_kinds=settings_schema.disabled_kinds(values),
                        hide_terms=values["hide_terms"], keep_terms=values["keep_terms"],
                        **{k: values[k] for k in settings_schema.SETTINGS_BOOLS})

    def build_detector(self, settings: Settings) -> Detector:
        # Слово из «всегда скрывать», совпавшее с уже известной сущностью, скрывается под её кодом, а не заводит второй
        # (Term1 вместо Name1 затирал бы разбор ФИО и оставлял другие формы фамилии открытыми).
        linked: dict[str, tuple[str, str]] = {}
        for term in settings.hide_terms:
            found = self.vault.entity_for_term(term, KNOWLEDGE_KINDS | {"PERSON"})
            if found:
                linked[term] = found
        if linked:
            settings = dataclasses.replace(settings, hide_terms=[t for t in settings.hide_terms if t not in linked])
        detector = Detector([], settings)
        detector.token_known = lambda kind, number, variant: \
            self.vault.lookup(kind, number, variant).status != "unknown"
        wanted = {t.strip().lower() for t in settings.hide_terms}
        for base, entity in list(self.vault.entities.items()):
            if entity["kind"] == "TERM" and not wanted & {str(x).strip().lower() for x in entity.get("spellings", [])}:
                continue      # слово, скрытое только в другом чате или убранное из списка, здесь не действует
            if entity["kind"] in KNOWLEDGE_KINDS and entity.get("spellings"):
                detector.entities.seed(entity["kind"], entity["key"], entity["spellings"])
        for term, (kind, key) in linked.items():
            detector.entities.register(kind, term.strip(), explicit=True, key=key)
        return detector

    def anonymize(self, uploads: list[Upload], options: dict | None = None, overrides: dict[str, str] | None = None,
                  progress: Progress | None = None, job: Job | None = None) -> Job:
        if job is None:
            with self.lock:
                job = self.new_job("anonymize", dict(options or {}))
        try:
            return self._anonymize(uploads, options, overrides, progress, job)
        except JobCancelled:
            if job is not None and job.snapshot is not None:
                self.vault.rollback(job.snapshot[0])      # остановленное задание не оставляет меток в хранилище
            raise
        finally:
            self.purge_inputs(job)

    def _anonymize(self, uploads: list[Upload], options: dict | None = None, overrides: dict[str, str] | None = None,
                   progress: Progress | None = None, job: Job | None = None) -> Job:
        options = dict(options or {})
        with self.lock:
            if job is None:
                job = self.new_job("anonymize", options)
            if job.snapshot is None:
                job.inputs = list(uploads)
                job.snapshot = (self.vault.snapshot(), self._commit_counter)
            job.options = options
            settings = self.settings_for(options)
            user_overrides = {fold(k): v for k, v in (overrides or {}).items()}
            def report(percent: float, stage: str) -> None:
                job.percent, job.stage = max(job.percent, percent), stage       # процент не откатывается и при втором проходе
                if progress:
                    progress(job.percent, stage)
            job.stage_tracker = StageTracker(job, max(1, len(uploads)))
            paths: list[tuple[Upload, Path, str]] = []
            for index, upload in enumerate(uploads):
                name = safe_name(upload.name)
                # Два файла с одним именем (Отчёт.txt из разных папок) не должны затирать друг друга.
                path = job.dir / "in" / str(index) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                upload.write_to(path)
                paths.append((upload, path, classify(path)))
            before = self.vault.snapshot() if settings.strict else None
            ctx, outcomes, suggestions = self._pass(job, paths, settings, user_overrides, report)
            auto_hide: dict[str, str] = {}
            for _ in range(STRICT_PASSES):
                # «Скрывать и сомнительные слова»: всё, что попало бы в «Возможно, нужно скрыть ещё», скрывается тем же
                # способом, как если бы человек отметил эти слова и обезличил заново. Слова из «Никогда не скрывать» и
                # решения самого человека («оставить») не трогаются. Прошлый проход откатывается, чтобы в нумерации
                # меток не было пропусков.
                fresh = self._strict_overrides(suggestions, settings, {**auto_hide, **user_overrides})
                if not settings.strict or not fresh:
                    break
                auto_hide.update(fresh)
                self.vault.rollback(before)
                shutil.rmtree(job.dir / "out", ignore_errors=True)
                ctx, outcomes, suggestions = self._pass(job, paths, settings, {**auto_hide, **user_overrides}, report,
                                                        set(auto_hide))
            job.files = outcomes
            job.stage_tracker.total = 1
            report(.98, "Собираю результат и сохраняю в хранилище")
            self._commit_job(job, "anonymize", outcomes, ctx)
            job.result = self._anonymize_result(job, ctx, suggestions)
            job.result["strict_hidden"] = len([k for k in auto_hide if k not in user_overrides])
            job.result["overrides"] = user_overrides
            job.state = "done"
            job.percent = 1.0
            report(1.0, "Готово")
            return job

    def _pass(self, job: Job, paths: list, settings: Settings, overrides: dict[str, str], report,
              auto_hidden: set[str] | None = None) -> tuple[TransformContext, list[FileOutcome], dict]:
        """Один проход по всем файлам задания со свежим детектором."""
        detector = self.build_detector(settings)
        ctx = TransformContext(self.vault, settings, detector, overrides=overrides, auto_hidden=auto_hidden or set())
        names_taken: dict[str, int] = {}
        tracker = job.stage_tracker
        supported = [(u, p, k) for u, p, k in paths if k in FORMAT_LABEL]
        if len(supported) > 1:
            # Первый проход только обучает детектор: полное ФИО из одного файла расшифровывает
            # инициалы в другом, и результат не зависит от порядка файлов.
            for index, (upload, path, kind) in enumerate(supported):
                if job.cancel:
                    raise JobCancelled()
                tracker.total = len(supported)
                tracker.file(index)
                tracker.set("Изучаю имена и названия", True)
                report(index / (2 * len(supported)), job.stage)
                hook = STAGE_HOOK.set(None)             # при обучении группы поиска не показываем: это ещё не замена
                try:
                    self._learn(detector, path, kind)
                finally:
                    STAGE_HOOK.reset(hook)
        outcomes: list[FileOutcome] = []
        suggestions: dict[str, dict] = {}
        job.total, job.processed = len(paths), 0
        for index, (upload, path, kind) in enumerate(paths):
            if job.cancel:
                raise JobCancelled()
            job.processed = index
            base = (len(supported) > 1) * .5
            tracker.total = len(paths)
            tracker.file(index)
            tracker.set("Читаю файл")
            report(base + (index / max(1, len(paths))) * (1 - base) * .98, job.stage)
            token = STAGE_HOOK.set(tracker.group)
            try:
                outcomes.append(self._anonymize_one(job, upload, path, kind, detector, ctx, suggestions, names_taken))
            finally:
                STAGE_HOOK.reset(token)
        job.processed = len(paths)
        if getattr(detector, "ner_unavailable", False) and outcomes:
            outcomes[0].add("info", NER_UNAVAILABLE_NOTE)      # один раз на задание
        if outcomes:
            from . import ner as _ner
            for note in _ner.take_notes():                      # слишком большой текст и т. п.: видно в задании, не молча
                if note != NER_UNAVAILABLE_NOTE:
                    outcomes[0].add("info", note)
        return ctx, outcomes, suggestions

    @staticmethod
    def _strict_overrides(suggestions: dict, settings: Settings, decided: dict[str, str]) -> dict[str, str]:
        """Подсказки, которые строгий режим скрывает сам: все, кроме уже решённых и слов из «Никогда не скрывать»."""
        keep = {fold(t) for t in settings.keep_terms}
        return {key: "hide" for key, entry in suggestions.items()
                if key not in decided and key not in keep and fold(entry["text"]) not in keep}

    def rerun(self, job_id: str, options: dict, overrides: dict[str, str], progress: Progress | None = None,
              job: Job | None = None) -> Job:
        """Повторный проход с решениями пользователя: скрыть сомнительное, оставить найденное."""
        with self.lock:
            old = self.jobs.get(job_id)
            if old is None:
                raise KeyError("Исходные файлы этого задания уже удалены. Загрузите файл заново.")
            snapshot, counter = old.snapshot if old.snapshot else (None, -1)
            if snapshot is not None and counter == self._commit_counter - 1 and old.vault_sig == self._vault_sig():
                # Между заданием и повтором ничего не менялось: токены, выданные впустую, возвращаем.
                self.vault.rollback(snapshot)
            # Настройки чата берутся заново из `options` (их могли изменить или снять): прежние значения этих ключей устарели.
            # Вызов без единой настройки чата (прямой повтор) оставляет прежние: иначе строгий режим пропал бы молча.
            stale = CHAT_SCOPED if CHAT_SCOPED & set(options) else set()
            carried = {k: v for k, v in old.options.items() if k not in stale}
            merged = {**carried, **options}
            merged_overrides = {**old.options.get("overrides", {}), **overrides}
            merged["overrides"] = merged_overrides
            merged["remembered"] = self._remember(overrides)
            # Решение о слове действует в этом проходе (и запоминается чатом), но общие настройки не меняет.
            decided = {k: list(v) for k, v in (merged.get("term_decisions") or {}).items()}
            for bucket, name in (("hide", "hide_terms"), ("keep", "keep_terms")):
                words = merged["remembered"][bucket]
                merged[name] = list(dict.fromkeys([*merged.get(name, []), *words]))
                decided[name] = list(dict.fromkeys([*decided.get(name, []), *words]))
            merged["term_decisions"] = decided
            fresh = job or self.new_job("anonymize", merged)
            fresh.inputs = old.inputs
            fresh.snapshot = (self.vault.snapshot(), self._commit_counter)
            self.forget_job(job_id)
            return self.anonymize(fresh.inputs, merged, merged_overrides, progress, job=fresh)

    def _vault_sig(self) -> str:
        with self.vault._lock:
            state = (self.vault.counters, self.vault.entities, self.vault.numbers, self.vault.pins, self.vault.file_names)
            return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

    def _remember(self, overrides: dict[str, str]) -> dict[str, list[str]]:
        """Решения человека о словах. Общие настройки они не меняют: слова запоминает чат (WebApp.remember_in_chat)."""
        added = {"hide": [], "keep": []}
        for word, choice in overrides.items():
            if choice in added and word not in added[choice]:
                added[choice].append(word)
        return added

    def _learn(self, detector: Detector, path: Path, kind: str) -> None:
        try:
            if kind == "TEXT":
                scan_text_file(path, path.name, detector)
            elif kind == "OOXML":
                scan_ooxml(path, path.name, detector, True, False)
            elif kind == "PDF":
                scan_pdf(path, path.name, detector)
        except Exception:
            return

    def _anonymize_one(self, job: Job, upload: Upload, path: Path, kind: str, detector: Detector,
                       ctx: TransformContext, suggestions: dict, names_taken: dict) -> FileOutcome:
        outcome = FileOutcome(name=path.name, format=FORMAT_LABEL.get(kind, ""))
        if upload.size > MAX_UPLOAD_BYTES:
            outcome.add("error", "Файл слишком большой (больше 300 МБ).")
            return outcome
        if kind not in FORMAT_LABEL:
            outcome.add("error", refusals.help_for_path(path))
            return outcome
        problem = container_problem(path.name, upload.head())
        if problem:
            outcome.add("error", problem)
            return outcome
        problem = unpacked_size_problem(path)
        if problem:
            outcome.add("error", problem)
            return outcome
        before = dict(ctx.counts)
        ctx.file_tokens = set()
        numeric_before = dict(ctx.numeric)
        dst = None
        try:
            out_name = self._anonymized_name(path.name, detector, ctx)
            key = out_name.casefold()
            names_taken[key] = names_taken.get(key, 0) + 1
            if names_taken[key] > 1:
                stem, ext = split_ext(out_name)
                out_name = f"{stem} ({names_taken[key]}){ext}"
            dst = job.dir / "out" / out_name
            transform = {"TEXT": transform_text_file, "OOXML": transform_ooxml, "PDF": transform_pdf, "IMAGE": transform_image}[kind]
            tracker = getattr(job, "stage_tracker", None)
            if tracker and kind == "IMAGE":
                tracker.set("Распознаю текст на изображении")
            result = transform(path, dst, path.name, detector, ctx)
            if tracker:
                tracker.set("Проверяю результат")
        except UnicodeDecodeError:
            self._discard_output(dst)
            outcome.add("error", "Не удалось определить кодировку текстового файла.")
            return outcome
        except Exception as exc:  # один плохой файл не должен ронять всё задание
            self._discard_output(dst)
            outcome.add("error", f"Не удалось обработать файл ({type(exc).__name__}). Возможно, он повреждён "
                                 "или защищён паролем.")
            return outcome
        if isinstance(result.integrity, dict) and result.integrity.get("macros"):
            # Файл с макросами transform_ooxml отдаёт нетронутой копией: наружу он не выходит (раньше уходил с предупреждением).
            self._discard_output(dst)
            outcome.add("error", refusals.MACRO_REFUSAL)
            return outcome
        outcome.out_name, outcome.out_path = out_name, str(dst)
        outcome.tokens = sorted(ctx.file_tokens)
        outcome.counts = {g: ctx.counts.get(g, 0) - before.get(g, 0) for g in ctx.counts
                          if g != "hidden" and ctx.counts.get(g, 0) - before.get(g, 0)}
        outcome.total = sum(outcome.counts.values())
        for warning in result.warnings:
            outcome.add("warn", warning)
        for notice in result.notices:
            outcome.add("info", notice)
        if result.status.value == "BLOCKED":
            self._discard_output(dst)
            outcome.out_path = ""
            outcome.add("error", "Файл не был изменён и не подходит для передачи наружу.")
            return outcome
        if ctx.numeric.get("replaced", 0) - numeric_before.get("replaced", 0):
            done = ctx.numeric["replaced"] - numeric_before.get("replaced", 0)
            outcome.add("info", f"Заменено чисел: {done}. Даты и годы не менялись. Результаты формул очищены: "
                                "Excel пересчитает их при открытии.")
        if kind == "TEXT" and outcome.total:
            try:
                rs.stamp_text_marker(dst, self.vault.vault_id)
            except Exception:
                pass           # пометка вспомогательная: без неё файл возвращается как раньше
        ok, problem = verify.check_openable(dst)
        if not ok:
            outcome.out_path = ""
            outcome.add("error", problem)
            return outcome
        if problem:
            outcome.add("warn", problem)
        numbers_done = ctx.numeric.get("replaced", 0) - numeric_before.get("replaced", 0)
        if outcome.total == 0 and not numbers_done:
            outcome.add("warn", "Данных для замены не найдено. Если в файле есть имена, названия или другая "
                                "конфиденциальная информация, добавьте нужные слова вручную и обезличьте файл заново.")
        for finding in result.findings:
            if finding.decision == Decision.AUTO or finding.category not in {"POSSIBLE_PERSON", "POSSIBLE_ENTITY"}:
                continue
            if ctx.overrides.get(fold(finding.original)) == "keep":
                continue
            if not_content(finding.location):
                continue
            entry = suggestions.setdefault(fold(finding.original), {
                "text": finding.original, "reason": finding.reason, "count": 0, "context": finding.context,
                "file": path.name, "strong": self._strong_suggestion(finding)})
            entry["count"] += 1
        return outcome

    @staticmethod
    def _strong_suggestion(finding) -> bool:
        """Похоже ли это на настоящую находку, которую не стоит пропускать.

        Слабые — аббревиатуры и латинские слова с заглавной буквы: в русском тексте их много, и почти все они
        обычные термины. Их список показывается, но тревогу не поднимает.
        """
        word = finding.original
        if any(mark in finding.location for mark in ALT_TEXT_MARKS):
            # Замещающий текст и подсказки пишут для людей: «Логотип Маяк-Строй», «Схема склада Альфа». Слово с заглавной
            # там почти всегда название, а текст этот никто не видит на слайде и не проверит глазами. Поэтому здесь даже
            # латиница и аббревиатуры идут в сильные подсказки. Сам текст сохраняется: он нужен для доступности.
            return True
        if finding.category == "POSSIBLE_PERSON":
            return finding.confidence >= .6
        # «МВтч», «кВт»: прописные буквы и строчный хвост — единица измерения или сокращение, а не название.
        if re.match(r"^[А-ЯЁA-Z]{2,}[а-яёa-z]+$", word):
            return False
        return not word.isascii() and not word.isupper()

    def _anonymized_name(self, name: str, detector: Detector, ctx: TransformContext) -> str:
        stem, ext = split_ext(name)
        # Подчёркивание — обычный разделитель слов в именах файлов, а для разбора оно часть слова.
        probe = stem.replace("_", " ")
        detector.harvest(probe, name)
        if ctx.settings.neutral_names:
            # Имя файла обычно выдаёт клиента или проект («Реестр_Клиент.xlsx»), а детектор узнаёт не всякое слово.
            # Поэтому имя заменяется целиком; исходное хранится в хранилище и возвращается при восстановлении.
            return f"{NEUTRAL_STEM}{self.vault.file_number(name)}{SUFFIX_ANON}{ext}"
        findings = ctx.apply_overrides(detector.scan(probe, name, "filename"))
        new_stem = replace_findings(stem, findings, ctx) if findings else stem
        return f"{new_stem}{SUFFIX_ANON}{ext}"

    def _commit_job(self, job: Job, kind: str, outcomes: list[FileOutcome], ctx: TransformContext) -> None:
        tokens: list[str] = []
        for group_tokens in ctx.tokens.values():
            tokens.extend(group_tokens)
        counts = {GROUP_LABELS.get(g, g): n for g, n in ctx.counts.items()}
        self.vault.log(kind, [o.out_name or o.name for o in outcomes if o.status != "error"], counts,
                       {"tokens": sorted(set(tokens))})
        self.vault.commit()
        self._commit_counter += 1
        job.vault_sig = self._vault_sig()

    def _anonymize_result(self, job: Job, ctx: TransformContext, suggestions: dict) -> dict:
        # Имена тем и шаблонов («Стандартная») Office переписывает сам и хранит в неиспользуемых образцах: утечкой они не считаются.
        job.replaced = [entry["original"] for entry in ctx.replaced.values() if entry.get("reason") != "Имя темы или шаблона оформления"]
        groups: dict[str, list[dict]] = {}
        for entry in ctx.replaced.values():
            groups.setdefault(entry["group"], []).append(
                {"original": entry["original"], "token": entry["token"], "count": entry["count"],
                 "reason": entry["reason"], "kind": entry["kind"]})
        for items in groups.values():
            items.sort(key=lambda e: (-e["count"], e["original"]))
        groups.pop("hidden", None)
        summary = [{"group": g, "label": GROUP_LABELS.get(g, g), "count": ctx.counts[g],
                    "unique": len({e["token"].split("_")[0] for e in groups.get(g, [])})}
                   for g in GROUP_LABELS if g != "hidden" and ctx.counts.get(g)]
        order = sorted(suggestions.values(), key=lambda e: (-e["count"], e["text"]))
        strong = [e for e in order if e["strong"]]
        weak = [e for e in order if not e["strong"]]
        return {"summary": summary, "groups": {GROUP_LABELS.get(g, g): v[:400] for g, v in groups.items()},
                "groups_order": [GROUP_LABELS.get(g, g) for g in GROUP_LABELS if g in groups],
                "suggestions": strong[:STRONG_LIMIT] + weak[:WEAK_LIMIT],
                # Сколько подсказок каждого вида всего: слабые никто не просматривал, и экран должен об этом сказать.
                "strong_total": len(strong), "weak_total": len(weak),
                "total": sum(n for g, n in ctx.counts.items() if g != "hidden"), "numbers": dict(ctx.numeric),
                "overrides": ctx.overrides, "remembered": job.options.get("remembered", {})}

    # -- восстановление -------------------------------------------------------

    def restore(self, uploads: list[Upload], progress: Progress | None = None, job: Job | None = None) -> Job:
        with self.lock:
            job = job or self.new_job("restore")
        try:
            return self._restore(uploads, progress, job)
        finally:
            self.purge_inputs(job)

    def _restore(self, uploads: list[Upload], progress: Progress | None, job: Job) -> Job:
        with self.lock:

            def report(percent: float, stage: str) -> None:
                job.percent, job.stage = percent, stage
                if progress:
                    progress(percent, stage)
            total = rs.RestoreStats()
            outcomes: list[FileOutcome] = []
            job.total = len(uploads)
            for index, upload in enumerate(uploads):
                if job.cancel:
                    raise JobCancelled()
                job.processed = index
                name = safe_name(upload.name)
                path = job.dir / "in" / str(index) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                upload.write_to(path)
                report(index / max(1, len(uploads)), f"Восстановление: {name}")
                outcomes.append(self._restore_one(job, path, total))
            job.files = outcomes
            job.processed = len(uploads)
            job.result = self._restore_result(job, total, outcomes)
            self.vault.log("restore", [o.out_name or o.name for o in outcomes if o.status != "error"],
                           {"Восстановлено": total.restored})
            self.vault.commit()
            job.state = "done"
            job.percent = 1.0
            report(1.0, "Готово")
            return job

    def _restore_one(self, job: Job, path: Path, total: "rs.RestoreStats") -> FileOutcome:
        kind = classify(path)
        outcome = FileOutcome(name=path.name, format=FORMAT_LABEL.get(kind, ""))
        problem = container_problem(path.name, path.read_bytes()[:16])
        if problem:
            outcome.add("error", problem)
            return outcome
        problem = unpacked_size_problem(path)
        if problem:
            outcome.add("error", problem)
            return outcome
        marker = read_vault_marker(path) if kind in ("OOXML", "PDF") else rs.read_text_marker(path) if kind == "TEXT" else ""
        if marker and marker not in self.vault.known_ids:
            outcome.add("error", "Файл обезличен другим хранилищем: другим компьютером или до очистки хранилища. Метки в нём "
                                 "означают другие значения, поэтому возврат остановлен. Загрузите резервную копию "
                                 "хранилища, в котором файл обезличивался (Настройки), и повторите.")
            return outcome
        restorer = rs.Restorer(self.vault)
        stem, ext = split_ext(path.name)
        stem = stem.replace(SUFFIX_ANON, "").replace("_anon", "")
        neutral = NEUTRAL_NAME.match(stem)
        original = self.vault.original_file_name(int(neutral.group(1))) if neutral else None
        if original:
            stem = split_ext(original)[0] + self._restored_name(stem[neutral.end():])
        else:
            stem = self._restored_name(stem)
        out_name = stem + SUFFIX_RESTORED + ext
        dst = job.dir / "out" / out_name
        counter = 2
        while dst.exists():
            dst = job.dir / "out" / f"{Path(out_name).stem} ({counter}){ext}"
            counter += 1
        try:
            if kind == "TEXT":
                rs.restore_text_file(path, dst, restorer)
            elif kind == "OOXML":
                if not rs.restore_ooxml(path, dst, restorer):
                    outcome.add("warn", "Структура файла после восстановления отличается от полученной.")
            elif kind == "PDF":
                rs.restore_pdf(path, dst, restorer)
            elif kind == "IMAGE":
                original = self.vault.original_image(hashlib.sha256(path.read_bytes()).hexdigest())
                if original is None:
                    outcome.add("error", "Эту картинку программа не обезличивала (или хранилище было очищено): оригинал не найден. "
                                         "Это может быть другая картинка или файл, обезличенный на другом компьютере: оригинал хранится только в хранилище, где файл был обезличен.")
                    return outcome
                dst = dst.with_suffix(".jpg" if original[:3] == b"\xff\xd8\xff" else (imagereplace.sniff(original) or ".png"))
                dst.write_bytes(original)
                outcome.out_name, outcome.out_path = dst.name, str(dst)
                outcome.add("info", "Картинка возвращена в исходном виде: закрашенные места восстановлены побайтно.")
                return outcome
            else:
                outcome.add("error", refusals.help_for_path(path))
                return outcome
        except Exception as exc:
            outcome.add("error", f"Не удалось обработать файл ({type(exc).__name__}). Возможно, он повреждён "
                                 "или защищён паролем.")
            return outcome
        stats = restorer.stats
        outcome.out_name, outcome.out_path = dst.name, str(dst)
        outcome.total = stats.restored
        outcome.tokens = sorted(stats.entities)
        outcome.counts = {"restored": stats.restored}
        ok, problem = verify.check_openable(dst)
        if not ok:
            outcome.out_path = ""
            outcome.add("error", problem)
            return outcome
        if problem:
            outcome.add("warn", problem)
        if stats.found == 0:
            outcome.add("warn", "В файле не найдено ни одной метки (Name1, Company1 и т.п.). Возможно, файл не был "
                                "обезличен этой программой или модель заменила метки.")
        if stats.unknown:
            listing = ", ".join(f"{t} ({n})" if n > 1 else t for t, n in sorted(stats.unknown.items())[:8])
            more = f" и ещё {len(stats.unknown) - 8}" if len(stats.unknown) > 8 else ""
            outcome.add("warn", f"Не удалось восстановить метки: {listing}{more}. Их нет в хранилище: "
                                "возможно, модель добавила их сама или файл обезличен на другом компьютере.")
        if stats.removed:
            outcome.add("warn", f"Секретные данные (пароли, ключи) удаляются безвозвратно и не восстанавливаются: "
                                f"{sum(stats.removed.values())} шт.")
        if stats.endings:
            outcome.add("warn", f"К меткам приклеены русские окончания ({stats.endings}): проверьте падежи в тексте.")
        if stats.loose:
            outcome.add("info", f"Меток с нарушенной записью возвращено: {stats.loose} (подчёркивания, пробел внутри метки и т.п.).")
        if stats.variant_fallback:
            outcome.add("info", f"У {stats.variant_fallback} меток номер написания не найден: подставлено основное написание.")
        if stats.finance:
            f = stats.finance
            if f.get("failed"):
                outcome.add("warn", "Суммы не удалось вернуть: записи о масштабировании не найдены или повреждены.")
            else:
                outcome.add("info", f"Суммы возвращены: без изменений {f.get('exact', 0)}, правки модели переведены в исходные единицы "
                                    f"{f.get('divided', 0)} (новых {f.get('new', 0)}). Формулы не менялись; Excel пересчитает их при открытии.")
                if stats.finance_changes:
                    outcome.add("info", "Что изменила модель: " + "; ".join(stats.finance_changes[:10])
                                + (f" и ещё {len(stats.finance_changes) - 10}" if len(stats.finance_changes) > 10 else ""))
                if f.get("missing"):
                    outcome.add("warn", f"Не найдено ячеек для возврата сумм: {f['missing']} (листы удалены или изменены).")
                for flag in stats.finance_flags[:12]:
                    outcome.add("warn", "Проверьте суммы: " + flag)
                if len(stats.finance_flags) > 12:
                    outcome.add("warn", f"Проверьте суммы: ещё {len(stats.finance_flags) - 12} ячеек без однозначного решения.")
        if stats.numbers:
            outcome.add("info", f"Возвращено чисел: {stats.numbers}. Формулы не менялись; Excel пересчитает их при открытии.")
        for fix in stats.sheet_fixes:
            outcome.add("warn", f"Имя листа исправлено под ограничения Excel: {fix}")
        # Остались ли токены в результате — самая полезная проверка: ничего не восстанавливается молча.
        try:
            leftover = set()
            for regex, email in ((TOKEN_RE, False), (EMAIL_TOKEN_RE, True)):
                for m in regex.finditer(extract_text(dst)):
                    kind, number, variant = parse_match(m, email=email)
                    # Только метки, которые хранилище знает: «company0» из исходного адреса — обычный текст.
                    canonical = format_token(kind, number, variant)
                    if m.group(0) == canonical and self.vault.lookup(kind, number, variant).status in ("ok", "variant_missing"):
                        leftover.add(m.group(0))
        except Exception:
            leftover = set()
        broken = self._broken_tokens(dst)
        if broken:
            outcome.add("warn", f"В файле остались метки с нарушенной записью: {', '.join(broken[:6])}. Исправьте их вручную "
                                "(например, Name 1 → Name1) и повторите возврат.")
        if leftover and not stats.unknown and not stats.removed:
            outcome.add("warn", f"В результате остались метки: {', '.join(sorted(leftover)[:6])}.")
        total.merge(stats)
        return outcome

    def _broken_tokens(self, path: Path) -> list[str]:
        """Похожее на метку, но записанное неверно. Пробел учитывается, только если такая метка есть в хранилище."""
        try:
            text = extract_text(path)
        except Exception:
            return []
        found = {m.group(0) for m in GLUED_TOKEN_RE.finditer(text)}
        for m in SPACED_TOKEN_RE.finditer(text):
            kind = next((k for k in KINDS if k.stem.lower() == m.group(1).lower()), None)
            if kind and self.vault.lookup(kind, int(m.group(2))).status in ("ok", "variant_missing", "removed"):
                found.add(m.group(0))
        return sorted(found)

    def _restored_name(self, stem: str) -> str:
        """Токены в имени файла: подчёркивание рядом с токеном — разделитель слов, а не часть токена."""
        namer = rs.Restorer(self.vault)
        edits = namer.matches(stem)
        taken = [(a, b) for a, b, _ in edits]
        for start, end, replacement in namer.matches(stem.replace("_", " ")):
            if not any(start < b and end > a for a, b in taken):
                edits.append((start, end, replacement))
        if not edits:
            return stem
        edits.sort()
        pieces, cursor = [], 0
        for start, end, replacement in edits:
            if start < cursor:
                continue
            pieces += [stem[cursor:start], replacement]
            cursor = end
        pieces.append(stem[cursor:])
        return "".join(pieces)

    def _restore_result(self, job: Job, stats: "rs.RestoreStats", outcomes: list[FileOutcome]) -> dict:
        sources = self._sources(stats)
        result = {"restored": stats.restored, "found": stats.found, "unknown": stats.unknown,
                  "numbers": stats.numbers, "sources": sources}
        target = next((o for o in outcomes if o.status != "error" and o.out_path), None)
        if target is None or not sources:
            return result
        main = sources[0]
        if main["missing"]:
            target.add("info", f"Из исходного файла «{main['name']}» в этом файле не встретились {main['missing']} из "
                               f"{main['total']} обезличенных значений{(': ' + ', '.join(main['missing_tokens'])) if main.get('missing_tokens') else ''}. "
                               "Если вы их не удаляли, проверьте результат работы модели.")
        strays = [x for x in sources[1:] if x["count"] <= 5]
        if strays and main["count"] >= 20 * max(x["count"] for x in strays):
            listing = ", ".join(f"«{x['name']}» ({x['count']})" for x in strays[:3])
            target.add("warn", f"Несколько меток относятся к другим ранее обезличенным файлам: {listing}. Если модель "
                               "добавила эти метки сама, они восстановлены неверно — проверьте результат.")
        elif len(sources) > 1:
            target.add("info", "Метки в файле относятся к нескольким исходным файлам: "
                               + ", ".join(f"«{x['name']}»" for x in sources[:4]) + ".")
        return result

    def _sources(self, stats: "rs.RestoreStats") -> list[dict]:
        """Из каких обезличенных файлов пришли восстановленные метки (жадное покрытие по журналу заданий)."""
        remaining = set(stats.entities)
        sources: list[dict] = []
        entries = [e for e in self.vault.history if e.get("kind") == "anonymize" and e.get("tokens")]
        while remaining:
            best, overlap = None, 0
            for entry in reversed(entries):
                count = len(remaining & set(entry["tokens"]))
                if count > overlap:
                    best, overlap = entry, count
            if best is None:
                break
            total = len(best["tokens"])
            matched = len(stats.entities & set(best["tokens"]))
            sources.append({"name": ", ".join(best.get("files", []))[:120], "total": total, "count": overlap,
                            "matched": matched, "missing": max(0, total - matched), "time": best.get("time"),
                            "missing_tokens": sorted(set(best["tokens"]) - stats.entities)[:8]})
            remaining -= set(best["tokens"])
        return sources

    # -- файлы результата -----------------------------------------------------

    def output_path(self, job_id: str, index: int) -> tuple[Path, str] | None:
        job = self.jobs.get(job_id)
        if not job or index >= len(job.files):
            return None
        outcome = job.files[index]
        if not outcome.out_path or outcome.status == "error" or not Path(outcome.out_path).is_file():
            return None
        return Path(outcome.out_path), outcome.out_name

    def zip_outputs(self, job_id: str) -> Path | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        archive = job.dir / ("Обезличенные файлы.zip" if job.kind == "anonymize" else "Восстановленные файлы.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for outcome in job.files:
                if outcome.out_path and outcome.status != "error" and Path(outcome.out_path).is_file():
                    z.write(outcome.out_path, outcome.out_name)
        return archive
