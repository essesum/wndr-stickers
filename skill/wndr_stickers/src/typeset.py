"""Впечатывание кириллицы в плашку.

Модель букв не рисует вообще — их ставит код настоящим шрифтом. Поэтому «объем»
всегда с твёрдым знаком, «ё» не превращается в «е», а вопросительный знак
появляется ровно тогда, когда он есть в исходной фразе.

Акцентное слово помечается звёздочками: «Это не *тантра*». Если разметки нет,
акцент иногда выбирается сам (auto_accent) — это главный источник
типографического разброса при жёсткой палитре.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .plate import Rect
from .style import ACCENT, BLACK, CREAM, RUST, SAND, TERRACOTTA

_ACCENT_RE = re.compile(r"\*([^*]+)\*")

#: Кавычки на стикерах запрещены совсем (решение Кати 2026-08-12) — вычищаются
#: из фразы где угодно, не только по краям.
_QUOTE_CHARS = "«»\"“”„‚"
_QUOTE_TABLE = str.maketrans("", "", _QUOTE_CHARS)

MAX_LINES = 3
LINE_SPACING = 0.12  # доля от кегля

#: Служебные слова акцентом не выделяются: «и» оранжевым — это не акцент, а шум.
_SKIP_ACCENT_WORDS = frozenset(
    "и в на не с я ты мы вы он она оно они это эта этот же бы а но у о об за "
    "от до по из как что чтобы так там тут все всё еще ещё уже для при или "
    "ли ни то мой моя твой твоя свой своя нет да".split()
)

#: Как часто безразметочная фраза получает автоакцент и как часто под акцентом
#: появляется росчерк. Не всегда: постоянный приём перестаёт быть приёмом.
AUTO_ACCENT_CHANCE = 0.6
FLOURISH_CHANCE = 0.5


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
        clean = _ACCENT_RE.sub(r"\1", raw).translate(_QUOTE_TABLE)
        if clean:
            words.append(Word(clean, accent))
    plain = " ".join(w.text for w in words)
    return plain, words


def auto_accent(
    words: list[Word],
    rng: random.Random,
    *,
    chance: float = AUTO_ACCENT_CHANCE,
) -> list[Word]:
    """Выбрать акцентное слово за человека, если он не разметил его сам."""
    if len(words) < 2 or any(w.accent for w in words):
        return words
    # На двухсловной фразе акцент перекрашивает половину стикера — если делать
    # это с обычной частотой, двухцветность сама становится монотонной.
    if len(words) == 2:
        chance *= 0.5
    if rng.random() >= chance:
        return words
    candidates = [
        i
        for i, w in enumerate(words)
        if len(w.text) >= 4 and w.text.lower().strip("!?.,…") not in _SKIP_ACCENT_WORDS
    ]
    if not candidates:
        return words
    index = rng.choice(candidates)
    return [Word(w.text, i == index) for i, w in enumerate(words)]


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


#: Тёмные заливки носят кремовый текст, светлые — чёрный. Оттенки v0.2 входят
#: в поиск ближайшего цвета, иначе терракотовая плашка считалась бы оранжевой
#: и получила бы кремовый текст с контрастом 2.4:1.
_PLATE_COLORS = (ACCENT, BLACK, CREAM, RUST, TERRACOTTA, SAND)
_DARK_FILLS = (ACCENT, BLACK, RUST)


def _nearest_base_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    return min(
        _PLATE_COLORS,
        key=lambda c: sum((a - b) ** 2 for a, b in zip(c, background, strict=True)),
    )


def pick_text_color(
    background: tuple[int, int, int], *, forbid_black: bool = False
) -> tuple[int, int, int]:
    """Canonical pairing from the official guide, not a generic contrast guess.

    При forbid_black (розы в дизайне) роль тёмного текста играет ржавый.
    """
    nearest = _nearest_base_color(background)
    if nearest in _DARK_FILLS:
        return CREAM
    return RUST if forbid_black else BLACK


def pick_accent_color(
    background: tuple[int, int, int],
    text_color: tuple[int, int, int],
    *,
    forbid_black: bool = False,
) -> tuple[int, int, int]:
    """Orange accent on black/cream/sand; black accent on orange-family plates.

    Ржавая плашка — исключение среди оранжевых: чёрный на #992D0E тонет
    (контраст ~1.8:1, живой пример — bolshe-zhizni-v9), поэтому акцент там
    оранжевый, как на чёрной.
    """
    nearest = _nearest_base_color(background)
    accent = BLACK if nearest in (ACCENT, TERRACOTTA) else ACCENT
    if accent == text_color:
        accent = BLACK if text_color != BLACK else CREAM
    if forbid_black and accent == BLACK:
        # Ржавый вместо чёрного, но не на ржавой плашке и не цветом текста —
        # там тёмный акцент берёт на себя оранжевый.
        accent = RUST if text_color != RUST and nearest != RUST else ACCENT
    return accent


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


def _draw_flourish(
    draw: ImageDraw.ImageDraw,
    x: float,
    baseline: float,
    width: float,
    font_size: int,
    colour: tuple[int, int, int],
) -> None:
    """Росчерк под акцентным словом: лёгкая дуга, как подчёркивание от руки."""
    y = baseline + max(2.0, font_size * 0.12)
    sag = font_size * 0.05
    thickness = max(2, font_size // 12)
    draw.line(
        [(x, y), (x + width * 0.5, y + sag), (x + width, y)],
        fill=(*colour, 255),
        width=thickness,
        joint="curve",
    )


def render(
    image: Image.Image,
    layout: Layout,
    rect: Rect,
    font_path: str,
    *,
    text_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
    underline_accents: bool = False,
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
        last_line = index == len(layout.lines) - 1
        x0, _, x1, _ = boxes[index]
        x = rect.left + (rect.width - (x1 - x0)) / 2 - x0
        for i, word in enumerate(line):
            colour = accent_color if word.accent else text_color
            draw.text((x, baseline), word.text, font=font, fill=(*colour, 255), anchor="ls")
            word_width = font.getlength(word.text)
            # Росчерк — только на нижней строке: между строками он попадает
            # в межстрочный зазор и читается как зачёркивание слова сверху.
            if word.accent and underline_accents and last_line:
                _draw_flourish(draw, x, baseline, word_width, layout.font_size, colour)
            x += word_width
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
    rng: random.Random | None = None,
    forbid_black: bool = False,
) -> tuple[Image.Image, Layout]:
    """Полный проход: разбор акцентов -> подбор кегля -> отрисовка.

    С rng включается типографический разброс: автоакцент и росчерк. Без rng
    поведение прежнее и полностью детерминированное — на этом держатся тесты
    и rebuild существующих стикеров. forbid_black — правило «розы без чёрного»:
    чёрный текст и чёрный акцент заменяются ржавым/оранжевым.
    """
    _, words = parse_accents(phrase)
    if rng is not None:
        words = auto_accent(words, rng)
    layout = fit_text(words, rect, font_path, max_lines=max_lines)
    if layout is None:
        raise ValueError(f"Текст не помещается в область {rect.as_tuple()}")
    text_color = pick_text_color(background, forbid_black=forbid_black)
    accent_color = pick_accent_color(background, text_color, forbid_black=forbid_black)
    has_accent = any(w.accent for line in layout.lines for w in line)
    underline = rng is not None and has_accent and rng.random() < FLOURISH_CHANCE
    rendered = render(
        plate,
        layout,
        rect,
        font_path,
        text_color=text_color,
        accent_color=accent_color,
        underline_accents=underline,
    )
    return rendered, layout
