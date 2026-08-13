"""Контракт четырёх действий после генерации."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, User

from bot.handlers import generate
from skill.wndr_stickers.src import db, pipeline
from skill.wndr_stickers.src.config import Settings


def _callback(router, name):
    return next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == name)


def test_keyboard_has_exact_four_actions():
    keyboard = generate._keyboard(42)
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["✅ В пак", "🎲 Другой стиль"],
        ["🔤 Поправить текст/акцент", "🗑 Не то"],
    ]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        ["pack:42", "style:42"],
        ["edit:42", "dismiss:42"],
    ]


@pytest.mark.asyncio
async def test_other_style_flips_clean_to_expressive(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path)
    router = generate.build_router(settings)
    callback = _callback(router, "_other_style")
    row = db.StickerRow(7, 222, "x", 1, "фраза", "/tmp/x.webp", False, shape="clean-oval")
    monkeypatch.setattr(db, "get_sticker", AsyncMock(return_value=row))
    monkeypatch.setattr(db, "log_ui_event", AsyncMock())
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
    )
    query = SimpleNamespace(
        data="style:7", from_user=User(id=222, is_bot=False, first_name="Ann"),
        message=message, answer=AsyncMock(),
    )
    await callback(query)
    assert produce.await_args.kwargs["mode_key"] == "expressive"


@pytest.mark.asyncio
async def test_edit_button_starts_force_reply_for_author(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path)
    router = generate.build_router(settings)
    callback = _callback(router, "_edit_text")
    row = db.StickerRow(
        7, 222, "x", 1, "фраза", "/tmp/x.webp", False,
        raw_path="/tmp/raw.png", shape="clean-oval",
    )
    monkeypatch.setattr(db, "get_sticker", AsyncMock(return_value=row))
    monkeypatch.setattr(db, "log_ui_event", AsyncMock())
    answer = AsyncMock()
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
    )
    object.__setattr__(message, "answer", answer)
    query = SimpleNamespace(
        data="edit:7", from_user=User(id=222, is_bot=False, first_name="Ann"),
        message=message, answer=AsyncMock(),
    )
    await callback(query)
    kwargs = answer.await_args.kwargs
    assert kwargs["reply_markup"].force_reply is True


@pytest.mark.asyncio
async def test_dismiss_logs_feedback_and_deletes_preview(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path)
    router = generate.build_router(settings)
    callback = _callback(router, "_dismiss")
    log_event = AsyncMock()
    row = db.StickerRow(7, 222, "x", 1, "фраза", "/tmp/x.webp", False)
    monkeypatch.setattr(db, "get_sticker", AsyncMock(return_value=row))
    monkeypatch.setattr(db, "log_ui_event", log_event)
    delete = AsyncMock()
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=10, type="private"),
    )
    object.__setattr__(message, "delete", delete)
    query = SimpleNamespace(
        data="dismiss:7", from_user=User(id=222, is_bot=False, first_name="Ann"),
        message=message, answer=AsyncMock(),
    )
    await callback(query)
    log_event.assert_awaited_once()
    delete.assert_awaited_once()


def test_make_sticker_accepts_forced_mode(tmp_path, monkeypatch):
    settings = Settings(state_dir=tmp_path, output_dir=tmp_path / "out")
    # Contract-level assertion: an unknown explicit mode is rejected before network.
    with pytest.raises(ValueError, match="unknown style mode"):
        pipeline.make_sticker("тест", settings, mode_key="missing")


@pytest.mark.asyncio
async def test_group_edit_ignores_unrelated_next_message(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path)
    router = generate.build_router(settings)
    edit = _callback(router, "_edit_text")
    plain = next(
        h.callback for h in router.message.handlers if h.callback.__name__ == "_plain_text"
    )
    row = db.StickerRow(
        7, 222, "x", 1, "фраза", "/tmp/x.webp", False,
        raw_path="/tmp/raw.png", shape="clean-oval",
    )
    monkeypatch.setattr(db, "get_sticker", AsyncMock(return_value=row))
    monkeypatch.setattr(db, "log_ui_event", AsyncMock())
    prompt = SimpleNamespace(message_id=99)
    answer = AsyncMock(return_value=prompt)
    source = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=-10, type="supergroup"),
    )
    object.__setattr__(source, "answer", answer)
    user = User(id=222, is_bot=False, first_name="Ann")
    await edit(SimpleNamespace(data="edit:7", from_user=user, message=source, answer=AsyncMock()))

    unrelated = SimpleNamespace(
        text="обычная реплика",
        chat=SimpleNamespace(id=-10, type="supergroup"),
        from_user=user,
        reply_to_message=None,
        bot=SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(id=999, username="bot"))),
        reply=AsyncMock(),
    )
    rebuild = AsyncMock()
    monkeypatch.setattr(pipeline, "rebuild_from_raw", rebuild)
    await plain(unrelated)
    rebuild.assert_not_awaited()
