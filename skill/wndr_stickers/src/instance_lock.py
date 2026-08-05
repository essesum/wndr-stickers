"""Fail-closed single-instance lock for the Telegram poller."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import TextIO


class AlreadyRunning(RuntimeError):
    """Another process already owns the bot lock."""


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise AlreadyRunning(f"бот уже запущен: lock={self.path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()
