"""Команды бота."""
from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from skill.wndr_stickers.src import db, pack, ratelimit
from skill.wndr_stickers.src.config import Settings
from skill.wndr_stickers.src.style import SHAPES

WELCOME = """\
Это бот стикеров <b>WNDR</b>.

WNDR Club — место, где мы вместе продвигаемся в важных областях жизни и
поддерживаем друг друга на пути. Наш meta-skill — действие: не ждать идеальных
условий, а двигаться вперёд, делать шаги и собирать результаты.

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
/zip — архив того, что сейчас в общем паке
/history — кто добавлял, убирал и возвращал
/delete — список с командами для удаления стикеров

Пак регулирует само сообщество: любой участник может добавить, убрать и вернуть
стикер. Удаление обратимо — файл и история остаются.
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
Стрелка/указатель — одна из канонических форм. Градиенты, 3D, реализм и \
сложный фольклорный орнамент — вне стиля.
"""


def _pack_summary(rows, *, fallback_pack_name: str) -> str:
    """Собрать честный ответ /pack: один или несколько Telegram-наборов."""
    counts: dict[str, int] = {}
    for row in rows:
        name = row.pack_name or fallback_pack_name
        counts[name] = counts.get(name, 0) + 1

    total = sum(counts.values())
    if len(counts) == 1:
        name, count = next(iter(counts.items()))
        return f"Стикеров в паке: <b>{count}</b>\nhttps://t.me/addstickers/{name}"

    lines = [f"Стикеров в общем паке: <b>{total}</b>", ""]
    for index, (name, count) in enumerate(counts.items(), start=1):
        lines.append(f"{index}. <b>{count}</b> — https://t.me/addstickers/{name}")
    return "\n".join(lines)


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
        await m.answer(_pack_summary(rows, fallback_pack_name=name))

    @router.message(Command("zip"))
    async def _zip(m: Message) -> None:
        rows = await db.pack_stickers(settings.db_path)
        archive, count = pack.rebuild_zip(
            settings.stickers_dir,
            settings.zip_path,
            active_paths=(Path(row.path) for row in rows),
        )
        if count == 0:
            await m.answer("Стикеров пока нет.")
            return
        await m.answer_document(
            FSInputFile(archive),
            caption=f"Активный общий пак: {count} файлов.",
        )

    @router.message(Command("history"))
    async def _history(m: Message) -> None:
        actions = await db.recent_community_actions(settings.db_path)
        if not actions:
            await m.answer("История общего пака пока пуста.")
            return
        verbs = {"added": "добавил", "removed": "убрал", "restored": "вернул"}
        lines = []
        for action in actions:
            actor = f"@{action.username}" if action.username else "участник"
            lines.append(
                f"{actor} {verbs.get(action.action, action.action)} «{action.phrase}»"
            )
        await m.answer("Последние действия:\n" + "\n".join(lines))

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
