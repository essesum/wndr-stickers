"""Оттенки палитры v0.2: рыжий/бежевый/чёрный получают по родственному тону.

Решение Кати 2026-08-12: базовая тройка остаётся основой, но пак был слишком
зажат — добавлены deep rust, terracotta и sand. Оттенки редкие (weighted),
иначе основа перестанет читаться как основа.
"""
from __future__ import annotations

import random
from collections import Counter

from PIL import Image

from skill.wndr_stickers.src import style
from skill.wndr_stickers.src.cutout import save_webp
from skill.wndr_stickers.src.verify import verify_sticker


def test_shade_constants_match_declared_hex():
    assert style.hexstr(style.RUST) == "#992D0E"
    assert style.hexstr(style.TERRACOTTA) == "#E0764A"
    assert style.hexstr(style.SAND) == "#D9BE93"


def test_base_palette_is_untouched():
    """Оттенки — добавка, а не замена: канон v0.1 обязан остаться как был."""
    assert style.hexstr(style.ACCENT) == "#CC3D11"
    assert style.hexstr(style.BLACK) == "#0D0D0D"
    assert style.hexstr(style.CREAM) == "#F2E2C8"
    assert style.hexstr(style.NEAR_WHITE) == "#F7F3EA"


def test_combo_pool_prefers_base_plates_but_every_shade_appears():
    rng = random.Random(7)
    counts = Counter(style.pick_combo(rng)["key"] for _ in range(900))
    base = {"black-plate", "accent-plate", "cream-plate"}
    shades = {"rust-plate", "terracotta-plate", "sand-plate"}
    for key in base | shades:
        assert counts[key] > 0, f"{key} ни разу не выпал"
    for shade_key in shades:
        for base_key in base:
            assert counts[base_key] > counts[shade_key], (
                f"оттенок {shade_key} выпадает чаще базового {base_key}"
            )


def test_plate_prompt_mentions_shades():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("rounded-rect"),
        combo={"fill": "warm sand #D9BE93"},
    )
    assert "#992D0E" in prompt
    assert "#E0764A" in prompt
    assert "#D9BE93" in prompt


def test_colour_ban_covers_shades_instead_of_counting_to_three():
    """Старый запрет «не больше трёх цветов» противоречил бы оттенкам."""
    assert "No more than three colours" not in style.NEGATIVE
    assert "outside the approved WNDR palette" in style.NEGATIVE


def test_placement_varies_top_and_bottom():
    rng = random.Random(3)
    seen = {style.pick_placement(rng) for _ in range(50)}
    assert seen == {"top", "bottom"}


def _plate(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    img.alpha_composite(Image.new("RGBA", (400, 400), (*color, 255)), (56, 56))
    return img


def test_shade_plates_pass_official_gate(tmp_path):
    """Приёмка обязана знать оттенки, иначе каждая новая плашка — брак."""
    for name in ("rust", "terracotta", "sand"):
        color = getattr(style, name.upper())
        path = save_webp(_plate(color), tmp_path / f"{name}.webp")
        result = verify_sticker(path, enforce_style=True)
        assert result.ok, (name, result.problems)
