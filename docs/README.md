# Документация

Оглавление всех документов проекта. Номер версии берётся из `anonymizer/__init__.py`; в документах он не повторяется.

## Для пользователей

| Документ | О чём |
|---|---|
| [../README.md](../README.md) | Что делает программа, установка, ограничения |
| [../QUICKSTART.md](../QUICKSTART.md) | Быстрый старт: обезличить и вернуть файл |
| [WINDOWS_INSTALL.md](WINDOWS_INSTALL.md) | Установка на Windows, подключение к Word, Excel, PowerPoint |
| [MAC_RELEASE.md](MAC_RELEASE.md) | Выпуск для macOS: сборка, подпись, лента обновлений |
| [Enigma_instruction.docx](Enigma_instruction.docx) | Инструкция в формате Word |

## Для разработчиков

| Документ | О чём |
|---|---|
| [../DEVELOPMENT.md](../DEVELOPMENT.md) | Окружение, запуск, тесты, проверки качества, сборка |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | Устройство программы |
| [../SECURITY.md](../SECURITY.md) | Модель угроз, что уходит по сети, пределы гарантий |
| [../CHANGELOG.md](../CHANGELOG.md) | История изменений |
| [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | Сторонние библиотеки в программе |
| [superpowers/worker-rules.md](superpowers/worker-rules.md) | Правила работы в git worktree |

## Возможности (docs/features)

| Документ | О чём |
|---|---|
| [features/chat.md](features/chat.md) | Чаты: файлы, версии, таблица замен |
| [features/ai-editing.md](features/ai-editing.md) | Правка docx, pptx, xlsx и текстовых файлов через ИИ, версии, лимиты |
| [features/providers-and-policy.md](features/providers-and-policy.md) | Провайдеры ИИ, свой адрес, выбор модели, секреты, `policy.json` |
| [features/preview-panel.md](features/preview-panel.md) | Панель просмотра файла |
| [features/office-addin.md](features/office-addin.md) | Панель в Word, Excel, PowerPoint |
| [features/folders.md](features/folders.md) | Обработка папки целиком |
| [features/images-and-ocr.md](features/images-and-ocr.md) | Картинки, сканы, OCR |
| [features/refusals.md](features/refusals.md) | Отказы по формату |

## Качество и выпуск

| Документ | О чём |
|---|---|
| [superpowers/release-checklist.md](superpowers/release-checklist.md) | Чек-лист выпуска, подпись, контрольные суммы |
| [superpowers/windows-verification.md](superpowers/windows-verification.md) | Пошаговая проверка на настоящем Windows |
| [superpowers/status-2026-10-14.md](superpowers/status-2026-10-14.md) | Последний статус: тесты, проверки, что не исправлено (раньше: `status-2026-10-12.md`, `status-2026-10-13.md`) |
| [superpowers/quality-matrix.md](superpowers/quality-matrix.md), [eval-failures.md](superpowers/eval-failures.md), [eval-natural-hits.md](superpowers/eval-natural-hits.md) | Создаются `tools/eval_real.py report` |
| [../tests/eval/README.md](../tests/eval/README.md) | Наборы для проверки качества, как их запускать |
| [superpowers/hygiene-audit-2026-10-15.md](superpowers/hygiene-audit-2026-10-15.md) | Аудит порядка в репозитории |

## Заметки по проектированию и исследованию (docs/superpowers)

Дизайн: `design-ai-editing.md`, `design-chat-13.md`, `design-flow-u1.md`, `specs/` (add-in, чаты), `research-chat-ui.md`, `research-reuse.md`.
Качество и безопасность: `audit-0810-formats.md`, `security-audit.md`, `leak-sweep-0910.md`, `hunt-findings.md`, `ui-audit-0910.md`, `audit/` (рабочие аудиты), `entity-coverage.md`, `en-eval-0910.md`, `ocr-evaluation.md`.
Темы: `finance-*.md` (маскирование сумм), `ner-*.md` (нейросеть для имён), `queue.md`, `handoff-orchestrator-9.md` и `prompt-orchestrator-9.md` (текущая передача дел).

## Архив (docs/archive)

Рабочие материалы завершённых этапов. Они не описывают текущее поведение, но по ним можно восстановить, почему что-то сделано.

| Что | Где |
|---|---|
| Передача дел версии 2.0 | `archive/HANDOFF-2.0.md` |
| Промпты и передачи оркестратора (`prompt-*`, `handoff-*`), задания (`brief-*`, `requests-*`) | `archive/superpowers-notes/` |
| Отчёты рабочих по этапам (`s6a-report.md` ... `s13a-report.md`, `w*`, `p*`, `u*`), контракт `p2b-contract.md` | `archive/superpowers-notes/` |
| Снимки экрана этапов (`shots-s9d`, `shots-u1` и т.д.) | `archive/shots/` |

Как найти старый отчёт: имя файла совпадает с названием этапа в сообщениях коммитов (`S9D: ...` значит `archive/superpowers-notes/s9d-report.md`, снимки `archive/shots/shots-s9d/`). Поиск: `git log --oneline --grep "S9D"` или `git grep -il "ключевое слово" docs/archive`.
Содержимое снимков экрана сделано на проверочных документах; перед публикацией репозитория просмотрите их.
