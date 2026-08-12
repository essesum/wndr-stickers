"""Удаление из пака. Найдено на живом боте: убрать стикер было нечем."""
import pytest

from bot.handlers import generate
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


async def test_delete_lookup_accepts_copyable_sticker_id(settings):
    await db.init_db(settings.db_path)
    sid = await _add(settings, phrase="люди очень ценны", slug="lyudi")
    await db.mark_in_pack(settings.db_path, sid, "🔥", "wndr_by_bot", file_id="FID1")

    found = await generate._find_in_pack_by_phrase_or_id(settings, f"#{sid}")

    assert found is not None and found.id == sid


async def test_delete_lookup_treats_bare_digits_as_phrase(settings):
    await db.init_db(settings.db_path)
    numeric_phrase = await _add(settings, phrase="42", slug="numeric")
    other = await _add(settings, phrase="другой", slug="other")
    await db.mark_in_pack(settings.db_path, numeric_phrase, "🔥", "wndr_by_bot", file_id="FID1")
    await db.mark_in_pack(settings.db_path, other, "🔥", "wndr_by_bot", file_id="FID2")

    found = await generate._find_in_pack_by_phrase_or_id(settings, "42")

    assert found is not None and found.id == numeric_phrase


def test_delete_hint_lists_copyable_delete_commands(settings):
    rows = [
        db.StickerRow(17, 111, "lyudi", 1, "люди <очень> ценны", "/tmp/a.webp", True),
        db.StickerRow(18, 111, "wndr", 1, "WNDR club", "/tmp/b.webp", True),
    ]

    text = generate._delete_hint_chunks(rows, settings, 111)[0]

    assert "<code>удали #17</code> — люди &lt;очень&gt; ценны" in text
    assert "<code>удали #18</code> — WNDR club" in text


def test_delete_hint_marks_what_each_person_may_touch(settings):
    """Права видно до нажатия, а не после: своё, чужое и основа выглядят по-разному."""
    rows = [
        db.StickerRow(1, 222, "a", 1, "своя", "/tmp/a.webp", True),
        db.StickerRow(2, 333, "b", 1, "чужая", "/tmp/b.webp", True),
        db.StickerRow(3, 333, "c", 1, "основа", "/tmp/c.webp", True, is_core=True),
    ]

    text = generate._delete_hint_chunks(rows, settings, 222)[0]
    assert "(твой)" in text and "(чужой)" in text and "(основа пака)" in text

    keyboard = generate._pack_list_keyboard(rows, settings, 222)
    labels = [row[0].text for row in keyboard.inline_keyboard]
    # Кнопка только у своего: чужой убирает модератор, у ядра кнопки нет.
    assert labels == ["✕ своя"]

    # Модератор (дефолтные ники клуба) видит ✕ у всего, кроме ядра.
    mod_keyboard = generate._pack_list_keyboard(rows, settings, 999, "IrinaFedyay")
    mod_labels = [row[0].text for row in mod_keyboard.inline_keyboard]
    assert mod_labels == ["✕ своя", "✕ чужая"]


def test_delete_hint_chunks_large_pack(settings):
    rows = [
        db.StickerRow(
            i,
            111,
            f"slug-{i}",
            1,
            "очень длинная фраза " * 8,
            f"/tmp/{i}.webp",
            True,
        )
        for i in range(1, 121)
    ]

    chunks = generate._delete_hint_chunks(rows, settings, 111, max_chars=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "<code>удали #1</code>" in chunks[0]
    assert "<code>удали #120</code>" in chunks[-1]


def test_pack_list_chunks_large_pack_and_escapes_html():
    rows = [
        db.StickerRow(
            i,
            111,
            f"slug-{i}",
            1,
            "фраза <с html> " * 8,
            f"/tmp/{i}.webp",
            True,
        )
        for i in range(1, 121)
    ]

    chunks = generate._pack_list_chunks(rows, max_chars=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "&lt;с html&gt;" in chunks[0]
    assert "#120" in chunks[-1]


def test_removed_message_escapes_html_phrase():
    text = generate._removed_message("люди <очень> ценны")

    assert "люди &lt;очень&gt; ценны" in text
