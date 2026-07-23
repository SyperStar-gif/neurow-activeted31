from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.repositories.json_file_repository import JsonFileRepository
from app.repositories.metrics_repository import MetricsRepository
from app.repositories.rate_limit_repository import RateLimitRepository
from app.schemas.contact import AIResult, EmailDelivery
from app.services.rate_limit_service import RateLimitService


@pytest.mark.asyncio
async def test_rate_limit_repository_enforces_limit(tmp_path: Path) -> None:
    repository = RateLimitRepository(tmp_path / "rate.json")
    first = await repository.consume("client", limit=2, window_seconds=60, now=100)
    second = await repository.consume("client", limit=2, window_seconds=60, now=101)
    third = await repository.consume("client", limit=2, window_seconds=60, now=102)

    assert first.allowed is True and first.remaining == 1
    assert second.allowed is True and second.remaining == 0
    assert third.allowed is False and third.remaining == 0
    assert third.retry_after == 58


@pytest.mark.asyncio
async def test_rate_limit_window_expires(tmp_path: Path) -> None:
    repository = RateLimitRepository(tmp_path / "rate.json")
    await repository.consume("client", limit=1, window_seconds=10, now=100)
    result = await repository.consume("client", limit=1, window_seconds=10, now=111)

    assert result.allowed is True


@pytest.mark.asyncio
async def test_json_repository_recovers_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "storage.json"
    path.write_text("{not-json", encoding="utf-8")
    repository = JsonFileRepository(path, {"counter": 0})

    assert await repository.read() == {"counter": 0}
    assert list(tmp_path.glob("storage.json.corrupt-*"))


@pytest.mark.asyncio
async def test_metrics_updates_are_serialized(tmp_path: Path) -> None:
    repository = MetricsRepository(tmp_path / "metrics.json")
    ai = AIResult(
        category="project",
        sentiment="positive",
        priority="normal",
        summary="Проект",
        suggested_reply="Спасибо",
        fallback_used=True,
        provider="local_fallback",
    )
    delivery = EmailDelivery(mode="simulation", owner="simulated", user="simulated")

    await asyncio.gather(
        *(repository.record_contact_success(ai, delivery) for _ in range(20))
    )
    metrics = await repository.snapshot()

    assert metrics["contacts"]["successful"] == 20
    assert metrics["contacts"]["ai_fallbacks"] == 20
    assert metrics["contacts"]["categories"]["project"] == 20
    assert metrics["contacts"]["emails_simulated"] == 40


def test_smtp_credentials_must_be_configured_together() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="test",
            smtp_username="user",
            smtp_password=None,
        )


def test_production_requires_strong_rate_limit_salt() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


def test_production_accepts_strong_rate_limit_salt() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        rate_limit_hash_salt="a-very-long-random-production-secret",
    )

    assert settings.app_env == "production"


def test_cors_wildcard_is_rejected() -> None:
    settings = Settings(_env_file=None, app_env="test", cors_origins="*")

    with pytest.raises(ValueError):
        _ = settings.cors_origins_list


@pytest.mark.asyncio
async def test_rate_limit_service_fails_open_when_storage_breaks(tmp_path: Path) -> None:
    class BrokenRepository:
        async def consume(self, *args, **kwargs):
            raise OSError("disk unavailable")

    settings = Settings(
        _env_file=None,
        app_env="test",
        rate_limit_fail_open=True,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    service = RateLimitService(BrokenRepository(), settings)

    decision = await service.check("127.0.0.1", "request-id")

    assert decision.allowed is True
    assert decision.degraded is True
