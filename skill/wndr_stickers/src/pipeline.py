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

    shape = style.shape_by_key(shape_key) if shape_key else None
    if shape is None:
        shape = style.pick_shape(allow_arrows=settings.allow_arrow_shapes, rng=rng)
    combo = style.pick_combo(rng)

    prompt = style.build_plate_prompt(
        shape=shape,
        combo=combo,
        motif=motif,
        allow_arrows=settings.allow_arrow_shapes,
    )

    generated = imagegen.generate(prompt, settings.reference_sheet_path, settings)

    plain, _ = typeset.parse_accents(phrase)
    slug, version, filename = naming.allocate(plain, settings.stickers_dir)

    raw_path = generated.save(settings.raw_dir / f"{slug}-v{version}.png")

    sticker = cutout.cut_out(raw_path)
    area = plate.safe_text_area(sticker)
    background = plate.dominant_color(sticker, area)
    lettered, layout = typeset.typeset(
        sticker, phrase, area, str(settings.font_path), background
    )

    canvas = cutout.telegram_canvas(lettered)
    destination = cutout.save_webp(canvas, settings.stickers_dir / filename)

    checks = verify.verify_sticker(destination)
    log.info(
        "стикер %s готов за %.1fс (%s/%s, форма %s)%s",
        filename,
        time.monotonic() - started,
        generated.provider,
        generated.model,
        shape.key,
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
    )


def make_illustration(
    motif: str,
    settings: Settings,
    *,
    name: str | None = None,
) -> StickerResult:
    """Стикер без текста: розы, коты, хинкали, костёр."""
    started = time.monotonic()
    prompt = style.build_illustration_prompt(
        motif=motif, allow_arrows=settings.allow_arrow_shapes
    )
    generated = imagegen.generate(prompt, settings.reference_sheet_path, settings)

    slug, version, filename = naming.allocate(name or motif, settings.stickers_dir)
    raw_path = generated.save(settings.raw_dir / f"{slug}-v{version}.png")

    sticker = cutout.cut_out(raw_path)
    canvas = cutout.telegram_canvas(sticker)
    destination = cutout.save_webp(canvas, settings.stickers_dir / filename)

    return StickerResult(
        path=destination,
        slug=slug,
        version=version,
        phrase="",
        provider=generated.provider,
        model=generated.model,
        shape="illustration",
        raw_path=raw_path,
        font_size=0,
        lines=[],
        checks=verify.verify_sticker(destination),
        seconds=time.monotonic() - started,
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
    slug, version, filename = naming.allocate(plain, settings.stickers_dir)
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
        checks=verify.verify_sticker(destination),
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
