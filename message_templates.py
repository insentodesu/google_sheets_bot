"""Message formatting rules for accountant notifications."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from html import escape
from typing import Any

import config


def _normalize_key(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _normalize_value(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").replace("\n", " ").split()).strip()


def _normalize_command(value: str) -> str:
    normalized = _normalize_value(value).casefold()
    return normalized.replace(",", "")


def _compact_command(value: str) -> str:
    """Нормализация для сопоставления типа команды: без пробелов и запятых, нижний регистр."""
    return "".join(_normalize_value(value).casefold().split()).replace(",", "")


def _has_upd_keyword(command: str) -> bool:
    c = _normalize_value(command).casefold()
    return "упд" in c or "upd" in c


def _is_upd_to_invoice_command(command: str) -> bool:
    """«УПД к Счету», в т.ч. «ИП … УПД к Счету» — короткое тело (Счёт, Дата, Менеджер)."""
    x = _compact_command(command)
    return x == "упдксчету" or x.endswith("упдксчету")


def _is_ip_style_command(command: str) -> bool:
    """Команда про ИП (ИП Точка, …): без УПД — семь полей без менеджера."""
    return _compact_command(command).startswith("ип")


def _row_map(row: dict[str, Any]) -> dict[str, str]:
    return {
        _normalize_key(key): _normalize_value(value)
        for key, value in row.items()
        if _normalize_key(key)
    }


def _get(row: dict[str, Any], *aliases: str) -> str:
    normalized = _row_map(row)
    for alias in aliases:
        value = normalized.get(_normalize_key(alias), "")
        if value:
            return value
    return ""


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """Зарезервировано для совместимости; формат сообщения задаётся типом команды."""

    pass


# Справочный набор подписей (выпадающий список в шаблоне, CHAT_OPTIONS в config).
# Бот принимает любой непустой текст в колонке «Бухгалтеру в чат», не только эти строки.
TEMPLATE_SPECS: dict[str, TemplateSpec] = {
    "Альфа, Счет, Маршрут": TemplateSpec(),
    "Альфа, Счет, УПД, Маршрут": TemplateSpec(),
    "Альфа, Счет": TemplateSpec(),
    "Альфа, Счет, УПД": TemplateSpec(),
    "Точка, Счет, Маршрут": TemplateSpec(),
    "Точка, Счет, УПД, Маршрут": TemplateSpec(),
    "Точка, Счет": TemplateSpec(),
    "Точка, Счет, УПД": TemplateSpec(),
    "ИП Точка, Счет, Маршрут": TemplateSpec(),
    "ИП Точка, Счет, Акт, Маршрут": TemplateSpec(),
    "УПД к Счету": TemplateSpec(),
    "Точка Полная Инф": TemplateSpec(),
}

COMMAND_ALIASES: dict[str, str] = {
    _normalize_command(command): command for command in TEMPLATE_SPECS
}


def supported_commands() -> list[str]:
    return list(TEMPLATE_SPECS.keys())


def resolve_command(command: str) -> str | None:
    """Опционально: совпадение с каноническим названием из TEMPLATE_SPECS (для скриптов/тестов)."""
    return COMMAND_ALIASES.get(_normalize_command(command))


def canonicalize_command(command: str) -> str:
    normalized_value = _normalize_value(command)
    return resolve_command(command) or normalized_value


def command_dedup_signature(raw_command: str) -> str:
    """Текст ячейки после нормализации пробелов — ключ дедупа в SQLite."""
    s = _normalize_value(raw_command.strip())
    return unicodedata.normalize("NFKC", s)


def stored_command_dedup_key(stored: str) -> str:
    """То же нормализованное представление, что и у command_dedup_signature, для сравнения с SQLite."""
    if not stored:
        return ""
    return unicodedata.normalize("NFKC", _normalize_value(stored.strip()))


def command_column_fingerprint(rows: list[Any], command_header_key: str) -> str:
    """Короткий хэш по всем непустым значениям колонки команды (для логов: меняется ли файл между опросами)."""
    parts: list[str] = []
    for r in rows:
        raw = str(r.values.get(command_header_key, "")).strip()
        v = command_dedup_signature(raw)
        if v:
            parts.append(f"{r.sheet_name}:{r.row_number}:{v}")
    parts.sort()
    body = "|".join(parts)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _bold(value: str) -> str:
    return f"<b>{escape(value)}</b>"


def _field_line(label: str, value: str) -> str:
    return f"<b>{escape(label)}: </b>{escape(value)}"


# Заголовки колонки с номером счёта в разных вариантах таблиц.
_INVOICE_NUMBER_ALIASES: tuple[str, ...] = (
    "Номер счета",
    "Номер счета ",
    "Номер счёта",
    "№ счета",
    "№ Счета",
    "Счет №",
)

# Полный набор (Счёт+УПД, обычный счёт с менеджером и т.п.)
_FULL_EIGHT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Дата", ("Дата",)),
    ("Заказчик", ("Заказчик", "Клиент")),
    ("Транспорт", ("Транспорт", "Наименование услуги")),
    ("Маршрут", ("Маршрут", "Адрес доставки")),
    ("Цена Клиенту", ("Цена клиенту", "Цена Клиенту")),
    ("Количество", ("Кол-во", "Количество")),
    ("Единица измерения", ("ед. изм.", "Единица измерения")),
    ("Менеджер", ("Менеджер",)),
)

# ИП без УПД в тексте команды — без менеджера.
_IP_SEVEN_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = _FULL_EIGHT_FIELDS[:-1]

_SHORT_UPD_TO_INVOICE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Счет", _INVOICE_NUMBER_ALIASES),
    ("Дата", ("Дата",)),
    ("Менеджер", ("Менеджер",)),
)


def _build_body_from_fields(command: str, row: dict[str, Any], fields: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    lines = [_bold(_normalize_value(command))]
    for label, aliases in fields:
        value = _get(row, *aliases)
        if not value:
            continue
        lines.append(_field_line(label, value))
    return "\n".join(lines)


def _build_short_upd_to_invoice(command: str, row: dict[str, Any]) -> str:
    lines: list[str] = []
    brand = config.UPD_MESSAGE_BRAND.strip()
    if brand:
        lines.append(_bold(brand))
    lines.append(_bold(_normalize_value(command)))
    for label, aliases in _SHORT_UPD_TO_INVOICE_FIELDS:
        value = _get(row, *aliases)
        if not value:
            continue
        lines.append(_field_line(label, value))
    return "\n".join(lines)


def build_message(
    command: str,
    row: dict[str, Any],
    *,
    command_column_key: str | None = None,
) -> str:
    """Первая строка — текст команды; дальше набор полей зависит от выбранного типа (см. ТЗ)."""
    _ = command_column_key  # аргумент оставлен для совместимости с scheduler.process_pending_rows
    command = command.strip()
    if not command:
        raise ValueError("Пустой текст команды")
    if _is_upd_to_invoice_command(command):
        return _build_short_upd_to_invoice(command, row)
    if _is_ip_style_command(command) and not _has_upd_keyword(command):
        return _build_body_from_fields(command, row, _IP_SEVEN_FIELDS)
    return _build_body_from_fields(command, row, _FULL_EIGHT_FIELDS)
