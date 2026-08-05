"""Community duplicate memory is local SQLite, never Katya's shared memory."""
from pathlib import Path

import pytest

from skill.wndr_stickers.src import community_memory as cm
from skill.wndr_stickers.src import db


def _match(phrase, score, slug="s", version=1):
    return cm.Similar(phrase=phrase, score=score, slug=slug, version=version, sticker_id=1)


def test_module_has_no_shared_memory_endpoint():
    source = Path(cm.__file__).read_text()
    for forbidden in ("QDRANT", "6333", "katya_memory", "Memory API", "8920"):
        assert forbidden not in source


def test_close_phrase_is_reported_as_duplicate():
    hit = cm.decide_duplicate([_match("Со мной все нормально", 0.94)], threshold=0.88)
    assert hit is not None and hit.phrase == "Со мной все нормально"


def test_distant_or_empty_matches_are_not_duplicates():
    assert cm.decide_duplicate([_match("Пусть все цветы расцветут", 0.41)], threshold=0.88) is None
    assert cm.decide_duplicate([], threshold=0.88) is None


def test_exact_repeat_normalisation():
    assert cm.same_phrase("Со мной все нормально", "  со мной   все нормально ")
    assert cm.same_phrase("Это не *тантра*", "Это не тантра")
    assert not cm.same_phrase("Со мной все нормально", "Со мной всё нормально")
    assert not cm.same_phrase("Я получаю удовольствие?", "Я получаю удовольствие")


@pytest.mark.asyncio
async def test_vectors_live_in_bot_sqlite_only(tmp_path, monkeypatch):
    path = tmp_path / "stickers.db"
    await db.init_db(path)

    async def fake_embed(text):
        return [1.0, 0.0] if "норм" in text else [0.0, 1.0]

    monkeypatch.setattr(cm, "embed", fake_embed)
    saved = await cm.remember(
        path,
        "Со мной все нормально",
        sticker_id=7,
        slug="so-mnoy",
        version=2,
    )
    assert saved

    hits = await cm.find_similar(path, "нормально", limit=3)
    assert hits and hits[0].sticker_id == 7
    assert hits[0].score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_embedding_failure_is_best_effort(tmp_path, monkeypatch):
    path = tmp_path / "stickers.db"
    await db.init_db(path)

    async def no_embedding(text):
        return None

    monkeypatch.setattr(cm, "embed", no_embedding)
    assert await cm.find_similar(path, "что угодно") == []
    assert not await cm.remember(path, "что угодно", sticker_id=1, slug="x", version=1)
