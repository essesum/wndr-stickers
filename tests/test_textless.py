"""Стикеры без текста: просьба напрямую и предложение от бота.

`make_illustration` жил в pipeline с самого начала, но ни одна ручка бота его
не звала — путь «без текста» просто не существовал. Теперь: «без текста костёр»
рисует картинку, а на фразу, похожую на описание картинки («костёр»), бот сам
предлагает выбор.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatType
from PIL import Image, ImageDraw

from bot.handlers import generate
from skill.wndr_stickers.src import db, pipeline
from skill.wndr_stickers.src.config import Settings
from skill.wndr_stickers.src.intent import Action, parse, suggest_textless
from skill.wndr_stickers.src.style import CREAM


# --- intent -------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("без текста костёр", "костёр"),
        ("нарисуй без текста костёр", "костёр"),
        ("картинку костёр", "костёр"),
        ("сделай картинку две розы", "две розы"),
        ("без надписи горы и солнце", "горы и солнце"),
    ],
)
def test_textless_request_is_an_illustration(text, phrase):
    got = parse(text)
    assert got.action is Action.ILLUSTRATE
    assert got.phrase == phrase


def test_textless_words_inside_a_phrase_do_not_trigger():
    """«стикер без текста не нужен» — это фраза, а не команда."""
    got = parse("стикер мне нужен, без текста скучно")
    assert got.action is Action.DRAW


@pytest.mark.parametrize("phrase", ["костёр", "две розы", "кот в короне"])
def test_visual_phrase_is_suggested_as_textless(phrase):
    assert suggest_textless(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    ["больше жизни", "Со мной все нормально", "Я приношу весь свой объем", "было!"],
)
def test_ordinary_pack_phrase_is_not_suggested(phrase):
    assert suggest_textless(phrase) is False


# --- pipeline: у картинки есть человекочитаемый ярлык -------------------------

class _FakeGenerated:
    provider = "fake"
    model = "fake"

    def save(self, path):
        image = Image.new("RGB", (512, 512), (0, 0, 0))
        ImageDraw.Draw(image).ellipse((60, 60, 452, 452), fill=CREAM)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return path


def test_make_illustration_labels_the_sticker(monkeypatch, tmp_path):
    """Ярлык «без текста …» нужен списку пака, повтору и проверке дублей."""
    settings = SimpleNamespace(
        allow_arrow_shapes=True,
        reference_sheet_path=tmp_path / "reference.png",
        stickers_dir=tmp_path / "stickers",
        raw_dir=tmp_path / "raw",
    )
    monkeypatch.setattr(
        pipeline.imagegen, "generate", lambda *_a, **_k: _FakeGenerated()
    )
    result = pipeline.make_illustration("костёр", settings)
    assert result.phrase == "без текста костёр"
    assert result.path.exists()


# --- handler: прямой путь и предложение ---------------------------------------

def _plain_text_handler(settings: Settings):
    router = generate.build_router(settings)
    return next(
        h.callback for h in router.message.handlers if h.callback.__name__ == "_plain_text"
    )


def _private_message(text: str):
    me = SimpleNamespace(id=999, username="WNDR_stickers_bot")
    return SimpleNamespace(
        chat=SimpleNamespace(type=ChatType.PRIVATE),
        text=text,
        reply_to_message=None,
        from_user=SimpleNamespace(id=222, username="ann"),
        bot=SimpleNamespace(me=AsyncMock(return_value=me)),
        answer=AsyncMock(),
        reply=AsyncMock(),
    )


async def test_textless_request_routes_to_illustration(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    handler = _plain_text_handler(settings)
    produce = AsyncMock()
    illustrate = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)
    monkeypatch.setattr(generate, "_produce_illustration", illustrate)

    await handler(_private_message("без текста костёр"))

    illustrate.assert_awaited_once()
    produce.assert_not_awaited()


async def test_visual_phrase_gets_a_textless_offer(tmp_path, monkeypatch):
    """На «костёр» бот не рисует молча текст, а даёт выбор с кнопками."""
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    await db.init_db(settings.db_path)
    await db.touch_user(settings.db_path, 222, "ann")
    handler = _plain_text_handler(settings)
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)

    message = _private_message("костёр")
    await handler(message)

    produce.assert_not_awaited()
    assert message.reply.await_count == 1
    markup = message.reply.await_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert any(data.startswith("illu:") for data in callbacks)
    assert any(data.startswith("text:") for data in callbacks)


async def test_ordinary_phrase_is_drawn_without_ceremony(tmp_path, monkeypatch):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "o")
    handler = _plain_text_handler(settings)
    produce = AsyncMock()
    monkeypatch.setattr(generate, "_produce", produce)

    await handler(_private_message("больше жизни"))

    produce.assert_awaited_once()
