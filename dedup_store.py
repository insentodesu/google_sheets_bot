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
META_MONTH_KEYS_CANONICAL_V1 = "month_sheet_row_keys_canonical_v1"


def _sheet_match_key(name: str) -> str:
    """Тот же принцип, что table_client._sheet_name_match_key (без циклического импорта)."""
    text = str(name or "").replace("\n", " ").replace("\r", " ")
    return " ".join(text.split()).strip().casefold()


def canonical_sheet_title_for_dedup(sheet_name: str) -> str:
    """Ключ строки в SQLite: Январь и Янв → одно имя (берём короткое из MONTH_SHEET_SHORT_NAMES).

    Так старый снимок после переименования вкладок «Январь»→«Янв» не превращается в лавину повторных отправок.
    """
    raw = str(sheet_name or "").strip()
    sk = _sheet_match_key(raw)
    if not sk:
        return raw
    for idx, full in enumerate(config.MONTH_SHEET_NAMES):
        if _sheet_match_key(full) == sk:
            if idx < len(config.MONTH_SHEET_SHORT_NAMES):
                short = config.MONTH_SHEET_SHORT_NAMES[idx].strip()
                if short:
                    return short
            return full.strip()
    for idx, short in enumerate(config.MONTH_SHEET_SHORT_NAMES):
        if short and _sheet_match_key(short) == sk:
            return short.strip()
    return raw


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
    canon = canonical_sheet_title_for_dedup(sheet_name)
    return f"{canon}:{row_number}"


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
            "DELETE FROM state_meta WHERE key IN ('snapshot_initialized', ?, ?)",
            (META_BOUND_SPREADSHEET_KEY, META_MONTH_KEYS_CANONICAL_V1),
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


def ensure_month_sheet_row_keys_canonical() -> None:
    """Один раз переписывает row_key/sheet_name для месячных листов под канонические короткие имена."""
    init_db()
    conn = sqlite3.connect(get_db_path())
    try:
        cur = conn.execute(
            "SELECT value FROM state_meta WHERE key = ?", (META_MONTH_KEYS_CANONICAL_V1,)
        )
        if cur.fetchone():
            return

        rows = conn.execute(
            "SELECT row_key, sheet_name, row_number, command FROM row_state"
        ).fetchall()

        merged: dict[str, SnapshotEntry] = {}
        collisions = 0
        for _old_key, sheet_name, row_number, command in rows:
            nk = build_row_key(sheet_name, row_number)
            canon_sheet = canonical_sheet_title_for_dedup(sheet_name)
            entry = SnapshotEntry(
                row_key=nk,
                sheet_name=canon_sheet,
                row_number=int(row_number),
                command=str(command),
            )
            if nk in merged and merged[nk].command != entry.command:
                collisions += 1
                logger.warning(
                    "Миграция ключей месяцев: конфликт %s — разные команды, оставлена последняя запись.",
                    nk,
                )
            merged[nk] = entry

        conn.execute("DELETE FROM row_state")
        if merged:
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
                    (e.row_key, e.sheet_name, e.row_number, e.command)
                    for e in merged.values()
                ],
            )

        conn.execute(
            """
            INSERT INTO state_meta (key, value)
            VALUES (?, '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (META_MONTH_KEYS_CANONICAL_V1,),
        )
        conn.commit()

        if rows:
            logger.info(
                "Миграция ключей месячных листов в SQLite: переписано строк снимка %s → уникальных ключей %s%s.",
                len(rows),
                len(merged),
                f", конфликтов {collisions}" if collisions else "",
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
