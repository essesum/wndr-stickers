"""Стилевой контракт WNDR.

Палитра снята с готовых стикеров, а не назначена на глаз. Формы — банк заготовок
из эталонного листа. Промпты просят у модели ТОЛЬКО плашку и образ, без единой
буквы: кириллицу впечатывает код (typeset.py), поэтому брака в тексте не бывает.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

# --- Палитра -----------------------------------------------------------------
ACCENT = (0xCC, 0x3D, 0x11)      # фирменный оранжево-красный
BLACK = (0x0D, 0x0D, 0x0D)       # чёрный
CREAM = (0xF2, 0xE2, 0xC8)       # тёплый молочно-кремовый
NEAR_WHITE = (0xF7, 0xF3, 0xEA)  # обводка / светлые плашки

PALETTE = {"accent": ACCENT, "black": BLACK, "cream": CREAM, "near_white": NEAR_WHITE}

# Цвета, которыми допустимо набирать текст.
TEXT_COLORS = (ACCENT, BLACK, CREAM, NEAR_WHITE)


def hexstr(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# --- Банк форм ---------------------------------------------------------------
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
        "a soft wavy speech blob with organic undulating edge",
        "мягкий, разговорный",
    ),
    Shape("starburst", "a starburst explosion plate with sharp rays", "громкий, восклицание"),
    Shape("lightning", "a lightning-bolt banner, cut parallelogram", "дерзкий, панч"),
    Shape(
        "oval", "a decorative oval with a small botanical sprig", "торжественный, ироничный"
    ),
    Shape("stamp", "a rectangle with a zigzag postage-stamp edge", "документальный, билет"),
    Shape("cloud", "a rounded cloud plate with gentle bumps", "тёплый, обнимающий"),
    Shape("arrow", "an arrow / pointer badge", "вводит продолжение", is_arrow=True),
)


def pick_shape(allow_arrows: bool = False, rng: random.Random | None = None) -> Shape:
    rng = rng or random.Random()
    pool = [s for s in SHAPES if allow_arrows or not s.is_arrow]
    return rng.choice(pool)


def shape_by_key(key: str) -> Shape | None:
    return next((s for s in SHAPES if s.key == key), None)


# --- Цветовые сочетания ------------------------------------------------------
# Ровно два цвета на плашку. Третий появляется только как акцент на 1-3 словах.
COMBOS = (
    {"key": "black-plate", "fill": "near-black #0D0D0D", "text": "cream #F2E2C8"},
    {"key": "accent-plate", "fill": "burnt orange #CC3D11", "text": "cream #F2E2C8"},
    {"key": "cream-plate", "fill": "cream #F2E2C8", "text": "near-black #0D0D0D"},
)


def pick_combo(rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    return rng.choice(list(COMBOS))


# --- Запреты -----------------------------------------------------------------
NEGATIVE = (
    "NO text, NO letters, NO typography, NO numbers, NO watermark, NO signature. "
    "No gradients, no 3D, no gloss, no drop shadows, no photorealism. "
    "No hohloma, no zhar-ptitsa, no ornate Russian folk framing, no architectural arches. "
    "No more than three colours. No tiny cluttered detail."
)

ARROW_BAN = " No arrows of any kind — neither straight, decorative, nor disguised as rays."


# --- Промпты -----------------------------------------------------------------
PLATE_PROMPT = """\
Using the attached WNDR sheet as a STRICT style reference, draw ONE single die-cut \
sticker plate, centred, on a plain solid pure-black background.

Shape: {shape_prompt}.
Plate fill: {fill}. A thick warm cream-white die-cut outline runs around the whole \
outer contour, with a thin black inner keyline.
Palette strictly and only: burnt orange #CC3D11, near-black #0D0D0D, cream #F2E2C8, \
off-white #F7F3EA.
Light silkscreen / old-print texture is welcome but must stay subtle.

CRITICAL — the interior of the plate must be a FLAT EMPTY area of solid {fill}, \
completely clean and uninterrupted across the middle {clean_band} of the plate. \
Typography will be added later by software, so any mark inside that area ruins it.

{illustration_clause}

The black background must touch all four corners of the canvas and must be clearly \
separated from any black inside the design by the cream outline — this is required \
for automatic cut-out.

{negative}{arrow_ban}
"""

ILLUSTRATION_CLAUSE = """\
Add ONE very simple, almost iconic illustrative element ({motif}) tucked into the \
{placement} edge of the plate only, drawn in heavy flat linework. It must not enter \
the clean central area. Plus 2-3 smooth organic aura-like waves hugging the centre, \
suggesting warmth and safety, drawn thin enough never to compete with the empty middle.\
"""

BARE_CLAUSE = """\
Keep the plate bare apart from the outline and, at most, one tiny star or a short \
underline touching the very edge of the plate.\
"""

ILLUSTRATION_PROMPT = """\
Using the attached WNDR sheet as a STRICT style reference, draw ONE die-cut \
illustration sticker of {motif}, centred, on a plain solid pure-black background.

Vintage botanical/engraving illustration style with heavy black linework and flat \
colour fills. A thick cream-white die-cut outline runs around the whole outer contour.
Palette strictly and only: burnt orange #CC3D11, near-black #0D0D0D, cream #F2E2C8, \
off-white #F7F3EA.

The black background must touch all four corners of the canvas and must be clearly \
separated from any black inside the design by the cream outline.

{negative}{arrow_ban}
"""


def build_plate_prompt(
    *,
    shape: Shape,
    combo: dict,
    motif: str | None = None,
    placement: str = "bottom",
    clean_band: str = "60%",
    allow_arrows: bool = False,
) -> str:
    """Промпт на плашку без единой буквы — текст впечатает код."""
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
        arrow_ban="" if allow_arrows else ARROW_BAN,
    )


def build_illustration_prompt(*, motif: str, allow_arrows: bool = False) -> str:
    """Промпт на чисто иллюстративный стикер без текста (розы, коты, хинкали…)."""
    return ILLUSTRATION_PROMPT.format(
        motif=motif,
        negative=NEGATIVE,
        arrow_ban="" if allow_arrows else ARROW_BAN,
    )
