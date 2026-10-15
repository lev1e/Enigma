# Разработка

## Окружение

Python 3.12. Основное окружение проекта называется `.venv312` (не в git).

```bash
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt          # то, что нужно для запуска
.venv312/bin/pip install -r requirements-build.txt    # плюс PyInstaller для сборки
.venv312/bin/python tools/fetch_office_js.py          # Office.js для панели add-in (в репозитории не хранится)
```

## Запуск

```bash
.venv312/bin/python main.py               # окно программы (фоновая программа запускается сама)
.venv312/bin/python main.py --serve       # только фоновая программа: хранилище и серверы, без окна
.venv312/bin/python tools/dev_server.py   # та же страница без окна, порт 8765, для правки внешнего вида
.venv312/bin/python tools/dev_addin_server.py  # панель Office с двойником Office.js, порт 8792
.venv312/bin/python tools/smoke_window.py # настоящий desktop.run(): одна копия, закрытие
```

## Тесты

```bash
.venv312/bin/python run_tests.py
.venv312/bin/python -m unittest discover -t . -s tests -p "test_*.py"   # то же, как в CI
.venv312/bin/python -m unittest tests.test_version_single_source        # один модуль
```

Полный набор идёт около 15 минут (на 14.10: 1717 тестов, 3 пропущены). Тесты, которым нужен pywebview, помечены `tests/_guards.requires_pywebview`; тесты с распознаванием пропускаются, если его нет.

## Проверки качества

- `tools/quality_gate.py` сравнивает результаты с `tests/eval/baseline.json` и завершается с ошибкой при ухудшении. Быстрый вариант: текстовые наборы v1, v2, английский и набор без персональных данных. Не нужен внешний корпус.
- `tools/quality_gate.py --full --jobs 2` добавляет картинки, закреплённый набор реальных документов и разбор находок. Нужен неотслеживаемый корпус (около 391 МБ, `tests/eval/real`, лежит только у владельца) и tesseract. Подробности: `tests/eval/README.md`.
- В CI: `.github/workflows/quality-gate.yml` (быстрые проверки на каждый push, тяжёлые ночью или вручную).

Инструменты оценки (`tools/`):

| Файл | Что делает |
|---|---|
| `eval_text.py` | Детектор на размеченном корпусе `tests/eval/text_corpus_v1.jsonl`: полнота, точность, утечки |
| `eval_docs.py` | Тот же корпус в виде настоящих файлов (docx, xlsx, pptx, pdf, txt, csv, html): обезличить, найти утечки, вернуть |
| `eval_images.py` | Картинки на синтетическом наборе: утечки, ложные закраски, точность возврата |
| `eval_noise.py` | Безобидные документы: программа не должна ничего заменять |
| `eval_real.py` | Реальные документы из `tests/eval/real_manifest.json` через весь конвейер (`run`, `report`, `publish`) |
| `eval_triage.py` | Разбор естественных находок по правилам |
| `eval_entities.py` | Покрытие видов данных по языкам и носителям |
| `eval_en_dense.py` | Быстрая проверка плотного английского набора |
| `eval_ids.py`, `eval_inject.py` | Помощники `eval_real.py`: синтетические личности и внедрение в документы |
| `fetch_real_corpus.py` | Скачать и проверить корпус реальных документов по SHA-256 |
| `ner_measure.py`, `ner_experiment.py` | Измерения необязательной нейросети для имён |
| `perf_compare.py` | Доказать, что ускорение не изменило находки |
| `finance_probe.py` | Маскирование сумм в xlsx |

## Сквозная проверка в окне

`tools/e2e_window.py` открывает настоящее окно (pywebview, только macOS), нажимает кнопки через JavaScript и проходит файлы. Системные окна «Открыть» и «Сохранить как» подменяются путями. Использует файлы из закрытой папки `case/`, поэтому запускать может только владелец. Снимки окон: `tools/shots_window.py`, `tools/usability_window.py`, `tools/chrome_shots.py` (тоже читают `case/`; готовые снимки наружу не отдавать).

## Сборка

Номер версии один: `anonymizer/__version__` в `anonymizer/__init__.py`. Остальное берётся из него (`pyproject.toml`, `tools/gen_version_info.py` пишет `packaging/version_info.txt`); тест `tests/test_version_single_source.py` это проверяет.

- macOS: `tools/release_mac.py`, подробности и ключ подписи в [docs/MAC_RELEASE.md](docs/MAC_RELEASE.md).
- Windows: `build_windows.ps1` локально или workflow `.github/workflows/windows-build.yml` (spec: `Anonymizer.spec`). Готовый файл запускается с `--selfcheck файл.json`. Проверка на настоящем Windows: [docs/superpowers/windows-verification.md](docs/superpowers/windows-verification.md).
- Порядок выпуска, подпись, контрольные суммы: [docs/superpowers/release-checklist.md](docs/superpowers/release-checklist.md).

## Работа в git worktree

Правила ([docs/superpowers/worker-rules.md](docs/superpowers/worker-rules.md)): свой worktree и своя ветка, менять только свои файлы; запускать только целевые тесты, не весь набор и не `e2e_window.py`; не больше `--jobs 2`; без загрузок и установок пакетов; интерпретатор брать из `.venv312` основной копии; любое утверждение подкреплять числом из названного инструмента. Корпус реальных документов в worktree подключается символьными ссылками, см. `tests/eval/README.md`. Папка `case/` закрытая: не читать, не копировать, не коммитить.
