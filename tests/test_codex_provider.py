"""Провайдер Codex: картинки по подписке ChatGPT, без API-ключа."""
import pytest

from skill.wndr_stickers.src import imagegen


def test_build_command_pins_a_supported_model():
    """gpt-4.1 из старого ~/.codex/config.toml не работает с аккаунтом ChatGPT."""
    cmd = imagegen.build_codex_command(
        workdir="/tmp/x", reference="/tmp/ref.png", model="gpt-5.5", last_message="/tmp/x/last.txt"
    )
    assert "-m" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5.5"


def test_build_command_attaches_the_reference_sheet():
    cmd = imagegen.build_codex_command(
        workdir="/tmp/x", reference="/tmp/ref.png", model="gpt-5.5", last_message="/tmp/x/last.txt"
    )
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == "/tmp/ref.png"


def test_build_command_can_run_outside_a_git_repo():
    cmd = imagegen.build_codex_command(
        workdir="/tmp/x", reference="/tmp/ref.png", model="gpt-5.5", last_message="/tmp/x/last.txt"
    )
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("-C") + 1] == "/tmp/x"


def test_newest_generated_image_picks_the_freshest(tmp_path):
    import os
    import time

    root = tmp_path / "generated_images"
    (root / "aaa").mkdir(parents=True)
    (root / "bbb").mkdir(parents=True)
    old = root / "aaa" / "call_old.png"
    new = root / "bbb" / "call_new.png"
    old.write_bytes(b"old")
    time.sleep(0.01)
    new.write_bytes(b"new")
    os.utime(old, (1, 1))

    assert imagegen.newest_generated_image(root) == new


def test_newest_generated_image_returns_none_when_empty(tmp_path):
    assert imagegen.newest_generated_image(tmp_path / "nope") is None


def test_codex_prompt_demands_a_named_output_file():
    prompt = imagegen.codex_prompt("PLATE PROMPT HERE", "plate.png")
    assert "PLATE PROMPT HERE" in prompt
    assert "plate.png" in prompt
    assert "image_gen" in prompt


def test_missing_binary_is_a_soft_failure(tmp_path, monkeypatch):
    """Нет codex в PATH — это повод пойти к следующему провайдеру, а не упасть."""
    monkeypatch.setattr(imagegen.shutil, "which", lambda _: None)
    with pytest.raises(imagegen.ProviderUnavailable):
        imagegen.generate_codex("prompt", tmp_path / "ref.png")
