"""Точка входа бота стикеров WNDR."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import commands as commands_handlers
from bot.handlers import generate as generate_handlers
from skill.wndr_stickers.src.config import get_settings
from skill.wndr_stickers.src.db import init_db
from skill.wndr_stickers.src.instance_lock import AlreadyRunning, InstanceLock


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN пуст. Создай бота в @BotFather (/newbot) "
            "и положи токен в ~/dev/wndr-stickers/.env"
        )
    if not settings.telegram_owner_id:
        raise SystemExit("TELEGRAM_OWNER_ID пуст — без него нельзя владеть стикерпаком.")
    if not settings.reference_sheet_path.exists():
        raise SystemExit(f"Нет референс-листа: {settings.reference_sheet_path}")
    if not settings.font_path.exists():
        raise SystemExit(f"Нет шрифта: {settings.font_path}")

    lock = InstanceLock(settings.lock_path)
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        raise SystemExit(str(exc)) from exc

    await init_db(settings.db_path)
    settings.stickers_dir.mkdir(parents=True, exist_ok=True)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(commands_handlers.build_router(settings))
    dp.include_router(generate_handlers.build_router(settings))

    me = await bot.get_me()
    logging.info(
        "wndr-stickers запущен: @%s, доступ=%s, провайдеры=%s, "
        "управление=community, владелец пака настроен=%s",
        me.username,
        settings.access_mode,
        settings.provider_chain,
        bool(settings.sticker_pack_owner),
    )
    try:
        await dp.start_polling(bot)
    finally:
        lock.release()


if __name__ == "__main__":
    asyncio.run(main())
