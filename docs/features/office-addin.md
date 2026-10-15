# Add-in для Word, Excel и PowerPoint

## Что это

Панель внутри Office. Она читает открытый файл (`getFileAsync`), отправляет движку, вставляет обезличенный или восстановленный результат (Word: тело, колонтитулы по разделам, свойства; Excel: листы и имена книги; PowerPoint: слайды), заново читает документ и сверяет его с результатом. Распознавание остаётся в `Service`. Установка: [../WINDOWS_INSTALL.md](../WINDOWS_INSTALL.md). Проект: `docs/superpowers/specs/2026-10-02-office-addin-design.md`.

## Как пользоваться

1. Установите программу; add-in подключается без прав администратора (Windows: `HKCU\Software\Microsoft\Office\16.0\WEF\Developer`, macOS: папка `wef` каждого приложения Office; `addin_install.py`).
2. Перезапустите Office; панель Anonymizer появляется на ленте.
3. Фоновая программа должна работать: автозапуск включается при установке (Windows: ключ `Run`, macOS: LaunchAgent `com.anonymizer.helper`).
4. В панели обезличьте или восстановите открытый документ; панель сверит результат.

## Безопасность и настройки

- Страница панели: `https://127.0.0.1:47831` (порт `addin.ADDIN_PORT`; если занят, окно программы сообщает об этом).
- Локальный корневой сертификат «Anonymizer local add-in CA», ограничен именами `localhost` и `127.0.0.1`, срок 3650 дней, сертификат сервера 397 дней, обновление за 45 дней (`certs.py`). Ставится в доверенные для текущего пользователя.
- Каждый запрос проверяется: `Host`, `Origin`, `Sec-Fetch-Site`, `X-Requested-With`, токен установки (`X-Addin-Token`).
- Копии оригинала до замены хранятся зашифрованными ключом устройства: не более 20 штук (`KEEP_BACKUPS`), срок 7 дней.
- Маршрутов ИИ в add-in нет; чаты общие с окном (`chat_api`).
- Office.js скачивается при сборке (`tools/fetch_office_js.py`), в репозиторий не входит.

## Пределы

Office сам записывает имя пользователя в свойства при сохранении; панель предупреждает об этом. Не проверено на настоящем Office (`docs/superpowers/status-2026-10-14.md`), установщик и Windows-ветки тоже.

## Где в коде

`anonymizer/addin.py` (сервер и API), `addin_install.py`, `certs.py`, `anonymizer/addin_web/` (`taskpane.html/css/js`, manifest-шаблоны, значки), `tools/dev_addin_server.py`, `tools/fake_office.js`.

## Тесты

`tests/test_addin.py`, `test_addin_chat.py`, `test_addin_chat_settings.py`, `test_addin_design_s9d.py`, `test_addin_rollback.py`, `test_dev_addin_server.py`, `test_ws_addin2.py`, `test_spec_datas.py`.
