import asyncio

import pytest

from skill.wndr_stickers.src import db, ratelimit
from skill.wndr_stickers.src.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        telegram_owner_id=111,
        state_dir=tmp_path,
        output_dir=tmp_path / "out",
        rate_per_user_hour=3,
        rate_per_user_day=5,
        rate_global_day=8,
    )


async def test_init_and_touch_user(settings):
    await db.init_db(settings.db_path)
    assert await db.touch_user(settings.db_path, 222, "ann")
    assert (await db.stats(settings.db_path))["users"] == 1


async def test_banned_user_is_reported(settings):
    await db.init_db(settings.db_path)
    await db.touch_user(settings.db_path, 222, "ann")
    await db.set_banned(settings.db_path, 222, True)
    assert not await db.touch_user(settings.db_path, 222, "ann")


async def test_only_successful_requests_count_towards_quota(settings):
    await db.init_db(settings.db_path)
    await db.log_request(settings.db_path, 222, "фраза", "rejected")
    await db.log_request(settings.db_path, 222, "фраза", "failed")
    assert await db.count_requests(settings.db_path, user_id=222, hours=1) == 0
    await db.log_request(settings.db_path, 222, "фраза", "ok")
    assert await db.count_requests(settings.db_path, user_id=222, hours=1) == 1


async def test_hourly_quota_blocks(settings):
    await db.init_db(settings.db_path)
    for _ in range(settings.rate_per_user_hour):
        await db.log_request(settings.db_path, 222, "фраза", "ok")
    verdict = await ratelimit.check(settings.db_path, settings, 222)
    assert not verdict
    assert "час" in verdict.reason


async def test_owner_is_never_limited(settings):
    await db.init_db(settings.db_path)
    for _ in range(50):
        await db.log_request(settings.db_path, 111, "фраза", "ok")
    assert await ratelimit.check(settings.db_path, settings, 111)


async def test_global_quota_blocks_a_fresh_user(settings):
    await db.init_db(settings.db_path)
    for user in range(300, 310):
        for _ in range(2):
            await db.log_request(settings.db_path, user, "фраза", "ok")
    verdict = await ratelimit.check(settings.db_path, settings, 999)
    assert not verdict
    assert "сообщества" in verdict.reason


async def test_remaining_counts_down(settings):
    await db.init_db(settings.db_path)
    before = await ratelimit.remaining(settings.db_path, settings, 222)
    await db.log_request(settings.db_path, 222, "фраза", "ok")
    after = await ratelimit.remaining(settings.db_path, settings, 222)
    assert after["hour"] == before["hour"] - 1
    assert after["day"] == before["day"] - 1


async def test_concurrent_requests_cannot_all_pass_one_slot(tmp_path):
    s = Settings(
        telegram_owner_id=111,
        state_dir=tmp_path,
        rate_per_user_hour=1,
        rate_per_user_day=1,
        rate_global_day=1,
    )
    await db.init_db(s.db_path)
    results = await asyncio.gather(
        *(ratelimit.reserve(s.db_path, s, 222, f"фраза {i}") for i in range(8))
    )
    allowed = [result for result in results if result]
    assert len(allowed) == 1
    assert allowed[0].request_id is not None


async def test_failed_reservation_releases_quota(tmp_path):
    s = Settings(
        telegram_owner_id=111,
        state_dir=tmp_path,
        rate_per_user_hour=1,
        rate_per_user_day=1,
        rate_global_day=1,
    )
    await db.init_db(s.db_path)
    first = await ratelimit.reserve(s.db_path, s, 222, "первая")
    assert first.request_id is not None
    await db.update_request(s.db_path, first.request_id, "failed", "provider down")
    assert await ratelimit.reserve(s.db_path, s, 222, "вторая")


async def test_access_mode_allowlist(tmp_path):
    s = Settings(
        telegram_owner_id=111,
        access_mode="allowlist",
        allowed_user_ids="222, 333",
        state_dir=tmp_path,
    )
    assert s.user_allowed(111)
    assert s.user_allowed(222)
    assert not s.user_allowed(444)


async def test_access_mode_open_lets_everyone_in(tmp_path):
    s = Settings(telegram_owner_id=111, access_mode="open", state_dir=tmp_path)
    assert s.user_allowed(999999)
