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

#: Кто и на каком основании может убрать стикер из пака. Голосование убрано
#: (решение Кати, 2026-08-12): чужой стикер убирает автор, владелец или
#: модератор клуба; остальным бот подсказывает, кому написать.
CORE, AUTHOR, OWNER, MODERATOR, ASK = "core", "author", "owner", "moderator", "ask"


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


def _redo_keyboard(request_id: int, label: str) -> InlineKeyboardMarkup:
    """Повтор по номеру заявки: фразу бот уже знает, перепечатывать её незачем.

    В callback_data кладём id, а не саму фразу — там всего 64 байта, и любая
    живая фраза туда не влезет.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"redo:{request_id}")]
        ]
    )


def _offer_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Выбор для фразы-картинки. В callback_data — id заявки: фраза не влезает."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🖼 Без текста", callback_data=f"illu:{request_id}"),
                InlineKeyboardButton(text="🔤 С текстом", callback_data=f"text:{request_id}"),
            ]
        ]
    )


def _pack_list_keyboard(
    rows: list[db.StickerRow],
    settings: Settings,
    user_id: int,
    username: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Кнопки ✕ под списком пака — только у того, что человек вправе убрать.

    У чужих стикеров кнопки нет вовсе: убрать их может лишь автор или
    модератор, и кнопка, которая ничего не делает, только злила бы.
    """
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows[:20]:
        right = _removal_right(row, user_id, settings, username)
        if right not in (AUTHOR, OWNER, MODERATOR):
            continue
        short = row.phrase if len(row.phrase) <= 18 else row.phrase[:17] + "…"
        buttons.append(
            [InlineKeyboardButton(text=f"✕ {short}", callback_data=f"rm:{row.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


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


#: Что человек увидит рядом со стикером в списке — по своим правам на него.
_RIGHT_HINT = {
    CORE: "основа пака",
    AUTHOR: "твой",
    OWNER: "твой пак",
    MODERATOR: "модерация",
    ASK: "чужой",
}


def _delete_hint_chunks(
    rows: list[db.StickerRow],
    settings: Settings,
    user_id: int,
    username: str | None = None,
    *,
    max_chars: int = 3500,
) -> list[str]:
    """Список пака с пометкой, что человек может сделать с каждым стикером."""
    if not rows:
        return ["В паке пока пусто."]
    header = "Что в паке. Нажми ✕ под сообщением или отправь строку боту:\n"
    chunks: list[str] = [header]
    for row in rows:
        right = _removal_right(row, user_id, settings, username)
        line = (
            f"<code>удали #{row.id}</code> — {html.escape(row.phrase)}"
            f" <i>({_RIGHT_HINT[right]})</i>\n"
        )
        if len(chunks[-1]) + len(line) > max_chars and chunks[-1] != header:
            chunks.append(header)
        chunks[-1] += line
    return [chunk.rstrip() for chunk in chunks]


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
    # Возврата нет: передумал — сделай новый. Обещать обратимость нельзя,
    # раз её больше не существует.
    return (
        f"Убрал «{html.escape(phrase)}». Обратно не вернуть — "
        "если нужен снова, пришли фразу, сделаю новый."
    )


#: Владелец узнаёт о поломках сам, а не из жалоб. Чаще раза в час не пишем:
#: при обрыве сети цепочка ложится на каждом запросе, и это был бы флуд.
_LAST_ALERT: dict[str, float] = {}
ALERT_COOLDOWN_SECONDS = 3600


async def _alert_owner(bot: Bot, settings: Settings, text: str, *, key: str = "chain") -> None:
    if not settings.telegram_owner_id:
        return
    now = asyncio.get_running_loop().time()
    if now - _LAST_ALERT.get(key, 0.0) < ALERT_COOLDOWN_SECONDS:
        return
    _LAST_ALERT[key] = now
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(settings.telegram_owner_id, f"⚠️ {text}")


async def _reply_delete_hint(
    m: Message,
    rows: list[db.StickerRow],
    settings: Settings,
    user_id: int,
    username: str | None = None,
) -> None:
    chunks = _delete_hint_chunks(rows, settings, user_id, username)
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        await m.reply(
            chunk,
            reply_markup=(
                _pack_list_keyboard(rows, settings, user_id, username) if last else None
            ),
        )


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


def _removal_right(
    row: db.StickerRow, user_id: int, settings: Settings, username: str | None = None
) -> str:
    """Основание для удаления. Порядок проверок и есть политика.

    Владелец может всё. Ядро не трогает никто, кроме владельца, — даже
    модераторы. Свой стикер автор убирает сам — он его сделал, ему и решать.
    Чужой убирает модератор клуба; остальным бот подсказывает, кому написать.
    """
    if user_id == settings.telegram_owner_id:
        return OWNER
    if row.is_core:
        return CORE
    if row.user_id == user_id:
        return AUTHOR
    if settings.is_moderator(user_id, username):
        return MODERATOR
    return ASK


async def _drop_from_pack(
    bot: Bot, settings: Settings, row: db.StickerRow, user_id: int, reason: str
) -> tuple[bool, str]:
    """Физически убрать стикер из набора. Общий путь для автора, владельца и модератора."""
    async with PACK_MUTATION_LOCK:
        fresh = await db.get_sticker(settings.db_path, row.id)
        if fresh is None or not fresh.in_pack:
            return False, "Его уже убрали."
        if not fresh.file_id:
            return False, (
                "Этот стикер добавлен до того, как бот научился удалять, "
                "и его идентификатор не сохранён. Убери вручную через @Stickers."
            )
        # Пак нельзя опустошать: удаление последнего стикера уничтожает набор
        # в Telegram, а имя удалённого набора не переиспользуется — ссылка,
        # которую все добавили, умерла бы навсегда.
        if len(await db.pack_stickers(settings.db_path)) <= 1:
            return False, (
                "Это последний стикер в паке — если убрать его, Telegram удалит "
                "весь набор и ссылка перестанет работать. Сделай новый, потом убирай."
            )
        if not await db.claim_pack_operation(settings.db_path, row.id, "removing"):
            return False, "Этот стикер уже кто-то меняет. Попробуй через минуту."
        try:
            await bot.delete_sticker_from_set(sticker=fresh.file_id)
        except Exception:  # noqa: BLE001
            await db.release_pack_operation(settings.db_path, row.id, "removing")
            log.exception("не удалось убрать стикер из набора")
            return False, "Не убралось. Состояние не потеряно — попробуй ещё раз."

        await db.mark_removed_from_pack(settings.db_path, row.id)
        await db.log_community_action(
            settings.db_path, row.id, user_id, "removed", reason
        )
        await _rebuild_public_zip(settings)
    return True, _removed_message(fresh.phrase)


def _foreign_removal_hint(settings: Settings) -> str:
    """Куда идти за удалением чужого стикера. Голосования больше нет."""
    mods = ", ".join(f"@{name}" for name in settings.moderator_mentions)
    return (
        "Чужой стикер может убрать только его автор или модераторы клуба"
        f"{f' ({mods})' if mods else ''}. "
        f"Хочешь, чтобы стикер убрали, — напиши {settings.moderator_contact}."
    )


async def _remove(m: Message, settings: Settings, phrase: str) -> None:
    """Убрать стикер из пака по правам: свой — сам, чужой — через модератора."""
    user = m.from_user
    assert user is not None and m.bot is not None

    if not phrase:
        rows = await db.pack_stickers(settings.db_path)
        await _reply_delete_hint(m, rows, settings, user.id, user.username)
        return

    row = await _find_in_pack_by_phrase_or_id(settings, phrase)
    if row is None:
        rows = await db.pack_stickers(settings.db_path)
        await m.reply(f"В паке нет «{html.escape(phrase)}».")
        await _reply_delete_hint(m, rows, settings, user.id, user.username)
        return

    if not settings.user_allowed(user.id) or not await db.touch_user(
        settings.db_path, user.id, user.username
    ):
        await m.reply("Доступ закрыт.")
        return

    right = _removal_right(row, user.id, settings, user.username)

    if right is CORE:
        await m.reply(
            "Это стикер из основы пака — он останется. "
            "Сделать новый можно всегда: просто пришли фразу."
        )
        return

    if right is ASK:
        await m.reply(_foreign_removal_hint(settings))
        return

    if right is AUTHOR:
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

    _, message = await _drop_from_pack(m.bot, settings, row, user.id, right)
    await m.reply(message)


async def _retire_anchor(bot: Bot, settings: Settings) -> None:
    """Снять якорный стикер, как только сообществу есть чем его заменить.

    Пак нельзя оставлять пустым: удаление последнего стикера уничтожает набор
    в Telegram, а его имя потом не переиспользуется — ссылка, которую все
    добавили, умерла бы. Поэтому при рестарте сезона один стикер оставлен
    якорем и помечен как неприкосновенный.

    Как только в паке появляется что-то ещё, держать якорь больше незачем:
    сезон наполняют участники. Правило самоотключается — после ухода якоря
    неприкосновенных в паке не остаётся и условие никогда не срабатывает снова.
    """
    rows = await db.pack_stickers(settings.db_path)
    if len(rows) < 2:
        return
    anchors = [row for row in rows if row.is_core]
    if len(anchors) != 1:
        return
    anchor = anchors[0]
    if not anchor.file_id:
        return
    try:
        await bot.delete_sticker_from_set(sticker=anchor.file_id)
    except Exception:  # noqa: BLE001 — не смогли снять, попробуем в следующий раз
        log.warning("якорный стикер не снялся, останется до следующего добавления")
        return
    await db.mark_removed_from_pack(settings.db_path, anchor.id)
    await db.clear_core(settings.db_path, anchor.id)
    log.info("якорь «%s» снят: сезон наполняют участники", anchor.phrase)


async def _add_row_to_pack(
    bot: Bot, settings: Settings, row: db.StickerRow, user: User
) -> tuple[bool, str]:
    """Положить стикер в общий пак; сериализовано и идемпотентно."""
    operation, action = "adding", "added"
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
        await _retire_anchor(bot, settings)
        await _rebuild_public_zip(settings)
        return True, f"Добавил «{html.escape(fresh.phrase)}» в общий пак:\n{link}"


#: Префикс, под которым стикеры-картинки живут в БД. По нему повтор («ещё
#: вариант», «попробовать ещё раз») понимает, что рисовать надо снова картинку.
ILLUSTRATION_LABEL = "без текста "


async def _produce(
    m: Message,
    settings: Settings,
    phrase: str,
    *,
    force: bool = False,
    requester: User | None = None,
    semaphore: asyncio.Semaphore | None = None,
    illustration: bool = False,
) -> None:
    """Сделать один стикер и отдать его в чат.

    `requester` нужен для кнопок: сообщение под ними принадлежит боту, поэтому
    `m.from_user` — это сам бот. Без явного автора квоты и авторство писались бы
    на бота, а не на человека, который нажал кнопку.

    При `illustration=True` `phrase` — это описание картинки, а не надпись:
    рисуется стикер без текста, в БД он живёт под ярлыком «без текста …».
    """
    user = requester or m.from_user
    assert user is not None
    label = f"{ILLUSTRATION_LABEL}{phrase}" if illustration else phrase

    if not settings.user_allowed(user.id):
        await m.answer("Бот сейчас работает по списку. Напиши Кате, чтобы тебя добавили.")
        return

    if not await db.touch_user(settings.db_path, user.id, user.username):
        await m.answer("Доступ закрыт.")
        return

    # Откуда пришёл запрос. Нужно, чтобы потом отличить личку от общего чата:
    # это разные сценарии, и по ним по-разному читается,живёт ли бот в клубе.
    chat_type = m.chat.type if m.chat else None

    verdict = phrase_moderation.check_phrase(label)
    if not verdict:
        await db.log_request(
            settings.db_path, user.id, label, "rejected", verdict.reason,
            chat_type=chat_type,
        )
        await m.answer(verdict.reason)
        return

    # Проверяем повтор ДО генерации: так не тратим вызов модели на то,
    # что в паке уже есть. Память сообщества недоступна — просто идём дальше.
    if settings.duplicate_check:
        similar = await community_memory.find_similar(settings.db_path, label)
        hit = community_memory.decide_duplicate(
            similar, threshold=settings.duplicate_threshold
        )
        if hit is not None and not force:
            rejected_id = await db.log_request(
                settings.db_path, user.id, label, "rejected", "duplicate",
                chat_type=chat_type,
            )
            await m.answer(
                f"Похожее уже есть: «{html.escape(hit.phrase)}» "
                f"({html.escape(hit.slug)}-v{hit.version}).",
                reply_markup=_redo_keyboard(rejected_id, "✨ Всё равно сделай"),
            )
            return

    allowance = await ratelimit.reserve(
        settings.db_path, settings, user.id, label, chat_type=chat_type
    )
    if not allowance or allowance.request_id is None:
        await m.answer(allowance.reason)
        return
    request_id = allowance.request_id

    notice = await m.answer(voice.waiting())

    def _run():
        if illustration:
            return pipeline.make_illustration(phrase, settings)
        return pipeline.make_sticker(phrase, settings)

    try:
        if semaphore is None:
            result = await asyncio.to_thread(_run)
        else:
            async with semaphore:
                result = await asyncio.to_thread(_run)
    except imagegen.ImageGenerationError as exc:
        await db.update_request(settings.db_path, request_id, "failed", str(exc)[:500])
        log.error("генерация не удалась: %s", exc)
        # Легла вся цепочка — это уже не невезение, а поломка. Владелец узнаёт
        # об этом сам, а не из жалоб: раньше бот обещал «Кате видно в логах»,
        # но в логи никто не смотрит в момент, когда всё встало.
        await _alert_owner(
            m.bot, settings, f"Все провайдеры отказали.\n<code>{html.escape(str(exc)[:600])}</code>"
        )
        await notice.edit_text(
            "Картинку сделать не вышло — все провайдеры отказали. "
            "Кате уже ушло уведомление.",
            reply_markup=_redo_keyboard(request_id, "🔁 Попробовать ещё раз"),
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
        await notice.edit_text(
            voice.failed(),
            reply_markup=_redo_keyboard(request_id, "🔁 Попробовать ещё раз"),
        )
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


async def _produce_illustration(
    m: Message,
    settings: Settings,
    motif: str,
    *,
    force: bool = False,
    requester: User | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """Стикер-картинка без надписи. Квоты, дубли и стиль-гейт — общие."""
    await _produce(
        m, settings, motif,
        force=force, requester=requester, semaphore=semaphore, illustration=True,
    )


async def _dispatch_produce(
    m: Message,
    settings: Settings,
    phrase: str,
    *,
    force: bool = False,
    requester: User | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """Повтор по фразе из БД: ярлык «без текста …» обязан снова дать картинку,
    а не стикер со словами «без текста» поперёк плашки."""
    if phrase.startswith(ILLUSTRATION_LABEL):
        await _produce_illustration(
            m, settings, phrase[len(ILLUSTRATION_LABEL):].strip(),
            force=force, requester=requester, semaphore=semaphore,
        )
        return
    await _produce(
        m, settings, phrase, force=force, requester=requester, semaphore=semaphore
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

        if got.action is intent.Action.GONE:
            # Человек просил вернуть — ему нужен ответ, а не стикер со словом
            # «верни». Возврата больше нет, и об этом надо сказать прямо.
            await m.reply(
                "Возврата больше нет: убранный стикер уходит насовсем.\n"
                "Но сделать заново — секунда: пришли фразу, и он будет новый."
            )
            return

        if got.action is intent.Action.ILLUSTRATE:
            if not got.phrase:
                await m.reply("Скажи, что нарисовать: например «без текста костёр».")
                return
            await _produce_illustration(
                m, settings, got.phrase, force=got.force, semaphore=generation_slots
            )
            return

        if not got.phrase:
            await m.reply("Напиши фразу — верну стикер.")
            return

        # Фраза похожа на описание картинки — предлагаем выбор, а не решаем
        # за человека. «!» пропускает вопрос и рисует как обычно.
        author = getattr(m, "from_user", None)
        if not got.force and intent.suggest_textless(got.phrase) and author is not None:
            offer_id = await db.log_request(
                settings.db_path, author.id, got.phrase, "offered",
                "похоже на картинку", chat_type=m.chat.type if m.chat else None,
            )
            await m.reply(
                f"«{html.escape(got.phrase)}» может быть и картинкой без слов. "
                "Как сделать?",
                reply_markup=_offer_keyboard(offer_id),
            )
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
        await db.log_ui_event(settings.db_path, "again", query.from_user.id)
        await query.answer("Делаю новый вариант")
        # force=True: кнопка и означает «сделай ещё один». Без этого проверка
        # дублей отбивала собственную же кнопку — первое, что видит человек,
        # нажавший «Ещё вариант», это отказ «похожее уже есть».
        await _dispatch_produce(
            query.message,
            settings,
            row.phrase,
            force=True,
            requester=query.from_user,
            semaphore=generation_slots,
        )

    @router.callback_query(F.data.startswith("redo:"))
    async def _redo(query: CallbackQuery) -> None:
        """«Ещё раз» и «Всё равно сделай» — одно действие: фраза у бота уже есть."""
        request_id = _callback_sticker_id(query.data)
        if request_id is None:
            await query.answer("Кнопка испорчена")
            return
        phrase = await db.get_request_phrase(settings.db_path, request_id)
        if not phrase or not isinstance(query.message, Message):
            await query.answer("Фраза потерялась")
            return
        await db.log_ui_event(settings.db_path, "redo", query.from_user.id)
        await query.answer("Делаю")
        # force=True: человек уже увидел отказ и нажал осознанно — отбивать его
        # той же проверкой дублей во второй раз было бы издевательством.
        await _dispatch_produce(
            query.message, settings, phrase,
            force=True, requester=query.from_user, semaphore=generation_slots,
        )

    @router.callback_query(F.data.startswith("illu:"))
    async def _offer_illustration(query: CallbackQuery) -> None:
        """«Без текста» из предложения бота: фраза становится описанием картинки."""
        request_id = _callback_sticker_id(query.data)
        if request_id is None:
            await query.answer("Кнопка испорчена")
            return
        phrase = await db.get_request_phrase(settings.db_path, request_id)
        if not phrase or not isinstance(query.message, Message):
            await query.answer("Фраза потерялась")
            return
        await db.log_ui_event(settings.db_path, "offer:illustration", query.from_user.id)
        await query.answer("Рисую картинку")
        await _produce_illustration(
            query.message, settings, phrase,
            force=True, requester=query.from_user, semaphore=generation_slots,
        )

    @router.callback_query(F.data.startswith("text:"))
    async def _offer_text(query: CallbackQuery) -> None:
        """«С текстом» из предложения бота — обычный путь, вопрос закрыт."""
        request_id = _callback_sticker_id(query.data)
        if request_id is None:
            await query.answer("Кнопка испорчена")
            return
        phrase = await db.get_request_phrase(settings.db_path, request_id)
        if not phrase or not isinstance(query.message, Message):
            await query.answer("Фраза потерялась")
            return
        await db.log_ui_event(settings.db_path, "offer:text", query.from_user.id)
        await query.answer("Делаю с текстом")
        await _produce(
            query.message, settings, phrase,
            force=True, requester=query.from_user, semaphore=generation_slots,
        )

    @router.callback_query(F.data.startswith("rm:"))
    async def _remove_button(query: CallbackQuery) -> None:
        """✕ в списке пака. Что именно произойдёт — зависит от прав нажавшего."""
        sticker_id = _callback_sticker_id(query.data)
        bot = query.bot
        assert bot is not None
        if sticker_id is None:
            await query.answer("Кнопка испорчена")
            return
        row = await db.get_sticker(settings.db_path, sticker_id)
        if row is None or not row.in_pack:
            await query.answer("Стикера уже нет в паке", show_alert=True)
            return

        user = query.from_user
        if not settings.user_allowed(user.id) or not await db.touch_user(
            settings.db_path, user.id, user.username
        ):
            await query.answer("Доступ закрыт", show_alert=True)
            return

        right = _removal_right(row, user.id, settings, user.username)
        await db.log_ui_event(settings.db_path, f"rm:{right}", user.id)
        if right is CORE:
            await query.answer("Это основа пака — она остаётся", show_alert=True)
            return

        # Кнопки «🙋 убрать» из сообщений времён голосования всё ещё живут
        # в чатах — на нажатие отвечаем новой политикой, а не молчанием.
        if right is ASK:
            await query.answer(_foreign_removal_hint(settings), show_alert=True)
            return

        if right is AUTHOR:
            used = await db.count_community_actions(
                settings.db_path, user_id=user.id, action="removed", hours=24
            )
            if used >= settings.rate_removals_per_user_day:
                await query.answer("На сегодня хватит удалений", show_alert=True)
                return
        await query.answer("Убираю…")
        _, message = await _drop_from_pack(bot, settings, row, user.id, right)

        if isinstance(query.message, Message):
            await query.message.answer(message)

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

        await db.log_ui_event(settings.db_path, "pack", query.from_user.id)
        await query.answer("Добавляю в пак…")
        _, message = await _add_row_to_pack(bot, settings, row, user)
        if isinstance(query.message, Message):
            await query.message.answer(message)

    return router


__all__ = ["build_router"]
