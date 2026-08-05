"""Апрув: заявка от автора -> решение модератора -> стикер в общем паке."""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from skill.wndr_stickers.src import approval, db, pack
from skill.wndr_stickers.src.config import Settings

log = logging.getLogger(__name__)


def decision_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ В пак", callback_data=f"ok:{submission_id}"),
                InlineKeyboardButton(text="🚫 Мимо", callback_data=f"no:{submission_id}"),
            ]
        ]
    )


async def notify_moderators(bot: Bot, settings: Settings, submission_id: int) -> int:
    """Рассылаем заявку. Возвращаем, скольким доставили."""
    submission = await db.get_submission(settings.db_path, submission_id)
    if submission is None:
        return 0

    caption = (
        f"Заявка в общий пак\n"
        f"«{submission.phrase}»\n"
        f"от id {submission.submitted_by}"
    )
    targets: list[int] = (
        [settings.moderation_chat_id]
        if settings.moderation_chat_id
        else sorted(settings.moderators)
    )

    delivered = 0
    for chat_id in targets:
        try:
            await bot.send_document(
                chat_id,
                FSInputFile(Path(submission.path)),
                caption=caption,
                reply_markup=decision_keyboard(submission_id),
            )
            delivered += 1
        except Exception:  # noqa: BLE001 — один недоступный модератор не рвёт рассылку
            log.warning("не доставил заявку %s в чат %s", submission_id, chat_id)
    return delivered


def build_router(settings: Settings) -> Router:
    router = Router(name="moderation")

    @router.message(Command("queue"))
    async def _queue(m: Message) -> None:
        if m.from_user is None or not approval.can_moderate(m.from_user.id, settings):
            return
        pending = await db.pending_submissions(settings.db_path)
        if not pending:
            await m.answer("Очередь пуста.")
            return
        await m.answer(
            f"Ждут решения: {len(pending)}\n\n"
            + "\n".join(approval.describe(s) for s in pending)
        )

    @router.message(Command("moderators"))
    async def _moderators(m: Message) -> None:
        if m.from_user is None or not approval.can_moderate(m.from_user.id, settings):
            return
        await m.answer(
            "Модераторы: "
            + ", ".join(str(i) for i in sorted(settings.moderators))
            + f"\nВладелец пака: {settings.sticker_pack_owner}"
            + "\n\nСписок правится в .env (MODERATOR_IDS, PACK_OWNER_ID) — "
            "проект не завязан на одного человека."
        )

    @router.callback_query(F.data.regexp(r"^(ok|no):\d+$"))
    async def _decide(query: CallbackQuery) -> None:
        user = query.from_user
        if not approval.can_moderate(user.id, settings):
            await query.answer("Это решают модераторы", show_alert=True)
            return

        verb, raw = (query.data or "no:0").split(":", 1)
        submission_id = int(raw)
        approved = verb == "ok"

        decided = await db.decide_submission(
            settings.db_path, submission_id, approved=approved, decided_by=user.id
        )
        if not decided:
            await query.answer("Уже решено кем-то другим", show_alert=True)
            return

        submission = await db.get_submission(settings.db_path, submission_id)
        if submission is None:
            return
        bot = query.bot
        assert bot is not None

        if not approved:
            await query.answer("Отклонено")
            with _suppress():
                await bot.send_message(
                    submission.submitted_by,
                    f"«{submission.phrase}» в общий пак не взяли. "
                    "Файл остаётся у тебя — можно доработать и предложить заново.",
                )
            return

        me = await bot.get_me()
        try:
            name, link, file_id = await pack.add_with_overflow(
                bot,
                owner_id=settings.sticker_pack_owner,
                slug=settings.pack_slug,
                bot_username=me.username or "",
                title=settings.pack_title,
                sticker_path=Path(submission.path),
                emoji=settings.default_emoji,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("не удалось добавить в пак")
            await query.answer("Не уехало в пак", show_alert=True)
            if isinstance(query.message, Message):
                await query.message.answer(f"Ошибка при добавлении: {exc}")
            return

        await db.mark_in_pack(
            settings.db_path, submission.sticker_id, settings.default_emoji, name, file_id
        )
        pack.rebuild_zip(settings.stickers_dir, settings.zip_path)
        await query.answer("Добавлено")

        promoted = await approval.maybe_grant_trust(
            settings.db_path, settings, submission.submitted_by
        )
        message = f"«{submission.phrase}» теперь в общем паке:\n{link}"
        if promoted:
            message += (
                "\n\nТвои стикеры больше не ждут очереди — теперь они попадают "
                "в пак сразу."
            )
        with _suppress():
            await bot.send_message(submission.submitted_by, message)

    return router


class _suppress:
    """Автор мог закрыть личку боту — это не повод ронять обработку."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            log.info("не смог уведомить автора: %s", exc)
        return True
