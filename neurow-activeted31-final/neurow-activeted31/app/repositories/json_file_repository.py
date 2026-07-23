from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from filelock import FileLock

T = TypeVar("T")
R = TypeVar("R")


class JsonFileRepository:
    """Small JSON repository with process and cross-process write protection."""

    def __init__(self, path: Path, default: T, *, lock_timeout: float = 5.0) -> None:
        self.path = path
        self.default = default
        self._async_lock = asyncio.Lock()
        self._file_lock = FileLock(f"{path}.lock", timeout=lock_timeout)

    async def read(self) -> T:
        async with self._async_lock:
            return await asyncio.to_thread(self._read_locked)

    async def update(self, mutator: Callable[[T], R]) -> R:
        async with self._async_lock:
            return await asyncio.to_thread(self._update_locked, mutator)

    def _read_locked(self) -> T:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock:
            return self._read_unlocked()

    def _update_locked(self, mutator: Callable[[T], R]) -> R:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock:
            data = self._read_unlocked()
            result = mutator(data)
            self._write_unlocked(data)
            return result

    def _read_unlocked(self) -> T:
        if not self.path.exists():
            return copy.deepcopy(self.default)
        try:
            with self.path.open("r", encoding="utf-8") as source:
                return json.load(source)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            self._quarantine_corrupt_file()
            return copy.deepcopy(self.default)

    def _quarantine_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        target = self.path.with_name(
            f"{self.path.name}.corrupt-{timestamp}-{uuid4().hex[:8]}"
        )
        with suppress(OSError):
            self.path.replace(target)

    def _write_unlocked(self, data: T) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                json.dump(data, target, ensure_ascii=False, indent=2)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            with suppress(OSError):
                os.unlink(temp_name)
            raise
