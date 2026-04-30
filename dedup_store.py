"""SQLite-backed snapshot state for accountant notifications."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import config

_db_path: str | None = None

logger = logging.getLogger(__name__)

META_BOUND_SPREADSHEET_KEY = "bound_google_spreadsheet_id"


def get_db_path() -> str:
    global _db_path
    if _db_path is None:
        path = Path(config.DATABASE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _db_path = str(path)
    return _db_path


def init_db() -> None:
    conn = sqlite3.connect(get_db_path())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        columns = conn.execute("PRAGMA table_info(row_state)").fetchall()
        column_names = {column[1] for column in columns}
        if columns and "sheet_name" not in column_names:
            conn.execute("DROP TABLE row_state")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS row_state (
                row_key TEXT PRIMARY KEY,
                sheet_name TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                command TEXT NOT NULL,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    row_key: str
    sheet_name: str
    row_number: int
    command: str  # command_dedup_signature: нормализованный текст ячейки «Бухгалтеру в чат»


def build_row_key(sheet_name: str, row_number: int) -> str:
    return f"{sheet_name}:{row_number}"


def ensure_bound_google_spreadsheet(spreadsheet_id: str) -> None:
    """При смене GOOGLE_SPREADSHEET_ID очищает снимок без рассылки; первый же опрос заново заполнит SQLite."""
    sid = spreadsheet_id.strip()
    if not sid:
        return
    init_db()
    conn = sqlite3.connect(get_db_path())
    try:
        cursor = conn.execute(
            "SELECT value FROM state_meta WHERE key = ?",
            (META_BOUND_SPREADSHEET_KEY,),
        )
        row = cursor.fetchone()
        prev = row[0].strip() if row else None

        if prev == sid:
            return

        if prev is None:
            conn.execute(
                """
                INSERT INTO state_meta (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (META_BOUND_SPREADSHEET_KEY, sid),
            )
            conn.commit()
            logger.info(
                "SQLite привязан к книге Google %s (снимок не очищался — первый запуск или до этого не было привязки к id книги).",
                sid,
            )
            return

        conn.execute("DELETE FROM row_state")
        conn.execute(
            "DELETE FROM state_meta WHERE key IN ('snapshot_initialized', ?)",
            (META_BOUND_SPREADSHEET_KEY,),
        )
        conn.execute(
            """
            INSERT INTO state_meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (META_BOUND_SPREADSHEET_KEY, sid),
        )
        conn.commit()
        logger.warning(
            "GOOGLE_SPREADSHEET_ID изменился (%s → %s): снимок dedup очищен; следующий опрос заполнит состояние без отправки "
            "(пока BOOTSTRAP_SEND_MAX=false).",
            prev,
            sid,
        )
    finally:
        conn.close()


def snapshot_initialized() -> bool:
    init_db()
    conn = sqlite3.connect(get_db_path())
    try:
        cursor = conn.execute(
            "SELECT value FROM state_meta WHERE key = 'snapshot_initialized'"
        )
        row = cursor.fetchone()
        return bool(row and row[0] == "1")
    finally:
        conn.close()


def load_snapshot() -> dict[str, SnapshotEntry]:
    init_db()
    conn = sqlite3.connect(get_db_path())
    try:
        cursor = conn.execute(
            """
            SELECT row_key, sheet_name, row_number, command
            FROM row_state
            """
        )
        return {
            row_key: SnapshotEntry(
                row_key=row_key,
                sheet_name=sheet_name,
                row_number=row_number,
                command=command,
            )
            for row_key, sheet_name, row_number, command in cursor.fetchall()
        }
    finally:
        conn.close()


def replace_snapshot(entries: Iterable[SnapshotEntry]) -> None:
    init_db()
    conn = sqlite3.connect(get_db_path())
    try:
        materialized_entries = list(entries)
        conn.execute("DELETE FROM row_state")
        if materialized_entries:
            conn.executemany(
                """
                INSERT INTO row_state (
                    row_key,
                    sheet_name,
                    row_number,
                    command,
                    last_seen_at
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        entry.row_key,
                        entry.sheet_name,
                        entry.row_number,
                        entry.command,
                    )
                    for entry in materialized_entries
                ],
            )
        conn.execute(
            """
            INSERT INTO state_meta (key, value)
            VALUES ('snapshot_initialized', '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        conn.commit()
    finally:
        conn.close()
