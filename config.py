"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Явно из каталога проекта (не из cwd), затем при необходимости MAX_CHAT_ID из соседнего yandex-бота.
load_dotenv(BASE_DIR / ".env")


def _maybe_max_chat_from_yandex() -> None:
    """Если MAX_CHAT_ID не задан или 0 — взять из ../yandex_sheets_max_bot/.env (тот же чат)."""
    raw = (os.getenv("MAX_CHAT_ID") or "").strip()
    if raw and raw != "0":
        return
    yandex_env = BASE_DIR.parent / "yandex_sheets_max_bot" / ".env"
    if not yandex_env.is_file():
        return
    vals = dotenv_values(yandex_env)
    cid = (vals.get("MAX_CHAT_ID") or "").strip()
    if cid and cid != "0":
        os.environ["MAX_CHAT_ID"] = cid


_maybe_max_chat_from_yandex()


def _as_bool(raw: str, default: bool = False) -> bool:
    value = (raw or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


# Google Sheets (service account JSON: enable Sheets API, share the spreadsheet with the account email)
GOOGLE_SERVICE_ACCOUNT_FILE: str = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "service_account.json"),
)
# Document id from https://docs.google.com/spreadsheets/d/<id>/edit
_DEFAULT_SPREADSHEET_ID: str = "1FtaQnep10k2yHW7krpVmB4uyMTn450ewmdVbXtgHyOM"
GOOGLE_SPREADSHEET_ID: str = (os.getenv("GOOGLE_SPREADSHEET_ID", "") or _DEFAULT_SPREADSHEET_ID).strip()
# Tab id from the URL (gid=...). If set, only this tab is read (overrides TABLE_SHEET_NAME / month list).
_ggid = (os.getenv("GOOGLE_SHEET_GID", "") or os.getenv("GOOGLE_SHEET_ID", "")).strip()
GOOGLE_WORKSHEET_GID: int | None = int(_ggid) if _ggid else None

MAX_BOT_TOKEN: str = os.getenv("MAX_BOT_TOKEN", "")
MAX_CHAT_ID: int = int(os.getenv("MAX_CHAT_ID", "0") or "0")
MAX_SSL_VERIFY: bool = _as_bool(os.getenv("MAX_SSL_VERIFY", "true"), default=True)
SEND_MODE: str = os.getenv("SEND_MODE", "max").strip().lower()

POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
# Один цикл чтения Google Sheet (gspread в thread); при превышении — ошибка в лог.
TABLE_LOAD_TIMEOUT_SECONDS: float = float(os.getenv("TABLE_LOAD_TIMEOUT_SECONDS", "180") or "180")
RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "2"))
RETRY_DELAY_SECONDS: int = int(os.getenv("RETRY_DELAY_SECONDS", "2"))

DATABASE_PATH: str = os.getenv(
    "DATABASE_PATH",
    str(BASE_DIR / "data" / "google_accounting_max_bot.db"),
)
BOOTSTRAP_SEND_MAX: bool = _as_bool(os.getenv("BOOTSTRAP_SEND_MAX", "false"), default=False)

TABLE_SHEET_NAME: str = os.getenv("TABLE_SHEET_NAME", "").strip()
TABLE_COMMAND_COLUMN: str = os.getenv("TABLE_COMMAND_COLUMN", "Бухгалтеру в чат").strip()
TABLE_COMMAND_SEND_EVERY_POLL: bool = _as_bool(
    os.getenv("TABLE_COMMAND_SEND_EVERY_POLL", "false"), default=False
)
DEDUP_STATUS_INFO_INTERVAL_SECONDS: int = max(
    0, int(os.getenv("DEDUP_STATUS_INFO_INTERVAL_SECONDS", "600") or "0")
)

UPD_MESSAGE_BRAND: str = os.getenv("UPD_MESSAGE_BRAND", "").strip()

MONTH_SHEET_NAMES: tuple[str, ...] = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)

# Пункты выпадающего списка в шаблоне; бот шлёт уведомление по любому непустому тексту
# в колонке TABLE_COMMAND_COLUMN (не обязан совпадать с этим списком).
CHAT_OPTIONS: list[str] = [
    "Альфа, Счет, Маршрут",
    "Альфа, Счет, УПД, Маршрут",
    "Альфа, Счет",
    "Альфа, Счет, УПД",
    "Точка, Счет, Маршрут",
    "Точка, Счет, УПД, Маршрут",
    "Точка, Счет",
    "Точка, Счет, УПД",
    "ИП Точка, Счет, Маршрут",
    "ИП Точка, Счет, Акт, Маршрут",
    "УПД к Счету",
    "Точка Полная Инф",
]
