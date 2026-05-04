"""Polling loop for accountant notifications."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

from aiohttp import TCPConnector
from maxapi import Bot
from maxapi.client.default import DefaultConnectionProperties
from maxapi.enums.parse_mode import ParseMode

import config
import dedup_store
from logging_config import setup_logging
from message_templates import (
    build_message,
    command_column_fingerprint,
    command_dedup_signature,
    stored_command_dedup_key,
)
from table_client import TableClient, normalize_header

setup_logging()
logger = logging.getLogger(__name__)

_last_dedup_status_log_at: float = 0.0


def _maybe_log_dedup_no_send_hint(skipped_same_command: int) -> None:
    """Редкое INFO: при дедупе без отправок — текст в ячейке не менялся; новое уведомление пойдёт после смены."""
    global _last_dedup_status_log_at
    interval = config.DEDUP_STATUS_INFO_INTERVAL_SECONDS
    if interval <= 0 or skipped_same_command <= 0:
        return
    now = time.monotonic()
    if _last_dedup_status_log_at > 0.0 and (now - _last_dedup_status_log_at) < interval:
        return
    _last_dedup_status_log_at = now
    logger.info(
        "Уведомлений нет: текст в колонке «%s» у %s строк совпадает с уже сохранённым в БД (дедуп). "
        "Чтобы отправить снова — поменяйте значение в Google Таблице либо сбросьте снимок (rm %s) с BOOTSTRAP_SEND_MAX. "
        "(Подсказка не чаще чем раз в %s с — DEDUP_STATUS_INFO_INTERVAL_SECONDS.)",
        config.TABLE_COMMAND_COLUMN,
        skipped_same_command,
        config.DATABASE_PATH,
        interval,
    )


def create_bot() -> Bot:
    default_conn = None
    if not config.MAX_SSL_VERIFY:
        default_conn = DefaultConnectionProperties(connector=TCPConnector(ssl=False))
    return Bot(token=config.MAX_BOT_TOKEN, default_connection=default_conn)


async def send_accounting_message(bot: Bot | None, text: str) -> bool:
    if config.SEND_MODE == "console":
        logger.info("Тестовое сообщение в консоль:\n%s", text)
        print(text, flush=True)
        return True

    for attempt in range(config.RETRY_ATTEMPTS):
        try:
            if bot is None:
                raise RuntimeError("MAX bot is not initialized")
            await bot.send_message(
                chat_id=config.MAX_CHAT_ID,
                text=text,
                format=ParseMode.HTML,
            )
            return True
        except Exception as exc:
            logger.warning(
                "Ошибка отправки в MAX (попытка %s/%s): %s",
                attempt + 1,
                config.RETRY_ATTEMPTS,
                exc,
            )
            if attempt < config.RETRY_ATTEMPTS - 1:
                await asyncio.sleep(config.RETRY_DELAY_SECONDS)
    return False


async def process_pending_rows(bot: Bot | None, client: TableClient | None = None) -> int:
    table_client = client or TableClient()
    sent_count = 0
    is_initialized = dedup_store.snapshot_initialized()
    was_initialized = is_initialized
    previous_snapshot = dedup_store.load_snapshot()
    next_snapshot: list[dedup_store.SnapshotEntry] = []
    skipped_same_command = 0

    command_header_key = normalize_header(config.TABLE_COMMAND_COLUMN)

    logger.info("Загрузка таблицы из источника…")
    try:
        rows = await asyncio.wait_for(
            table_client.get_rows(),
            timeout=config.TABLE_LOAD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Таймаут загрузки таблицы (%s с): сеть/Google API или очень большой лист. "
            "Увеличьте TABLE_LOAD_TIMEOUT_SECONDS в .env",
            config.TABLE_LOAD_TIMEOUT_SECONDS,
        )
        raise

    missing_with_command = 0
    if was_initialized:
        for row in rows:
            rk = dedup_store.build_row_key(row.sheet_name, row.row_number)
            ds = command_dedup_signature(
                str(row.values.get(command_header_key, "")).strip()
            )
            if not ds:
                continue
            if rk not in previous_snapshot:
                missing_with_command += 1

    silent_catchup_bulk_missing = (
        config.CATCHUP_SILENT_MISSING_ROWS_THRESHOLD > 0
        and was_initialized
        and missing_with_command > config.CATCHUP_SILENT_MISSING_ROWS_THRESHOLD
        and not config.TABLE_COMMAND_SEND_EVERY_POLL
    )
    if silent_catchup_bulk_missing:
        logger.warning(
            "Строк с «%s», которых нет в SQLite-снимке: %s (порог тихого догона %s). "
            "Уведомления в MAX только если меняется значение у строки уже из снимка; "
            "остальное записываем без отправки.",
            config.TABLE_COMMAND_COLUMN,
            missing_with_command,
            config.CATCHUP_SILENT_MISSING_ROWS_THRESHOLD,
        )

    catchup_rows_recorded = 0
    for row in rows:
        sheet_disp = dedup_store.canonical_sheet_title_for_dedup(row.sheet_name)
        row_key = dedup_store.build_row_key(row.sheet_name, row.row_number)
        previous_command = previous_snapshot.get(
            row_key,
            dedup_store.SnapshotEntry(
                row_key=row_key,
                sheet_name=sheet_disp,
                row_number=row.row_number,
                command="",
            ),
        ).command
        raw_command = row.values.get(command_header_key, "").strip()
        dedup_sig = command_dedup_signature(raw_command)

        if not dedup_sig:
            continue

        if not is_initialized and not config.BOOTSTRAP_SEND_MAX:
            next_snapshot.append(
                dedup_store.SnapshotEntry(
                    row_key=row_key,
                    sheet_name=sheet_disp,
                    row_number=row.row_number,
                    command=dedup_sig,
                )
            )
            continue

        if dedup_sig == stored_command_dedup_key(previous_command) and not config.TABLE_COMMAND_SEND_EVERY_POLL:
            skipped_same_command += 1
            next_snapshot.append(
                dedup_store.SnapshotEntry(
                    row_key=row_key,
                    sheet_name=sheet_disp,
                    row_number=row.row_number,
                    command=dedup_sig,
                )
            )
            continue

        if silent_catchup_bulk_missing and row_key not in previous_snapshot:
            catchup_rows_recorded += 1
            next_snapshot.append(
                dedup_store.SnapshotEntry(
                    row_key=row_key,
                    sheet_name=sheet_disp,
                    row_number=row.row_number,
                    command=dedup_sig,
                )
            )
            continue

        try:
            text = build_message(raw_command, row.values, command_column_key=command_header_key)
        except Exception:
            logger.exception(
                "Строка %s листа %s: ошибка сборки текста сообщения (проверьте данные строки)",
                row.row_number,
                row.sheet_name,
            )
            next_snapshot.append(
                dedup_store.SnapshotEntry(
                    row_key=row_key,
                    sheet_name=sheet_disp,
                    row_number=row.row_number,
                    command=dedup_sig,
                )
            )
            continue

        if not await send_accounting_message(bot, text):
            logger.error("Не удалось отправить строку %s листа %s", row.row_number, row.sheet_name)
            next_snapshot.append(
                dedup_store.SnapshotEntry(
                    row_key=row_key,
                    sheet_name=sheet_disp,
                    row_number=row.row_number,
                    command=previous_command if previous_command else "",
                )
            )
            continue

        next_snapshot.append(
            dedup_store.SnapshotEntry(
                row_key=row_key,
                sheet_name=sheet_disp,
                row_number=row.row_number,
                command=dedup_sig,
            )
        )
        sent_count += 1
        logger.info(
            "Отправлено уведомление sheet=%s row=%s command=%s",
            row.sheet_name,
            row.row_number,
            raw_command,
        )

    dedup_store.replace_snapshot(next_snapshot)

    rows_with_command = sum(
        1
        for r in rows
        if command_dedup_signature(str(r.values.get(command_header_key, "")).strip())
    )
    cmd_fp = command_column_fingerprint(rows, command_header_key)
    logger.info(
        "Опрос: строк в файле=%s, с заполненным «%s»=%s, отправлено в MAX=%s, cmd_fp=%s | "
        "дедуп: было ключей=%s, в новом снимке=%s, совпало с прошлым=%s | "
        "нет в снимке с командой=%s, тихо записано при догоне=%s",
        len(rows),
        config.TABLE_COMMAND_COLUMN,
        rows_with_command,
        sent_count,
        cmd_fp,
        len(previous_snapshot),
        len(next_snapshot),
        skipped_same_command,
        missing_with_command,
        catchup_rows_recorded,
    )

    if (
        was_initialized
        and sent_count >= 40
        and skipped_same_command == 0
        and rows_with_command >= 80
    ):
        logger.warning(
            "За один опрос отправлено %s сообщений и ни одна строка не совпала с предыдущим снимком — "
            "обычно так бывает при пустом/битом SQLite или после смены логики ключей листов. "
            "Проверьте «строк в снимке» при старте и при необходимости сделайте тихий сброс: "
            "stop → rm %s → start при BOOTSTRAP_SEND_MAX=false.",
            sent_count,
            config.DATABASE_PATH,
        )

    # Обычное состояние после рассылки: таблица не менялась — не засоряем journalctl WARNING каждые N секунд.
    if (
        sent_count == 0
        and rows_with_command > 0
        and was_initialized
        and skipped_same_command > 0
    ):
        _maybe_log_dedup_no_send_hint(skipped_same_command)
        logger.debug(
            "Отправок нет: для %s строк «%s» совпадает с SQLite (дедуп). Чтобы снова разослать текущие "
            "значения — rm %s и рестарт с BOOTSTRAP_SEND_MAX=true; иначе смените пункт в таблице.",
            skipped_same_command,
            config.TABLE_COMMAND_COLUMN,
            config.DATABASE_PATH,
        )

    return sent_count


async def run_scheduler_loop() -> None:
    if config.SEND_MODE not in {"max", "console"}:
        logger.error("SEND_MODE должен быть max или console")
        sys.exit(1)
    if config.SEND_MODE == "max" and not config.MAX_BOT_TOKEN:
        logger.error("MAX_BOT_TOKEN не задан")
        sys.exit(1)
    if config.SEND_MODE == "max" and not config.MAX_CHAT_ID:
        logger.error("MAX_CHAT_ID не задан")
        sys.exit(1)
    sa_path = Path(config.GOOGLE_SERVICE_ACCOUNT_FILE)
    if not sa_path.is_file():
        logger.error("Файл сервисного аккаунта не найден: %s (GOOGLE_SERVICE_ACCOUNT_FILE)", sa_path)
        sys.exit(1)
    if not config.GOOGLE_SPREADSHEET_ID:
        logger.error("GOOGLE_SPREADSHEET_ID не задан")
        sys.exit(1)
    if config.GOOGLE_WORKSHEET_GID is not None:
        sheet_mode = f"gid={config.GOOGLE_WORKSHEET_GID}"
    elif config.TABLE_SHEET_NAME:
        sheet_mode = f"sheet={config.TABLE_SHEET_NAME!r}"
    else:
        sheet_mode = "месячные листы (или первый, если нет совпадений)"

    dedup_store.init_db()
    dedup_store.ensure_bound_google_spreadsheet(config.GOOGLE_SPREADSHEET_ID)
    dedup_store.ensure_month_sheet_row_keys_canonical()
    snap_init = dedup_store.snapshot_initialized()
    snap_rows = len(dedup_store.load_snapshot())
    if snap_init and snap_rows == 0:
        logger.warning(
            "В SQLite помечено snapshot_initialized=true, но таблица снимка пустая — "
            "бот воспринимает все строки с командой как новые и может заспамить MAX. "
            "Остановите сервис и удалите файл БД (%s), затем запустите снова при BOOTSTRAP_SEND_MAX=false "
            "(первый опрос заполнит снимок без отправки).",
            config.DATABASE_PATH,
        )
    bot = create_bot() if config.SEND_MODE == "max" else None
    client = TableClient()
    # Одна строка: по ней в journalctl видно версию кода, .env (BOOTSTRAP_SEND_MAX) и был ли уже снимок в БД.
    logger.info(
        "Старт бота | mode=%s poll=%ss | BOOTSTRAP_SEND_MAX=%s | snapshot_initialized=%s | "
        "Google spreadsheet=%s | листы=%s | BASE_DIR=%s | scheduler=%s | БД=%s | колонка=%s | строк в снимке=%s",
        config.SEND_MODE,
        config.POLL_INTERVAL_SECONDS,
        config.BOOTSTRAP_SEND_MAX,
        snap_init,
        config.GOOGLE_SPREADSHEET_ID,
        sheet_mode,
        config.BASE_DIR,
        Path(__file__).resolve(),
        config.DATABASE_PATH,
        config.TABLE_COMMAND_COLUMN,
        snap_rows,
    )
    if config.BOOTSTRAP_SEND_MAX and snap_init:
        logger.warning(
            "BOOTSTRAP_SEND_MAX включён, но в SQLite уже есть снимок (snapshot_initialized=true). "
            "Одноразовая рассылка срабатывает только при первом опросе после удаления файла БД. "
            "Остановите сервис, выполните: rm -f %s — затем снова start (флаг можно оставить). "
            "После рассылки верните BOOTSTRAP_SEND_MAX=false.",
            config.DATABASE_PATH,
        )
    if config.TABLE_COMMAND_SEND_EVERY_POLL:
        logger.warning(
            "TABLE_COMMAND_SEND_EVERY_POLL включён: уведомления в MAX по каждой строке с валидной командой "
            "на каждом опросе (интервал %s с) — возможен сильный спам.",
            config.POLL_INTERVAL_SECONDS,
        )

    try:
        while True:
            try:
                await process_pending_rows(bot, client)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка в polling-цикле")

            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Остановка (Ctrl+C / отмена задачи).")
        raise
    finally:
        if bot is not None:
            try:
                await bot.close_session()
            except Exception as exc:
                logger.warning("При закрытии сессии MAX: %s", exc)
            else:
                logger.debug("Сессия MAX (aiohttp) закрыта.")
