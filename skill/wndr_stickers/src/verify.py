"""Техническая приёмка финального файла — до того, как он уедет в пак."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

MAX_BYTES = 512 * 1024
REQUIRED_SIZE = (512, 512)


@dataclass
class VerifyResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    size: tuple[int, int] | None = None
    bytes: int | None = None

    def __bool__(self) -> bool:
        return self.ok


def verify_sticker(path: Path, *, max_bytes: int = MAX_BYTES) -> VerifyResult:
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
    opaque = [name for name, value in corners.items() if value != 0]
    if opaque:
        problems.append("углы не прозрачны: " + ", ".join(opaque))

    bbox = alpha.getbbox()
    if bbox is None:
        problems.append("стикер пустой")
    elif bbox[0] == 0 or bbox[1] == 0 or bbox[2] == w or bbox[3] == h:
        problems.append("стикер касается краёв холста")

    return VerifyResult(ok=not problems, problems=problems, size=dims, bytes=size_bytes)


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
