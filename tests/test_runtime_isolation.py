"""OS-level boundary for the community-facing Telegram runtime."""
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "deploy" / "wndr-stickers.sb"
PLIST = ROOT / "deploy" / "com.katya.wndr-stickers.plist"
REAL_HOME = Path("/Users/ekaterinasum")


def test_launchagent_starts_bot_inside_seatbelt_without_local_proxy():
    config = plistlib.loads(PLIST.read_bytes())
    args = config["ProgramArguments"]
    assert args[:3] == [
        "/usr/bin/sandbox-exec",
        "-f",
        str(PROFILE),
    ]
    assert args[3:] == [str(ROOT / ".venv/bin/python"), "-m", "bot.main"]

    env = config["EnvironmentVariables"]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["WNDR_RUNTIME_SANDBOX"] == "1"
    assert not any("PROXY" in key.upper() for key in env)



def test_installed_launchagent_has_runtime_sandbox_marker_when_present():
    installed = Path.home() / "Library/LaunchAgents/com.katya.wndr-stickers.plist"
    if not installed.exists():
        pytest.skip("LaunchAgent is not installed on this machine")
    config = plistlib.loads(installed.read_bytes())
    assert config["EnvironmentVariables"]["WNDR_RUNTIME_SANDBOX"] == "1"
    assert config["ProgramArguments"][:3] == [
        "/usr/bin/sandbox-exec",
        "-f",
        str(PROFILE),
    ]


def test_runtime_profile_has_fail_closed_home_and_loopback_rules():
    profile = PROFILE.read_text()
    deny_home = profile.index(
        '(deny file-read* (subpath "/Users/ekaterinasum"))'
    )
    allow_repo = profile.index(
        '(allow file-read* (subpath "/Users/ekaterinasum/dev/wndr-stickers"))'
    )
    allow_runtime = profile.index(
        '(allow file-read* file-write* (subpath "/Users/ekaterinasum/.wndr-stickers"))'
    )
    assert deny_home < allow_repo
    assert deny_home < allow_runtime
    assert '(allow file-read* (literal "/Users/ekaterinasum/.codex/auth.json"))' in profile

    for port in (6333, 6334, 8920, 11434, 49530, 10808, 10809, 10810, 10811):
        assert f'(deny network-outbound (remote tcp "localhost:{port}"))' in profile
    assert "localhost:*" not in profile


@pytest.mark.skipif(
    not Path("/usr/bin/sandbox-exec").exists() or Path.home() != REAL_HOME,
    reason="host-specific macOS Seatbelt integration",
)
def test_runtime_seatbelt_allows_own_repo_but_denies_katya_context():
    prefix = ["/usr/bin/sandbox-exec", "-f", str(PROFILE)]
    allowed = subprocess.run(  # noqa: S603
        [*prefix, "/bin/test", "-r", str(ROOT / "README.md")],
        check=False,
    )
    assert allowed.returncode == 0

    for protected in (
        REAL_HOME / ".hermes",
        REAL_HOME / ".hermes-work",
        REAL_HOME / ".ai-system",
        REAL_HOME / "katya-ai",
        REAL_HOME / "KatyaLibrary",
    ):
        denied = subprocess.run(  # noqa: S603
            [*prefix, "/bin/test", "-r", str(protected)],
            check=False,
        )
        assert denied.returncode != 0, protected

    auth = subprocess.run(  # noqa: S603
        [*prefix, "/bin/test", "-r", str(REAL_HOME / ".codex/auth.json")],
        check=False,
    )
    assert auth.returncode == 0


@pytest.mark.skipif(
    not Path("/usr/bin/sandbox-exec").exists() or shutil.which("nc") is None,
    reason="macOS Seatbelt integration",
)
def test_runtime_seatbelt_blocks_known_local_ai_and_proxy_ports():
    for port in (6333, 6334, 8920, 11434, 10808, 10809, 10810, 10811):
        result = subprocess.run(  # noqa: S603
            [
                "/usr/bin/sandbox-exec",
                "-f",
                str(PROFILE),
                shutil.which("nc") or "/usr/bin/nc",
                "-z",
                "-w",
                "1",
                "127.0.0.1",
                str(port),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0, port
