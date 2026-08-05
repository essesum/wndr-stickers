"""Апрув: что попадает в общий стикерпак.

Автор получает свой файл сразу — это его стикер, он ничего не ждёт. Но в ОБЩИЙ
пак стикер уезжает только после решения модератора. Модераторов список, а не
один человек: если владелец сменится, модерация продолжит работать.
"""
from __future__ import annotations

from pathlib import Path

from . import db
from .config import Settings


def can_moderate(user_id: int, settings: Settings) -> bool:
    return user_id == settings.telegram_owner_id or user_id in settings.moderators


async def needs_approval(db_path: Path, settings: Settings, user_id: int) -> bool:
    """Модераторам и доверенным апрув не нужен — их стикеры уезжают сразу."""
    if not settings.require_approval:
        return False
    if can_moderate(user_id, settings):
        return False
    return not (settings.auto_trust_after and await db.is_trusted(db_path, user_id))


async def maybe_grant_trust(db_path: Path, settings: Settings, user_id: int) -> bool:
    """Набрал достаточно одобренных — дальше добавляет в пак без очереди."""
    if not settings.auto_trust_after:
        return False
    if await db.is_trusted(db_path, user_id):
        return False
    if await db.approved_count(db_path, user_id) < settings.auto_trust_after:
        return False
    await db.set_trusted(db_path, user_id, True)
    return True


def describe(submission: db.Submission) -> str:
    """Строка для очереди модератора."""
    return (
        f"#{submission.id} «{submission.phrase}» "
        f"от {submission.submitted_by} · {submission.created_at}"
    )
