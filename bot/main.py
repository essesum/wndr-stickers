"""Точка входа бота стикеров WNDR."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent, Message

from bot.handlers import commands as commands_handlers
from bot.handlers import generate as generate_handlers
from skill.wndr_stickers.src.config import Settings, get_settings
from skill.wndr_stickers.src.db import init_db
from skill.wndr_stickers.src.instance_lock import AlreadyRunning, InstanceLock

log = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(settings: Settings) -> None:
    """Ротация вместо бесконечного файла.

    Под launchd stdout/stderr уходят в файлы, которые никто не подрезает, а
    aiogram при обрыве сети пишет по две строки на каждую попытку. Пишем в свой
    ротируемый файл; launchd-овый stderr остаётся сырым каналом для того, что
    падает мимо logging. В терминале дополнительно печатаем на экран.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for stale in list(root.handlers):
        root.removeHandler(stale)

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)

    if sys.stderr.isatty():
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(console)


def register_error_handler(dp: Dispatcher) -> None:
    """Молчание — худший ответ.

    Без этого исключение в обработчике видно только в логе: человек написал
    боту и не получил ничего, даже отказа.
    """

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        log.exception("необработанная ошибка: %s", event.exception)
        message = event.update.message or (
            event.update.callback_query.message
            if event.update.callback_query
            else None
        )
        if isinstance(message, Message):
            with contextlib.suppress(TelegramAPIError):
                await message.answer(
                    "Что-то сломалось на моей стороне. Попробуй ещё раз — "
                    "Кате уже видно в логах."
                )
        return True


async def main() -> None:
    settings = get_settings()
    setup_logging(settings)

    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN пуст. Создай бота в @BotFather (/newbot) "
            "и положи токен в ~/dev/wndr-stickers/.env"
        )
    if not settings.telegram_owner_id:
        raise SystemExit("TELEGRAM_OWNER_ID пуст — без него нельзя владеть стикерпаком.")
    if not settings.reference_sheet_path.exists():
        raise SystemExit(f"Нет ретро-референса: {settings.reference_sheet_path}")
    flat_reference = settings.reference_for("clean")
    if not flat_reference.exists():
        raise SystemExit(f"Нет плоского референса: {flat_reference}")
    if not settings.font_file.exists():
        raise SystemExit(f"Нет шрифта: {settings.font_file}")

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
    register_error_handler(dp)

    # .me() кладёт результат в кэш бота — обработчики потом читают его без
    # похода в сеть. Одновременно это проверка токена до старта polling.
    me = await bot.me()
    log.info(
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
        # Сессию закрываем явно: иначе на остановке остаётся висеть открытый
        # aiohttp-коннектор и в лог падает "Unclosed client session".
        with contextlib.suppress(Exception):
            await bot.session.close()
        lock.release()


if __name__ == "__main__":
    asyncio.run(main())
