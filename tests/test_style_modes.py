"""Режимы стиля (classic/expressive) и правило «розы — без чёрного»."""
import random

from PIL import Image, ImageDraw

from skill.wndr_stickers.src import style, typeset
from skill.wndr_stickers.src.cutout import save_webp
from skill.wndr_stickers.src.style import (
    ACCENT,
    BLACK,
    CREAM,
    RUST,
    SAND,
    TERRACOTTA,
)
from skill.wndr_stickers.src.verify import verify_sticker


# --- Режимы ------------------------------------------------------------------
def test_both_modes_appear():
    """Пак должен мешать оба характера, а не выродиться в один."""
    seen = {style.pick_mode(random.Random(seed)).key for seed in range(200)}
    assert seen == {"classic", "expressive"}


def test_mode_by_key():
    # Оба режима носят автоакцент: на flat-листе оранжевые слова почти всюду.
    assert style.mode_by_key("classic").typographic_spread is True
    assert style.mode_by_key("expressive").typographic_spread is True
    assert style.mode_by_key("classic").look == "clean"
    assert style.mode_by_key("expressive").look == "ornate"
    assert style.mode_by_key("nope") is None


def test_classic_mode_is_flat_sticker_sheet():
    """Classic — плоский лист: базовая тройка, spark/plain, без гравюрных мотивов."""
    mode = style.mode_by_key("classic")
    densities = set()
    for seed in range(200):
        rng = random.Random(seed)
        combo = style.pick_combo(rng, keys=mode.combo_keys)
        assert combo["key"] in ("black-plate", "accent-plate", "cream-plate")
        density = style.pick_density(rng, keys=mode.density_keys)
        assert density.key in ("spark", "plain")
        densities.add(density.key)
        assert style.pick_motif(rng, chance=mode.motif_chance) is None
        shape = style.pick_shape(rng=rng, bank=style.shape_bank(mode.look))
        assert shape.key.startswith("clean-")
    # Искры — основной приём, но голая плашка тоже должна выпадать.
    assert densities == {"spark", "plain"}


def test_clean_shapes_carry_no_vintage_ornament():
    """В плоском банке нет гравюры, винтажа и ботаники — форма плоская и чистая."""
    for shape in style.CLEAN_SHAPES:
        for word in ("engraved", "wreath", "ornament", "vintage", "botanical", "doubled"):
            assert word not in shape.prompt, (shape.key, word)


def test_clean_look_prompt_is_flat():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("clean-rect"),
        combo={"fill": "cream #F2E2C8"},
        density=style.density_by_key("plain"),
        look="clean",
    )
    assert "silkscreen" not in prompt
    assert "COMPLETELY PLAIN" in prompt
    assert "FLAT modern die-cut sticker" in prompt


def test_spark_density_is_flat_sparkles_only():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("clean-cloud"),
        combo={"fill": "near-black #0D0D0D"},
        density=style.density_by_key("spark"),
        look="clean",
    )
    assert "four-point sparkle stars" in prompt
    assert "no engraving" in prompt


def test_ornate_look_is_still_the_default():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("rounded-rect"),
        combo={"fill": "cream #F2E2C8"},
        density=style.density_by_key("framed"),
    )
    assert "silkscreen print label" in prompt


def test_flat_densities_stay_out_of_expressive_draw():
    """spark и plain — приёмы classic; expressive гоняет свои плотности."""
    mode = style.mode_by_key("expressive")
    keys = {
        style.pick_density(random.Random(seed), keys=mode.density_keys).key
        for seed in range(300)
    }
    assert keys == {"bare", "framed", "ornate"}


def test_shape_by_key_finds_both_banks():
    assert style.shape_by_key("rounded-rect") is not None
    assert style.shape_by_key("clean-ticket") is not None


def test_expressive_mode_still_uses_full_variety():
    mode = style.mode_by_key("expressive")
    combos = {
        style.pick_combo(random.Random(seed), keys=mode.combo_keys)["key"]
        for seed in range(400)
    }
    assert combos == {c["key"] for c in style.COMBOS}
    motifs = {
        style.pick_motif(random.Random(seed), chance=mode.motif_chance)
        for seed in range(200)
    }
    assert None in motifs and len(motifs) > 3


# --- Розы --------------------------------------------------------------------
def test_mentions_roses_positive():
    assert style.mentions_roses("a pair of engraved roses with leaves")
    assert style.mentions_roses("розы")
    assert style.mentions_roses("Роза")
    assert style.mentions_roses("букет роз")
    assert style.mentions_roses("розочка для мамы")
    wreath = style.shape_by_key("wreath")
    assert style.mentions_roses(wreath.prompt)


def test_mentions_roses_negative():
    assert not style.mentions_roses("розовый закат")  # цвет, не цветок
    assert not style.mentions_roses("мороз и солнце")
    assert not style.mentions_roses("a scalloped rosette badge")
    assert not style.mentions_roses("розетка в стене")
    assert not style.mentions_roses(None, "")


def test_no_black_combo_filter():
    for seed in range(300):
        combo = style.pick_combo(random.Random(seed), no_black=True)
        assert "#0D0D0D" not in combo["fill"]


def test_rose_motif_prompt_bans_black():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("rounded-rect"),
        combo={"fill": "burnt orange #CC3D11"},
        motif="a pair of engraved roses with leaves",
        density=style.density_by_key("bare"),
    )
    assert "FORBIDDEN" in prompt
    assert "heavy deep rust #992D0E linework" in prompt
    assert "heavy black linework" not in prompt


def test_wreath_shape_alone_triggers_rose_rule():
    """В рамке wreath — гравированные розы, значит правило действует и без мотива."""
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("wreath"),
        combo={"fill": "cream #F2E2C8"},
        density=style.density_by_key("framed"),
    )
    assert "FORBIDDEN" in prompt


def test_plain_prompt_keeps_black_linework():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("scallop-frame"),
        combo={"fill": "cream #F2E2C8"},
        motif="a sprig of wheat",
        density=style.density_by_key("bare"),
    )
    assert "FORBIDDEN" not in prompt
    assert "heavy black linework" in prompt


def test_rose_illustration_prompt_bans_black():
    prompt = style.build_illustration_prompt(motif="розы")
    assert "FORBIDDEN" in prompt
    assert "heavy black linework" not in prompt
    ordinary = style.build_illustration_prompt(motif="костёр")
    assert "FORBIDDEN" not in ordinary
    assert "heavy black linework" in ordinary


# --- Текстовые цвета без чёрного ---------------------------------------------
def test_typeset_colors_never_black_for_roses():
    for fill in (ACCENT, CREAM, RUST, TERRACOTTA, SAND):
        text = typeset.pick_text_color(fill, forbid_black=True)
        accent = typeset.pick_accent_color(fill, text, forbid_black=True)
        assert text != BLACK, fill
        assert accent != BLACK, fill
        assert accent != text, fill
        assert accent != fill, fill


def test_typeset_colors_unchanged_without_flag():
    assert typeset.pick_text_color(CREAM) == BLACK
    assert typeset.pick_accent_color(ACCENT, CREAM) == BLACK


# --- Приёмка -----------------------------------------------------------------
def _plate(fill, line) -> Image.Image:
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((40, 40, 472, 472), fill=(*fill, 255))
    draw.ellipse((150, 150, 362, 362), outline=(*line, 255), width=24)
    return img


def test_verify_rejects_black_when_forbidden(tmp_path):
    path = save_webp(_plate(CREAM, BLACK), tmp_path / "rose-black.webp")
    result = verify_sticker(path, enforce_style=True, forbid_black=True)
    assert not result.ok
    assert any("розы без чёрного" in p for p in result.problems)


def test_verify_accepts_rust_instead_of_black(tmp_path):
    path = save_webp(_plate(CREAM, RUST), tmp_path / "rose-rust.webp")
    result = verify_sticker(path, enforce_style=True, forbid_black=True)
    assert result.ok, result.problems


def test_verify_without_flag_still_accepts_black(tmp_path):
    path = save_webp(_plate(CREAM, BLACK), tmp_path / "plain-black.webp")
    result = verify_sticker(path, enforce_style=True)
    assert result.ok, result.problems
