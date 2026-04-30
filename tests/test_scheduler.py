"""Tests for the polling scheduler."""

import asyncio
import io
from contextlib import redirect_stdout
from unittest.mock import AsyncMock

import dedup_store
import scheduler
from maxapi.enums.parse_mode import ParseMode
from table_client import SpreadsheetRow


def make_row(command: str, **overrides):
    sheet_name = overrides.pop("sheet_name", "Январь")
    row_number = overrides.pop("row_number", 2)
    values = {
        "Бухгалтеру в чат": command,
        "Дата": "28.03.2026",
        "Клиент": "ЭС",
        "Номер счета": "123",
        "Наименование услуги": "Манипулятор 8т",
        "Цена клиенту": "3 600,00",
        "Кол-во": "14",
        "ед. изм.": "м/ч",
        "Менеджер": "Рассказова Д",
    }
    values.update(overrides)
    return SpreadsheetRow(sheet_name=sheet_name, row_number=row_number, values=values)


class SequenceClient:
    def __init__(self, batches):
        self._batches = list(batches)
        self._index = 0

    async def get_rows(self):
        if self._index >= len(self._batches):
            return self._batches[-1]
        rows = self._batches[self._index]
        self._index += 1
        return rows


def test_process_pending_rows_bootstraps_snapshot_without_sending(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient([[make_row("Альфа, Счет")], [make_row("Альфа, Счет")]])
    bot = AsyncMock()
    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 0
    bot.send_message.assert_not_called()
    dedup_store._db_path = None


def test_process_pending_rows_bootstrap_sends_when_flag_true(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_bootstrap_send.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")
    monkeypatch.setattr(scheduler.config, "BOOTSTRAP_SEND_MAX", True)

    client = SequenceClient([[make_row("Альфа, Счет")], [make_row("Альфа, Счет")]])
    bot = AsyncMock()
    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 1
    assert second_count == 0
    bot.send_message.assert_called_once()
    dedup_store._db_path = None


def test_process_pending_rows_sends_every_poll_when_flag_true(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_every_poll.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")
    monkeypatch.setattr(scheduler.config, "TABLE_COMMAND_SEND_EVERY_POLL", True)

    client = SequenceClient(
        [
            [make_row("Альфа, Счет")],
            [make_row("Альфа, Счет")],
            [make_row("Альфа, Счет")],
        ]
    )
    bot = AsyncMock()
    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    third_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 1
    assert third_count == 1
    assert bot.send_message.call_count == 2
    dedup_store._db_path = None


def test_process_pending_rows_console_mode_prints_message(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_console.db")
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "console")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        sent_count = asyncio.run(
            scheduler.process_pending_rows(None, SequenceClient([[make_row("Альфа, Счет")]]))
        )

    assert sent_count == 0
    assert buffer.getvalue() == ""
    dedup_store._db_path = None


def test_process_pending_rows_ignores_non_command_changes(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_ignore_changes.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient(
        [
            [make_row("Альфа, Счет", Клиент="ЭС")],
            [make_row("Альфа, Счет", Клиент="Другой клиент")],
        ]
    )
    bot = AsyncMock()

    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 0
    bot.send_message.assert_not_called()
    dedup_store._db_path = None


def test_process_pending_rows_sends_when_command_appears_later(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_appears.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient(
        [
            [make_row("", Клиент="ЭС")],
            [make_row("Альфа Счет УПД", Клиент="ЭС")],
        ]
    )
    bot = AsyncMock()

    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 1
    bot.send_message.assert_called_once()
    assert bot.send_message.await_args.kwargs["format"] == ParseMode.HTML
    dedup_store._db_path = None


def test_process_pending_rows_sends_when_raw_differs_but_template_same(tmp_path, monkeypatch):
    """Разные подписи в ячейке, но один шаблон в COMMAND_ALIASES — дедуп по тексту, не по канону."""
    dedup_store._db_path = str(tmp_path / "scheduler_raw_vs_canon.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient(
        [
            [make_row("Альфа, Счет")],
            [make_row("Альфа Счет")],
        ]
    )
    bot = AsyncMock()

    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 1
    bot.send_message.assert_called_once()
    dedup_store._db_path = None


def test_process_pending_rows_sends_when_command_changes(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_command_change.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient(
        [
            [make_row("Альфа, Счет")],
            [make_row("Точка, Счет")],
        ]
    )
    bot = AsyncMock()

    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 1
    bot.send_message.assert_called_once()
    dedup_store._db_path = None


def test_process_pending_rows_sends_each_command_change_in_one_cycle(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_multi_row_cycle.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient(
        [
            [
                make_row("Альфа, Счет", sheet_name="Январь", row_number=2),
                make_row("Точка, Счет", sheet_name="Февраль", row_number=3),
            ],
            [
                make_row("Точка, Счет", sheet_name="Январь", row_number=2),
                make_row("Точка, Счет, УПД", sheet_name="Февраль", row_number=3),
            ],
        ]
    )
    bot = AsyncMock()

    first = asyncio.run(scheduler.process_pending_rows(bot, client))
    second = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first == 0
    assert second == 2
    assert bot.send_message.call_count == 2
    dedup_store._db_path = None


def test_process_pending_rows_tracks_rows_per_sheet(tmp_path, monkeypatch):
    dedup_store._db_path = str(tmp_path / "scheduler_multi_sheet.db")
    monkeypatch.setattr(scheduler.config, "MAX_CHAT_ID", 123456)
    monkeypatch.setattr(scheduler.config, "SEND_MODE", "max")

    client = SequenceClient(
        [
            [
                make_row("Альфа, Счет", sheet_name="Январь"),
                make_row("Точка, Счет", sheet_name="Февраль"),
            ],
            [
                make_row("Альфа, Счет", sheet_name="Январь"),
                make_row("Точка, Счет, УПД", sheet_name="Февраль"),
            ],
        ]
    )
    bot = AsyncMock()

    first_count = asyncio.run(scheduler.process_pending_rows(bot, client))
    second_count = asyncio.run(scheduler.process_pending_rows(bot, client))

    assert first_count == 0
    assert second_count == 1
    bot.send_message.assert_called_once()
    dedup_store._db_path = None
