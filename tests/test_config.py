"""Настройки должны переживать .env, заполненный по образцу — с пустыми полями."""
from skill.wndr_stickers.src.config import Settings


def test_empty_numeric_fields_do_not_crash(tmp_path):
    """В .env.example PACK_OWNER_ID документирован пустым."""
    s = Settings(
        telegram_owner_id=111,
        pack_owner_id="",
        state_dir=tmp_path,
    )
    assert s.pack_owner_id == 0


def test_empty_pack_owner_falls_back_to_bot_owner(tmp_path):
    s = Settings(telegram_owner_id=111, pack_owner_id="", state_dir=tmp_path)
    assert s.sticker_pack_owner == 111


def test_explicit_pack_owner_wins(tmp_path):
    s = Settings(telegram_owner_id=111, pack_owner_id=777, state_dir=tmp_path)
    assert s.sticker_pack_owner == 777


def test_community_governance_defaults_are_bounded(tmp_path):
    s = Settings(telegram_owner_id=111, state_dir=tmp_path)
    assert s.rate_removals_per_user_day == 5
    assert s.pack_action_cooldown_seconds == 30


def test_whitespace_in_numeric_field_is_tolerated(tmp_path):
    s = Settings(telegram_owner_id=111, pack_owner_id="  ", state_dir=tmp_path)
    assert s.pack_owner_id == 0


def test_style_assets_are_repo_relative_by_default(tmp_path):
    s = Settings(state_dir=tmp_path)

    assert s.reference_sheet_path == s._absolute(s.reference_sheet)
    assert s.reference_for("clean") == s._absolute(s.reference_sheet_flat)
    assert s.reference_for("ornate") == s.reference_sheet_path
    assert s.font_file == s._absolute(s.font_path)
    assert s.reference_sheet_path.is_file()
    assert s.reference_for("clean").is_file()
    assert s.font_file.is_file()
