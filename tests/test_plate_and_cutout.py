import numpy as np
from PIL import Image, ImageDraw

from skill.wndr_stickers.src.cutout import (
    CANVAS_SIZE,
    cut_out,
    remove_connected_background,
    telegram_canvas,
)
from skill.wndr_stickers.src.plate import (
    Rect,
    dominant_color,
    erode,
    largest_rectangle,
    safe_text_area,
)
from skill.wndr_stickers.src.style import ACCENT, BLACK, CREAM


def make_plate(size=(800, 600), fill=BLACK, motif=False) -> Image.Image:
    """Чёрный фон + плашка с толстым кремовым кантом, как рисует модель."""
    img = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(img)
    w, h = size
    d.rounded_rectangle([60, 60, w - 60, h - 60], radius=48, fill=CREAM)
    d.rounded_rectangle([90, 90, w - 90, h - 90], radius=36, fill=fill)
    if motif:
        d.ellipse([w - 220, h - 200, w - 120, h - 120], fill=ACCENT)
    return img


def test_background_flood_fill_only_touches_edge_connected_black():
    img = make_plate(fill=BLACK)
    out = remove_connected_background(img)
    assert out.getpixel((0, 0))[3] == 0, "угол должен стать прозрачным"
    cx, cy = img.width // 2, img.height // 2
    assert out.getpixel((cx, cy))[3] == 255, "чёрный внутри плашки обязан выжить"


def test_inner_black_survives_because_cream_outline_separates_it():
    img = make_plate(fill=BLACK)
    out = remove_connected_background(img)
    arr = np.asarray(out)
    inner = arr[150:-150, 150:-150]
    assert (inner[:, :, 3] == 255).all()


def test_cut_out_trims_to_content():
    img = make_plate(size=(800, 600))
    out = cut_out(img)
    # поле в 60px по кругу должно уйти
    assert out.width < 800 and out.height < 600
    assert out.getpixel((0, 0))[3] > 0 or out.getpixel((out.width // 2, 0))[3] > 0


def test_telegram_canvas_is_512_with_transparent_corners():
    img = make_plate()
    canvas = telegram_canvas(remove_connected_background(img))
    assert canvas.size == (CANVAS_SIZE, CANVAS_SIZE)
    for xy in [(0, 0), (511, 0), (0, 511), (511, 511)]:
        assert canvas.getpixel(xy)[3] == 0


def test_telegram_canvas_keeps_a_safety_margin():
    img = make_plate()
    canvas = telegram_canvas(remove_connected_background(img))
    bbox = canvas.getchannel("A").getbbox()
    assert bbox is not None
    assert bbox[0] >= 15 and bbox[1] >= 15
    assert bbox[2] <= CANVAS_SIZE - 15 and bbox[3] <= CANVAS_SIZE - 15


def test_erode_shrinks_a_solid_block():
    mask = np.zeros((50, 50), dtype=bool)
    mask[10:40, 10:40] = True
    out = erode(mask, 3)
    assert out[20, 20]
    assert not out[10, 10], "край должен съесться"
    assert out.sum() < mask.sum()


def test_erode_of_thin_shape_is_empty():
    mask = np.zeros((50, 50), dtype=bool)
    mask[24:26, 10:40] = True
    assert not erode(mask, 5).any()


def test_largest_rectangle_finds_the_obvious_block():
    ok = np.zeros((20, 30), dtype=bool)
    ok[5:15, 4:24] = True
    rect = largest_rectangle(ok)
    assert rect == Rect(4, 5, 24, 15)
    assert rect.area == 200


def test_largest_rectangle_prefers_area_over_shape():
    ok = np.zeros((20, 20), dtype=bool)
    ok[0:2, 0:20] = True   # площадь 40
    ok[5:15, 5:11] = True  # площадь 60
    rect = largest_rectangle(ok)
    assert rect is not None and rect.area == 60


def test_largest_rectangle_on_empty_is_none():
    assert largest_rectangle(np.zeros((10, 10), dtype=bool)) is None


def test_safe_text_area_lands_inside_the_plate():
    sticker = cut_out(make_plate(fill=BLACK))
    rect = safe_text_area(sticker)
    assert rect.width > 0 and rect.height > 0
    alpha = np.asarray(sticker)[:, :, 3]
    patch = alpha[rect.top : rect.bottom, rect.left : rect.right]
    assert (patch > 8).all(), "область под текст обязана лежать внутри стикера"


def test_safe_text_area_avoids_the_illustration():
    sticker = cut_out(make_plate(fill=BLACK, motif=True))
    rect = safe_text_area(sticker)
    arr = np.asarray(sticker)
    patch = arr[rect.top : rect.bottom, rect.left : rect.right, :3]
    # оранжевого образа в области набора быть не должно
    close_to_accent = (np.abs(patch.astype(int) - np.array(ACCENT)).sum(axis=2) < 60).mean()
    assert close_to_accent < 0.02


def test_dominant_color_reads_the_plate_fill():
    sticker = cut_out(make_plate(fill=BLACK))
    rect = safe_text_area(sticker)
    assert sum(dominant_color(sticker, rect)) < 120, "заливка тёмная"

    sticker_cream = cut_out(make_plate(fill=CREAM))
    rect_cream = safe_text_area(sticker_cream)
    assert sum(dominant_color(sticker_cream, rect_cream)) > 500, "заливка светлая"
