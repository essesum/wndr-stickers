import zipfile

from skill.wndr_stickers.src.pack import pack_name, rebuild_zip


def test_pack_name_matches_telegram_requirement():
    # Telegram требует суффикс _by_<botusername>
    assert pack_name("wndr", "wndr_stickers_bot") == "wndr_by_wndr_stickers_bot"


def test_rebuild_zip_collects_every_version(tmp_path):
    stickers = tmp_path / "telegram-stickers"
    stickers.mkdir()
    for name in ("a-v1.webp", "a-v2.webp", "b-v1.webp"):
        (stickers / name).write_bytes(b"webp")
    archive, count = rebuild_zip(stickers, tmp_path / "out.zip")
    assert count == 3
    with zipfile.ZipFile(archive) as z:
        assert sorted(z.namelist()) == ["a-v1.webp", "a-v2.webp", "b-v1.webp"]


def test_rebuild_zip_ignores_non_webp(tmp_path):
    stickers = tmp_path / "telegram-stickers"
    stickers.mkdir()
    (stickers / "a-v1.webp").write_bytes(b"webp")
    (stickers / "notes.txt").write_text("x")
    (stickers / "raw.png").write_bytes(b"png")
    _, count = rebuild_zip(stickers, tmp_path / "out.zip")
    assert count == 1


def test_rebuild_zip_is_idempotent(tmp_path):
    stickers = tmp_path / "telegram-stickers"
    stickers.mkdir()
    (stickers / "a-v1.webp").write_bytes(b"webp")
    zip_path = tmp_path / "out.zip"
    rebuild_zip(stickers, zip_path)
    _, count = rebuild_zip(stickers, zip_path)
    assert count == 1
    with zipfile.ZipFile(zip_path) as z:
        assert z.namelist() == ["a-v1.webp"]


def test_rebuild_zip_on_empty_dir(tmp_path):
    stickers = tmp_path / "telegram-stickers"
    stickers.mkdir()
    _, count = rebuild_zip(stickers, tmp_path / "out.zip")
    assert count == 0
