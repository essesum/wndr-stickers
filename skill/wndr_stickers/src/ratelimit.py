"""Квоты. Бот открыт сообществу, а картинки платные — считаем и по людям, и в целом."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import db
from .config import Settings


@dataclass
class Allowance:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


async def check(db_path: Path, settings: Settings, user_id: int) -> Allowance:
    """Владельца не ограничиваем — он платит за картинки."""
    if user_id == settings.telegram_owner_id:
        return Allowance(True)

    per_hour = await db.count_requests(db_path, user_id=user_id, hours=1)
    if per_hour >= settings.rate_per_user_hour:
        return Allowance(
            False,
            f"На час хватит: {settings.rate_per_user_hour} стикеров уже сделано. "
            "Возвращайся попозже.",
        )

    per_day = await db.count_requests(db_path, user_id=user_id, hours=24)
    if per_day >= settings.rate_per_user_day:
        return Allowance(
            False, f"Дневной лимит {settings.rate_per_user_day} стикеров исчерпан."
        )

    global_day = await db.count_requests(db_path, user_id=None, hours=24)
    if global_day >= settings.rate_global_day:
        return Allowance(
            False,
            "Общий дневной лимит сообщества исчерпан — картинки платные. "
            "Завтра лимит обнулится.",
        )

    return Allowance(True)


async def remaining(db_path: Path, settings: Settings, user_id: int) -> dict[str, int]:
    per_hour = await db.count_requests(db_path, user_id=user_id, hours=1)
    per_day = await db.count_requests(db_path, user_id=user_id, hours=24)
    global_day = await db.count_requests(db_path, user_id=None, hours=24)
    return {
        "hour": max(0, settings.rate_per_user_hour - per_hour),
        "day": max(0, settings.rate_per_user_day - per_day),
        "global": max(0, settings.rate_global_day - global_day),
    }
