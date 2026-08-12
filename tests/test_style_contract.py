"""Canonical WNDR visual contract from docs/reference/WNDR-Sticker-Agent-v0.1.pdf."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PIL import Image, ImageDraw

from bot.handlers.commands import STYLE
from skill.wndr_stickers.src import pipeline, style

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/reference/wndr-style-contract.v0.1.json"
SOURCE_PDF = ROOT / "docs/reference/WNDR-Sticker-Agent-v0.1.pdf"


def test_canonical_style_source_and_contract_are_checked_in():
    assert SOURCE_PDF.is_file()
    data = json.loads(CONTRACT.read_text())
    assert data["source_sha256"] == (
        "61cafa0d22e11880fb5364d221b918f447cea44dae1ac9ff9017b201d9153a10"
    )
    assert hashlib.sha256(SOURCE_PDF.read_bytes()).hexdigest() == data["source_sha256"]
    assert data["palette"] == {
        "accent": "#CC3D11",
        "black": "#0D0D0D",
        "cream": "#F2E2C8",
        "outline": "#F7F3EA",
    }
    assert data["outline"]["outer_px_at_512"] == [8, 12]
    assert "arrow / pointer badge" in data["allowed_plate_forms"]
    assert (
        "model-generated text, letters, numbers, captions, watermarks or signatures"
        in data["hard_bans"]
    )


def test_style_constants_match_canonical_palette():
    assert style.hexstr(style.ACCENT) == "#CC3D11"
    assert style.hexstr(style.BLACK) == "#0D0D0D"
    assert style.hexstr(style.CREAM) == "#F2E2C8"
    assert style.hexstr(style.NEAR_WHITE) == "#F7F3EA"


def test_prompt_matches_canonical_constraints_and_has_no_ad_hoc_arrow_ban():
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("arrow"),
        combo={"fill": "cream #F2E2C8"},
        allow_arrows=False,
    )
    assert "#CC3D11" in prompt
    assert "#0D0D0D" in prompt
    assert "#F2E2C8" in prompt
    assert "#F7F3EA" in prompt
    assert "8-12 px" in prompt
    assert "plain solid pure-black background" in prompt
    assert "NO text" in prompt and "NO letters" in prompt
    assert "No gradients" in prompt
    assert "no 3D" in prompt
    assert "no gloss" in prompt
    assert "no drop shadows" in prompt
    assert "no photorealism/photo" in prompt
    # v0.2: счёт «не больше трёх цветов» заменён запретом выходить за палитру —
    # иначе оттенки rust/terracotta/sand были бы нарушением собственного промпта.
    assert "outside the approved WNDR palette" in prompt
    assert "No arrows" not in prompt
    assert "aura-like waves" not in prompt


def test_user_phrase_is_not_part_of_plate_generation_prompt():
    user_phrase = "Кто не сдох, тот молодец?"
    prompt = style.build_plate_prompt(
        shape=style.shape_by_key("rounded-rect"),
        combo={"fill": "near-black #0D0D0D"},
        motif=None,
    )
    assert user_phrase not in prompt
    assert "Typography will be added later by software" in prompt


def test_make_sticker_keeps_user_phrase_out_of_image_provider_prompt(monkeypatch, tmp_path):
    user_phrase = "Кто не сдох, тот молодец?"
    seen = {}

    class Settings:
        allow_arrow_shapes = True
        reference_sheet_path = tmp_path / "reference.png"
        stickers_dir = tmp_path / "stickers"
        raw_dir = tmp_path / "raw"
        font_path = "/System/Library/Fonts/Supplemental/Impact.ttf"

    def fake_generate(prompt, reference, settings):
        seen["prompt"] = prompt
        seen["reference"] = reference
        raise RuntimeError("stop before image processing")

    monkeypatch.setattr(pipeline.imagegen, "generate", fake_generate)

    with pytest.raises(RuntimeError, match="stop before image processing"):
        pipeline.make_sticker(user_phrase, Settings(), rng=__import__("random").Random(1))

    assert user_phrase not in seen["prompt"]
    assert "NO text" in seen["prompt"]
    assert seen["reference"] == Settings.reference_sheet_path


def test_pipeline_rejects_and_removes_noncanonical_sticker(monkeypatch, tmp_path):
    class FakeGenerated:
        provider = "fake"
        model = "fake"

        def save(self, path):
            image = Image.new("RGB", (512, 512), (0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (55, 120, 457, 392),
                radius=45,
                fill=(0, 180, 255),
                outline=(247, 243, 234),
                width=10,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)
            return path

    settings = SimpleNamespace(
        allow_arrow_shapes=True,
        reference_sheet_path=tmp_path / "reference.png",
        stickers_dir=tmp_path / "stickers",
        raw_dir=tmp_path / "raw",
        font_path="/System/Library/Fonts/Supplemental/Impact.ttf",
    )
    monkeypatch.setattr(pipeline.imagegen, "generate", lambda *_args, **_kwargs: FakeGenerated())

    with pytest.raises(pipeline.StickerVerificationError, match="WNDR-контракта"):
        pipeline.make_sticker(
            "Палитра gate test", cast(Any, settings), rng=random.Random(1)
        )

    assert not list(settings.stickers_dir.glob("*.webp"))


def test_user_facing_style_copy_keeps_canonical_arrow_form():
    assert "Стрелка/указатель — одна из канонических форм" in STYLE
    assert "Стрелки, градиенты" not in STYLE
