"""Настройки должны переживать .env, заполненный по образцу — с пустыми полями."""
from skill.wndr_stickers.src.config import Settings


def test_empty_numeric_fields_do_not_crash(tmp_path):
    """В .env.example PACK_OWNER_ID и MODERATION_CHAT_ID документированы пустыми."""
    s = Settings(
        telegram_owner_id=111,
        pack_owner_id="",
        moderation_chat_id="",
        state_dir=tmp_path,
    )
    assert s.pack_owner_id == 0
    assert s.moderation_chat_id == 0


def test_empty_pack_owner_falls_back_to_bot_owner(tmp_path):
    s = Settings(telegram_owner_id=111, pack_owner_id="", state_dir=tmp_path)
    assert s.sticker_pack_owner == 111


def test_explicit_pack_owner_wins(tmp_path):
    s = Settings(telegram_owner_id=111, pack_owner_id=777, state_dir=tmp_path)
    assert s.sticker_pack_owner == 777


def test_empty_moderator_list_leaves_owner_alone(tmp_path):
    s = Settings(telegram_owner_id=111, moderator_ids="", state_dir=tmp_path)
    assert s.moderators == {111}


def test_whitespace_in_numeric_field_is_tolerated(tmp_path):
    s = Settings(telegram_owner_id=111, pack_owner_id="  ", state_dir=tmp_path)
    assert s.pack_owner_id == 0
