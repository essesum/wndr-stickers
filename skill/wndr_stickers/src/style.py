"""Canonical WNDR style contract.

The source of truth is docs/reference/WNDR-Sticker-Agent-v0.1.pdf, sections
2 (approved result), 8 (visual style), and 9 (generation prompts). The image
model draws only empty plates/illustrations on black; all sticker text is added
later by code.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

# --- Palette -----------------------------------------------------------------
ACCENT = (0xCC, 0x3D, 0x11)      # #CC3D11, accent / selected words / rays
BLACK = (0x0D, 0x0D, 0x0D)       # #0D0D0D, fill or text on light plates
CREAM = (0xF2, 0xE2, 0xC8)       # #F2E2C8, fill or text on dark plates
NEAR_WHITE = (0xF7, 0xF3, 0xEA)  # #F7F3EA, outer die-cut outline

PALETTE = {"accent": ACCENT, "black": BLACK, "cream": CREAM, "near_white": NEAR_WHITE}

# Colours that may be used by code-rendered text.
TEXT_COLORS = (ACCENT, BLACK, CREAM, NEAR_WHITE)


def hexstr(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# --- Shape bank --------------------------------------------------------------
@dataclass(frozen=True)
class Shape:
    key: str
    prompt: str
    character: str
    is_arrow: bool = False


#: Формы взяты с живого пака WndrMorelife: там плашка — это не прямоугольник с
#: текстом, а оформленный знак с рамкой, кантами и орнаментом. Простые примитивы
#: («скруглённый прямоугольник») давали пустые пресные стикеры, потому что модель
#: честно рисовала ровно то, что просили.
SHAPES: tuple[Shape, ...] = (
    Shape(
        "rounded-rect",
        "a rounded rectangle plate with a doubled contrasting keyline and small "
        "ornamental corner marks",
        "нейтральный, много текста",
    ),
    Shape(
        "rosette",
        "a scalloped rosette badge with a wavy petal-shaped outer edge and a thin "
        "concentric inner keyline following the scallops",
        "торжественный, знак качества",
    ),
    Shape(
        "wreath",
        "an ornate badge framed by an engraved botanical wreath of roses and leaves "
        "growing along the left and right edges and meeting at top and bottom",
        "цветущий, праздничный",
    ),
    Shape(
        "celestial-burst",
        "a starburst badge with long pointed rays around the whole contour, with a "
        "small engraved crescent moon, sun face and scattered stars worked into the "
        "rays and the frame",
        "громкий, космический",
    ),
    Shape(
        "ticket",
        "a horizontal ticket / coupon plate with semicircular notches punched into "
        "the left and right sides and a dashed perforation line near one end",
        "документальный, билет",
    ),
    Shape(
        "banner-swash",
        "a rounded banner plate with a small pointed tail at the bottom and a thin "
        "decorative swash flourish curving under the text area",
        "разговорный, тёплый",
    ),
    Shape(
        "ray-oval",
        "a horizontal oval plate with short straight dashes radiating outward from "
        "the left and right sides like an emphasis mark",
        "восклицание, акцент",
    ),
    Shape(
        "lightning",
        "a bold cut-parallelogram banner with a lightning-bolt notch on one edge and "
        "a doubled contrasting keyline",
        "дерзкий, панч",
    ),
    Shape(
        "arrow",
        "an arrow / pointer badge with a doubled keyline and small star accents at "
        "the tail",
        "вводит продолжение",
        is_arrow=True,
    ),
)


def pick_shape(allow_arrows: bool = True, rng: random.Random | None = None) -> Shape:
    rng = rng or random.Random()
    pool = [s for s in SHAPES if allow_arrows or not s.is_arrow]
    return rng.choice(pool)


def shape_by_key(key: str) -> Shape | None:
    return next((s for s in SHAPES if s.key == key), None)


# --- Colour pairings ---------------------------------------------------------
# Exactly two base colours per plate. A third colour appears only as the later
# code-rendered accent on 1-3 words.
COMBOS = (
    {"key": "black-plate", "fill": "near-black #0D0D0D", "text": "cream #F2E2C8"},
    {"key": "accent-plate", "fill": "burnt orange #CC3D11", "text": "cream #F2E2C8"},
    {"key": "cream-plate", "fill": "cream #F2E2C8", "text": "near-black #0D0D0D"},
)


def pick_combo(rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    return rng.choice(list(COMBOS))


# --- Bans --------------------------------------------------------------------
#: «No tiny cluttered detail» отсюда убрано намеренно: модель понимала это как
#: запрет на орнамент вообще и выдавала пустые плашки. Богатая рамка — это и
#: есть стиль пака, ограничивать надо середину, а не контур.
NEGATIVE = (
    "NO text, NO letters, NO typography, NO numbers, NO captions, "
    "NO watermark, NO signature. "
    "No gradients, no 3D, no gloss, no drop shadows, no photorealism/photo. "
    "No more than three colours in the design itself, not counting the "
    "cream die-cut outline. No non-black background outside the sticker."
)


# --- Prompts -----------------------------------------------------------------
PLATE_PROMPT = """\
Using the attached WNDR sheet as a STRICT style reference, draw ONE single die-cut \
sticker plate, centred, on a plain solid pure-black background.

Shape: {shape_prompt}.
Plate fill: {fill}. A warm cream-white outer die-cut outline (#F7F3EA) runs around \
the whole contour and should read as 8-12 px at 512 px, with a thin contrasting \
inner keyline echoing the contour a few pixels inside it.
Palette strictly and only: burnt orange #CC3D11, near-black #0D0D0D, cream \
#F2E2C8, plus the off-white die-cut outline #F7F3EA. The three design colours \
may all appear together in the frame and ornament; the flat central fill stays \
a single colour.
Flat retro 1970s signage / silkscreen look, in the spirit of an ornate vintage \
label: the border and frame are richly decorated, the centre is calm.

CRITICAL — the interior of the plate must be a FLAT EMPTY area of solid {fill}, \
completely clean and uninterrupted across the middle {clean_band} of the plate. \
The fill must be absolutely uniform: no gradient, lighting, shading, glow, vignette, \
paper texture, tonal variation, or dimensional effect. Typography will be added \
later by software, so any mark inside that area ruins it.

{illustration_clause}

The black background must touch all four corners of the canvas and must be clearly \
separated from any black inside the design by the cream outline — this is required \
for automatic cut-out.

{negative}
"""

ILLUSTRATION_CLAUSE = """\
Add ONE very simple, almost iconic illustrative element ({motif}) tucked into the \
{placement} edge of the plate only. Draw it as a vintage engraving / botanical \
illustration with heavy black linework and flat fills. It must not enter the clean \
central area.\
"""

#: Раньше здесь стояло «keep the plate bare … at most one tiny mark», и модель
#: честно рисовала пустую плашку. Богатство живёт в рамке — просить его надо
#: прямо, иначе его не будет.
BARE_CLAUSE = """\
Decorate the FRAME generously in engraved vintage-label fashion: layered keylines \
following the contour, and ornament worked into the border — small stars and \
sparkles, short rays, botanical sprigs, or a repeating edge motif, whatever suits \
the shape. The ornament belongs to the border and the corners; it must never \
enter the clean central area.\
"""

ILLUSTRATION_PROMPT = """\
Using the attached WNDR sheet as a STRICT style reference, draw ONE die-cut \
illustration sticker of {motif}, centred, on a plain solid pure-black background.

Vintage botanical/engraving illustration style with heavy black linework and flat \
colour fills. A thick warm cream-white die-cut outline (#F7F3EA) runs around the \
whole outer contour and should read as 8-12 px at 512 px.
Palette strictly and only: burnt orange #CC3D11, near-black #0D0D0D, cream \
#F2E2C8, off-white #F7F3EA.

The black background must touch all four corners of the canvas and must be clearly \
separated from any black inside the design by the cream outline.

{negative}
"""

def build_plate_prompt(
    *,
    shape: Shape,
    combo: dict,
    motif: str | None = None,
    placement: str = "bottom",
    clean_band: str = "60%",
    allow_arrows: bool = True,
) -> str:
    """Prompt for an empty plate — user phrase is rendered later by code."""
    _ = allow_arrows  # Backward-compatible argument; arrows are canonical in v0.1.
    if motif:
        illustration = ILLUSTRATION_CLAUSE.format(motif=motif, placement=placement)
    else:
        illustration = BARE_CLAUSE
    return PLATE_PROMPT.format(
        shape_prompt=shape.prompt,
        fill=combo["fill"],
        clean_band=clean_band,
        illustration_clause=illustration,
        negative=NEGATIVE,
    )


def build_illustration_prompt(*, motif: str, allow_arrows: bool = True) -> str:
    """Prompt for a textless illustration sticker (roses, cats, khinkali…)."""
    _ = allow_arrows  # Backward-compatible argument; no canonical blanket arrow ban.
    return ILLUSTRATION_PROMPT.format(
        motif=motif,
        negative=NEGATIVE,
    )
