"""Полный путь: фраза -> плашка от модели -> впечатанный текст -> WebP для Telegram."""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import cutout, imagegen, naming, plate, style, typeset, verify
from .config import Settings

log = logging.getLogger(__name__)


class StickerVerificationError(RuntimeError):
    """Generated file failed the official WNDR contract and must not be delivered."""

    def __init__(self, checks: verify.VerifyResult):
        self.checks = checks
        super().__init__("; ".join(checks.problems) or "WNDR style verification failed")


def _verify_or_reject(path: Path, *, forbid_black: bool = False) -> verify.VerifyResult:
    checks = verify.verify_sticker(path, enforce_style=True, forbid_black=forbid_black)
    if not checks.ok:
        path.unlink(missing_ok=True)
        raise StickerVerificationError(checks)
    return checks


@dataclass
class StickerResult:
    path: Path
    slug: str
    version: int
    phrase: str
    provider: str
    model: str
    shape: str
    raw_path: Path
    font_size: int
    lines: list[str]
    checks: verify.VerifyResult
    seconds: float
    mode: str = ""

    @property
    def ok(self) -> bool:
        return self.checks.ok


def make_sticker(
    phrase: str,
    settings: Settings,
    *,
    shape_key: str | None = None,
    motif: str | None = None,
    rng: random.Random | None = None,
) -> StickerResult:
    """Один стикер. Текст ставит код, поэтому по буквам ошибиться нельзя."""
    started = time.monotonic()
    rng = rng or random.Random()

    # Режим стиля выбирается на каждый стикер: «classic» — сдержанный первый
    # стиль пака, «expressive» — нарядный v0.2 с оттенками и картинками.
    mode = style.pick_mode(rng)

    shape = style.shape_by_key(shape_key) if shape_key else None
    if shape is None:
        shape = style.pick_shape(
            allow_arrows=settings.allow_arrow_shapes,
            rng=rng,
            bank=style.shape_bank(mode.look),
        )
    # Плотность и мотив выбираются на каждый стикер. Без этого пак получался
    # одинаковым: сперва все плашки были голые, потом все — нарядные.
    density = style.pick_density(rng, keys=mode.density_keys)
    motif = motif or style.pick_motif(rng, chance=mode.motif_chance)
    # Правило «розы — без чёрного»: срабатывает и на мотив, и на wreath-форму.
    roses = style.mentions_roses(shape.prompt, motif)
    combo = style.pick_combo(rng, keys=mode.combo_keys, no_black=roses)

    prompt = style.build_plate_prompt(
        shape=shape,
        combo=combo,
        motif=motif,
        placement=style.pick_placement(rng),
        density=density,
        allow_arrows=settings.allow_arrow_shapes,
        look=mode.look,
    )

    generated = imagegen.generate(prompt, settings.reference_sheet_path, settings)

    plain, _ = typeset.parse_accents(phrase)
    slug, version, filename = naming.reserve(plain, settings.stickers_dir)

    raw_path = generated.save(settings.raw_dir / f"{slug}-v{version}.png")

    sticker = cutout.cut_out(raw_path)
    area = plate.safe_text_area(sticker)
    background = plate.dominant_color(sticker, area)
    lettered, layout = typeset.typeset(
        sticker,
        phrase,
        area,
        str(settings.font_path),
        background,
        # В classic-режиме rng не передаётся: типографика прежняя,
        # детерминированная — без автоакцента и росчерка.
        rng=rng if mode.typographic_spread else None,
        forbid_black=roses,
    )

    canvas = cutout.telegram_canvas(lettered)
    destination = cutout.save_webp(canvas, settings.stickers_dir / filename)

    checks = _verify_or_reject(destination, forbid_black=roses)
    log.info(
        "стикер %s готов за %.1fс (%s/%s, форма %s, режим %s)%s",
        filename,
        time.monotonic() - started,
        generated.provider,
        generated.model,
        shape.key,
        mode.key,
        "" if checks.ok else f"; замечания: {checks.problems}",
    )

    return StickerResult(
        path=destination,
        slug=slug,
        version=version,
        phrase=plain,
        provider=generated.provider,
        model=generated.model,
        shape=shape.key,
        raw_path=raw_path,
        font_size=layout.font_size,
        lines=[" ".join(w.text for w in line) for line in layout.lines],
        checks=checks,
        seconds=time.monotonic() - started,
        mode=mode.key,
    )


def make_illustration(
    motif: str,
    settings: Settings,
    *,
    name: str | None = None,
) -> StickerResult:
    """Стикер без текста: розы, коты, хинкали, костёр."""
    started = time.monotonic()
    roses = style.mentions_roses(motif)
    prompt = style.build_illustration_prompt(
        motif=motif, allow_arrows=settings.allow_arrow_shapes
    )
    generated = imagegen.generate(prompt, settings.reference_sheet_path, settings)

    slug, version, filename = naming.reserve(name or motif, settings.stickers_dir)
    raw_path = generated.save(settings.raw_dir / f"{slug}-v{version}.png")

    sticker = cutout.cut_out(raw_path)
    canvas = cutout.telegram_canvas(sticker)
    destination = cutout.save_webp(canvas, settings.stickers_dir / filename)

    return StickerResult(
        path=destination,
        slug=slug,
        version=version,
        # Ярлык, а не надпись: на самом стикере текста нет, но списку пака,
        # кнопке «ещё вариант» и проверке дублей нужно чем-то его называть.
        phrase=f"без текста {motif}",
        provider=generated.provider,
        model=generated.model,
        shape="illustration",
        raw_path=raw_path,
        font_size=0,
        lines=[],
        checks=_verify_or_reject(destination, forbid_black=roses),
        seconds=time.monotonic() - started,
        mode="illustration",
    )


def rebuild_from_raw(raw_path: Path, phrase: str, settings: Settings) -> StickerResult:
    """Переверстать текст на уже сгенерированной плашке — без повторного вызова модели."""
    started = time.monotonic()
    sticker = cutout.cut_out(raw_path)
    area = plate.safe_text_area(sticker)
    background = plate.dominant_color(sticker, area)
    lettered, layout = typeset.typeset(
        sticker, phrase, area, str(settings.font_path), background
    )
    plain, _ = typeset.parse_accents(phrase)
    slug, version, filename = naming.reserve(plain, settings.stickers_dir)
    destination = cutout.save_webp(
        cutout.telegram_canvas(lettered), settings.stickers_dir / filename
    )
    return StickerResult(
        path=destination,
        slug=slug,
        version=version,
        phrase=plain,
        provider="reuse",
        model="reuse",
        shape="reuse",
        raw_path=raw_path,
        font_size=layout.font_size,
        lines=[" ".join(w.text for w in line) for line in layout.lines],
        checks=_verify_or_reject(destination),
        seconds=time.monotonic() - started,
    )


def preview_layout(
    phrase: str, settings: Settings, box: tuple[int, int] = (900, 500)
) -> Image.Image:
    """Верстка без модели — чтобы быстро посмотреть разбивку строк и кегль."""
    canvas = Image.new("RGBA", box, (*style.BLACK, 255))
    area = plate.Rect(
        int(box[0] * 0.08), int(box[1] * 0.12), int(box[0] * 0.92), int(box[1] * 0.88)
    )
    rendered, _ = typeset.typeset(canvas, phrase, area, str(settings.font_path), style.BLACK)
    return rendered
