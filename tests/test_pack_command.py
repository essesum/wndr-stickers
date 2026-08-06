"""Команда /pack должна честно показывать все продолжения Telegram-пака."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import commands
from skill.wndr_stickers.src import db
from skill.wndr_stickers.src.config import Settings


class _Result:
    def __init__(self, path: Path, phrase: str, slug: str, version: int):
        self.slug = slug
        self.version = version
        self.phrase = phrase
        self.path = str(path)
        self.raw_path = str(path.with_suffix(".png"))
        self.provider = "test"
        self.model = "test"
        self.shape = "blob"


@pytest.mark.asyncio
async def test_pack_command_lists_all_pack_continuations(tmp_path):
    settings = Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "out")
    await db.init_db(settings.db_path)

    for idx, pack_name in enumerate(("wndr_by_wndr_bot", "wndr_2_by_wndr_bot"), start=1):
        sticker_path = settings.stickers_dir / f"s{idx}-v1.webp"
        sticker_path.parent.mkdir(parents=True, exist_ok=True)
        sticker_path.write_bytes(b"webp")
        request_id = await db.log_request(settings.db_path, 222, f"фраза {idx}", "ok")
        sticker_id = await db.save_sticker(
            settings.db_path,
            request_id=request_id,
            user_id=222,
            result=_Result(sticker_path, f"фраза {idx}", f"s{idx}", 1),
        )
        await db.mark_in_pack(settings.db_path, sticker_id, "🔥", pack_name, f"file-{idx}")

    router = commands.build_router(settings)
    callback = next(h.callback for h in router.message.handlers if h.callback.__name__ == "_pack")
    message = SimpleNamespace(
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="wndr_bot"))),
        answer=AsyncMock(),
    )

    await callback(message)

    text = message.answer.await_args.args[0]
    assert "Стикеров в общем паке: <b>2</b>" in text
    assert "https://t.me/addstickers/wndr_by_wndr_bot" in text
    assert "https://t.me/addstickers/wndr_2_by_wndr_bot" in text


def test_pack_summary_preserves_single_pack_text():
    row = db.StickerRow(1, 222, "s", 1, "фраза", "/tmp/s.webp", True, "in", None, "wndr")
    assert commands._pack_summary([row], fallback_pack_name="fallback") == (
        "Стикеров в паке: <b>1</b>\nhttps://t.me/addstickers/wndr"
    )
