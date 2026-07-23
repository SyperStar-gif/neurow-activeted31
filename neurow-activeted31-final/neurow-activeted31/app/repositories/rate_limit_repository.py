from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

from app.repositories.json_file_repository import JsonFileRepository


@dataclass(frozen=True, slots=True)
class RateLimitRecord:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_epoch: int


class RateLimitRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 5.0) -> None:
        self.storage = JsonFileRepository(path, {}, lock_timeout=lock_timeout)

    async def consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> RateLimitRecord:
        current = now if now is not None else time.time()
        boundary = current - window_seconds

        def mutate(data: dict[str, list[float]]) -> RateLimitRecord:
            for stored_key in list(data):
                active = [timestamp for timestamp in data[stored_key] if timestamp > boundary]
                if active:
                    data[stored_key] = active
                else:
                    data.pop(stored_key, None)

            timestamps = list(data.get(key, []))
            allowed = len(timestamps) < limit
            if allowed:
                timestamps.append(current)
                data[key] = timestamps

            oldest = min(timestamps) if timestamps else current
            reset_epoch = math.ceil(oldest + window_seconds)
            retry_after = max(1, math.ceil(reset_epoch - current))
            remaining = max(0, limit - len(timestamps))
            return RateLimitRecord(
                allowed=allowed,
                limit=limit,
                remaining=remaining,
                retry_after=retry_after,
                reset_epoch=reset_epoch,
            )

        return await self.storage.update(mutate)
