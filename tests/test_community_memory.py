"""Своя память сообщества: что уже было и что повторяется.

Отдельная коллекция Qdrant, не katya_memory: это память сообщества, а не Кати.
SQLite остаётся истиной, коллекция — перестраиваемый индекс поверх неё.
"""
from skill.wndr_stickers.src import community_memory as cm


def _match(phrase, score, slug="s", version=1):
    return cm.Similar(phrase=phrase, score=score, slug=slug, version=version, sticker_id=1)


def test_collection_is_separate_from_katya_memory():
    assert cm.COLLECTION == "wndr_community"
    assert cm.COLLECTION != "katya_memory"


def test_vector_params_match_the_system_embedder():
    # embeddinggemma:300m -> 768, Cosine, как в katya_memory
    assert cm.DIMS == 768
    assert cm.DISTANCE == "Cosine"


def test_close_phrase_is_reported_as_duplicate():
    hit = cm.decide_duplicate([_match("Со мной все нормально", 0.94)], threshold=0.88)
    assert hit is not None
    assert hit.phrase == "Со мной все нормально"


def test_distant_phrase_is_not_a_duplicate():
    assert cm.decide_duplicate([_match("Пусть все цветы расцветут", 0.41)], threshold=0.88) is None


def test_empty_matches_are_not_a_duplicate():
    assert cm.decide_duplicate([], threshold=0.88) is None


def test_the_closest_match_wins():
    hit = cm.decide_duplicate(
        [_match("дальше", 0.90), _match("ближе", 0.97), _match("средне", 0.93)],
        threshold=0.88,
    )
    assert hit.phrase == "ближе"


def test_threshold_is_inclusive_at_the_boundary():
    assert cm.decide_duplicate([_match("ровно", 0.88)], threshold=0.88) is not None


def test_exact_repeat_is_caught_before_embedding():
    """Точный повтор ловим строкой, не тратя вызов эмбеддера."""
    assert cm.same_phrase("Со мной все нормально", "  со мной   все нормально ")
    assert cm.same_phrase("Это не *тантра*", "Это не тантра")


def test_different_phrases_are_not_the_same():
    assert not cm.same_phrase("Со мной все нормально", "Со мной всё нормально")
    assert not cm.same_phrase("Я получаю удовольствие?", "Я получаю удовольствие")


def test_payload_carries_no_personal_data():
    """В общей памяти не должно быть Telegram-ID: они живут только в SQLite."""
    payload = cm.build_payload(
        phrase="Со мной все нормально", sticker_id=7, slug="so-mnoy", version=2, status="approved"
    )
    assert payload["phrase"] == "Со мной все нормально"
    assert payload["slug"] == "so-mnoy"
    assert payload["status"] == "approved"
    flat = " ".join(str(v) for v in payload.values()).lower()
    for forbidden in ("user_id", "submitted_by", "telegram", "author"):
        assert forbidden not in flat
    assert "user_id" not in payload and "submitted_by" not in payload


def test_point_id_is_stable_for_the_same_sticker():
    """Переиндексация не должна плодить дубли одного и того же стикера."""
    assert cm.point_id(42) == cm.point_id(42)
    assert cm.point_id(42) != cm.point_id(43)
