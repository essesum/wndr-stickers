"""Canonical WNDR style contract.

The source of truth is the two approved reference sheets in assets/reference/
(решение Кати, 2026-08-13): wndr-ref-flat.png — плоская стикер-графика для
classic-режима, wndr-ref-retro.png — ретро-шелкография для expressive и
иллюстраций. docs/reference/WNDR-Sticker-Agent-v0.1.pdf остаётся историей v0.1.
The image model draws only empty plates/illustrations on black; all sticker
text is added later by code.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

# --- Palette -----------------------------------------------------------------
ACCENT = (0xCC, 0x3D, 0x11)      # #CC3D11, accent / selected words / rays
BLACK = (0x0D, 0x0D, 0x0D)       # #0D0D0D, fill or text on light plates
CREAM = (0xF2, 0xE2, 0xC8)       # #F2E2C8, fill or text on dark plates
NEAR_WHITE = (0xF7, 0xF3, 0xEA)  # #F7F3EA, outer die-cut outline

PALETTE = {"accent": ACCENT, "black": BLACK, "cream": CREAM, "near_white": NEAR_WHITE}

# --- Оттенки v0.2 (решение Кати, 2026-08-12) ---------------------------------
# Базовая тройка остаётся канонической основой, но на одной тройке пак выходил
# зажатым. Каждый базовый цвет получил по родственному тону; оттенки выпадают
# заметно реже базы (веса в COMBOS), иначе основа перестала бы читаться.
RUST = (0x99, 0x2D, 0x0E)        # #992D0E, тёмно-ржавый — тень рыжего
TERRACOTTA = (0xE0, 0x76, 0x4A)  # #E0764A, светлая терракота — свет рыжего
SAND = (0xD9, 0xBE, 0x93)        # #D9BE93, тёплый песочный — тень бежевого

SHADES = {"rust": RUST, "terracotta": TERRACOTTA, "sand": SAND}

#: Всё, что приёмка считает «своим» цветом, включая оттенки.
FULL_PALETTE = (ACCENT, BLACK, CREAM, NEAR_WHITE, RUST, TERRACOTTA, SAND)

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


#: Формы ретро-листа (wndr-ref-retro.png): органичные кляксы, волнистые рамки,
#: колючие вспышки, гравюрные веточки. Простые примитивы («скруглённый
#: прямоугольник») давали пустые пресные стикеры, потому что модель честно
#: рисовала ровно то, что просили.
SHAPES: tuple[Shape, ...] = (
    Shape(
        "rounded-rect",
        "a rounded rectangle plate with a doubled contrasting keyline frame, like "
        "a vintage product label",
        "нейтральный, много текста",
    ),
    Shape(
        "blob",
        "an organic rounded blob plate with a smooth irregular gently-wavy contour, "
        "like a splash of thick paint",
        "мягкий, живой",
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
        "spiky-burst",
        "a loud starburst / splash badge with many irregular sharp triangular "
        "spikes around the whole contour",
        "громкий, восклицание",
    ),
    Shape(
        "scallop-frame",
        "a rectangle plate with a softly scalloped wavy border and a dashed "
        "keyline echoing the contour just inside the edge",
        "открытка, аккуратный",
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
        "a road-sign arrow / pointer badge with a doubled keyline and small star "
        "accents at the tail",
        "вводит продолжение",
        is_arrow=True,
    ),
)


#: Плоский банк для classic-режима — формы с flat-листа (wndr-ref-flat.png):
#: билет с перфорацией, облачко со строчкой-пунктиром, speech bubble, зигзаг.
#: Плашка простая и гладкая, но с характером; никакой гравюры и винтажа.
CLEAN_SHAPES: tuple[Shape, ...] = (
    Shape(
        "clean-rect",
        "a plain flat rounded rectangle plate with crisp edges and nothing else",
        "нейтральный, много текста",
    ),
    Shape(
        "clean-oval",
        "a plain flat horizontal oval plate with crisp edges and nothing else",
        "спокойный, вывеска",
    ),
    Shape(
        "clean-ticket",
        "a flat horizontal ticket / coupon plate with rounded corners, "
        "semicircular notches punched into the sides and one vertical dashed "
        "perforation line near an end",
        "документальный, билет",
    ),
    Shape(
        "clean-bubble",
        "a flat rounded speech-bubble plate with a short pointed tail at a "
        "bottom corner",
        "реплика, разговорный",
    ),
    Shape(
        "clean-cloud",
        "a flat scalloped cloud badge with soft rounded bumps around the "
        "contour and a dashed stitch line just inside the edge",
        "мягкий, игривый",
    ),
    Shape(
        "clean-burst",
        "a flat badge with a jagged zigzag starburst contour of short "
        "triangular points all around",
        "громкий, восклицание",
    ),
    Shape(
        "clean-arrow",
        "a plain flat arrow / pointer badge with crisp edges and nothing else",
        "вводит продолжение",
        is_arrow=True,
    ),
)

ALL_SHAPES: tuple[Shape, ...] = SHAPES + CLEAN_SHAPES


def shape_bank(look: str) -> tuple[Shape, ...]:
    return CLEAN_SHAPES if look == "clean" else SHAPES


def pick_shape(
    allow_arrows: bool = True,
    rng: random.Random | None = None,
    *,
    bank: tuple[Shape, ...] | None = None,
) -> Shape:
    rng = rng or random.Random()
    pool = [s for s in (bank or SHAPES) if allow_arrows or not s.is_arrow]
    return rng.choice(pool)


def shape_by_key(key: str) -> Shape | None:
    return next((s for s in ALL_SHAPES if s.key == key), None)


# --- Ornament density --------------------------------------------------------
# Референс WNDR неоднороден: билет и «было!» почти голые, венок из роз и солнце
# с луной — богатые. Если всегда рисовать нарядно, получается своя монотонность,
# просто с другой стороны. Плотность выбирается на каждый стикер отдельно.
@dataclass(frozen=True)
class Density:
    key: str
    clause: str
    weight: int


DENSITIES: tuple[Density, ...] = (
    Density(
        "plain",
        "Keep the plate COMPLETELY PLAIN: only the flat single-colour fill, the "
        "cream die-cut outline and one thin inner keyline. No ornament "
        "whatsoever — no marks, no stars, no rays, no sprigs, no corner "
        "decorations, no patterns. Pure minimal signage; the emptiness is the "
        "design.",
        1,
    ),
    Density(
        "spark",
        "Decorate with exactly one or two flat four-point sparkle stars in a "
        "contrasting palette colour, tucked near the edge of the plate away "
        "from the centre, and optionally a few short flat emphasis dashes "
        "radiating from the contour. Nothing else: no texture, no engraving, "
        "no botanical ornament.",
        3,
    ),
    Density(
        "bare",
        "Keep the plate almost bare: the die-cut outline, one thin inner keyline, "
        "and at most a single small mark (a star, a short ray, a tiny sprig) "
        "touching the very edge. Let the empty plate do the work.",
        3,
    ),
    Density(
        "framed",
        "Decorate the FRAME moderately: layered keylines following the contour and "
        "a restrained repeating edge motif or small accents in the corners. "
        "Nothing enters the clean central area.",
        4,
    ),
    Density(
        "ornate",
        "Decorate the FRAME generously in engraved vintage-label fashion: layered "
        "keylines, and ornament worked all around the border — stars and sparkles, "
        "rays, botanical sprigs, a repeating edge pattern. Rich border, calm centre. "
        "The ornament must never enter the clean central area.",
        3,
    ),
)


def pick_density(
    rng: random.Random | None = None, *, keys: tuple[str, ...] | None = None
) -> Density:
    rng = rng or random.Random()
    pool = [d for d in DENSITIES if keys is None or d.key in keys]
    weights = [d.weight for d in pool]
    # Веса играют только внутри пула режима: classic делит spark/plain 3:1
    # (на flat-листе искры почти на каждом стикере), expressive гоняет свои.
    if not any(weights):
        weights = [1] * len(pool)
    return rng.choices(pool, weights=weights, k=1)[0]


def density_by_key(key: str) -> Density | None:
    return next((d for d in DENSITIES if d.key == key), None)


# --- Motif bank --------------------------------------------------------------
# Картинка внутри стикера. Механизм в коде был с самого начала, но pipeline
# всегда передавал motif=None, поэтому ни один стикер его не получил.
#: Никакой мистики (луны, солнца с лицами, глаза) — решение Кати 2026-08-13:
#: в рефах её нет, а модель от неё скатывалась в таро-эстетику.
MOTIFS: tuple[str, ...] = (
    "a pair of engraved roses with leaves",
    "a sprig of wheat",
    "a lightning bolt",
    "an engraved flame",
    "a leafy laurel branch",
    "a blooming daisy seen from above",
    "a feijoa fruit with leaves",
    "a khinkali dumpling",
    "a small jug of fruit punch",
    "a curled sleeping cat",
)

#: Насколько часто внутри стикера появляется картинка. Не всегда: в референсе
#: иллюстрированных примерно каждый третий, остальные держатся на типографике.
MOTIF_CHANCE = 0.45


def pick_motif(
    rng: random.Random | None = None, *, chance: float = MOTIF_CHANCE
) -> str | None:
    rng = rng or random.Random()
    if rng.random() >= chance:
        return None
    return rng.choice(list(MOTIFS))


def pick_placement(rng: random.Random | None = None) -> str:
    """Куда прижать мотив. Всегда «bottom» — своя монотонность, как с плотностью."""
    rng = rng or random.Random()
    return rng.choice(("top", "bottom"))


# --- Розы без чёрного --------------------------------------------------------
# Правило Кати (2026-08-12): если в дизайне есть розы, чёрный не используется
# нигде — ни в заливке, ни в линовке, ни в тексте. Тёмную работу берёт на себя
# ржавый #992D0E. Чёрный фон холста не считается: это технический слой, который
# срезается при вырубке. Правило срабатывает и на мотив с розами, и на
# wreath-форму (в её рамке гравированные розы), и на «без текста розы».
_ROSE_RE = re.compile(
    r"\broses?\b|\bроз(?:а|ы|е|у|ой|ам|ах|ами|очк\w*)?\b",
    re.IGNORECASE,
)


def mentions_roses(*texts: str | None) -> bool:
    """Есть ли розы в любом из текстов (промпт формы, мотив, фраза)."""
    return any(_ROSE_RE.search(t) for t in texts if t)


ROSE_NO_BLACK_CLAUSE = """\
This design features roses, so near-black #0D0D0D is FORBIDDEN anywhere inside \
the sticker: no black fills, no black linework, no black ornament. Draw every \
dark tone and all engraved linework in deep rust #992D0E instead. Only the \
technical pure-black canvas background outside the sticker stays black.\
"""


# --- Colour pairings ---------------------------------------------------------
# Exactly two base colours per plate. A third colour appears only as the later
# code-rendered accent on 1-3 words.
COMBOS = (
    {"key": "black-plate", "fill": "near-black #0D0D0D", "text": "cream #F2E2C8", "weight": 3},
    {"key": "accent-plate", "fill": "burnt orange #CC3D11", "text": "cream #F2E2C8", "weight": 3},
    {"key": "cream-plate", "fill": "cream #F2E2C8", "text": "near-black #0D0D0D", "weight": 3},
    {"key": "rust-plate", "fill": "deep rust #992D0E", "text": "cream #F2E2C8", "weight": 1},
    {
        "key": "terracotta-plate",
        "fill": "soft terracotta #E0764A",
        "text": "near-black #0D0D0D",
        "weight": 1,
    },
    {
        "key": "sand-plate",
        "fill": "warm sand #D9BE93",
        "text": "near-black #0D0D0D",
        "weight": 1,
    },
)


def pick_combo(
    rng: random.Random | None = None,
    *,
    keys: tuple[str, ...] | None = None,
    no_black: bool = False,
) -> dict:
    rng = rng or random.Random()
    pool = [c for c in COMBOS if keys is None or c["key"] in keys]
    if no_black:
        # Розы: чёрной заливке не бывать. Текстовый цвет здесь не фильтруем —
        # его выбирает typeset и при no_black сам заменяет чёрный на ржавый.
        pool = [c for c in pool if "#0D0D0D" not in c["fill"]]
    return rng.choices(pool, weights=[c["weight"] for c in pool], k=1)[0]


# --- Style modes -------------------------------------------------------------
# Два характера пака (решение Кати, 2026-08-12): «classic» — сдержанный первый
# стиль (базовая тройка, спокойная плашка, ровный центр без автоакцента),
# «expressive» — нарядный v0.2 с оттенками, мотивами-картинками и
# типографическими вольностями. Чередуются случайно: пак не скатывается
# ни в монотонную строгость, ни в сплошной карнавал, и нажимать хочется ещё.
@dataclass(frozen=True)
class Mode:
    key: str
    combo_keys: tuple[str, ...] | None  # None — все COMBOS со своими весами
    density_keys: tuple[str, ...] | None  # None — все DENSITIES
    motif_chance: float
    typographic_spread: bool  # автоакцент и росчерк
    weight: int
    look: str  # ключ LOOKS и выбор банка форм (shape_bank)


MODES: tuple[Mode, ...] = (
    # Плоский стиль flat-листа: гладкие формы с характером, звёздочки-искры,
    # базовая тройка, ни мотивов-гравюр, автоакцент оставляем типографике.
    # Контраст с expressive должен быть виден с одного взгляда — поэтому
    # веса поровну, чтобы чередование ощущалось.
    Mode(
        "classic",
        combo_keys=("black-plate", "accent-plate", "cream-plate"),
        density_keys=("spark", "plain"),
        motif_chance=0.0,
        typographic_spread=True,
        weight=1,
        look="clean",
    ),
    Mode(
        "expressive",
        combo_keys=None,
        density_keys=("bare", "framed", "ornate"),
        motif_chance=MOTIF_CHANCE,
        typographic_spread=True,
        weight=1,
        look="ornate",
    ),
)


def pick_mode(rng: random.Random | None = None) -> Mode:
    rng = rng or random.Random()
    return rng.choices(list(MODES), weights=[m.weight for m in MODES], k=1)[0]


def mode_by_key(key: str) -> Mode | None:
    return next((m for m in MODES if m.key == key), None)


# --- Bans --------------------------------------------------------------------
#: «No tiny cluttered detail» отсюда убрано намеренно: модель понимала это как
#: запрет на орнамент вообще и выдавала пустые плашки. Богатая рамка — это и
#: есть стиль пака, ограничивать надо середину, а не контур.
NEGATIVE = (
    "NO text, NO letters, NO typography, NO numbers, NO captions, "
    "NO watermark, NO signature. "
    "No gradients, no 3D, no gloss, no drop shadows, no photorealism/photo. "
    "No blur, no soft focus, no glow, no airbrush, no smudges or fog anywhere. "
    "No moons, no sun faces, no celestial, mystical, tarot or zodiac imagery. "
    "No colours outside the approved WNDR palette and its listed shades; at most "
    "four palette colours in one design, not counting the cream die-cut outline. "
    "No non-black background outside the sticker."
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
#F2E2C8, with supporting shades — deep rust #992D0E, soft terracotta #E0764A, \
warm sand #D9BE93 — used sparingly, plus the off-white die-cut outline #F7F3EA. \
The design colours may appear together in the frame and ornament; the flat \
central fill stays a single colour.
{look}

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

#: Как выглядит плашка целиком: нарядная этикетка (expressive) или голая
#: вывеска (classic). Раньше «ornate vintage label» был зашит в PLATE_PROMPT
#: намертво — из-за этого даже сдержанный режим выходил с рюшками.
LOOKS = {
    "ornate": (
        "Retro 1960s-70s silkscreen print label, exactly like the attached "
        "reference sheet: slightly muted inks, a hint of paper grain and worn "
        "print texture, engraved vintage ornament — botanical sprigs, laurel "
        "branches, four-point sparkle stars, short radiating dashes. Rich "
        "vintage frame, calm centre."
    ),
    "clean": (
        "Completely FLAT modern die-cut sticker graphic, exactly like the "
        "attached reference sheet: smooth bold vector shapes, perfectly even "
        "solid fills, crisp clean edges. Absolutely no texture, no grain, no "
        "engraving, no vintage wear — pure flat colour, confident and graphic."
    ),
}


ILLUSTRATION_CLAUSE = """\
Add ONE very simple, almost iconic illustrative element ({motif}) tucked into the \
{placement} edge of the plate only. Draw it as a vintage engraving / botanical \
illustration with heavy {linework} linework and flat fills. It must not enter the \
clean central area.\
"""

#: Оставлено для совместимости: раньше это был единственный вариант оформления и
#: он требовал пустой плашки. Теперь оформление выбирается из DENSITIES.
BARE_CLAUSE = next(d for d in DENSITIES if d.key == "bare").clause

ILLUSTRATION_PROMPT = """\
Using the attached WNDR sheet as a STRICT style reference, draw ONE die-cut \
illustration sticker of {motif}, centred, on a plain solid pure-black background.

Vintage botanical/engraving illustration style with heavy {linework} linework and \
flat colour fills. A thick warm cream-white die-cut outline (#F7F3EA) runs around the \
whole outer contour and should read as 8-12 px at 512 px.
Palette strictly and only: burnt orange #CC3D11, near-black #0D0D0D, cream \
#F2E2C8, off-white #F7F3EA, with supporting shades deep rust #992D0E, soft \
terracotta #E0764A and warm sand #D9BE93 used sparingly.

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
    density: Density | None = None,
    look: str = "ornate",
) -> str:
    """Prompt for an empty plate — user phrase is rendered later by code.

    Мотив и плотность независимы: картинка может лежать и на почти голой плашке,
    и внутри богатой рамки. Это и даёт разброс, ради которого всё затевалось.
    """
    _ = allow_arrows  # Backward-compatible argument; arrows are canonical in v0.1.
    roses = mentions_roses(shape.prompt, motif)
    linework = "deep rust #992D0E" if roses else "black"
    parts = [density.clause if density else BARE_CLAUSE]
    if motif:
        parts.append(
            ILLUSTRATION_CLAUSE.format(motif=motif, placement=placement, linework=linework)
        )
    if roses:
        parts.append(ROSE_NO_BLACK_CLAUSE)
    illustration = "\n\n".join(parts)
    return PLATE_PROMPT.format(
        shape_prompt=shape.prompt,
        fill=combo["fill"],
        clean_band=clean_band,
        illustration_clause=illustration,
        negative=NEGATIVE,
        look=LOOKS[look],
    )


def build_illustration_prompt(*, motif: str, allow_arrows: bool = True) -> str:
    """Prompt for a textless illustration sticker (roses, cats, khinkali…)."""
    _ = allow_arrows  # Backward-compatible argument; no canonical blanket arrow ban.
    roses = mentions_roses(motif)
    prompt = ILLUSTRATION_PROMPT.format(
        motif=motif,
        negative=NEGATIVE,
        linework="deep rust #992D0E" if roses else "black",
    )
    if roses:
        prompt += "\n" + ROSE_NO_BLACK_CLAUSE
    return prompt
