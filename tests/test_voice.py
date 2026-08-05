"""Голос бота. Он разговаривает с сообществом, а не отчитывается о работе."""
import random

import pytest

from skill.wndr_stickers.src import voice

#: Слова из машинного отчёта. Человеку в чате они ничего не говорят.
LEAKY = ("плашк", "промпт", "генерир", "пайплайн", "модель", "провайдер", "webp", "512")


def test_there_are_enough_waiting_phrases_to_not_repeat():
    assert len(set(voice.WAITING)) >= 6


def test_waiting_phrases_never_leak_implementation():
    for phrase in voice.WAITING:
        low = phrase.lower()
        for word in LEAKY:
            assert word not in low, f"{phrase!r} протекает словом {word!r}"


def test_waiting_phrases_are_short_enough_for_a_chat():
    for phrase in voice.WAITING:
        assert len(phrase) <= 60, f"{phrase!r} слишком длинная"


def test_waiting_phrases_carry_the_pause():
    """Многоточие обещает продолжение — человек понимает, что надо подождать."""
    for phrase in voice.WAITING:
        assert phrase.rstrip().endswith("…"), f"{phrase!r} без многоточия"


def test_waiting_picks_from_the_list():
    for seed in range(30):
        assert voice.waiting(random.Random(seed)) in voice.WAITING


def test_waiting_actually_varies():
    seen = {voice.waiting(random.Random(seed)) for seed in range(40)}
    assert len(seen) >= 4, "фразы не перемешиваются"


def test_help_text_names_what_the_bot_does():
    text = voice.help_text()
    for expected in ("стикер", "*", "пак"):
        assert expected in text.lower(), f"в справке нет {expected!r}"


def test_help_text_is_short_because_the_bot_is_not_a_conversationalist():
    """Задача бота — делать контент, а не разговаривать. Ответил и работает дальше."""
    assert len(voice.help_text()) <= 420


def test_help_text_does_not_brag_about_internals():
    low = voice.help_text().lower()
    for word in ("шрифт", "впечатыв", "твёрд", "кегль", "плашк"):
        assert word not in low, f"справка хвастается внутренностями: {word!r}"


# --- подпись под готовым стикером ---------------------------------------------
# Была машинным отчётом: «форма lightning · кегль 133».

def test_done_caption_leads_with_the_phrase():
    assert "Со мной все нормально" in voice.done("Со мной все нормально")


def test_done_caption_has_no_machine_report():
    caption = voice.done("Со мной все нормально").lower()
    for word in ("форма", "кегль", "lightning", "провайдер", "codex"):
        assert word not in caption, f"в подписи машинный отчёт: {word!r}"


def test_done_caption_varies():
    seen = {voice.done("фраза", random.Random(seed)) for seed in range(40)}
    assert len(seen) >= 3, "подпись всегда одинаковая"


def test_failure_message_does_not_blame_the_user():
    text = voice.failed().lower()
    assert "ты" not in text.split(), "не вали на человека"
    assert len(voice.failed()) <= 200


def test_help_text_invites_to_try_the_asked_phrase():
    """На «что ты умеешь?» бот предлагает сделать стикер из этой же фразы."""
    text = voice.help_text("что ты умеешь?")
    assert "что ты умеешь?" in text


def test_help_text_without_a_phrase_does_not_dangle():
    assert "None" not in voice.help_text()
    assert "«»" not in voice.help_text()


@pytest.mark.parametrize("phrase", ["было!", 'сделай "я так чувствую"'])
def test_help_text_survives_odd_phrases(phrase):
    assert phrase in voice.help_text(phrase)
