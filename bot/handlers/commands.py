"""Команды бота."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from skill.wndr_stickers.src import db, pack, ratelimit
from skill.wndr_stickers.src.config import Settings
from skill.wndr_stickers.src.style import SHAPES

WELCOME = """\
Это бот стикеров <b>WNDR</b>.

Пришли фразу — верну готовый стикер 512×512 в стиле пака.
Плашку рисует модель, а текст впечатываю я сам, поэтому буквы всегда ровные: \
«объем» останется с твёрдым знаком, а вопросительный знак появится только если \
ты его написала.

<b>Акцент.</b> Оберни слово звёздочками, оно станет оранжевым:
<code>Это не *тантра*</code>

<b>Команды</b>
/style — палитра и формы пака
/quota — сколько стикеров тебе ещё доступно
/pack — ссылка на общий стикерпак
/zip — архив со всеми версиями
"""

STYLE = """\
<b>Палитра WNDR</b> — ровно три цвета плюс обводка:
• оранжево-красный <code>#CC3D11</code>
• чёрный <code>#0D0D0D</code>
• кремовый <code>#F2E2C8</code>
• кант <code>#F7F3EA</code>

<b>Формы плашек</b>
{shapes}

Типографика доминирует: крупный жирный узкий гротеск, 1–3 строки по центру. \
Стрелки, градиенты, реализм и сложный фольклорный орнамент — вне стиля.
"""


def build_router(settings: Settings) -> Router:
    router = Router(name="commands")

    @router.message(CommandStart())
    async def _start(m: Message) -> None:
        if m.from_user:
            await db.touch_user(settings.db_path, m.from_user.id, m.from_user.username)
        await m.answer(WELCOME)

    @router.message(Command("help"))
    async def _help(m: Message) -> None:
        await m.answer(WELCOME)

    @router.message(Command("style"))
    async def _style(m: Message) -> None:
        shapes = "\n".join(
            f"• {s.key} — {s.character}"
            for s in SHAPES
            if settings.allow_arrow_shapes or not s.is_arrow
        )
        await m.answer(STYLE.format(shapes=shapes))

    @router.message(Command("quota"))
    async def _quota(m: Message) -> None:
        if not m.from_user:
            return
        left = await ratelimit.remaining(settings.db_path, settings, m.from_user.id)
        if m.from_user.id == settings.telegram_owner_id:
            await m.answer("Ты владелец — лимитов нет.")
            return
        await m.answer(
            f"Осталось стикеров: <b>{left['hour']}</b> в этот час, "
            f"<b>{left['day']}</b> за сутки.\n"
            f"Общий запас сообщества на сегодня: <b>{left['global']}</b>."
        )

    @router.message(Command("pack"))
    async def _pack(m: Message) -> None:
        me = await m.bot.get_me()
        name = pack.pack_name(settings.pack_slug, me.username or "")
        rows = await db.pack_stickers(settings.db_path)
        if not rows:
            await m.answer(
                "В паке пока пусто. Сделай стикер и нажми «В пак» под ним."
            )
            return
        await m.answer(
            f"Стикеров в паке: <b>{len(rows)}</b>\n"
            f"https://t.me/addstickers/{name}"
        )

    @router.message(Command("zip"))
    async def _zip(m: Message) -> None:
        archive, count = pack.rebuild_zip(settings.stickers_dir, settings.zip_path)
        if count == 0:
            await m.answer("Стикеров пока нет.")
            return
        await m.answer_document(
            FSInputFile(archive),
            caption=f"Все версии: {count} файлов.",
        )

    @router.message(Command("stats"), F.from_user.id == settings.telegram_owner_id)
    async def _stats(m: Message) -> None:
        data = await db.stats(settings.db_path)
        await m.answer(
            f"Пользователей: {data['users']}\n"
            f"Стикеров всего: {data['stickers']}\n"
            f"В паке: {data['in_pack']}\n"
            f"Сделано за сутки: {data['today']}"
        )

    return router
