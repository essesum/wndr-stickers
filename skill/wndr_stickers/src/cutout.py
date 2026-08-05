"""Вырезание фона и подготовка холста Telegram.

Модель рисует на сплошном чёрном. Нельзя просто сделать чёрный прозрачным —
чёрный используется внутри дизайна. Убираем только ту чёрную область, которая
связана с краями холста, заливкой от границы.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image

#: Пиксель считается фоном, если максимальный канал RGB не выше порога.
BACKGROUND_MAX_CHANNEL = 42

#: Telegram: холст ровно 512×512, стикер вписан в 472 — остаётся ~20px поля.
CANVAS_SIZE = 512
CONTENT_SIZE = 472


def remove_connected_background(
    image: Image.Image, threshold: int = BACKGROUND_MAX_CHANNEL
) -> Image.Image:
    """Прозрачным делаем только чёрное, связанное с краями холста."""
    rgba = image.convert("RGBA")
    px = rgba.load()
    width, height = rgba.size
    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        idx = y * width + x
        if not seen[idx]:
            seen[idx] = 1
            queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        r, g, b, _ = px[x, y]
        if max(r, g, b) > threshold:
            continue
        px[x, y] = (r, g, b, 0)
        if x:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)
    return rgba


def trim_to_content(image: Image.Image) -> Image.Image:
    """Обрезаем пустые поля по альфа-каналу."""
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        raise ValueError("No visible sticker content")
    return image.crop(bbox)


def telegram_canvas(
    image: Image.Image, canvas: int = CANVAS_SIZE, content: int = CONTENT_SIZE
) -> Image.Image:
    """Вписываем в content×content с сохранением пропорций, центрируем на canvas×canvas."""
    cropped = trim_to_content(image)
    scale = min(content / cropped.width, content / cropped.height)
    size = (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale)))
    cropped = cropped.resize(size, Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.alpha_composite(cropped, ((canvas - size[0]) // 2, (canvas - size[1]) // 2))
    return out


def save_webp(image: Image.Image, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "WEBP", lossless=True, method=6)
    return destination


def cut_out(source: Path | Image.Image) -> Image.Image:
    """PNG на чёрном -> обрезанный RGBA в исходном разрешении (текст ещё не впечатан)."""
    image = Image.open(source) if isinstance(source, Path) else source
    return trim_to_content(remove_connected_background(image))
