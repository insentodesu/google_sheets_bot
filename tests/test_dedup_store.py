"""Tests for snapshot state storage."""

import dedup_store


def test_bound_change_resets_snapshot(tmp_path):
    dedup_store._db_path = str(tmp_path / "bound_switch.db")
    dedup_store.ensure_bound_google_spreadsheet("spreadsheet-old")
    dedup_store.replace_snapshot(
        [
            dedup_store.SnapshotEntry(
                row_key=dedup_store.build_row_key("Январь", 2),
                sheet_name="Январь",
                row_number=2,
                command="Альфа, Счет",
            )
        ]
    )
    assert dedup_store.snapshot_initialized() is True

    dedup_store.ensure_bound_google_spreadsheet("spreadsheet-new")

    assert dedup_store.load_snapshot() == {}
    assert dedup_store.snapshot_initialized() is False
    dedup_store._db_path = None


def test_replace_and_load_snapshot(tmp_path):
    dedup_store._db_path = str(tmp_path / "dedup.db")
    dedup_store.replace_snapshot(
        [
            dedup_store.SnapshotEntry(
                row_key=dedup_store.build_row_key("Январь", 2),
                sheet_name="Январь",
                row_number=2,
                command="Альфа, Счет",
            )
        ]
    )

    snapshot = dedup_store.load_snapshot()

    assert snapshot[dedup_store.build_row_key("Январь", 2)].command == "Альфа, Счет"
    assert dedup_store.snapshot_initialized() is True
    dedup_store._db_path = None


def test_replace_snapshot_removes_missing_rows(tmp_path):
    dedup_store._db_path = str(tmp_path / "dedup_replace.db")
    dedup_store.replace_snapshot(
        [
            dedup_store.SnapshotEntry(
                row_key=dedup_store.build_row_key("Январь", 2),
                sheet_name="Январь",
                row_number=2,
                command="Альфа, Счет",
            )
        ]
    )

    dedup_store.replace_snapshot([])

    assert dedup_store.load_snapshot() == {}
    dedup_store._db_path = None


def test_build_row_key_includes_sheet_name():
    assert dedup_store.build_row_key("Январь", 2) != dedup_store.build_row_key("Февраль", 2)


def test_month_sheet_long_and_short_share_row_key():
    assert dedup_store.build_row_key("Январь", 10) == dedup_store.build_row_key("Янв", 10)


def test_migration_rewrites_legacy_month_row_keys(tmp_path):
    import sqlite3

    dedup_store._db_path = str(tmp_path / "month_migrate.db")
    dedup_store.init_db()
    conn = sqlite3.connect(dedup_store._db_path)
    conn.execute(
        """
        INSERT INTO row_state (row_key, sheet_name, row_number, command)
        VALUES ('Январь:10', 'Январь', 10, 'Альфа, Счет')
        """
    )
    conn.commit()
    conn.close()

    dedup_store.ensure_month_sheet_row_keys_canonical()
    snap = dedup_store.load_snapshot()
    assert dedup_store.build_row_key("Янв", 10) in snap
    assert snap[dedup_store.build_row_key("Янв", 10)].command == "Альфа, Счет"
    assert "Январь:10" not in snap

    dedup_store.ensure_month_sheet_row_keys_canonical()
    assert len(dedup_store.load_snapshot()) == 1

    dedup_store._db_path = None
