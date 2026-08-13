"""Разбор сгенерированной плашки: куда безопасно ставить текст.

Модель рисует плашку с пустой серединой. Нам нужно найти внутри неё максимальный
прямоугольник, который (а) целиком лежит внутри стикера, (б) отстоит от кремового
канта, (в) попадает в РОВНУЮ заливку, а не в иллюстрацию или обводку.

Ровность считаем через локальную дисперсию яркости: там, где модель нарисовала
образ или кант, дисперсия высокая; на чистой заливке — near zero.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def area(self) -> int:
        return self.width * self.height

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


def _box_count(mask: np.ndarray, r: int) -> np.ndarray:
    """Количество True в окне (2r+1)² вокруг каждого пикселя. За границей — False."""
    h, w = mask.shape
    k = 2 * r + 1
    pad = np.zeros((h + 2 * r, w + 2 * r), dtype=np.int64)
    pad[r : r + h, r : r + w] = mask
    ii = pad.cumsum(0).cumsum(1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    return ii[k : k + h, k : k + w] - ii[0:h, k : k + w] - ii[k : k + h, 0:w] + ii[0:h, 0:w]


def _box_sum(values: np.ndarray, r: int) -> np.ndarray:
    """Сумма значений в окне (2r+1)². За границей — нули."""
    h, w = values.shape
    k = 2 * r + 1
    pad = np.zeros((h + 2 * r, w + 2 * r), dtype=np.float64)
    pad[r : r + h, r : r + w] = values
    ii = pad.cumsum(0).cumsum(1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    return ii[k : k + h, k : k + w] - ii[0:h, k : k + w] - ii[k : k + h, 0:w] + ii[0:h, 0:w]


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Точная box-эрозия: True только там, где всё окно внутри маски."""
    if radius <= 0:
        return mask.copy()
    k = 2 * radius + 1
    return _box_count(mask, radius) == k * k


def flatness(rgba: np.ndarray, radius: int) -> np.ndarray:
    """Локальная дисперсия яркости в окне. Чем ниже — тем ровнее заливка."""
    gray = rgba[:, :, :3].astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    k = (2 * radius + 1) ** 2
    mean = _box_sum(gray, radius) / k
    mean_sq = _box_sum(gray * gray, radius) / k
    return np.maximum(mean_sq - mean * mean, 0.0)


def largest_rectangle(ok: np.ndarray) -> Rect | None:
    """Наибольший вписанный прямоугольник из True. Классика: гистограмма + стек."""
    h, w = ok.shape
    if h == 0 or w == 0 or not ok.any():
        return None
    heights = [0] * w
    best_area = 0
    best: tuple[int, int, int, int] | None = None  # left, top, right, bottom
    for y in range(h):
        row = ok[y]
        for x in range(w):
            heights[x] = heights[x] + 1 if row[x] else 0
        stack: list[int] = []  # индексы строго возрастающих высот
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            while stack and heights[stack[-1]] > cur:
                height = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                area = height * (x - left)
                if area > best_area:
                    best_area = area
                    best = (left, y - height + 1, x, y + 1)
            stack.append(x)
    if best is None:
        return None
    return Rect(*best)


def _largest_rectangle_scaled(ok: np.ndarray, work_width: int = 320) -> Rect | None:
    """Ищем на уменьшенной сетке (min-pooling), результат масштабируем обратно."""
    h, w = ok.shape
    if w <= work_width:
        return largest_rectangle(ok)
    step = int(np.ceil(w / work_width))
    hh, ww = h // step, w // step
    if hh == 0 or ww == 0:
        return largest_rectangle(ok)
    # min-pooling: блок годится, только если ВСЕ его пиксели годятся
    pooled = ok[: hh * step, : ww * step].reshape(hh, step, ww, step).all(axis=(1, 3))
    rect = largest_rectangle(pooled)
    if rect is None:
        return None
    return Rect(rect.left * step, rect.top * step, rect.right * step, rect.bottom * step)


def safe_text_area(
    image: Image.Image,
    *,
    outline_fraction: float = 0.055,
    flat_window_fraction: float = 0.012,
    flat_tolerance: float = 90.0,
) -> Rect:
    """Наибольшая ровная область внутри плашки, пригодная под набор текста.

    outline_fraction — отступ от края стикера долей от меньшей стороны; должен
    покрывать толстый кремовый кант.
    """
    rgba = np.asarray(image.convert("RGBA"))
    alpha = rgba[:, :, 3] > 8
    short_side = min(rgba.shape[0], rgba.shape[1])

    inset = max(1, int(short_side * outline_fraction))
    inside = erode(alpha, inset)
    if not inside.any():
        # Плашка тоньше расчётного канта — отступаем настолько, насколько можем.
        for smaller in (inset // 2, inset // 4, 1):
            inside = erode(alpha, max(1, smaller))
            if inside.any():
                break

    flat_radius = max(1, int(short_side * flat_window_fraction))
    flat = flatness(rgba, flat_radius) <= flat_tolerance

    rect = _largest_rectangle_scaled(inside & flat)
    if rect is None or rect.area == 0:
        rect = _largest_rectangle_scaled(inside)
    if rect is None or rect.area == 0:
        h, w = alpha.shape
        pad = short_side // 4
        rect = Rect(pad, pad, w - pad, h - pad)
    return rect


def off_fill_fraction(
    image: Image.Image,
    rect: Rect,
    fill: tuple[int, int, int],
    *,
    tolerance: float = 60.0,
) -> float:
    """Доля пикселей области, заметно отличных от цвета заливки.

    Ловит брак вроде размытого светлого пятна посреди плашки: медиана ещё
    может совпасть с задуманной заливкой, но половина зоны текста — чужого
    цвета, и текст ляжет на кашу. На честной ровной заливке доля около нуля.
    """
    rgba = np.asarray(image.convert("RGBA"))
    patch = rgba[rect.top : rect.bottom, rect.left : rect.right]
    if patch.size == 0:
        return 1.0
    visible = patch[patch[:, :, 3] > 8]
    if visible.size == 0:
        return 1.0
    dist = np.linalg.norm(
        visible[:, :3].astype(np.float64) - np.asarray(fill, dtype=np.float64),
        axis=1,
    )
    return float((dist > tolerance).mean())


def dominant_color(image: Image.Image, rect: Rect) -> tuple[int, int, int]:
    """Медианный цвет заливки внутри области — по нему выбираем цвет текста."""
    rgba = np.asarray(image.convert("RGBA"))
    patch = rgba[rect.top : rect.bottom, rect.left : rect.right]
    if patch.size == 0:
        return (0, 0, 0)
    visible = patch[patch[:, :, 3] > 8]
    if visible.size == 0:
        return (0, 0, 0)
    med = np.median(visible[:, :3], axis=0)
    return (int(med[0]), int(med[1]), int(med[2]))
