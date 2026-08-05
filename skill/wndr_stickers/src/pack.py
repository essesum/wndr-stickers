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


def pack_name(slug: str, bot_username: str, index: int = 1) -> str:
    """Telegram требует, чтобы имя набора заканчивалось на _by_<botusername>.

    Статичный набор вмещает 120 стикеров, поэтому пак с номером 2 и дальше —
    это продолжение, а не отдельный проект.
    """
    base = slug if index <= 1 else f"{slug}_{index}"
    return f"{base}_by_{bot_username}"


def pack_title(base: str, index: int = 1) -> str:
    return base if index <= 1 else f"{base} ({index})"


def is_pack_full(exc: Exception) -> bool:
    """Набор упёрся в лимит Telegram — надо заводить продолжение."""
    text = str(exc).upper()
    return "STICKERS_TOO_MUCH" in text or "STICKERSET_TOO_MUCH" in text


def is_pack_missing(exc: Exception) -> bool:
    """Набора ещё нет — его надо создать."""
    return "STICKERSET_INVALID" in str(exc).upper()


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
        if not is_pack_missing(exc):
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


async def add_with_overflow(
    bot: Bot,
    *,
    owner_id: int,
    slug: str,
    bot_username: str,
    title: str,
    sticker_path: Path,
    emoji: str,
    max_packs: int = 50,
) -> tuple[str, str, str | None]:
    """Кладём стикер, переходя в следующий пак, когда текущий заполнен.

    Возвращаем (имя набора, ссылка). Владельцем всех наборов остаётся owner_id —
    это требование Telegram, а не привязка проекта к человеку: сменить владельца
    можно одной строкой в конфиге.
    """
    for index in range(1, max_packs + 1):
        name = pack_name(slug, bot_username, index)
        try:
            created = await ensure_pack(
                bot,
                owner_id=owner_id,
                name=name,
                title=pack_title(title, index),
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
            # file_id последнего стикера в наборе — им Telegram адресует
            # удаление. Без него убрать стикер из пака невозможно.
            file_id = None
            try:
                current = await bot.get_sticker_set(name=name)
                if current.stickers:
                    file_id = current.stickers[-1].file_id
            except Exception:  # noqa: BLE001 — не смогли узнать, добавление уже прошло
                log.warning("не получил file_id только что добавленного стикера")
            return name, f"https://t.me/addstickers/{name}", file_id
        except TelegramBadRequest as exc:
            if is_pack_full(exc):
                log.info("пак %s заполнен, перехожу к следующему", name)
                continue
            raise
    raise RuntimeError(f"все {max_packs} наборов заполнены")


def rebuild_zip(stickers_dir: Path, zip_path: Path) -> tuple[Path, int]:
    """Пересобираем архив из всех версий. Ничего не удаляем — только добавляем."""
    files = sorted(p for p in stickers_dir.glob("*.webp") if p.is_file())
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    return zip_path, len(files)
