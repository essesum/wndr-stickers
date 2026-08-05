"""Главный сценарий: фраза -> стикер -> кнопки «ещё вариант» и «в пак»."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from skill.wndr_stickers.src import db, imagegen, moderation, pack, pipeline, ratelimit
from skill.wndr_stickers.src.config import Settings

log = logging.getLogger(__name__)


def _keyboard(sticker_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Ещё вариант", callback_data=f"again:{sticker_id}"),
                InlineKeyboardButton(text="➕ В пак", callback_data=f"pack:{sticker_id}"),
            ]
        ]
    )


async def _produce(m: Message, settings: Settings, phrase: str) -> None:
    """Сделать один стикер и отдать его в чат."""
    user = m.from_user
    assert user is not None

    if not settings.user_allowed(user.id):
        await m.answer("Бот сейчас работает по списку. Напиши Кате, чтобы тебя добавили.")
        return

    if not await db.touch_user(settings.db_path, user.id, user.username):
        await m.answer("Доступ закрыт.")
        return

    verdict = moderation.check_phrase(phrase)
    if not verdict:
        await db.log_request(settings.db_path, user.id, phrase, "rejected", verdict.reason)
        await m.answer(verdict.reason)
        return

    allowance = await ratelimit.check(settings.db_path, settings, user.id)
    if not allowance:
        await db.log_request(settings.db_path, user.id, phrase, "rejected", allowance.reason)
        await m.answer(allowance.reason)
        return

    notice = await m.answer("Рисую плашку и набираю текст, это займёт полминуты…")
    try:
        result = await asyncio.to_thread(pipeline.make_sticker, phrase, settings)
    except imagegen.ImageGenerationError as exc:
        await db.log_request(settings.db_path, user.id, phrase, "failed", str(exc)[:500])
        log.error("генерация не удалась: %s", exc)
        await notice.edit_text(
            "Картинку сделать не вышло — все провайдеры отказали. "
            "Чаще всего это кончившиеся кредиты. Кате уже видно в логах."
        )
        return
    except Exception as exc:  # noqa: BLE001
        await db.log_request(settings.db_path, user.id, phrase, "failed", str(exc)[:500])
        log.exception("пайплайн упал")
        await notice.edit_text(f"Что-то сломалось: {type(exc).__name__}. Попробуй ещё раз.")
        return

    request_id = await db.log_request(settings.db_path, user.id, phrase, "ok")
    sticker_id = await db.save_sticker(
        settings.db_path, request_id=request_id, user_id=user.id, result=result
    )

    caption = f"«{result.phrase}»\nформа {result.shape} · кегль {result.font_size}"
    if not result.ok:
        caption += "\n⚠️ " + "; ".join(result.checks.problems)

    await notice.delete()
    # документом — чтобы Telegram не пережал файл и он остался пригодным для пака
    await m.answer_document(
        FSInputFile(result.path),
        caption=caption,
        reply_markup=_keyboard(sticker_id),
    )


def build_router(settings: Settings) -> Router:
    router = Router(name="generate")

    @router.message(Command("sticker"))
    async def _explicit(m: Message, command: Command) -> None:
        phrase = (command.args or "").strip()
        if not phrase:
            await m.answer("Напиши так: <code>/sticker Со мной все нормально</code>")
            return
        await _produce(m, settings, phrase)

    @router.message(F.text & ~F.text.startswith("/"))
    async def _plain_text(m: Message) -> None:
        await _produce(m, settings, (m.text or "").strip())

    @router.callback_query(F.data.startswith("again:"))
    async def _again(query: CallbackQuery) -> None:
        await query.answer("Делаю новый вариант")
        sticker_id = int((query.data or "0:0").split(":", 1)[1])
        row = await db.get_sticker(settings.db_path, sticker_id)
        if row is None or not isinstance(query.message, Message):
            return
        await _produce(query.message, settings, row.phrase)

    @router.callback_query(F.data.startswith("pack:"))
    async def _to_pack(query: CallbackQuery) -> None:
        sticker_id = int((query.data or "0:0").split(":", 1)[1])
        row = await db.get_sticker(settings.db_path, sticker_id)
        if row is None:
            await query.answer("Стикер потерялся")
            return
        if row.in_pack:
            await query.answer("Уже в паке")
            return

        await query.answer("Добавляю в пак…")
        bot = query.bot
        assert bot is not None
        me = await bot.get_me()
        name = pack.pack_name(settings.pack_slug, me.username or "")
        from pathlib import Path

        try:
            link = await pack.add_to_pack(
                bot,
                owner_id=settings.telegram_owner_id,
                name=name,
                title=settings.pack_title,
                sticker_path=Path(row.path),
                emoji=settings.default_emoji,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("не удалось добавить в пак")
            if isinstance(query.message, Message):
                await query.message.answer(f"В пак не уехало: {exc}")
            return

        await db.mark_in_pack(settings.db_path, sticker_id, settings.default_emoji)
        pack.rebuild_zip(settings.stickers_dir, settings.zip_path)
        if isinstance(query.message, Message):
            await query.message.answer(f"Готово, стикер в паке:\n{link}")

    return router


__all__ = ["build_router", "BufferedInputFile"]
