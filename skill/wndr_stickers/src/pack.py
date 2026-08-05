"""Стикерпак в Telegram и общий ZIP.

Владелец пака — Катя: Bot API требует user_id владельца при создании набора,
поэтому что бы ни сгенерировало сообщество, набор всегда принадлежит ей.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputSticker

log = logging.getLogger(__name__)


def pack_name(slug: str, bot_username: str) -> str:
    """Telegram требует, чтобы имя набора заканчивалось на _by_<botusername>."""
    return f"{slug}_by_{bot_username}"


async def ensure_pack(
    bot: Bot,
    *,
    owner_id: int,
    name: str,
    title: str,
    first_sticker: Path,
    emoji: str,
) -> bool:
    """Возвращает True, если набор пришлось создать."""
    try:
        await bot.get_sticker_set(name=name)
        return False
    except TelegramBadRequest as exc:
        if "STICKERSET_INVALID" not in str(exc).upper():
            raise

    await bot.create_new_sticker_set(
        user_id=owner_id,
        name=name,
        title=title,
        stickers=[
            InputSticker(
                sticker=FSInputFile(first_sticker),
                format="static",
                emoji_list=[emoji],
            )
        ],
    )
    log.info("создан стикерпак %s", name)
    return True


async def add_to_pack(
    bot: Bot,
    *,
    owner_id: int,
    name: str,
    title: str,
    sticker_path: Path,
    emoji: str,
) -> str:
    """Кладём стикер в набор, создавая его при первом обращении. Отдаём ссылку."""
    created = await ensure_pack(
        bot,
        owner_id=owner_id,
        name=name,
        title=title,
        first_sticker=sticker_path,
        emoji=emoji,
    )
    if not created:
        await bot.add_sticker_to_set(
            user_id=owner_id,
            name=name,
            sticker=InputSticker(
                sticker=FSInputFile(sticker_path),
                format="static",
                emoji_list=[emoji],
            ),
        )
    return f"https://t.me/addstickers/{name}"


def rebuild_zip(stickers_dir: Path, zip_path: Path) -> tuple[Path, int]:
    """Пересобираем архив из всех версий. Ничего не удаляем — только добавляем."""
    files = sorted(p for p in stickers_dir.glob("*.webp") if p.is_file())
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    return zip_path, len(files)
