import pytest
from PIL import Image

from skill.wndr_stickers.src.plate import Rect
from skill.wndr_stickers.src.style import ACCENT, BLACK, CREAM
from skill.wndr_stickers.src.typeset import (
    Word,
    contrast_ratio,
    fit_text,
    parse_accents,
    pick_accent_color,
    pick_text_color,
    typeset,
)

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"


def test_parse_accents_extracts_marked_words():
    plain, words = parse_accents("Это не *тантра*")
    assert plain == "Это не тантра"
    assert [w.text for w in words] == ["Это", "не", "тантра"]
    assert [w.accent for w in words] == [False, False, True]


def test_parse_accents_preserves_hard_sign_and_yo():
    plain, words = parse_accents("Я приношу весь свой объем")
    assert plain == "Я приношу весь свой объем"
    assert words[-1].text == "объем"
    assert "ъ" in words[-1].text


def test_parse_accents_keeps_question_mark_only_when_given():
    assert parse_accents("Я сейчас получаю удовольствие")[0] == "Я сейчас получаю удовольствие"
    assert parse_accents("Я получаю сейчас удовольствие?")[0] == "Я получаю сейчас удовольствие?"


def test_text_colour_contrasts_with_plate():
    assert pick_text_color(BLACK) in (CREAM, (0xF7, 0xF3, 0xEA))
    assert pick_text_color(CREAM) == BLACK


def test_accent_colour_differs_from_text_colour():
    text = pick_text_color(BLACK)
    accent = pick_accent_color(BLACK, text)
    assert accent != text


def test_contrast_ratio_is_symmetric_and_bounded():
    assert contrast_ratio(BLACK, CREAM) == pytest.approx(contrast_ratio(CREAM, BLACK))
    assert 1.0 <= contrast_ratio(BLACK, CREAM) <= 21.0


def test_fit_text_uses_bigger_type_in_a_bigger_box():
    words = [Word("ПУСТЬ", False), Word("ВСЕ", False), Word("ЦВЕТЫ", False)]
    small = fit_text(words, Rect(0, 0, 200, 100), FONT)
    large = fit_text(words, Rect(0, 0, 600, 300), FONT)
    assert small is not None and large is not None
    assert large.font_size > small.font_size


def test_fit_text_respects_the_box():
    words = [Word("Я", False), Word("ПРИНОШУ", False), Word("ВЕСЬ", False), Word("ОБЪЕМ", False)]
    rect = Rect(10, 10, 410, 210)
    layout = fit_text(words, rect, FONT)
    assert layout is not None
    assert layout.width <= rect.width
    assert layout.height <= rect.height
    assert len(layout.lines) <= 3


def test_fit_text_keeps_every_word():
    words = [Word("Со", False), Word("мной", False), Word("все", False), Word("нормально", False)]
    layout = fit_text(words, Rect(0, 0, 500, 250), FONT)
    assert layout is not None
    rendered = [w.text for line in layout.lines for w in line]
    assert rendered == ["Со", "мной", "все", "нормально"]


def test_fit_text_returns_none_for_no_words():
    assert fit_text([], Rect(0, 0, 500, 250), FONT) is None


def test_typeset_draws_pixels_inside_the_rect():
    plate = Image.new("RGBA", (600, 400), (*BLACK, 255))
    rect = Rect(50, 50, 550, 350)
    out, layout = typeset(plate, "Со мной все нормально", rect, FONT, BLACK)
    assert layout.font_size > 0
    # внутри области появились небелые/нефоновые пиксели
    patch = out.crop(rect.as_tuple())
    colours = {p[:3] for p in patch.getdata()}
    assert colours != {BLACK}


def test_typeset_raises_when_text_cannot_fit():
    plate = Image.new("RGBA", (600, 400), (*BLACK, 255))
    with pytest.raises(ValueError):
        typeset(plate, "Я приношу весь свой объем", Rect(0, 0, 6, 4), FONT, BLACK)


def test_accent_word_renders_in_a_different_colour():
    plate = Image.new("RGBA", (600, 400), (*BLACK, 255))
    rect = Rect(50, 50, 550, 350)
    out, _ = typeset(plate, "Это не *тантра*", rect, FONT, BLACK)
    colours = {p[:3] for p in out.crop(rect.as_tuple()).getdata()}
    assert ACCENT in colours
