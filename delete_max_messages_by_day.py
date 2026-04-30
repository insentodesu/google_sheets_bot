#!/usr/bin/env python3
"""
Удалить из MAX-чата сообщения бухбота за календарный день (по локальному времени).

Берётся последняя страница истории (до 100 сообщений), по timestamp отбирается нужный день.
В каналах у постов часто нет sender — по умолчанию допускается совпадение по шаблону текста
уведомления (Дата/Клиент/Номер счета); иначе запустите с --strict-bot-sender-only.

Запуск из каталога проекта:
  python delete_max_messages_by_day.py --date 2026-04-28 --dry-run
  python delete_max_messages_by_day.py --date 2026-04-28

Переменные окружения: MAX_BOT_TOKEN, MAX_CHAT_ID, MAX_SSL_VERIFY; PURGE_MESSAGES_TZ (дата дня).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import TCPConnector
from maxapi import Bot
from maxapi.client.default import DefaultConnectionProperties

# Загрузка .env до импорта config (у config свой load_dotenv из BASE_DIR).
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from logging_config import setup_logging  # noqa: E402

setup_logging()
logger = logging.getLogger("purge_max")


def _create_bot() -> Bot:
    default_conn = None
    if not config.MAX_SSL_VERIFY:
        default_conn = DefaultConnectionProperties(connector=TCPConnector(ssl=False))
    return Bot(token=config.MAX_BOT_TOKEN, default_connection=default_conn)


def _looks_like_accounting_notice(text: str | None) -> bool:
    """Похоже ли на рассылку бухбота (см. message_templates.build_message).

    В истории канала текст часто без HTML-тегов, поэтому ищем характерные поля строки."""
    if not text:
        return False
    t = text
    has_inv = "Номер счета" in t or "Номер счёта" in t
    block = ("Клиент" in t or "Клиент:" in t) and ("Дата" in t or "Дата:" in t)
    if block and has_inv:
        return True
    # Вариант с разметкой (если когда-то сохранится с тегами)
    return ("<b>" in t or "</b>" in t) and block and has_inv


def _ms_to_local_day(ts_ms: int, tz: ZoneInfo) -> date:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=tz).date()


async def _purge_day(
    bot: Bot,
    chat_id: int,
    bot_user_id: int,
    day: date,
    tz: ZoneInfo,
    *,
    dry_run: bool,
    guess_anonymous_posts: bool,
    recent_limit: int,
) -> tuple[int, int]:
    """Возвращает (найдено_наших, удалено_или_бы_удалено).

    MAX API в ряде окружений не возвращает сообщения при фильтре from/to; поэтому берём
    последние `recent_limit` сообщений чата и отбираем по календарному дню по timestamp.
    """
    found = 0
    done = 0
    seen_mids: set[str] = set()

    n = max(1, min(100, recent_limit))
    batch = await bot.get_messages(chat_id=chat_id, count=n)
    if len(batch.messages) >= 100:
        logger.warning(
            "В одном запросе не больше 100 сообщений; если в канале шумнее — часть постов за день может не попасть в выборку."
        )

    matching_day = [
        m
        for m in batch.messages
        if m.body is not None and _ms_to_local_day(m.timestamp, tz) == day
    ]
    if not matching_day:
        logger.info(
            "Среди последних %s сообщений нет записей за %s (%s).",
            len(batch.messages),
            day,
            tz.key,
        )

    for m in matching_day:
        if m.body is None:
            continue
        mid = m.body.mid
        if mid in seen_mids:
            continue
        sender = m.sender
        ours = sender is not None and sender.is_bot and sender.user_id == bot_user_id
        anon_ok = (
            guess_anonymous_posts
            and sender is None
            and _looks_like_accounting_notice(m.body.text or "")
        )
        if not ours and not anon_ok:
            continue
        seen_mids.add(mid)
        found += 1
        if dry_run:
            tag = "anon+pattern" if anon_ok else "sender"
            logger.info("[dry-run] удалил бы mid=%s ts=%s (%s)", mid, m.timestamp, tag)
            done += 1
        else:
            try:
                await bot.delete_message(mid)
                done += 1
                prefix = "~" if anon_ok else ""
                logger.info("%sУдалено mid=%s", prefix, mid)
            except Exception as exc:
                logger.warning("Не удалось удалить mid=%s: %s", mid, exc)

    return found, done


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Удалить сообщения бота в MAX за указанный день.")
    parser.add_argument(
        "--date",
        required=True,
        help="Дата YYYY-MM-DD (календарный день в PURGE_MESSAGES_TZ / Europe/Moscow).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, что было бы удалено.",
    )
    parser.add_argument(
        "--strict-bot-sender-only",
        action="store_true",
        help="Не удалять по шаблону текста — только сообщения с sender.is_bot=id бота "
        "(в канале чаще всего ни одного сообщения не попадёт).",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=100,
        metavar="N",
        help="Сколько последних сообщений чата запросить (1–100). Записи за день фильтруются по времени локально.",
    )
    args = parser.parse_args()

    if not config.MAX_BOT_TOKEN.strip():
        logger.error("MAX_BOT_TOKEN не задан")
        return 1
    if not config.MAX_CHAT_ID:
        logger.error("MAX_CHAT_ID не задан")
        return 1

    try:
        day = date.fromisoformat(args.date)
    except ValueError:
        logger.error("Неверный формат --date, ожидается YYYY-MM-DD")
        return 1

    tz_name = (os.getenv("PURGE_MESSAGES_TZ", "") or "Europe/Moscow").strip()
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:
        logger.error("Неверная зона PURGE_MESSAGES_TZ=%r: %s", tz_name, exc)
        return 1

    bot = _create_bot()
    try:
        me = await bot.get_me()
        bot_user_id = me.user_id
        logger.info(
            "Бот user_id=%s | чат=%s | день=%s (%s) | dry_run=%s",
            bot_user_id,
            config.MAX_CHAT_ID,
            day,
            tz_name,
            args.dry_run,
        )
        found, done = await _purge_day(
            bot,
            config.MAX_CHAT_ID,
            bot_user_id,
            day,
            tz,
            dry_run=args.dry_run,
            guess_anonymous_posts=not args.strict_bot_sender_only,
            recent_limit=args.recent,
        )
        logger.info("Готово: найдено сообщений бота=%s, обработано=%s", found, done)
        if found == 0:
            logger.info(
                "Ничего подходящего среди последних сообщений за выбранный день. "
                "Проверьте --date и PURGE_MESSAGES_TZ; при переполнении 100 сообщений попробуйте --recent 100 после освежения истории."
            )
    finally:
        await bot.close_session()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
