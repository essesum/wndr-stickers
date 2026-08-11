"""Самоуправление общего пака: обратимость, журнал и Telegram-регрессии."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest
from aiogram.enums import ChatType
from aiogram.types import Chat, Message, User

from bot.handlers import generate
from skill.wndr_stickers.src import db, naming
from skill.wndr_stickers.src.config import Settings


def _fake_bot(*, username: str, id: int = 1) -> SimpleNamespace:
    """Дубль Bot с обоими вариантами: .me() кэширующий и .get_me() сырой."""
    me = SimpleNamespace(id=id, username=username)
    return SimpleNamespace(
        me=AsyncMock(return_value=me), get_me=AsyncMock(return_value=me)
    )


class _Result:
    def __init__(self, path: Path, phrase: str = "я так чувствую"):
        self.slug = "ya-tak"
        self.version = 1
        self.phrase = phrase
        self.path = str(path)
        self.raw_path = str(path.with_suffix(".png"))
        self.provider = "test"
        self.model = "test"
        self.shape = "cloud"


@pytest.fixture
async def state(tmp_path):
    settings = Settings(
        telegram_owner_id=111,
        state_dir=tmp_path,
        output_dir=tmp_path / "out",
        pack_action_cooldown_seconds=0,
    )
    await db.init_db(settings.db_path)
    await db.touch_user(settings.db_path, 222, "ann")
    sticker_path = settings.stickers_dir / "ya-tak-v1.webp"
    sticker_path.parent.mkdir(parents=True, exist_ok=True)
    sticker_path.write_bytes(b"webp")
    request_id = await db.log_request(settings.db_path, 222, "я так чувствую", "ok")
    sticker_id = await db.save_sticker(
        settings.db_path,
        request_id=request_id,
        user_id=222,
        result=_Result(sticker_path),
    )
    return settings, sticker_id


async def test_pack_operation_claim_is_atomic(state):
    settings, sticker_id = state
    assert await db.claim_pack_operation(settings.db_path, sticker_id, "adding")
    assert not await db.claim_pack_operation(settings.db_path, sticker_id, "adding")
    await db.release_pack_operation(settings.db_path, sticker_id, "adding")
    assert (await db.get_sticker(settings.db_path, sticker_id)).pack_state == "out"


async def test_removed_sticker_is_findable_and_action_is_visible(state):
    settings, sticker_id = state
    await db.mark_in_pack(settings.db_path, sticker_id, "✨", "wndr", "file-1")
    await db.mark_removed_from_pack(settings.db_path, sticker_id)
    await db.log_community_action(settings.db_path, sticker_id, 222, "removed")

    found = await db.find_removed(settings.db_path, "  Я так   чувствую ")
    assert found is not None and found.id == sticker_id
    actions = await db.recent_community_actions(settings.db_path)
    assert [(a.action, a.username, a.phrase) for a in actions] == [
        ("removed", "ann", "я так чувствую")
    ]


async def test_private_draft_cannot_be_restored_into_public_pack(state):
    settings, _ = state
    assert await db.find_removed(settings.db_path, "я так чувствую") is None


async def test_parallel_generations_reserve_distinct_versions(tmp_path):
    results = await asyncio.gather(
        *(asyncio.to_thread(naming.reserve, "одна фраза", tmp_path) for _ in range(8))
    )
    assert sorted(version for _, version, _ in results) == list(range(1, 9))
    assert len({filename for _, _, filename in results}) == 8


async def test_add_failure_rolls_back_retryable_state(state, monkeypatch):
    settings, sticker_id = state
    row = await db.get_sticker(settings.db_path, sticker_id)
    user = User(id=222, is_bot=False, first_name="Ann", username="ann")
    bot = _fake_bot(username="wndr_bot")

    async def fail(*args, **kwargs):
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr(generate.pack, "add_with_overflow", fail)
    ok, message = await generate._add_row_to_pack(
        bot, settings, row, user
    )
    assert not ok
    assert "состояние сохранено" in message.lower()
    fresh = await db.get_sticker(settings.db_path, sticker_id)
    assert not fresh.in_pack and fresh.pack_state == "out"


async def test_add_success_records_actor_and_public_membership(state, monkeypatch):
    settings, sticker_id = state
    row = await db.get_sticker(settings.db_path, sticker_id)
    user = User(id=222, is_bot=False, first_name="Ann", username="ann")
    bot = _fake_bot(username="wndr_bot")
    monkeypatch.setattr(
        generate.pack,
        "add_with_overflow",
        AsyncMock(return_value=("wndr_by_wndr_bot", "https://t.me/addstickers/wndr", "file-1")),
    )

    ok, _ = await generate._add_row_to_pack(bot, settings, row, user)
    assert ok
    fresh = await db.get_sticker(settings.db_path, sticker_id)
    assert fresh.in_pack and fresh.pack_state == "in" and fresh.file_id == "file-1"
    action = (await db.recent_community_actions(settings.db_path))[0]
    assert (action.action, action.user_id) == ("added", 222)


async def test_help_handler_never_calls_generation(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path)
    router = generate.build_router(settings)
    callback = next(
        h.callback for h in router.message.handlers if h.callback.__name__ == "_plain_text"
    )
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)
    message = SimpleNamespace(
        chat=SimpleNamespace(type=ChatType.PRIVATE),
        text="что ты умеешь?",
        reply_to_message=None,
        bot=_fake_bot(id=999, username="WNDR_bot"),
        answer=AsyncMock(),
        reply=AsyncMock(),
    )

    await callback(message)
    produce.assert_not_awaited()
    message.reply.assert_awaited_once()


async def test_again_callback_uses_clicking_human_not_bot_author(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path)
    router = generate.build_router(settings)
    callback = next(
        h.callback for h in router.callback_query.handlers if h.callback.__name__ == "_again"
    )
    human = User(id=222, is_bot=False, first_name="Ann")
    bot_author = User(id=999, is_bot=True, first_name="WNDR")
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=222, type=ChatType.PRIVATE),
        from_user=bot_author,
    )
    query = SimpleNamespace(
        data="again:17",
        from_user=human,
        message=message,
        answer=AsyncMock(),
    )
    row = db.StickerRow(17, 222, "x", 1, "фраза", "/tmp/x.webp", False)
    monkeypatch.setattr(db, "get_sticker", AsyncMock(return_value=row))
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)

    await callback(query)
    produce.assert_awaited_once()
    args, kwargs = produce.await_args
    assert args == (message, settings, "фраза")
    assert kwargs["force"] is True
    assert kwargs["requester"] == human
    assert isinstance(kwargs["semaphore"], asyncio.Semaphore)


async def test_legacy_database_migrates_pack_state(tmp_path):
    path = tmp_path / "legacy.db"
    async with aiosqlite.connect(path) as database:
        await database.execute(
            "CREATE TABLE stickers (id INTEGER PRIMARY KEY, request_id INTEGER, "
            "user_id INTEGER NOT NULL, slug TEXT NOT NULL, version INTEGER NOT NULL, "
            "phrase TEXT NOT NULL, path TEXT NOT NULL, raw_path TEXT, provider TEXT, "
            "model TEXT, shape TEXT, in_pack INTEGER NOT NULL DEFAULT 0, emoji TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(slug,version))"
        )
        await database.execute(
            "INSERT INTO stickers(user_id,slug,version,phrase,path,in_pack) "
            "VALUES(1,'old',1,'старая','/tmp/old.webp',1)"
        )
        await database.commit()

    await db.init_db(path)
    row = await db.get_sticker(path, 1)
    assert row is not None and row.in_pack and row.pack_state == "in"
