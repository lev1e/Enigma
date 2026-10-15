# Third-party notices

Anonymizer bundles the following third-party software in `anonymizer/web/vendor/`.
It runs fully offline; none of these components contact any network.

| Component | Version | Copyright | Licence |
|---|---|---|---|
| DOMPurify | 3.4.17 | Cure53 (Mario Heiderich) and other contributors | Apache License 2.0 (dual MPL-2.0; Apache-2.0 elected) |
| marked | 18.1.1 | MarkedJS; Christopher Jeffrey | MIT License |
| highlight.js | 11.11.1 | Ivan Sagalaev and contributors | BSD 3-Clause License |

Full licence texts: `anonymizer/web/vendor/licenses/`. File hashes, sources and sizes: `anonymizer/web/vendor/MANIFEST.json`.

## Python-зависимости

Список составлен по `requirements.txt`, `requirements-build.txt` и метаданным установленных пакетов (`.venv312/.../*.dist-info/METADATA`). Лицензии указаны только те, что названы в метаданных пакета. Тексты лицензий пакетов лежат в их `dist-info` и не копируются в `vendor/licenses/`.

Прямые зависимости (`requirements.txt`):

- cryptography 46.0.0: Apache-2.0 OR BSD-3-Clause
- lxml 6.1.1: BSD-3-Clause
- openpyxl 3.1.5: MIT
- python-docx 1.2.0: MIT
- python-pptx 1.0.2: MIT
- PyMuPDF 1.26.6: двойная лицензия GNU AGPL 3.0 или коммерческая Artifex. **Требует проверки владельцем** (см. ниже).
- Pillow 12.3.0: MIT-CMU
- pymorphy3 2.0.6: MIT; pymorphy3-dicts-ru 2.4.417150.4580142: MIT
- pywebview 6.2.1: BSD-3-Clause
- pythonnet 3.0.5 (только Windows): лицензия в репозитории и в установленном окружении не указана (пакет не установлен на macOS). Не проверено.
- natasha 1.6.0 (по желанию, `anonymizer/ner.py`): MIT. **Требует проверки владельцем** (см. ниже).

Транзитивные зависимости, установленные в окружении, и их лицензии по метаданным:

- numpy 2.5.4: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0
- et_xmlfile 2.0.0: MIT; xlsxwriter 3.2.9: BSD-2-Clause; typing_extensions 4.16.0: PSF-2.0
- cffi 2.1.1: MIT-0; pycparser 3.0: BSD-3-Clause
- pymorphy2 0.9.1, pymorphy2-dicts-ru, DAWG-Python 0.7.2, dawg2-python 0.9.0, docopt 0.6.2: MIT
- slovnet 0.6.0, navec 0.10.0, razdel 0.5.0, yargy 0.16.0, ipymarkup 0.9.0: MIT
- intervaltree 3.2.1: Apache-2.0; sortedcontainers 2.4.0: Apache-2.0
- proxy_tools 0.1.0, bottle 0.13.4: MIT
- pyobjc-core и фреймворки pyobjc 12.2.2 (macOS, нужны pywebview): MIT

Сборка (`requirements-build.txt`, в программу как библиотека не входит):

- PyInstaller 6.15.0: GPLv2-or-later с особым исключением, разрешающим собирать и распространять программы любой лицензии; pyinstaller-hooks-contrib 2026.8: Apache-2.0 и GPLv2 (по метаданным); altgraph, macholib, setuptools, packaging: MIT/Apache-2.0/BSD.

Не входит в этот перечень и не проверено: лицензия весов моделей natasha/slovnet (пакеты `slovnet`, `navec` содержат код, веса моделей скачиваются или лежат отдельно), лицензия и состав Office.js (Microsoft, подробности в `docs/superpowers/release-checklist.md` и `tools/fetch_office_js.py`), шрифтов, входящих в установщик.

### Нужна проверка владельцем

- **PyMuPDF (AGPL-3.0 или коммерческая Artifex):** распространение собранной программы с PyMuPDF под AGPL накладывает условия на всю программу (исходный код для пользователей, в том числе при сетевом доступе). Нужно решить: коммерческая лицензия Artifex или соблюдение AGPL. В репозитории решение не зафиксировано.
- **natasha / slovnet:** код пакетов под MIT, но происхождение обучающих данных моделей (новостные корпуса) и лицензия данных не подтверждены (`docs/superpowers/status-2026-10-14.md`, `docs/superpowers/ner-experiment.md`).
- **pythonnet (Windows):** лицензия не названа в репозитории.
