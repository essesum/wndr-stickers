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


SHAPES: tuple[Shape, ...] = (
    Shape("rounded-rect", "a rounded rectangle plate", "нейтральный, много текста"),
    Shape(
        "wavy-blob",
        "a wavy speech blob / organic blob plate",
        "мягкий, разговорный",
    ),
    Shape("starburst", "a starburst explosion plate with rays", "громкий, восклицание"),
    Shape("lightning", "a lightning-bolt banner / cut parallelogram", "дерзкий, панч"),
    Shape(
        "oval", "a decorative oval with a small botanical ornament", "торжественный, ироничный"
    ),
    Shape("arrow", "an arrow / pointer badge", "вводит продолжение", is_arrow=True),
    Shape("stamp", "a rectangle with a toothed postage-stamp edge", "документальный, билет"),
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
NEGATIVE = (
    "NO text, NO letters, NO typography, NO numbers, NO captions, "
    "NO watermark, NO signature. "
    "No gradients, no 3D, no gloss, no drop shadows, no photorealism/photo. "
    "No more than three colours. No non-black background. No tiny cluttered detail."
)


# --- Prompts -----------------------------------------------------------------
PLATE_PROMPT = """\
Using the attached WNDR sheet as a STRICT style reference, draw ONE single die-cut \
sticker plate, centred, on a plain solid pure-black background.

Shape: {shape_prompt}.
Plate fill: {fill}. A warm cream-white outer die-cut outline (#F7F3EA) runs around \
the whole contour and should read as 8-12 px at 512 px, optionally with a thin \
inner keyline.
Palette strictly and only: burnt orange #CC3D11, near-black #0D0D0D, cream \
#F2E2C8, off-white #F7F3EA. Use exactly two base colours on this plate; any \
third colour may appear only as tiny edge decoration, never as a full fill.
Flat retro 1970s signage / silkscreen look.

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

BARE_CLAUSE = """\
Keep the plate bare apart from the outline and, at most, one tiny star, ray, \
botanical mark, or short underline touching the very edge of the plate.\
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
