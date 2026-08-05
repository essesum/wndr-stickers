from skill.wndr_stickers.src.moderation import check_phrase


def test_normal_phrases_pass():
    for phrase in [
        "Со мной все нормально",
        "Я приношу весь свой объем",
        "Пусть все цветы расцветут",
        "Я сейчас получаю удовольствие",
        "было!",
        "Это не *тантра*",
    ]:
        assert check_phrase(phrase), f"{phrase!r} должна проходить"


def test_pack_lexicon_is_not_censored():
    # В самом паке живут «фейхуевого» и «кто сдох, тот — лох» — это стиль, не брак.
    assert check_phrase("Кто сдох, тот - лох")
    assert check_phrase("Ящик фейхуевого морса")


def test_too_long_is_rejected():
    verdict = check_phrase("а" * 80)
    assert not verdict
    assert "длинно" in verdict.reason


def test_too_short_is_rejected():
    assert not check_phrase("я")


def test_too_many_words_is_rejected():
    verdict = check_phrase("одно два три четыре пять шесть семь восемь девять")
    assert not verdict
    assert "слов" in verdict.reason


def test_links_and_mentions_are_rejected():
    assert not check_phrase("заходи на https://spam.ru")
    assert not check_phrase("пиши @somebody сюда")
    assert not check_phrase("t.me/channel")


def test_keyboard_mash_is_rejected():
    assert not check_phrase("ааааааааа привет")


def test_unpaired_accent_marker_is_explained():
    verdict = check_phrase("Это не *тантра")
    assert not verdict
    assert "парой" in verdict.reason


def test_emoji_are_rejected_with_the_offending_chars():
    verdict = check_phrase("Со мной все 🔥 нормально")
    assert not verdict
    assert "🔥" in verdict.reason


def test_blocklist_is_enforced():
    assert not check_phrase("heil всем")
