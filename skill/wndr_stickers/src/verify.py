"""Техническая приёмка финального файла — до того, как он уедет в пак."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

from .style import ACCENT, BLACK, CREAM, NEAR_WHITE

MAX_BYTES = 512 * 1024
REQUIRED_SIZE = (512, 512)


def _palette_distance(pixels: np.ndarray) -> np.ndarray:
    """Насколько далеко пиксели от палитры WNDR.

    Считаем расстояние не до самих цветов, а до отрезков между ними. Пиксель на
    границе оранжевого и кремового — это сглаживание контура, а не чужой цвет:
    учитывать его как нарушение значит штрафовать за густоту орнамента. Именно
    так и было: чем наряднее плашка, тем больше у неё краёв и тем вернее она
    проваливала приёмку, хотя палитру никто не нарушал.
    """
    palette = np.array([ACCENT, BLACK, CREAM, NEAR_WHITE], dtype=np.float64)
    points = pixels.astype(np.float64)

    best = np.linalg.norm(points[:, None, :] - palette[None, :, :], axis=2).min(axis=1)
    for first, second in combinations(range(len(palette)), 2):
        a, b = palette[first], palette[second]
        segment = b - a
        length_sq = float(segment @ segment)
        if length_sq == 0:
            continue
        t = np.clip(((points - a) @ segment) / length_sq, 0.0, 1.0)
        projected = a + t[:, None] * segment
        best = np.minimum(best, np.linalg.norm(points - projected, axis=1))
    return best


@dataclass
class VerifyResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    size: tuple[int, int] | None = None
    bytes: int | None = None
    palette_fraction: float | None = None

    def __bool__(self) -> bool:
        return self.ok


def verify_sticker(
    path: Path,
    *,
    max_bytes: int = MAX_BYTES,
    enforce_style: bool = False,
    palette_tolerance: int = 48,
    min_palette_fraction: float = 0.85,
) -> VerifyResult:
    problems: list[str] = []
    if not path.exists():
        return VerifyResult(ok=False, problems=[f"файла нет: {path}"])

    size_bytes = path.stat().st_size
    with Image.open(path) as im:
        fmt = im.format
        image = im.convert("RGBA")
        dims = image.size

    if fmt != "WEBP":
        problems.append(f"формат {fmt}, ожидался WEBP")
    if dims != REQUIRED_SIZE:
        problems.append(f"размер {dims[0]}×{dims[1]}, ожидался 512×512")
    if size_bytes > max_bytes:
        problems.append(f"вес {size_bytes} B больше {max_bytes} B")

    alpha = image.getchannel("A")
    w, h = alpha.size
    corners = {
        "левый верхний": alpha.getpixel((0, 0)),
        "правый верхний": alpha.getpixel((w - 1, 0)),
        "левый нижний": alpha.getpixel((0, h - 1)),
        "правый нижний": alpha.getpixel((w - 1, h - 1)),
    }
    opaque_corners = [name for name, value in corners.items() if value != 0]
    if opaque_corners:
        problems.append("углы не прозрачны: " + ", ".join(opaque_corners))

    bbox = alpha.getbbox()
    if bbox is None:
        problems.append("стикер пустой")
    elif bbox[0] == 0 or bbox[1] == 0 or bbox[2] == w or bbox[3] == h:
        problems.append("стикер касается краёв холста")

    palette_fraction = None
    if enforce_style:
        rgba = np.asarray(image, dtype=np.uint8)
        opaque_pixels = rgba[rgba[:, :, 3] > 16][:, :3]
        if len(opaque_pixels):
            distance = _palette_distance(opaque_pixels)
            palette_fraction = float((distance <= palette_tolerance).mean())
            if palette_fraction < min_palette_fraction:
                problems.append(
                    "палитра вне WNDR-контракта: "
                    f"{palette_fraction:.1%} канонических пикселей, "
                    f"нужно минимум {min_palette_fraction:.0%}"
                )

    return VerifyResult(
        ok=not problems,
        problems=problems,
        size=dims,
        bytes=size_bytes,
        palette_fraction=palette_fraction,
    )


def verify_text(rendered_phrase: str, requested_phrase: str) -> VerifyResult:
    """Посимвольная сверка. При впечатывании кодом расхождение означает баг у нас."""
    problems: list[str] = []
    if rendered_phrase != requested_phrase:
        problems.append(
            f"текст разошёлся: набрано {rendered_phrase!r}, просили {requested_phrase!r}"
        )
        for i, (a, b) in enumerate(zip(rendered_phrase, requested_phrase, strict=False)):
            if a != b:
                problems.append(f"первое расхождение на позиции {i}: {a!r} вместо {b!r}")
                break
    return VerifyResult(ok=not problems, problems=problems)
