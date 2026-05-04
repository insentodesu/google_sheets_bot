"""Tests for Google Sheets table client (no network)."""

from unittest.mock import MagicMock

import pytest
from gspread import WorksheetNotFound

import config
import table_client
from table_client import (
    TableClient,
    _build_spreadsheet_rows,
    normalize_cell,
    normalize_header,
)


def test_normalize_header_strips_newlines():
    assert normalize_header("  a \n b  ") == "a b"


def test_normalize_cell_nonbreaking_space():
    assert normalize_cell("x\xa0y") == "x y"


def test_build_spreadsheet_rows_basic():
    rows = _build_spreadsheet_rows(
        "Январь",
        [
            ["Дата", "Бухгалтеру в чат"],
            ["28.03.2026", "Альфа, Счет"],
        ],
    )
    assert len(rows) == 1
    assert rows[0].sheet_name == "Январь"
    assert rows[0].row_number == 2
    assert rows[0].values["Бухгалтеру в чат"] == "Альфа, Счет"


def test_build_spreadsheet_rows_skips_fully_empty_row():
    rows = _build_spreadsheet_rows(
        "Лист1",
        [
            ["A", "B"],
            ["1", "2"],
            ["", "   "],
            ["3", "4"],
        ],
    )
    assert len(rows) == 2
    assert rows[0].values["A"] == "1"
    assert rows[1].values["A"] == "3"


def test_select_worksheets_by_gid(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", 1401714661)
    monkeypatch.setattr(config, "TABLE_SHEET_NAME", "")
    ws = MagicMock()
    ws.title = "Вкладка"
    sh = MagicMock()
    sh.worksheets.return_value = [ws, MagicMock(title="Other")]
    sh.get_worksheet_by_id.return_value = ws
    client = TableClient()
    out = client._select_worksheets(sh)
    sh.get_worksheet_by_id.assert_called_once_with(1401714661)
    assert out == [ws]


def test_select_worksheets_gid_missing_raises(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", 999)
    monkeypatch.setattr(config, "TABLE_SHEET_NAME", "")
    sh = MagicMock()
    sh.worksheets.return_value = [MagicMock(title="A")]
    sh.get_worksheet_by_id.side_effect = WorksheetNotFound("x")
    client = TableClient()
    with pytest.raises(ValueError, match="не найден"):
        client._select_worksheets(sh)


def test_select_worksheets_by_table_sheet_name_fuzzy(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", None)
    monkeypatch.setattr(config, "TABLE_SHEET_NAME", "январь")
    w1 = MagicMock()
    w1.title = "  Январь  "
    w2 = MagicMock()
    w2.title = "Февраль"
    sh = MagicMock()
    sh.worksheets.return_value = [w1, w2]
    client = TableClient()
    out = client._select_worksheets(sh)
    assert out == [w1]


def test_select_worksheets_month_abbreviations(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", None)
    monkeypatch.setattr(config, "TABLE_SHEET_NAME", "")
    sheets = [MagicMock(title=m) for m in ("Янв", "Февр", "Март")]
    sh = MagicMock()
    sh.worksheets.return_value = sheets
    client = TableClient()
    out = client._select_worksheets(sh)
    assert [w.title for w in out] == ["Янв", "Февр", "Март"]


def test_select_worksheets_month_order(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", None)
    monkeypatch.setattr(config, "TABLE_SHEET_NAME", "")
    sheets = [MagicMock(title=m) for m in ("Март", "Январь", "Февраль")]
    by_title = {m.title: m for m in sheets}
    sh = MagicMock()
    sh.worksheets.return_value = list(by_title.values())
    client = TableClient()
    out = client._select_worksheets(sh)
    assert [w.title for w in out] == ["Январь", "Февраль", "Март"]


def test_select_worksheets_fallback_first(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", None)
    monkeypatch.setattr(config, "TABLE_SHEET_NAME", "")
    a = MagicMock()
    a.title = "Сводка"
    b = MagicMock()
    b.title = "Прочее"
    sh = MagicMock()
    sh.worksheets.return_value = [a, b]
    client = TableClient()
    out = client._select_worksheets(sh)
    assert out == [a]


def test_get_rows_sync_merges_worksheets(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_WORKSHEET_GID", None)
    w = MagicMock()
    w.title = "Only"
    w.get_all_values.return_value = [
        ["Кол1", "Бухгалтеру в чат"],
        ["a", "Альфа, Счет"],
    ]
    sh = MagicMock()
    sh.worksheets.return_value = [w]

    def fake_client() -> MagicMock:
        c = MagicMock()
        c.open_by_key.return_value = sh
        return c

    monkeypatch.setattr(table_client, "_get_gspread_client", fake_client)
    client = TableClient(spreadsheet_id="test_id", sheet_name="Only")
    rows = client._get_rows_sync()
    assert len(rows) == 1
    assert rows[0].sheet_name == "Only"
    assert "Альфа, Счет" in (rows[0].values.get("Бухгалтеру в чат") or "")
