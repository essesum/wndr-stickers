"""Дизайнерская полировка типографики (ревью живого пака 2026-08-12)."""
import random

from PIL import Image

from skill.wndr_stickers.src.plate import Rect
from skill.wndr_stickers.src.style import ACCENT, BLACK, CREAM, RUST
from skill.wndr_stickers.src.typeset import (
    Word,
    auto_accent,
    fit_text,
    pick_accent_color,
    render,
)

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"


def test_rust_plate_gets_orange_accent_not_black():
    """Чёрный акцент на #992D0E тонул (bolshe-zhizni-v9): контраст ~1.8:1."""
    assert pick_accent_color(RUST, CREAM) == ACCENT


def test_two_word_phrase_gets_accent_less_often():
    """Акцент на 1 из 2 слов перекрашивает полстикера — приём должен быть реже."""
    words = [Word("больше", False), Word("жизни", False)]
    hits = sum(
        any(w.accent for w in auto_accent(words, random.Random(seed), chance=1.0))
        for seed in range(400)
    )
    # При chance=1.0 эффективная вероятность для пары слов — 0.5.
    assert 140 < hits < 260


def _accent_ink(words: list[Word], underline: bool, max_lines: int = 2) -> int:
    plate = Image.new("RGBA", (400, 400), (*BLACK, 255))
    rect = Rect(40, 40, 360, 360)
    layout = fit_text(words, rect, FONT, max_lines=max_lines)
    assert layout is not None
    assert len(layout.lines) == 2, "фикс проверяется именно на двух строках"
    out = render(
        plate, layout, rect, FONT,
        text_color=CREAM, accent_color=ACCENT, underline_accents=underline,
    )
    return sum(1 for p in out.crop(rect.as_tuple()).getdata() if p[:3] == ACCENT)


def test_no_flourish_between_lines():
    """Росчерк под первой строкой читался как зачёркивание (more-life-v8/v12)."""
    words = [Word("больше", True), Word("жизни", False)]
    assert _accent_ink(words, underline=True) == _accent_ink(words, underline=False)


def test_flourish_still_drawn_on_last_line():
    words = [Word("больше", False), Word("жизни", True)]
    assert _accent_ink(words, underline=True) > _accent_ink(words, underline=False)
