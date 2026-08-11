"""Квоты. Платный слот резервируется до запуска провайдера."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from . import db
from .config import Settings


@dataclass
class Allowance:
    ok: bool
    reason: str = ""
    request_id: int | None = None

    def __bool__(self) -> bool:
        return self.ok


_RESERVATION_LOCK = asyncio.Lock()


def _hour_reason(settings: Settings) -> str:
    return (
        f"На час хватит: {settings.rate_per_user_hour} стикеров уже сделано. "
        "Возвращайся попозже."
    )


async def check(db_path: Path, settings: Settings, user_id: int) -> Allowance:
    """Read-only проверка для UX; запуск генерации обязан использовать reserve().

    Ноль в настройке означает «без лимита»: тогда соответствующий запрос к базе
    даже не выполняется. Считать при этом не перестаём — `reserve()` всё равно
    пишет строку в `requests`, поэтому снятые лимиты не лишают нас цифр о том,
    сколько на самом деле генерировали.
    """
    if user_id == settings.telegram_owner_id:
        return Allowance(True)

    if settings.rate_per_user_hour:
        per_hour = await db.count_quota_requests(db_path, user_id=user_id, hours=1)
        if per_hour >= settings.rate_per_user_hour:
            return Allowance(False, _hour_reason(settings))

    if settings.rate_per_user_day:
        per_day = await db.count_quota_requests(db_path, user_id=user_id, hours=24)
        if per_day >= settings.rate_per_user_day:
            return Allowance(
                False, f"Дневной лимит {settings.rate_per_user_day} стикеров исчерпан."
            )

    if settings.rate_global_day:
        global_day = await db.count_quota_requests(db_path, user_id=None, hours=24)
        if global_day >= settings.rate_global_day:
            return Allowance(
                False,
                "Общий дневной лимит сообщества исчерпан — картинки платные. "
                "Завтра лимит обнулится.",
            )

    return Allowance(True)


async def reserve(
    db_path: Path,
    settings: Settings,
    user_id: int,
    phrase: str,
    chat_type: str | None = None,
) -> Allowance:
    """Атомарно занять слот; единственный runtime защищён InstanceLock."""
    async with _RESERVATION_LOCK:
        allowance = await check(db_path, settings, user_id)
        if not allowance:
            return allowance
        request_id = await db.log_request(
            db_path, user_id, phrase, "pending", chat_type=chat_type
        )
        return Allowance(True, request_id=request_id)


async def remaining(
    db_path: Path, settings: Settings, user_id: int
) -> dict[str, int | None]:
    """Сколько осталось. None означает «лимита нет», а не «ноль осталось»."""
    async def left(limit: int, *, user: int | None, hours: int) -> int | None:
        if not limit:
            return None
        used = await db.count_quota_requests(db_path, user_id=user, hours=hours)
        return max(0, limit - used)

    return {
        "hour": await left(settings.rate_per_user_hour, user=user_id, hours=1),
        "day": await left(settings.rate_per_user_day, user=user_id, hours=24),
        "global": await left(settings.rate_global_day, user=None, hours=24),
    }


async def used(db_path: Path, settings: Settings, user_id: int) -> dict[str, int]:
    """Сколько уже сделано. Работает и при снятых лимитах — это и есть замер."""
    return {
        "hour": await db.count_quota_requests(db_path, user_id=user_id, hours=1),
        "day": await db.count_quota_requests(db_path, user_id=user_id, hours=24),
        "global": await db.count_quota_requests(db_path, user_id=None, hours=24),
    }
