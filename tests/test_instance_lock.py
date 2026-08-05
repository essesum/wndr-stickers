"""Single-instance guard: Telegram polling may have exactly one owner."""
from pathlib import Path

import pytest

from skill.wndr_stickers.src.instance_lock import AlreadyRunning, InstanceLock


def test_second_instance_fails_closed(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    first = InstanceLock(lock_path)
    second = InstanceLock(lock_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning):
            second.acquire()
    finally:
        first.release()


def test_lock_can_be_reacquired_after_release(tmp_path: Path):
    lock_path = tmp_path / "bot.lock"
    first = InstanceLock(lock_path)
    first.acquire()
    first.release()
    second = InstanceLock(lock_path)
    second.acquire()
    second.release()
