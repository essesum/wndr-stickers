"""Типографическое разнообразие: автоакцент, росчерк, оттенки, никаких кавычек.

Пак был зажат: один шрифт, один цвет, весь текст ровно по центру. Референс
WndrMorelife держит единство на палитре, а разнообразие — на типографике:
акцентные слова цветом, подчёркивания-росчерки. Кавычки на стикерах Катя
запретила совсем.
"""
from __future__ import annotations

import random

from PIL import Image

from skill.wndr_stickers.src.plate import Rect
from skill.wndr_stickers.src.style import ACCENT, BLACK, CREAM, RUST, SAND, TERRACOTTA
from skill.wndr_stickers.src.typeset import (
    Word,
    auto_accent,
    fit_text,
    parse_accents,
    pick_accent_color,
    pick_text_color,
    render,
    typeset,
)

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"


# --- кавычки не попадают на стикер -------------------------------------------

def test_parse_accents_drops_surrounding_quotes():
    assert parse_accents("«я так чувствую»")[0] == "я так чувствую"


def test_parse_accents_drops_quotes_inside_the_phrase():
    assert parse_accents('сказал "хватит" и ушёл')[0] == "сказал хватит и ушёл"
    assert parse_accents("это „оно“ самое")[0] == "это оно самое"


def test_question_and_exclamation_survive_quote_stripping():
    assert parse_accents("«было!»")[0] == "было!"


# --- пары текст/фон для оттенков ---------------------------------------------

def test_text_colour_on_shade_plates():
    assert pick_text_color(RUST) == CREAM
    assert pick_text_color(TERRACOTTA) == BLACK
    assert pick_text_color(SAND) == BLACK


def test_accent_colour_on_shade_plates_differs_from_text():
    for background in (RUST, TERRACOTTA, SAND):
        text = pick_text_color(background)
        accent = pick_accent_color(background, text)
        assert accent != text


def test_sand_plate_gets_the_orange_accent():
    assert pick_accent_color(SAND, BLACK) == ACCENT


# --- автоакцент ---------------------------------------------------------------

def test_auto_accent_marks_exactly_one_meaningful_word():
    words = [
        Word("Делать", False),
        Word("шаги", False),
        Word("и", False),
        Word("собирать", False),
        Word("результаты", False),
    ]
    out = auto_accent(words, random.Random(1), chance=1.0)
    assert sum(w.accent for w in out) == 1
    marked = next(w for w in out if w.accent)
    assert marked.text != "и", "предлоги и союзы — не акцент"


def test_auto_accent_respects_manual_marking():
    words = [Word("Это", False), Word("тантра", True)]
    assert auto_accent(words, random.Random(1), chance=1.0) == words


def test_auto_accent_leaves_a_single_word_alone():
    words = [Word("было!", False)]
    assert auto_accent(words, random.Random(1), chance=1.0) == words


def test_auto_accent_respects_chance_zero():
    words = [Word("Делать", False), Word("шаги", False)]
    assert auto_accent(words, random.Random(1), chance=0.0) == words


# --- росчерк под акцентом -----------------------------------------------------

def _accent_pixel_count(underline: bool) -> int:
    plate = Image.new("RGBA", (600, 400), (*BLACK, 255))
    rect = Rect(50, 50, 550, 350)
    words = [Word("Это", False), Word("не", False), Word("тантра", True)]
    layout = fit_text(words, rect, FONT)
    assert layout is not None
    out = render(
        plate,
        layout,
        rect,
        FONT,
        text_color=CREAM,
        accent_color=ACCENT,
        underline_accents=underline,
    )
    return sum(1 for p in out.crop(rect.as_tuple()).getdata() if p[:3] == ACCENT)


def test_underline_flourish_adds_accent_ink():
    assert _accent_pixel_count(True) > _accent_pixel_count(False)


# --- typeset с rng даёт вариативность, но не ломает контракт ------------------

def test_typeset_with_rng_still_fits_and_keeps_the_phrase():
    plate = Image.new("RGBA", (600, 400), (*BLACK, 255))
    rect = Rect(50, 50, 550, 350)
    out, layout = typeset(
        plate, "Делать шаги и собирать результаты", rect, FONT, BLACK,
        rng=random.Random(2),
    )
    rendered = " ".join(w.text for line in layout.lines for w in line)
    assert rendered == "Делать шаги и собирать результаты"
    assert layout.width <= rect.width
    assert layout.height <= rect.height


def test_typeset_with_rng_sometimes_paints_an_accent_word():
    """Хотя бы на одном из сидов появляется акцентный цвет — детерминированно."""
    plate = Image.new("RGBA", (600, 400), (*BLACK, 255))
    rect = Rect(50, 50, 550, 350)
    for seed in range(8):
        out, _ = typeset(
            plate, "Делать шаги и собирать результаты", rect, FONT, BLACK,
            rng=random.Random(seed),
        )
        colours = {p[:3] for p in out.crop(rect.as_tuple()).getdata()}
        if ACCENT in colours:
            return
    raise AssertionError("ни на одном сиде автоакцент не сработал")
