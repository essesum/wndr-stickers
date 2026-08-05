from PIL import Image

from skill.wndr_stickers.src.cutout import save_webp
from skill.wndr_stickers.src.verify import verify_sticker, verify_text


def _canvas(bbox=(40, 40, 472, 472), size=(512, 512)) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    inner = Image.new("RGBA", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (200, 30, 10, 255))
    img.alpha_composite(inner, (bbox[0], bbox[1]))
    return img


def test_good_sticker_passes(tmp_path):
    path = save_webp(_canvas(), tmp_path / "ok.webp")
    result = verify_sticker(path)
    assert result.ok, result.problems
    assert result.size == (512, 512)


def test_wrong_size_is_caught(tmp_path):
    path = save_webp(_canvas(bbox=(10, 10, 200, 200), size=(256, 256)), tmp_path / "small.webp")
    result = verify_sticker(path)
    assert not result.ok
    assert any("512" in p for p in result.problems)


def test_opaque_corners_are_caught(tmp_path):
    path = save_webp(Image.new("RGBA", (512, 512), (10, 10, 10, 255)), tmp_path / "opaque.webp")
    result = verify_sticker(path)
    assert not result.ok
    assert any("углы" in p for p in result.problems)


def test_touching_the_edge_is_caught(tmp_path):
    path = save_webp(_canvas(bbox=(0, 40, 512, 472)), tmp_path / "edge.webp")
    result = verify_sticker(path)
    assert not result.ok
    assert any("касается" in p for p in result.problems)


def test_missing_file_is_reported(tmp_path):
    result = verify_sticker(tmp_path / "nope.webp")
    assert not result.ok


def test_text_verification_is_character_exact():
    assert verify_text("Я приношу весь свой объем", "Я приношу весь свой объем")
    assert not verify_text("Я приношу весь свой обем", "Я приношу весь свой объем")
    assert not verify_text("Я сейчас получаю удовольствие?", "Я сейчас получаю удовольствие")
    assert not verify_text("Со мной всё нормально", "Со мной все нормально")


def test_text_verification_reports_first_mismatch_position():
    result = verify_text("Со мной всё нормально", "Со мной все нормально")
    assert any("позиции" in p for p in result.problems)
