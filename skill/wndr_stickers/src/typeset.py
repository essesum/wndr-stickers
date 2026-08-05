"""Впечатывание кириллицы в плашку.

Модель букв не рисует вообще — их ставит код настоящим шрифтом. Поэтому «объем»
всегда с твёрдым знаком, «ё» не превращается в «е», а вопросительный знак
появляется ровно тогда, когда он есть в исходной фразе.

Акцентное слово помечается звёздочками: «Это не *тантра*».
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .plate import Rect
from .style import ACCENT, BLACK, CREAM

_ACCENT_RE = re.compile(r"\*([^*]+)\*")

MAX_LINES = 3
LINE_SPACING = 0.12  # доля от кегля


@dataclass(frozen=True)
class Word:
    text: str
    accent: bool


@dataclass(frozen=True)
class Layout:
    lines: list[list[Word]]
    font_size: int
    width: int
    height: int


def parse_accents(phrase: str) -> tuple[str, list[Word]]:
    """«Это не *тантра*» -> ('Это не тантра', [Word('Это'), Word('не'), Word('тантра', True)])."""
    words: list[Word] = []
    for raw in phrase.split():
        accent = bool(_ACCENT_RE.search(raw))
        clean = _ACCENT_RE.sub(r"\1", raw)
        if clean:
            words.append(Word(clean, accent))
    plain = " ".join(w.text for w in words)
    return plain, words


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _nearest_base_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    return min(
        (ACCENT, BLACK, CREAM),
        key=lambda c: sum((a - b) ** 2 for a, b in zip(c, background, strict=True)),
    )


def pick_text_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Canonical pairing from the official guide, not a generic contrast guess."""
    nearest = _nearest_base_color(background)
    return CREAM if nearest in (ACCENT, BLACK) else BLACK


def pick_accent_color(
    background: tuple[int, int, int], text_color: tuple[int, int, int]
) -> tuple[int, int, int]:
    """Orange accent on black/cream; black accent on an orange plate."""
    nearest = _nearest_base_color(background)
    accent = BLACK if nearest == ACCENT else ACCENT
    return accent if accent != text_color else (BLACK if text_color != BLACK else CREAM)


def _split_into_lines(words: list[Word], line_count: int) -> list[list[Word]]:
    """Балансируем строки по числу символов — жадно, но ровно."""
    if line_count <= 1 or len(words) <= 1:
        return [words]
    total = sum(len(w.text) for w in words) + len(words) - 1
    target = total / line_count
    lines: list[list[Word]] = []
    current: list[Word] = []
    current_len = 0
    for i, word in enumerate(words):
        remaining_words = len(words) - i
        remaining_lines = line_count - len(lines)
        must_break = remaining_words < remaining_lines
        candidate = current_len + (1 if current else 0) + len(word.text)
        if current and (must_break or candidate > target * 1.15) and len(lines) < line_count - 1:
            lines.append(current)
            current, current_len = [word], len(word.text)
        else:
            current.append(word)
            current_len = candidate
    if current:
        lines.append(current)
    return lines


def _cap_height(font: ImageFont.FreeTypeFont) -> float:
    """Высота прописной по чернилам, не по метрикам шрифта."""
    top = font.getbbox("Н", anchor="ls")[1]
    return abs(top)


def _measure(
    lines: list[list[Word]], font: ImageFont.FreeTypeFont, spacing: int
) -> tuple[int, int, list[int]]:
    """Габариты блока по чернилам: строки прижаты друг к другу, без воздуха метрик.

    Меряем от базовой линии (anchor="ls"), поэтому пустой запас сверху и снизу,
    который Impact носит в метриках, в расчёт не идёт и кегль выходит крупнее.
    """
    widths: list[int] = []
    tops: list[float] = []
    bottoms: list[float] = []
    for line in lines:
        text = " ".join(w.text for w in line)
        x0, y0, x1, y1 = font.getbbox(text, anchor="ls")
        widths.append(int(x1 - x0))
        tops.append(y0)
        bottoms.append(y1)

    if not widths:
        return 0, 0, []

    step = _cap_height(font) + spacing
    # верх блока — над базовой линией первой строки, низ — под последней
    height = int((len(lines) - 1) * step + (bottoms[-1] - tops[0]))
    return max(widths), height, widths


def fit_text(
    words: list[Word],
    rect: Rect,
    font_path: str,
    *,
    max_lines: int = MAX_LINES,
    min_size: int = 8,
) -> Layout | None:
    """Подбираем разбивку и максимальный кегль, при котором текст влезает в rect."""
    if not words:
        return None
    best: Layout | None = None
    max_size = max(min_size, rect.height)
    for line_count in range(1, min(max_lines, len(words)) + 1):
        lines = _split_into_lines(words, line_count)
        if len(lines) != line_count:
            continue
        low, high, found = min_size, max_size, None
        while low <= high:
            mid = (low + high) // 2
            font = ImageFont.truetype(font_path, mid)
            spacing = int(mid * LINE_SPACING)
            width, height, _ = _measure(lines, font, spacing)
            if width <= rect.width and height <= rect.height:
                found = mid
                low = mid + 1
            else:
                high = mid - 1
        if found is None:
            continue
        font = ImageFont.truetype(font_path, found)
        spacing = int(found * LINE_SPACING)
        width, height, _ = _measure(lines, font, spacing)
        candidate = Layout(lines=lines, font_size=found, width=width, height=height)
        if best is None or candidate.font_size > best.font_size:
            best = candidate
    return best


def render(
    image: Image.Image,
    layout: Layout,
    rect: Rect,
    font_path: str,
    *,
    text_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
) -> Image.Image:
    """Рисуем строки по центру области. Акцентные слова — отдельным цветом."""
    out = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(out)
    font = ImageFont.truetype(font_path, layout.font_size)
    spacing = int(layout.font_size * LINE_SPACING)

    texts = [" ".join(w.text for w in line) for line in layout.lines]
    boxes = [font.getbbox(t, anchor="ls") for t in texts]
    step = _cap_height(font) + spacing

    # Центрируем блок по чернилам: верх — над базовой линией первой строки.
    block_height = (len(texts) - 1) * step + (boxes[-1][3] - boxes[0][1])
    first_baseline = rect.top + (rect.height - block_height) / 2 - boxes[0][1]

    space_width = font.getlength(" ")
    for index, line in enumerate(layout.lines):
        baseline = first_baseline + index * step
        x0, _, x1, _ = boxes[index]
        x = rect.left + (rect.width - (x1 - x0)) / 2 - x0
        for i, word in enumerate(line):
            colour = accent_color if word.accent else text_color
            draw.text((x, baseline), word.text, font=font, fill=(*colour, 255), anchor="ls")
            x += font.getlength(word.text)
            if i < len(line) - 1:
                x += space_width
    return out


def typeset(
    plate: Image.Image,
    phrase: str,
    rect: Rect,
    font_path: str,
    background: tuple[int, int, int],
    *,
    max_lines: int = MAX_LINES,
) -> tuple[Image.Image, Layout]:
    """Полный проход: разбор акцентов -> подбор кегля -> отрисовка."""
    _, words = parse_accents(phrase)
    layout = fit_text(words, rect, font_path, max_lines=max_lines)
    if layout is None:
        raise ValueError(f"Текст не помещается в область {rect.as_tuple()}")
    text_color = pick_text_color(background)
    accent_color = pick_accent_color(background, text_color)
    rendered = render(
        plate, layout, rect, font_path, text_color=text_color, accent_color=accent_color
    )
    return rendered, layout
