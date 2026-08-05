"""Удаление из пака. Найдено на живом боте: убрать стикер было нечем."""
import pytest

from skill.wndr_stickers.src import db
from skill.wndr_stickers.src.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(telegram_owner_id=111, state_dir=tmp_path, output_dir=tmp_path / "out")


class _Result:
    def __init__(self, slug="fraza", version=1, phrase="фраза"):
        self.slug, self.version, self.phrase = slug, version, phrase
        self.path = f"/tmp/{slug}-v{version}.webp"
        self.raw_path = f"/tmp/{slug}-v{version}.png"
        self.provider, self.model, self.shape = "codex", "gpt-5.5", "cloud"


async def _add(settings, phrase="фраза", slug="fraza", version=1) -> int:
    rid = await db.log_request(settings.db_path, 111, phrase, "ok")
    return await db.save_sticker(
        settings.db_path, request_id=rid, user_id=111, result=_Result(slug, version, phrase)
    )


async def test_file_id_is_remembered_when_added(settings):
    """Без file_id Telegram удалить стикер не даст — он адресует набор именно им."""
    await db.init_db(settings.db_path)
    sid = await _add(settings)
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="CAACAgIAAxUAAX")
    row = await db.get_sticker(settings.db_path, sid)
    assert row.file_id == "CAACAgIAAxUAAX"
    assert row.in_pack


async def test_find_sticker_in_pack_by_phrase(settings):
    await db.init_db(settings.db_path)
    sid = await _add(settings, phrase="я так чувствую", slug="ya-tak")
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="FID1")
    found = await db.find_in_pack(settings.db_path, "я так чувствую")
    assert found is not None and found.id == sid


async def test_lookup_ignores_case_and_spacing(settings):
    await db.init_db(settings.db_path)
    sid = await _add(settings, phrase="Я так чувствую", slug="ya-tak")
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="FID1")
    assert (await db.find_in_pack(settings.db_path, "  я так   чувствую ")).id == sid


async def test_lookup_skips_stickers_not_in_pack(settings):
    await db.init_db(settings.db_path)
    await _add(settings, phrase="я так чувствую", slug="ya-tak")
    assert await db.find_in_pack(settings.db_path, "я так чувствую") is None


async def test_unknown_phrase_is_not_found(settings):
    await db.init_db(settings.db_path)
    assert await db.find_in_pack(settings.db_path, "такого нет") is None


async def test_marking_removed_clears_pack_membership(settings):
    await db.init_db(settings.db_path)
    sid = await _add(settings)
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="FID1")
    await db.mark_removed_from_pack(settings.db_path, sid)
    row = await db.get_sticker(settings.db_path, sid)
    assert not row.in_pack
    assert await db.find_in_pack(settings.db_path, "фраза") is None


async def test_removed_sticker_can_be_added_again(settings):
    """Удалили по ошибке — можно вернуть, файл никуда не делся."""
    await db.init_db(settings.db_path)
    sid = await _add(settings)
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="FID1")
    await db.mark_removed_from_pack(settings.db_path, sid)
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="FID2")
    row = await db.get_sticker(settings.db_path, sid)
    assert row.in_pack and row.file_id == "FID2"


async def test_latest_match_wins_when_phrase_repeats(settings):
    """Одна фраза может иметь несколько версий — убираем ту, что реально в паке."""
    await db.init_db(settings.db_path)
    old = await _add(settings, phrase="я так чувствую", slug="ya-tak", version=1)
    new = await _add(settings, phrase="я так чувствую", slug="ya-tak", version=2)
    await db.mark_in_pack(settings.db_path, old, "🔥", "wndr_by_bot", file_id="FID1")
    await db.mark_removed_from_pack(settings.db_path, old)
    await db.mark_in_pack(settings.db_path, new, "🔥", "wndr_by_bot", file_id="FID2")
    assert (await db.find_in_pack(settings.db_path, "я так чувствую")).id == new
