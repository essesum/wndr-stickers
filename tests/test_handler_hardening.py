"""Регрессии на устойчивость обработчиков.

Здесь не про фичи, а про то, что бот не должен ломать сам себя: callback_data
приходит от клиента и может быть любой, а всё, что уходит человеку, идёт
с parse_mode=HTML и обязано быть экранировано.
"""
from __future__ import annotations

import html
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatType
from aiogram.types import User

from bot.handlers import commands, generate
from skill.wndr_stickers.src import db, ratelimit
from skill.wndr_stickers.src.config import Settings


@pytest.mark.parametrize(
    ("chat_type", "should_answer"),
    [
        (ChatType.PRIVATE, True),
        (ChatType.GROUP, False),
        (ChatType.SUPERGROUP, False),
        # Канал: раньше "channel" не был в белом списке ("group","supergroup"),
        # гейт выключался и бот рисовал стикер на каждый пост.
        (ChatType.CHANNEL, False),
    ],
)
async def test_bot_stays_silent_without_a_mention_outside_private(
    tmp_path, monkeypatch, chat_type, should_answer
):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    router = generate.build_router(settings)
    callback = next(
        h.callback for h in router.message.handlers if h.callback.__name__ == "_plain_text"
    )
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)

    me = SimpleNamespace(id=999, username="WNDR_stickers_bot")
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type),
        text="Хорошая цитата дня",
        reply_to_message=None,
        bot=SimpleNamespace(me=AsyncMock(return_value=me)),
        answer=AsyncMock(),
        reply=AsyncMock(),
    )

    await callback(message)
    assert produce.await_count == (1 if should_answer else 0)


@pytest.mark.parametrize(
    "chat_type", [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]
)
async def test_mention_still_works_everywhere(tmp_path, monkeypatch, chat_type):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    router = generate.build_router(settings)
    callback = next(
        h.callback for h in router.message.handlers if h.callback.__name__ == "_plain_text"
    )
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)

    me = SimpleNamespace(id=999, username="WNDR_stickers_bot")
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type),
        text="@WNDR_stickers_bot это величие",
        reply_to_message=None,
        bot=SimpleNamespace(me=AsyncMock(return_value=me)),
        answer=AsyncMock(),
        reply=AsyncMock(),
    )

    await callback(message)
    assert produce.await_count == 1
    assert produce.await_args.args[2] == "это величие"


async def test_core_sticker_survives_a_community_delete(tmp_path, monkeypatch):
    """Ядро не убирает никто, кроме владельца, — даже участник с правом удалять."""
    settings = Settings(
        telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o"
    )
    await db.init_db(settings.db_path)
    await db.touch_user(settings.db_path, 222, "ann")
    path = settings.stickers_dir / "core-v1.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"webp")
    request_id = await db.log_request(settings.db_path, 111, "основа", "ok")
    sticker_id = await db.save_sticker(
        settings.db_path,
        request_id=request_id,
        user_id=111,
        result=SimpleNamespace(
            slug="core", version=1, phrase="основа", path=str(path),
            raw_path=str(path), provider="t", model="t", shape="cloud",
        ),
    )
    await db.mark_in_pack(settings.db_path, sticker_id, "🔥", "wndr", "file-core")
    async with db.connect(settings.db_path) as conn:
        await conn.execute("UPDATE stickers SET is_core=1 WHERE id=?", (sticker_id,))
        await conn.commit()

    deleted = AsyncMock()
    message = SimpleNamespace(
        from_user=User(id=222, is_bot=False, first_name="Ann", username="ann"),
        bot=SimpleNamespace(delete_sticker_from_set=deleted),
        reply=AsyncMock(),
    )
    await generate._remove(message, settings, "основа")

    deleted.assert_not_awaited()
    assert (await db.get_sticker(settings.db_path, sticker_id)).in_pack
    assert "основы пака" in message.reply.await_args.args[0]

    # владелец — может
    message.from_user = User(id=111, is_bot=False, first_name="K", username="k")
    await generate._remove(message, settings, "основа")
    deleted.assert_awaited_once()
    assert not (await db.get_sticker(settings.db_path, sticker_id)).in_pack


async def _add_sticker(settings, *, user_id: int, phrase: str, slug: str):
    path = settings.stickers_dir / f"{slug}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"webp")
    request_id = await db.log_request(settings.db_path, user_id, phrase, "ok")
    return await db.save_sticker(
        settings.db_path,
        request_id=request_id,
        user_id=user_id,
        result=SimpleNamespace(
            slug=slug, version=1, phrase=phrase, path=str(path), raw_path=str(path),
            provider="t", model="t", shape="cloud", seconds=1.0,
        ),
    )


async def test_anchor_retires_once_the_community_fills_the_pack(tmp_path):
    """Якорь держит набор живым, пока он пуст, и уходит, когда есть замена."""
    settings = Settings(
        telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o"
    )
    await db.init_db(settings.db_path)
    anchor_id = await _add_sticker(settings, user_id=111, phrase="KEEP WNDRING", slug="kw")
    await db.mark_in_pack(settings.db_path, anchor_id, "🔥", "wndr", "file-anchor")
    async with db.connect(settings.db_path) as conn:
        await conn.execute("UPDATE stickers SET is_core=1 WHERE id=?", (anchor_id,))
        await conn.commit()

    deleted = AsyncMock()
    bot = SimpleNamespace(delete_sticker_from_set=deleted)

    # Пока якорь один в паке — снимать нельзя, иначе набор исчезнет.
    await generate._retire_anchor(bot, settings)
    deleted.assert_not_awaited()
    assert (await db.get_sticker(settings.db_path, anchor_id)).in_pack

    # Появился стикер участника — якорь больше не нужен.
    theirs = await _add_sticker(settings, user_id=222, phrase="это величие", slug="ev")
    await db.mark_in_pack(settings.db_path, theirs, "🔥", "wndr", "file-theirs")
    await generate._retire_anchor(bot, settings)

    deleted.assert_awaited_once_with(sticker="file-anchor")
    gone = await db.get_sticker(settings.db_path, anchor_id)
    assert not gone.in_pack and not gone.is_core
    assert [r.id for r in await db.pack_stickers(settings.db_path)] == [theirs]

    # Правило самоотключается: неприкосновенных в паке не осталось.
    deleted.reset_mock()
    await generate._retire_anchor(bot, settings)
    deleted.assert_not_awaited()


async def test_zero_limit_means_no_limit_but_still_counted(tmp_path):
    """Снятая квота не должна отключать подсчёт — цифры нужны для замера."""
    settings = Settings(
        telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o",
        rate_per_user_hour=0, rate_per_user_day=0, rate_global_day=0,
    )
    await db.init_db(settings.db_path)

    for _ in range(50):
        allowance = await ratelimit.reserve(settings.db_path, settings, 222, "фраза")
        assert allowance, "лимит снят — отказа быть не должно"
        await db.update_request(settings.db_path, allowance.request_id, "ok")

    assert await ratelimit.remaining(settings.db_path, settings, 222) == {
        "hour": None, "day": None, "global": None
    }
    spent = await ratelimit.used(settings.db_path, settings, 222)
    assert spent["day"] == 50 and spent["global"] == 50


async def test_limits_still_bite_when_configured(tmp_path):
    settings = Settings(
        telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o",
        rate_per_user_hour=3, rate_per_user_day=0, rate_global_day=0,
    )
    await db.init_db(settings.db_path)
    for _ in range(3):
        allowance = await ratelimit.reserve(settings.db_path, settings, 222, "ф")
        await db.update_request(settings.db_path, allowance.request_id, "ok")
    assert not await ratelimit.reserve(settings.db_path, settings, 222, "ф")


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("again:12", 12),
        ("pack:7", 7),
        ("again:abc", None),
        ("again:", None),
        ("pack:-1", None),
        ("again:1 or 1=1", None),
        # isdigit() пропускает не-ASCII цифры, а id у нас всегда обычное число
        ("again:٣", None),
        # больше 2**63-1 — sqlite3 бросил бы OverflowError на execute()
        ("pack:99999999999999999999", None),
        (None, None),
        ("", None),
    ],
)
def test_callback_sticker_id_never_raises_on_client_supplied_data(data, expected):
    """int() на сырой callback_data падал ValueError и убивал обработчик."""
    assert generate._callback_sticker_id(data) == expected


async def test_restore_escapes_phrase_from_the_user(tmp_path):
    """«верни в пак <b>…» не должен ломать parse_mode и вставлять чужой HTML."""
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    await db.init_db(settings.db_path)
    message = SimpleNamespace(
        from_user=User(id=222, is_bot=False, first_name="Ann", username="ann"),
        bot=SimpleNamespace(),
        reply=AsyncMock(),
    )

    injection = '<a href="https://evil.example">t.me/wndr</a>'
    await generate._restore(message, settings, injection)

    sent = message.reply.await_args.args[0]
    assert "<a href=" not in sent
    assert html.escape(injection) in sent


async def test_history_escapes_phrases_and_usernames(tmp_path):
    """Одна строка с «<» не должна ронять весь ответ /history."""
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    await db.init_db(settings.db_path)

    actions = [
        SimpleNamespace(username="ann<b>", action="added", phrase="<i>фраза</i>"),
    ]
    router = commands.build_router(settings)
    callback = next(
        h.callback for h in router.message.handlers if h.callback.__name__ == "_history"
    )
    message = SimpleNamespace(answer=AsyncMock())

    original = db.recent_community_actions
    db.recent_community_actions = AsyncMock(return_value=actions)
    try:
        await callback(message)
    finally:
        db.recent_community_actions = original

    sent = message.answer.await_args.args[0]
    assert "<i>" not in sent and "<b>" not in sent
    assert "&lt;i&gt;фраза&lt;/i&gt;" in sent
