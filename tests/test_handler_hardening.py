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
from skill.wndr_stickers.src import db
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
