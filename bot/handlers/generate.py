"""Главный сценарий: фраза -> стикер -> кнопки «ещё вариант» и «в пак»."""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from skill.wndr_stickers.src import (
    community_memory,
    db,
    imagegen,
    intent,
    pack,
    pipeline,
    ratelimit,
    voice,
)
from skill.wndr_stickers.src import moderation as phrase_moderation
from skill.wndr_stickers.src.config import Settings

log = logging.getLogger(__name__)
PACK_MUTATION_LOCK = asyncio.Lock()


#: id в SQLite — знаковый 64-битный; больше него sqlite3 бросает OverflowError
#: прямо на execute(), то есть падение обработчика вместо отказа.
_MAX_SQLITE_INT = 2**63 - 1


def _callback_sticker_id(data: str | None) -> int | None:
    """id из callback_data кнопки.

    Клиент присылает эту строку сам, так что она может быть какой угодно —
    голый `int()` здесь падал с ValueError. `isdigit()` тоже недостаточно: он
    пропускает не-ASCII цифры («٣»), а id у нас всегда обычное число.
    """
    _, _, raw = (data or "").partition(":")
    raw = raw.strip()
    if not (raw.isascii() and raw.isdigit()):
        return None
    value = int(raw)
    return value if value <= _MAX_SQLITE_INT else None


def _keyboard(sticker_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Ещё вариант", callback_data=f"again:{sticker_id}"),
                InlineKeyboardButton(text="➕ В пак", callback_data=f"pack:{sticker_id}"),
            ]
        ]
    )


async def _rebuild_public_zip(settings: Settings) -> None:
    rows = await db.pack_stickers(settings.db_path)
    pack.rebuild_zip(
        settings.stickers_dir,
        settings.zip_path,
        active_paths=(Path(row.path) for row in rows),
    )


async def _cooldown_left(settings: Settings, sticker_id: int, user_id: int) -> int:
    if user_id == settings.telegram_owner_id:
        return 0
    elapsed = await db.seconds_since_last_community_action(settings.db_path, sticker_id)
    if elapsed is None:
        return 0
    return max(0, settings.pack_action_cooldown_seconds - elapsed)


def _delete_hint_chunks(rows: list[db.StickerRow], *, max_chars: int = 3500) -> list[str]:
    if not rows:
        return ["В паке пока пусто."]
    header = "Что удалить? Скопируй строку целиком и отправь боту:\n"
    chunks: list[str] = [header]
    for row in rows:
        line = f"<code>удали #{row.id}</code> — {html.escape(row.phrase)}\n"
        if len(chunks[-1]) + len(line) > max_chars and chunks[-1] != header:
            chunks.append(header)
        chunks[-1] += line
    return [chunk.rstrip() for chunk in chunks]


def _delete_hint(rows: list[db.StickerRow]) -> str:
    return _delete_hint_chunks(rows)[0]


def _pack_list_chunks(rows: list[db.StickerRow], *, max_chars: int = 3500) -> list[str]:
    if not rows:
        return ["В паке пока пусто."]
    header = "В паке:\n"
    chunks: list[str] = [header]
    for row in rows:
        line = f"• #{row.id} — {html.escape(row.phrase)}\n"
        if len(chunks[-1]) + len(line) > max_chars and chunks[-1] != header:
            chunks.append(header)
        chunks[-1] += line
    return [chunk.rstrip() for chunk in chunks]


def _removed_message(phrase: str) -> str:
    return (
        f"Убрал «{html.escape(phrase)}». Файл сохранён: любой участник может вернуть его "
        "командой «верни в пак»."
    )


async def _reply_delete_hint(m: Message, rows: list[db.StickerRow]) -> None:
    for chunk in _delete_hint_chunks(rows):
        await m.reply(chunk)


async def _reply_pack_list(m: Message, rows: list[db.StickerRow]) -> None:
    for chunk in _pack_list_chunks(rows):
        await m.reply(chunk)


async def _find_in_pack_by_phrase_or_id(settings: Settings, phrase: str) -> db.StickerRow | None:
    key = phrase.strip()
    if key.startswith("#") and key[1:].isdigit():
        row = await db.get_sticker(settings.db_path, int(key[1:]))
        if row and row.in_pack:
            return row
        return None
    return await db.find_in_pack(settings.db_path, phrase)


async def _remove(m: Message, settings: Settings, phrase: str) -> None:
    """Убрать стикер из общего пака; действие открыто и обратимо."""
    user = m.from_user
    assert user is not None and m.bot is not None

    if not phrase:
        rows = await db.pack_stickers(settings.db_path)
        await _reply_delete_hint(m, rows)
        return

    row = await _find_in_pack_by_phrase_or_id(settings, phrase)
    if row is None:
        rows = await db.pack_stickers(settings.db_path)
        await m.reply(f"В паке нет «{html.escape(phrase)}».")
        await _reply_delete_hint(m, rows)
        return

    if not settings.user_allowed(user.id) or not await db.touch_user(
        settings.db_path, user.id, user.username
    ):
        await m.reply("Доступ закрыт.")
        return

    if not row.file_id:
        await m.reply(
            "Этот стикер добавлен до того, как бот научился удалять, "
            "и его идентификатор не сохранён. Убери вручную через @Stickers."
        )
        return

    async with PACK_MUTATION_LOCK:
        fresh = await db.get_sticker(settings.db_path, row.id)
        if fresh is None or not fresh.in_pack:
            await m.reply("Его уже убрали — можно вернуть командой «верни в пак …».")
            return
        if user.id != settings.telegram_owner_id:
            used = await db.count_community_actions(
                settings.db_path, user_id=user.id, action="removed", hours=24
            )
            if used >= settings.rate_removals_per_user_day:
                await m.reply("На сегодня хватит удалений. Сообщество — не кнопочный тир.")
                return
        cooldown = await _cooldown_left(settings, row.id, user.id)
        if cooldown:
            await m.reply(f"Подожди {cooldown} сек., чтобы пак не дёргался туда-сюда.")
            return
        if not await db.claim_pack_operation(settings.db_path, row.id, "removing"):
            await m.reply("Этот стикер уже кто-то меняет. Попробуй через минуту.")
            return
        try:
            assert fresh.file_id is not None
            await m.bot.delete_sticker_from_set(sticker=fresh.file_id)
        except Exception:  # noqa: BLE001
            await db.release_pack_operation(settings.db_path, row.id, "removing")
            log.exception("не удалось убрать стикер из набора")
            await m.reply("Не убралось. Состояние не потеряно — попробуй ещё раз.")
            return

        await db.mark_removed_from_pack(settings.db_path, row.id)
        await db.log_community_action(settings.db_path, row.id, user.id, "removed")
        await _rebuild_public_zip(settings)
    await m.reply(_removed_message(row.phrase))


async def _add_row_to_pack(
    bot: Bot,
    settings: Settings,
    row: db.StickerRow,
    user: User,
    *,
    restoring: bool,
) -> tuple[bool, str]:
    """Добавить/вернуть стикер; сериализовано и идемпотентно."""
    operation = "restoring" if restoring else "adding"
    action = "restored" if restoring else "added"
    async with PACK_MUTATION_LOCK:
        fresh = await db.get_sticker(settings.db_path, row.id)
        if fresh is None:
            return False, "Стикер потерялся."
        if fresh.in_pack:
            return True, "Он уже в паке."
        cooldown = await _cooldown_left(settings, row.id, user.id)
        if cooldown:
            return False, f"Подожди {cooldown} сек., чтобы пак не дёргался туда-сюда."
        if not await db.claim_pack_operation(settings.db_path, row.id, operation):
            return False, "Этот стикер уже кто-то меняет. Попробуй через минуту."

        me = await bot.me()
        try:
            name, link, file_id = await pack.add_with_overflow(
                bot,
                owner_id=settings.sticker_pack_owner,
                slug=settings.pack_slug,
                bot_username=me.username or "",
                title=settings.pack_title,
                sticker_path=Path(fresh.path),
                emoji=settings.default_emoji,
            )
        except Exception:  # noqa: BLE001
            await db.release_pack_operation(settings.db_path, row.id, operation)
            log.exception("не удалось добавить стикер в пак")
            return False, "В пак не уехало. Состояние сохранено — попробуй ещё раз."

        await db.mark_in_pack(
            settings.db_path, row.id, settings.default_emoji, name, file_id
        )
        await db.log_community_action(settings.db_path, row.id, user.id, action, name)
        await _rebuild_public_zip(settings)
        verb = "Вернул" if restoring else "Добавил"
        return True, f"{verb} «{html.escape(fresh.phrase)}» в общий пак:\n{link}"


async def _restore(m: Message, settings: Settings, phrase: str) -> None:
    user = m.from_user
    assert user is not None and m.bot is not None
    if not phrase:
        await m.reply('Что вернуть? Например: <code>верни в пак "я так чувствую"</code>')
        return
    if not settings.user_allowed(user.id) or not await db.touch_user(
        settings.db_path, user.id, user.username
    ):
        await m.reply("Доступ закрыт.")
        return
    row = await db.find_removed(settings.db_path, phrase)
    if row is None:
        # Текст сюда приходит как есть, без moderation.check_phrase: экранируем,
        # иначе `<b>` ломает parse_mode=HTML, а `<a href>` даёт чужую ссылку
        # голосом бота.
        await m.reply(f"Не нашёл удалённый стикер «{html.escape(phrase)}».")
        return
    _, message = await _add_row_to_pack(m.bot, settings, row, user, restoring=True)
    await m.reply(message)


async def _produce(
    m: Message,
    settings: Settings,
    phrase: str,
    *,
    force: bool = False,
    requester: User | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """Сделать один стикер и отдать его в чат.

    `requester` нужен для кнопок: сообщение под ними принадлежит боту, поэтому
    `m.from_user` — это сам бот. Без явного автора квоты и авторство писались бы
    на бота, а не на человека, который нажал кнопку.
    """
    user = requester or m.from_user
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

    # Проверяем повтор ДО генерации: так не тратим вызов модели на то,
    # что в паке уже есть. Память сообщества недоступна — просто идём дальше.
    if settings.duplicate_check:
        similar = await community_memory.find_similar(settings.db_path, phrase)
        hit = community_memory.decide_duplicate(
            similar, threshold=settings.duplicate_threshold
        )
        if hit is not None and not force:
            await m.answer(
                f"Похожее уже есть: «{html.escape(hit.phrase)}» "
                f"({html.escape(hit.slug)}-v{hit.version}).\n"
                "Если всё равно нужен свой вариант — пришли фразу ещё раз "
                "с «!» в начале."
            )
            await db.log_request(settings.db_path, user.id, phrase, "rejected", "duplicate")
            return

    allowance = await ratelimit.reserve(settings.db_path, settings, user.id, phrase)
    if not allowance or allowance.request_id is None:
        await m.answer(allowance.reason)
        return
    request_id = allowance.request_id

    notice = await m.answer(voice.waiting())
    try:
        if semaphore is None:
            result = await asyncio.to_thread(pipeline.make_sticker, phrase, settings)
        else:
            async with semaphore:
                result = await asyncio.to_thread(pipeline.make_sticker, phrase, settings)
    except imagegen.ImageGenerationError as exc:
        await db.update_request(settings.db_path, request_id, "failed", str(exc)[:500])
        log.error("генерация не удалась: %s", exc)
        await notice.edit_text(
            "Картинку сделать не вышло — все провайдеры отказали. "
            "Чаще всего это кончившиеся кредиты. Кате уже видно в логах."
        )
        return
    except pipeline.StickerVerificationError as exc:
        await db.update_request(settings.db_path, request_id, "failed", str(exc)[:500])
        log.warning("вариант отклонён WNDR style gate: %s", exc)
        await notice.edit_text(
            "Вариант не прошёл проверку фирменного стиля WNDR, поэтому я его не отправляю. "
            "Попробуй ещё раз — плохой вариант в пак не попадёт."
        )
        return
    except Exception as exc:  # noqa: BLE001
        await db.update_request(settings.db_path, request_id, "failed", str(exc)[:500])
        log.exception("пайплайн упал")
        await notice.edit_text(voice.failed())
        return

    await db.update_request(settings.db_path, request_id, "ok")
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

    caption = voice.done(html.escape(result.phrase))
    # Стикер уже сгенерирован, оплачен и записан. Убрать «колдую…» — косметика,
    # и её неудача (истёкшее окно удаления, сетевой сбой) не повод не отдать
    # человеку то, за что он потратил квоту.
    with contextlib.suppress(TelegramAPIError):
        await notice.delete()
    # документом — чтобы Telegram не пережал файл и он остался пригодным для пака
    await m.answer_document(
        FSInputFile(result.path),
        caption=caption,
        reply_markup=_keyboard(sticker_id),
    )


def build_router(settings: Settings) -> Router:
    router = Router(name="generate")
    generation_slots = asyncio.Semaphore(max(1, settings.max_concurrent_generations))

    @router.message(Command("sticker"))
    async def _explicit(m: Message, command: CommandObject) -> None:
        phrase = (command.args or "").strip()
        if not phrase:
            await m.answer("Напиши так: <code>/sticker Со мной все нормально</code>")
            return
        await _produce(m, settings, phrase, semaphore=generation_slots)

    @router.message(Command("delete", "remove"))
    async def _delete_command(m: Message, command: CommandObject) -> None:
        await _remove(m, settings, (command.args or "").strip())

    @router.message(F.text & ~F.text.startswith("/"))
    async def _plain_text(m: Message) -> None:
        assert m.bot is not None
        # .me() кэширует, .get_me() — нет. Здесь это вызов на каждое сообщение
        # чата, то есть лишний round-trip к api.telegram.org перед любой работой.
        me = await m.bot.me()
        # Тег обязателен везде, кроме личной переписки: в общем чате бот иначе
        # нарисует стикер на каждую реплику. Раньше здесь был белый список
        # ("group", "supergroup") — он пропускал канал, где chat.type ==
        # "channel", и гейт молча выключался. Проверяем private, а не
        # перечисляем групповые типы: новый тип чата не откроет бота заново.
        is_private = m.chat.type == ChatType.PRIVATE
        replied_to_bot = bool(
            m.reply_to_message
            and m.reply_to_message.from_user
            and m.reply_to_message.from_user.id == me.id
        )
        got = intent.parse(
            m.text or "",
            bot_username=me.username,
            require_mention=not is_private and not replied_to_bot,
        )
        if not got.addressed:
            return

        if got.action is intent.Action.HELP:
            await m.reply(voice.help_text(got.phrase))
            return

        if got.action is intent.Action.LIST:
            rows = await db.pack_stickers(settings.db_path)
            await _reply_pack_list(m, rows)
            return

        if got.action is intent.Action.DELETE:
            await _remove(m, settings, got.phrase)
            return

        if got.action is intent.Action.RESTORE:
            await _restore(m, settings, got.phrase)
            return

        if not got.phrase:
            await m.reply("Напиши фразу — верну стикер.")
            return
        await _produce(
            m, settings, got.phrase, force=got.force, semaphore=generation_slots
        )

    @router.callback_query(F.data.startswith("again:"))
    async def _again(query: CallbackQuery) -> None:
        sticker_id = _callback_sticker_id(query.data)
        if sticker_id is None:
            await query.answer("Кнопка испорчена")
            return
        row = await db.get_sticker(settings.db_path, sticker_id)
        if row is None or not isinstance(query.message, Message):
            await query.answer("Стикер потерялся")
            return
        await query.answer("Делаю новый вариант")
        # force=True: кнопка и означает «сделай ещё один». Без этого проверка
        # дублей отбивала собственную же кнопку — первое, что видит человек,
        # нажавший «Ещё вариант», это отказ «похожее уже есть».
        await _produce(
            query.message,
            settings,
            row.phrase,
            force=True,
            requester=query.from_user,
            semaphore=generation_slots,
        )

    @router.callback_query(F.data.startswith("pack:"))
    async def _to_pack(query: CallbackQuery) -> None:
        sticker_id = _callback_sticker_id(query.data)
        if sticker_id is None:
            await query.answer("Кнопка испорчена")
            return
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
        if not settings.user_allowed(user.id) or not await db.touch_user(
            settings.db_path, user.id, user.username
        ):
            await query.answer("Доступ закрыт", show_alert=True)
            return

        await query.answer("Добавляю в пак…")
        _, message = await _add_row_to_pack(bot, settings, row, user, restoring=False)
        if isinstance(query.message, Message):
            await query.message.answer(message)

    return router


__all__ = ["build_router"]
