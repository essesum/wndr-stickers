"""Главный сценарий: фраза -> стикер -> кнопки «ещё вариант» и «в пак»."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.handlers import moderation
from skill.wndr_stickers.src import (
    approval,
    community_memory,
    db,
    imagegen,
    pack,
    pipeline,
    ratelimit,
)
from skill.wndr_stickers.src import moderation as phrase_moderation
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


async def _produce(
    m: Message, settings: Settings, phrase: str, *, force: bool = False
) -> None:
    """Сделать один стикер и отдать его в чат."""
    user = m.from_user
    assert user is not None

    if not settings.user_allowed(user.id):
        await m.answer("Бот сейчас работает по списку. Напиши Кате, чтобы тебя добавили.")
        return

    if not await db.touch_user(settings.db_path, user.id, user.username):
        await m.answer("Доступ закрыт.")
        return

    verdict = phrase_moderation.check_phrase(phrase)
    if not verdict:
        await db.log_request(settings.db_path, user.id, phrase, "rejected", verdict.reason)
        await m.answer(verdict.reason)
        return

    allowance = await ratelimit.check(settings.db_path, settings, user.id)
    if not allowance:
        await db.log_request(settings.db_path, user.id, phrase, "rejected", allowance.reason)
        await m.answer(allowance.reason)
        return

    # Проверяем повтор ДО генерации: так не тратим вызов модели на то,
    # что в паке уже есть. Память сообщества недоступна — просто идём дальше.
    if settings.duplicate_check:
        similar = await community_memory.find_similar(settings.db_path, phrase)
        hit = community_memory.decide_duplicate(
            similar, threshold=settings.duplicate_threshold
        )
        if hit is not None and not force:
            await m.answer(
                f"Похожее уже есть: «{hit.phrase}» ({hit.slug}-v{hit.version}).\n"
                "Если всё равно нужен свой вариант — пришли фразу ещё раз "
                "с «!» в начале."
            )
            await db.log_request(settings.db_path, user.id, phrase, "rejected", "duplicate")
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
    except pipeline.StickerVerificationError as exc:
        await db.log_request(settings.db_path, user.id, phrase, "failed", str(exc)[:500])
        log.warning("вариант отклонён WNDR style gate: %s", exc)
        await notice.edit_text(
            "Вариант не прошёл проверку фирменного стиля WNDR, поэтому я его не отправляю. "
            "Попробуй ещё раз — плохой вариант в пак не попадёт."
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
    # Запоминаем фразу, чтобы следующий такой же запрос поймался как повтор.
    await community_memory.remember(
        settings.db_path,
        result.phrase,
        sticker_id=sticker_id,
        slug=result.slug,
        version=result.version,
    )

    caption = f"«{result.phrase}»\nформа {result.shape} · кегль {result.font_size}"
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
        text = (m.text or "").strip()
        # «!» в начале — сделать вариант, даже если похожее уже есть.
        force = text.startswith("!")
        await _produce(m, settings, text.lstrip("!").strip(), force=force)

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

        user = query.from_user
        bot = query.bot
        assert bot is not None

        # Модераторы и доверенные кладут сразу, остальные — через очередь.
        if await approval.needs_approval(settings.db_path, settings, user.id):
            submission_id = await db.create_submission(
                settings.db_path, sticker_id, user.id
            )
            delivered = await moderation.notify_moderators(bot, settings, submission_id)
            await query.answer("Отправила на апрув")
            if isinstance(query.message, Message):
                await query.message.answer(
                    "Заявка ушла модераторам"
                    + (f" ({delivered})" if delivered else ", но никто не получил — "
                       "проверь MODERATOR_IDS")
                    + ". Файл уже твой, ждать его не нужно."
                )
            return

        await query.answer("Добавляю в пак…")
        me = await bot.get_me()
        try:
            name, link = await pack.add_with_overflow(
                bot,
                owner_id=settings.sticker_pack_owner,
                slug=settings.pack_slug,
                bot_username=me.username or "",
                title=settings.pack_title,
                sticker_path=Path(row.path),
                emoji=settings.default_emoji,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("не удалось добавить в пак")
            if isinstance(query.message, Message):
                await query.message.answer(f"В пак не уехало: {exc}")
            return

        await db.mark_in_pack(
            settings.db_path, sticker_id, settings.default_emoji, name
        )
        pack.rebuild_zip(settings.stickers_dir, settings.zip_path)
        if isinstance(query.message, Message):
            await query.message.answer(f"Готово, стикер в паке:\n{link}")

    return router


__all__ = ["build_router"]
