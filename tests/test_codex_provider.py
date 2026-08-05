"""Провайдер Codex: подписка ChatGPT внутри жёсткой локальной песочницы."""
import subprocess
from pathlib import Path

import pytest

from skill.wndr_stickers.src import imagegen


def _command(**overrides):
    args = {
        "workdir": "/tmp/x",
        "reference": "/tmp/ref.png",
        "model": "gpt-5.5",
        "last_message": "/tmp/x/last.txt",
        "prompt": "НАРИСУЙ ПЛАШКУ",
        "sandbox_profile": "/tmp/x/profile.sb",
    }
    args.update(overrides)
    return imagegen.build_codex_command(**args)


def test_command_actually_carries_the_prompt():
    cmd = _command()
    assert cmd[-1] == "НАРИСУЙ ПЛАШКУ"


def test_build_command_pins_supported_model_and_reference():
    cmd = _command()
    assert cmd[cmd.index("-m") + 1] == "gpt-5.5"
    assert cmd[cmd.index("-i") + 1] == "/tmp/ref.png"
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("-C") + 1] == "/tmp/x"


def test_codex_ignores_global_context_and_persists_nothing():
    cmd = _command()
    assert "--ephemeral" in cmd
    assert "--ignore-user-config" in cmd
    assert "--ignore-rules" in cmd


def test_command_is_wrapped_in_macos_sandbox_when_profile_is_given():
    cmd = _command()
    assert cmd[:3] == ["/usr/bin/sandbox-exec", "-f", "/tmp/x/profile.sb"]
    assert "codex" in cmd


def test_command_omits_nested_sandbox_when_profile_is_none():
    cmd = _command(sandbox_profile=None)
    assert cmd[0:2] == ["codex", "exec"]
    assert "/usr/bin/sandbox-exec" not in cmd


def test_sandbox_profile_denies_real_home(tmp_path):
    profile = imagegen.codex_sandbox_profile(Path("/Users/example"))
    assert '(subpath "/Users/example")' in profile
    assert "deny file-read*" in profile
    assert "deny file-write*" in profile
    for port in (6333, 6334, 8920, 11434, 49530, 10808, 10809, 10810, 10811):
        assert f'(deny network-outbound (remote tcp "localhost:{port}"))' in profile
    assert "localhost:*" not in profile


def test_sanitized_codex_environment_contains_no_arbitrary_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("VERY_SECRET_TOKEN", "must-not-pass")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-pass")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10811")
    monkeypatch.setenv("WNDR_RUNTIME_SANDBOX", "1")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = imagegen.codex_environment(tmp_path / "home")
    assert "VERY_SECRET_TOKEN" not in env
    assert "OPENAI_API_KEY" not in env
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "WNDR_RUNTIME_SANDBOX" not in env
    assert "HTTPS_PROXY" not in env
    assert env["HOME"] == str(tmp_path / "home")
    assert env["CODEX_HOME"] == str(tmp_path / "home")


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


def test_codex_prompt_demands_named_output_file():
    prompt = imagegen.codex_prompt("PLATE PROMPT HERE", "plate.png")
    assert "PLATE PROMPT HERE" in prompt
    assert "plate.png" in prompt
    assert "image_gen" in prompt


def test_stdin_is_closed_and_isolated_home_is_used(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)

        class R:
            stdout = ""
            stderr = ""
            returncode = 0

        return R()

    source_auth = tmp_path / "source-auth.json"
    source_auth.write_text('{"auth_mode":"test"}')
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    monkeypatch.setattr(imagegen.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(imagegen.subprocess, "run", fake_run)

    with pytest.raises(imagegen.ImageGenerationError):
        imagegen.generate_codex("prompt", ref, auth_source=source_auth)

    assert seen.get("stdin") is subprocess.DEVNULL
    assert "input" not in seen
    assert seen["env"]["HOME"] == seen["env"]["CODEX_HOME"]
    assert seen["env"]["HOME"].startswith("/var/")
    assert "VERY_SECRET_TOKEN" not in seen["env"]


def test_generate_codex_skips_nested_sandbox_inside_runtime_sandbox(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)
        (tmp_path / "unused").mkdir(exist_ok=True)

        class R:
            stdout = ""
            stderr = ""
            returncode = 0

        return R()

    source_auth = tmp_path / "source-auth.json"
    source_auth.write_text('{"auth_mode":"test"}')
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    monkeypatch.setenv("WNDR_RUNTIME_SANDBOX", "1")
    monkeypatch.setattr(imagegen.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(imagegen.subprocess, "run", fake_run)

    with pytest.raises(imagegen.ImageGenerationError):
        imagegen.generate_codex("static plate prompt", ref, auth_source=source_auth)

    assert seen["cmd"][0:2] == ["codex", "exec"]
    assert "/usr/bin/sandbox-exec" not in seen["cmd"]
    assert seen["env"]["HOME"] == seen["env"]["CODEX_HOME"]


def test_generate_codex_uses_nested_sandbox_without_runtime_marker(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)

        class R:
            stdout = ""
            stderr = ""
            returncode = 0

        return R()

    source_auth = tmp_path / "source-auth.json"
    source_auth.write_text('{"auth_mode":"test"}')
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"x")
    monkeypatch.delenv("WNDR_RUNTIME_SANDBOX", raising=False)
    monkeypatch.setattr(imagegen.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(imagegen.subprocess, "run", fake_run)

    with pytest.raises(imagegen.ImageGenerationError):
        imagegen.generate_codex("static plate prompt", ref, auth_source=source_auth)

    assert seen["cmd"][:2] == ["/usr/bin/sandbox-exec", "-f"]
    assert seen["cmd"][2].endswith("codex.sb")


def test_missing_binary_is_soft_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(imagegen.shutil, "which", lambda _: None)
    with pytest.raises(imagegen.ProviderUnavailable):
        imagegen.generate_codex("prompt", tmp_path / "ref.png")
