"""Апрув: что попадает в общий пак, решают модераторы, а не автор стикера."""
import pytest

from skill.wndr_stickers.src import approval, db
from skill.wndr_stickers.src.config import Settings
from skill.wndr_stickers.src.pack import pack_name


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        telegram_owner_id=111,
        pack_owner_id=111,
        moderator_ids="222, 333",
        state_dir=tmp_path,
        output_dir=tmp_path / "out",
        auto_trust_after=3,
    )


class _Result:
    """Минимальный дублёр StickerResult — в БД уходят только эти поля."""

    def __init__(self, slug="fraza", version=1):
        self.slug = slug
        self.version = version
        self.phrase = "фраза"
        self.path = f"/tmp/{slug}-v{version}.webp"
        self.raw_path = f"/tmp/{slug}-v{version}.png"
        self.provider = "codex"
        self.model = "gpt-image"
        self.shape = "cloud"


async def _sticker(settings, user_id=999, slug="fraza", version=1) -> int:
    request_id = await db.log_request(settings.db_path, user_id, "фраза", "ok")
    return await db.save_sticker(
        settings.db_path,
        request_id=request_id,
        user_id=user_id,
        result=_Result(slug, version),
    )


# --- права модерации ---------------------------------------------------------

def test_owner_can_moderate(settings):
    assert approval.can_moderate(111, settings)


def test_listed_moderators_can_moderate(settings):
    assert approval.can_moderate(222, settings)
    assert approval.can_moderate(333, settings)


def test_random_community_member_cannot_moderate(settings):
    assert not approval.can_moderate(999, settings)


def test_moderators_survive_owner_change(tmp_path):
    """Пак не должен быть завязан на одного человека: владелец сменился — модерация цела."""
    s = Settings(
        telegram_owner_id=111,
        pack_owner_id=777,
        moderator_ids="222",
        state_dir=tmp_path,
    )
    assert approval.can_moderate(222, s)
    assert s.pack_owner_id == 777, "владелец пака задаётся отдельно и передаётся"


# --- очередь -----------------------------------------------------------------

async def test_submission_starts_pending(settings):
    await db.init_db(settings.db_path)
    sticker_id = await _sticker(settings)
    sub_id = await db.create_submission(settings.db_path, sticker_id, 999)
    sub = await db.get_submission(settings.db_path, sub_id)
    assert sub is not None
    assert sub.status == "pending"
    assert sub.submitted_by == 999


async def test_same_sticker_cannot_be_submitted_twice(settings):
    await db.init_db(settings.db_path)
    sticker_id = await _sticker(settings)
    first = await db.create_submission(settings.db_path, sticker_id, 999)
    second = await db.create_submission(settings.db_path, sticker_id, 999)
    assert first == second, "повторная заявка возвращает существующую, а не плодит дубли"
    assert len(await db.pending_submissions(settings.db_path)) == 1


async def test_approving_marks_decision_and_who_made_it(settings):
    await db.init_db(settings.db_path)
    sub_id = await db.create_submission(settings.db_path, await _sticker(settings), 999)
    assert await db.decide_submission(settings.db_path, sub_id, approved=True, decided_by=222)
    sub = await db.get_submission(settings.db_path, sub_id)
    assert sub.status == "approved"
    assert sub.decided_by == 222
    assert sub.decided_at


async def test_rejecting_keeps_the_reason(settings):
    await db.init_db(settings.db_path)
    sub_id = await db.create_submission(settings.db_path, await _sticker(settings), 999)
    await db.decide_submission(
        settings.db_path, sub_id, approved=False, decided_by=222, reason="не в стиле"
    )
    sub = await db.get_submission(settings.db_path, sub_id)
    assert sub.status == "rejected"
    assert sub.reason == "не в стиле"


async def test_second_decision_is_refused(settings):
    """Двое модераторов нажали одновременно — выигрывает первый, второй получает отказ."""
    await db.init_db(settings.db_path)
    sub_id = await db.create_submission(settings.db_path, await _sticker(settings), 999)
    assert await db.decide_submission(settings.db_path, sub_id, approved=True, decided_by=222)
    assert not await db.decide_submission(
        settings.db_path, sub_id, approved=False, decided_by=333
    )
    sub = await db.get_submission(settings.db_path, sub_id)
    assert sub.status == "approved" and sub.decided_by == 222


async def test_decided_submissions_leave_the_queue(settings):
    await db.init_db(settings.db_path)
    keep = await db.create_submission(settings.db_path, await _sticker(settings, slug="a"), 999)
    gone = await db.create_submission(settings.db_path, await _sticker(settings, slug="b"), 999)
    await db.decide_submission(settings.db_path, gone, approved=True, decided_by=222)
    pending = await db.pending_submissions(settings.db_path)
    assert [s.id for s in pending] == [keep]


# --- доверие -----------------------------------------------------------------

async def test_approved_count_only_counts_approved(settings):
    await db.init_db(settings.db_path)
    for i, approved in enumerate([True, True, False]):
        sub = await db.create_submission(
            settings.db_path, await _sticker(settings, slug=f"s{i}"), 999
        )
        await db.decide_submission(
            settings.db_path, sub, approved=approved, decided_by=222
        )
    assert await db.approved_count(settings.db_path, 999) == 2


async def test_trust_is_granted_after_enough_approvals(settings):
    await db.init_db(settings.db_path)
    await db.touch_user(settings.db_path, 999, "ann")
    for i in range(settings.auto_trust_after):
        sub = await db.create_submission(
            settings.db_path, await _sticker(settings, slug=f"s{i}"), 999
        )
        await db.decide_submission(settings.db_path, sub, approved=True, decided_by=222)
    assert await approval.maybe_grant_trust(settings.db_path, settings, 999)
    assert await db.is_trusted(settings.db_path, 999)


async def test_trust_is_not_granted_too_early(settings):
    await db.init_db(settings.db_path)
    await db.touch_user(settings.db_path, 999, "ann")
    sub = await db.create_submission(settings.db_path, await _sticker(settings), 999)
    await db.decide_submission(settings.db_path, sub, approved=True, decided_by=222)
    assert not await approval.maybe_grant_trust(settings.db_path, settings, 999)
    assert not await db.is_trusted(settings.db_path, 999)


# --- переполнение пака -------------------------------------------------------

def test_first_pack_has_no_index_suffix():
    assert pack_name("wndr", "wndr_bot", 1) == "wndr_by_wndr_bot"


def test_overflow_packs_are_numbered():
    # Telegram держит максимум 120 статичных стикеров в наборе
    assert pack_name("wndr", "wndr_bot", 2) == "wndr_2_by_wndr_bot"
    assert pack_name("wndr", "wndr_bot", 3) == "wndr_3_by_wndr_bot"
