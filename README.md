# Accounting MAX Bot (Google Sheets)

Сервис на Python: раз в `POLL_INTERVAL_SECONDS` читает Google Таблицу через [gspread](https://github.com/burnash/gspread) (сервисный аккаунт) и шлёт уведомления бухгалтеру в MAX по значению в колонке `Бухгалтеру в чат` (или той, что задана в `TABLE_COMMAND_COLUMN`).

## Зависимости

- `maxapi` — отправка в MAX.
- `gspread` + `google-auth` — чтение таблицы по API.
- SQLite — дедупликация, чтобы не слать одно и то же при неизменной ячейке.

## Команды (пункты выпадающего списка)

Список в конфиге `CHAT_OPTIONS` в [config.py](config.py); в ячейку можно ввести любой непустой осмысленный текст в колонке команды.

## Google Cloud и доступ к таблице

1. Создать проект в [Google Cloud Console](https://console.cloud.google.com/), включить **Google Sheets API** (и при необходимости Drive API; для gspread с сервисным аккаунтом обычно достаточно тех же scope, что в коде).
2. Создать **сервисный аккаунт**, скачать JSON-ключ, сохранить рядом с ботом, например `service_account.json` (файл в [`.gitignore`](.gitignore), не коммитить).
3. Открыть Google Таблицу → **Доступ** → добавить **email** сервисного аккаунта из JSON (`client_email`) с ролью **Редактор** (или «Читатель», если боту достаточно чтения).
4. В `.env` указать:
   - `GOOGLE_SERVICE_ACCOUNT_FILE` — путь к JSON;
   - `GOOGLE_SPREADSHEET_ID` — id из URL: `https://docs.google.com/spreadsheets/d/<id>/edit`;
   - опционально `GOOGLE_SHEET_GID` — значение `gid` из URL вкладки (читать только этот лист);
   - либо `TABLE_SHEET_NAME` — имя вкладки;
   - иначе бот пытается взять все листы с именами «Январь»…«Декабрь»; если не находит — первый лист (см. логи).

## Установка и запуск

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# отредактировать .env: MAX_*, Google, при необходимости DATABASE_PATH
python run.py
```

Режим отладки без MAX: `SEND_MODE=console` — сообщения печатаются в консоль.

## Поведение

- Первый запуск с пустой БД по умолчанию **не** рассылает MAX: только заполняет снимок. Одноразовая рассылка текущих значений: удалить файл БД, выставить `BOOTSTRAP_SEND_MAX=true`, перезапустить, потом выключить флаг.
- Дедуп: пока нормализованный текст в колонке команды совпадает с сохранённым, повторных отправок нет. См. `DEDUP_STATUS_INFO_INTERVAL_SECONDS` в [config.py](config.py).
- `TABLE_COMMAND_SEND_EVERY_POLL=true` — на каждом опросе слать снова по всем строкам с валидной командой (риск спама).

## systemd

Примеры: [deploy/run-google-accounting-max.sh](deploy/run-google-accounting-max.sh) и [deploy/google-accounting-max.service](deploy/google-accounting-max.service). Подставьте реальный путь к клону репозитория в `WorkingDirectory` и `ExecStart`.

## Отличия от `yandex_sheets_max_bot`

Тот же цикл **scheduler** / **message_templates** / **dedup_store**, но источник — только Google Sheets API, без скачивания XLSX с Яндекса. БД по умолчанию: `data/google_accounting_max_bot.db`, чтобы не пересекаться с яндекс-ботом на одном сервере.
