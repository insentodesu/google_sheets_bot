"""Tests for accountant message formatting."""

import pytest

from message_templates import build_message


def test_build_message_alpha_with_upd_and_route():
    row = {
        "Дата": "28.03.2026",
        "Клиент": "ЭС",
        "Менеджер": "Рассказова Д",
        "Номер счета ": "123",
        "номер УПД": "456",
        "Адрес доставки": "Красное село код 3.24",
        "Наименование услуги": "Манипулятор 8т",
        "Цена клиенту": "3 600,00",
        "Кол-во": "14",
        "ед. изм.": "м/ч",
    }

    message = build_message("Альфа, Счет, УПД, Маршрут", row)

    assert message == (
        "<b>Альфа, Счет, УПД, Маршрут</b>\n"
        "<b>Дата: </b>28.03.2026\n"
        "<b>Заказчик: </b>ЭС\n"
        "<b>Транспорт: </b>Манипулятор 8т\n"
        "<b>Маршрут: </b>Красное село код 3.24\n"
        "<b>Цена Клиенту: </b>3 600,00\n"
        "<b>Количество: </b>14\n"
        "<b>Единица измерения: </b>м/ч\n"
        "<b>Менеджер: </b>Рассказова Д"
    )


def test_build_message_non_upd_only_fixed_columns_not_full_row():
    row = {
        "Бухгалтеру в чат": "Точка Полная Инф",
        "Дата": "28.03.2026",
        "Клиент": "ЭС",
        "Менеджер": "Рассказова Д",
        "Номер счета ": "123",
        "номер УПД": "456",
        "Адрес доставки": "Маршрут",
        "Наименование услуги": "Манипулятор 8т",
        "Водитель": "Иванов И.И.",
        "Цена клиенту": "3 600,00",
        "Кол-во": "14",
        "ед. изм.": "м/ч",
        "Сумма клиенту": "50 400,00",
        "Поставщик": "ООО Поставщик",
        "Номер вход.док.": "789",
    }

    message = build_message("Точка Полная Инф", row, command_column_key="Бухгалтеру в чат")

    assert message == (
        "<b>Точка Полная Инф</b>\n"
        "<b>Дата: </b>28.03.2026\n"
        "<b>Заказчик: </b>ЭС\n"
        "<b>Транспорт: </b>Манипулятор 8т\n"
        "<b>Маршрут: </b>Маршрут\n"
        "<b>Цена Клиенту: </b>3 600,00\n"
        "<b>Количество: </b>14\n"
        "<b>Единица измерения: </b>м/ч\n"
        "<b>Менеджер: </b>Рассказова Д"
    )


def test_build_message_upd_to_invoice_uses_invoice_number():
    row = {
        "Дата": "28.03.2026",
        "Менеджер": "Рассказова Д",
        "Номер счета ": "123",
    }

    message = build_message("УПД к Счету", row)

    assert message == (
        "<b>УПД к Счету</b>\n"
        "<b>Счет: </b>123\n"
        "<b>Дата: </b>28.03.2026\n"
        "<b>Менеджер: </b>Рассказова Д"
    )


def test_build_message_upd_shows_brand_when_config_set(monkeypatch):
    import config as app_config

    monkeypatch.setattr(app_config, "UPD_MESSAGE_BRAND", "Acme")
    row = {"Дата": "1", "Клиент": "X", "Менеджер": "Y", "Номер счета": "Z"}
    message = build_message("УПД к Счету", row)
    assert message.startswith("<b>Acme</b>\n")
    assert "<b>УПД к Счету</b>" in message


def test_build_message_accepts_command_without_commas():
    row = {
        "Дата": "28.03.2026",
        "Клиент": "ЭС",
        "Менеджер": "Рассказова Д",
        "Наименование услуги": "Манипулятор 8т",
        "Цена клиенту": "3 600,00",
        "Кол-во": "14",
        "ед. изм.": "м/ч",
    }

    message = build_message("Альфа Счет УПД", row)

    assert message == (
        "<b>Альфа Счет УПД</b>\n"
        "<b>Дата: </b>28.03.2026\n"
        "<b>Заказчик: </b>ЭС\n"
        "<b>Транспорт: </b>Манипулятор 8т\n"
        "<b>Цена Клиенту: </b>3 600,00\n"
        "<b>Количество: </b>14\n"
        "<b>Единица измерения: </b>м/ч\n"
        "<b>Менеджер: </b>Рассказова Д"
    )


def test_build_message_ip_route_uses_selected_dropdown_title():
    row = {
        "Дата": "28.03.2026",
        "Клиент": "ЭС",
        "Менеджер": "Рассказова Д",
        "Номер счета": "INV-9",
        "Адрес доставки": "Маршрут",
        "Услуга/товар": "Услуга X",
        "Наименование услуги": "Манипулятор 8т",
        "Цена клиенту": "3 600,00",
        "Кол-во": "14",
        "ед. изм.": "м/ч",
        "Сумма клиенту": "50 400,00",
    }

    message = build_message("ИП Точка Счет Акт Маршрут", row)

    assert message == (
        "<b>ИП Точка Счет Акт Маршрут</b>\n"
        "<b>Дата: </b>28.03.2026\n"
        "<b>Заказчик: </b>ЭС\n"
        "<b>Транспорт: </b>Манипулятор 8т\n"
        "<b>Маршрут: </b>Маршрут\n"
        "<b>Цена Клиенту: </b>3 600,00\n"
        "<b>Количество: </b>14\n"
        "<b>Единица измерения: </b>м/ч"
    )


def test_build_message_upd_to_invoice_full_row_order_matches_sheet_format():
    row = {
        "Дата": "2026-01-02",
        "Клиент": "Стройпроекты",
        "Менеджер": "Кузь",
        "Адрес доставки": 'Орлово-Денисовский пр. д.19, ЖК "Бионика" (Хайтбаев)',
        "Услуга/товар": "Услуга",
        "Транспорт": "Мини погрузчик с щеткой",
        "ед. изм.": "м/ч",
        "Цена клиенту": "2 312,50",
        "Кол-во": "12.0",
        "Сумма клиенту": "27 750,00",
        "Своя Найм": "Н",
        "Номер счета": "INV-001",
    }

    message = build_message("УПД к Счету", row)

    assert message == (
        "<b>УПД к Счету</b>\n"
        "<b>Счет: </b>INV-001\n"
        "<b>Дата: </b>2026-01-02\n"
        "<b>Менеджер: </b>Кузь"
    )


def test_build_message_accepts_any_command_text_not_in_template_list():
    row = {
        "Дата": "2026-01-01",
        "Клиент": "Кто-то",
        "Сумма клиенту": "100",
        "Примечание": "тест",
    }
    message = build_message("Новый пункт, которого нет в TEMPLATE_SPECS", row)
    assert "<b>Новый пункт, которого нет в TEMPLATE_SPECS</b>" in message
    assert "<b>Дата: </b>2026-01-01" in message
    assert "<b>Заказчик: </b>Кто-то" in message
    assert "Примечание" not in message
    assert "Сумма клиенту" not in message


def test_non_upd_fixed_fields_match_product_example():
    """Непустые колонки из фиксированного набора ТЗ (полный блок с менеджером)."""
    row = {
        "Дата": "2026-01-06",
        "Клиент": "Стройпроекты",
        "Менеджер": "Кузь",
        "Номер счета": "4.0",
        "Адрес доставки": 'Октябрьская набережная д.38, ЖК "Пульс"',
        "Услуга/товар": "Услуга",
        "Наименование услуги": "Мини погрузчик с щеткой",
        "ед. изм.": "м/ч",
        "Цена клиенту": "2 312,50",
        "Кол-во": "9.0",
        "Сумма клиенту": "20 812,50",
    }
    message = build_message("Точка Счет Маршрут", row)
    assert message == (
        "<b>Точка Счет Маршрут</b>\n"
        "<b>Дата: </b>2026-01-06\n"
        "<b>Заказчик: </b>Стройпроекты\n"
        "<b>Транспорт: </b>Мини погрузчик с щеткой\n"
        "<b>Маршрут: </b>Октябрьская набережная д.38, ЖК &quot;Пульс&quot;\n"
        "<b>Цена Клиенту: </b>2 312,50\n"
        "<b>Количество: </b>9.0\n"
        "<b>Единица измерения: </b>м/ч\n"
        "<b>Менеджер: </b>Кузь"
    )


def test_ip_upd_to_invoice_compact_command():
    """ИП, УПД к Счету — тот же короткий формат, что и УПД к Счету."""
    row = {"Номер счета": "55", "Дата": "01.02.2026", "Менеджер": "Иванов"}
    message = build_message("ИП, УПД к Счету", row)
    assert "<b>Счет: </b>55" in message
    assert "<b>Дата: </b>01.02.2026" in message
    assert "<b>Менеджер: </b>Иванов" in message


def test_build_message_rejects_empty_command():
    with pytest.raises(ValueError, match="Пустой текст команды"):
        build_message("   ", {"Дата": "1"})


def test_stored_command_dedup_key_matches_signature_for_roundtrip():
    from message_templates import command_dedup_signature, stored_command_dedup_key

    raw = "Альфа, Счет"
    sig = command_dedup_signature(raw)
    assert stored_command_dedup_key(sig) == sig


def test_command_column_fingerprint_length():
    from types import SimpleNamespace

    from message_templates import command_column_fingerprint

    rows = [
        SimpleNamespace(sheet_name="Январь", row_number=2, values={"К": "Альфа, Счет"}),
    ]
    assert len(command_column_fingerprint(rows, "К")) == 12
