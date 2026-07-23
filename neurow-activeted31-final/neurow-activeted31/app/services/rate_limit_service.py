from __future__ import annotations

import logging
from dataclasses import dataclass
from time import time

from app.core.config import Settings
from app.core.exceptions import RateLimitStorageError
from app.core.security import hash_identifier
from app.repositories.rate_limit_repository import RateLimitRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_epoch: int
    degraded: bool = False


class RateLimitService:
    def __init__(self, repository: RateLimitRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def hash_identifier(self, identifier: str) -> str:
        return hash_identifier(identifier, self.settings.rate_limit_salt)

    async def check(self, client_ip: str, request_id: str) -> RateLimitDecision:
        key = self.hash_identifier(client_ip)
        try:
            record = await self.repository.consume(
                key,
                limit=self.settings.rate_limit_requests,
                window_seconds=self.settings.rate_limit_window_seconds,
            )
            return RateLimitDecision(
                allowed=record.allowed,
                limit=record.limit,
                remaining=record.remaining,
                retry_after=record.retry_after,
                reset_epoch=record.reset_epoch,
            )
        except Exception as exc:
            logger.exception(
                "Rate limit storage failed",
                extra={
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                },
            )
            if not self.settings.rate_limit_fail_open:
                raise RateLimitStorageError(
                    "Rate limiting временно недоступен"
                ) from exc
            now = int(time())
            return RateLimitDecision(
                allowed=True,
                limit=self.settings.rate_limit_requests,
                remaining=self.settings.rate_limit_requests,
                retry_after=0,
                reset_epoch=now + self.settings.rate_limit_window_seconds,
                degraded=True,
            )
