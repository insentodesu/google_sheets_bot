"""Load rows from Google Sheets via gspread (service account)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None


def normalize_header(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\n", " ").replace("\r", " ")
    return " ".join(text.split()).strip()


def normalize_cell(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ").replace("\r", " ").replace("\n", " ")
    return " ".join(text.split()).strip()


def _sheet_name_match_key(name: str) -> str:
    return normalize_header(name).casefold()


def _get_gspread_client() -> gspread.Client:
    global _client
    if _client is None:
        path = config.GOOGLE_SERVICE_ACCOUNT_FILE
        creds = Credentials.from_service_account_file(path, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


@dataclass(slots=True)
class SpreadsheetRow:
    sheet_name: str
    row_number: int
    values: dict[str, str]


def _build_spreadsheet_rows(
    sheet_name: str,
    rows: list[list[Any]] | list[tuple[Any, ...]],
) -> list[SpreadsheetRow]:
    if not rows:
        return []
    headers = [normalize_header(cell) for cell in rows[0]]
    dup_count = Counter(h for h in headers if h)
    for h, c in dup_count.items():
        if c > 1:
            logger.warning(
                "Дублируется заголовок столбца после нормализации: %r (%s раз). "
                "Значения в dict ячеек перезаписываются — колонка «%s» может читаться не из той ячейки.",
                h,
                c,
                config.TABLE_COMMAND_COLUMN,
            )
    result: list[SpreadsheetRow] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(normalize_cell(cell) for cell in row):
            continue
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        values = {
            headers[idx]: normalize_cell(padded[idx])
            for idx in range(len(headers))
            if headers[idx]
        }
        result.append(
            SpreadsheetRow(
                sheet_name=sheet_name,
                row_number=row_number,
                values=values,
            )
        )
    return result


class TableClient:
    """Reads data from a Google spreadsheet using a service account."""

    def __init__(
        self,
        spreadsheet_id: str | None = None,
        sheet_name: str | None = None,
        command_column: str | None = None,
    ) -> None:
        self.spreadsheet_id = (spreadsheet_id or config.GOOGLE_SPREADSHEET_ID).strip()
        self.sheet_name = (sheet_name or config.TABLE_SHEET_NAME).strip()
        self.command_column = normalize_header(command_column or config.TABLE_COMMAND_COLUMN)

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        try:
            return _get_gspread_client().open_by_key(self.spreadsheet_id)
        except PermissionError:
            hint = ""
            try:
                with open(config.GOOGLE_SERVICE_ACCOUNT_FILE, encoding="utf-8") as f:
                    mail = json.load(f).get("client_email")
                if isinstance(mail, str) and mail:
                    hint = f' Добавьте доступ к книге этому аккаунту: "{mail}".'
            except (OSError, ValueError):
                pass
            logger.error(
                "Отказ Google API (нет прав на книгу или неверный id). Обычно: «Настройки доступа» "
                "к таблице → пригласить email из поля client_email в JSON ключе.%s Файл ключа: %s",
                hint,
                config.GOOGLE_SERVICE_ACCOUNT_FILE,
            )
            raise

    def _select_worksheets(self, spreadsheet: gspread.Spreadsheet) -> list[gspread.Worksheet]:
        all_ws = spreadsheet.worksheets()
        if not all_ws:
            logger.info("В книге нет листов")
            return []
        names_list = [ws.title for ws in all_ws]
        if config.GOOGLE_WORKSHEET_GID is not None:
            try:
                ws = spreadsheet.get_worksheet_by_id(int(config.GOOGLE_WORKSHEET_GID))
            except gspread.WorksheetNotFound as exc:
                raise ValueError(
                    f"Лист с gid={config.GOOGLE_WORKSHEET_GID!r} не найден. "
                    f"Листы: {','.join(names_list)}"
                ) from exc
            logger.info(
                "Google Sheets: в книге %s лист(ов) | выбран один лист по GOOGLE_SHEET_GID: %s",
                len(all_ws),
                ws.title,
            )
            return [ws]

        if self.sheet_name:
            want = _sheet_name_match_key(self.sheet_name)
            for w in all_ws:
                if _sheet_name_match_key(w.title) == want:
                    logger.info(
                        "Google Sheets: в книге %s лист(ов) | выбран один лист по TABLE_SHEET_NAME: %s",
                        len(all_ws),
                        w.title,
                    )
                    return [w]
            try:
                w = spreadsheet.worksheet(self.sheet_name)
            except gspread.WorksheetNotFound as exc:
                raise ValueError(
                    f"TABLE_SHEET_NAME={self.sheet_name!r} не совпал ни с одним листом. "
                    f"Доступные: {','.join(names_list)}"
                ) from exc
            logger.warning(
                "Точного совпадения по ключу нет, используется gspread.worksheet(%r)",
                self.sheet_name,
            )
            return [w]

        by_key: dict[str, gspread.Worksheet] = {}
        for w in all_ws:
            k = _sheet_name_match_key(w.title)
            if k:
                by_key[k] = w

        month_sheets: list[gspread.Worksheet] = []
        for month in config.MONTH_SHEET_NAMES:
            k = _sheet_name_match_key(month)
            if k in by_key:
                month_sheets.append(by_key[k])

        if month_sheets:
            logger.info(
                "Google Sheets: листы в книге (%s): %s | для опроса выбрано месяцев: %s — %s",
                len(all_ws),
                ",".join(names_list),
                len(month_sheets),
                ",".join(w.title for w in month_sheets),
            )
            if len(month_sheets) < 12:
                logger.info(
                    "В книге найдено %s месячных листов из 12 (остальные имена не совпали).",
                    len(month_sheets),
                )
            return month_sheets

        if names_list:
            logger.warning(
                "Ни один лист не совпал с именами Январь…Декабрь (без учёта регистра и лишних пробелов). "
                "В файле: %s. Читается только первый лист %r. "
                "Переименуйте листы, задайте TABLE_SHEET_NAME или GOOGLE_SHEET_GID из URL.",
                ",".join(names_list),
                names_list[0],
            )
            return [all_ws[0]]
        return []

    def _get_rows_sync(self) -> list[SpreadsheetRow]:
        if not self.spreadsheet_id:
            raise ValueError("GOOGLE_SPREADSHEET_ID is not configured")
        spreadsheet = self._get_spreadsheet()
        worksheets = self._select_worksheets(spreadsheet)
        result: list[SpreadsheetRow] = []
        for ws in worksheets:
            rows = ws.get_all_values()
            result.extend(_build_spreadsheet_rows(ws.title, rows))
        return result

    async def get_rows(self) -> list[SpreadsheetRow]:
        return await asyncio.to_thread(self._get_rows_sync)

    async def get_actionable_rows(self) -> list[SpreadsheetRow]:
        rows = await self.get_rows()
        return [row for row in rows if normalize_cell(row.values.get(self.command_column, ""))]
