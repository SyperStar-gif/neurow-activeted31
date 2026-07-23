from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_email_service, get_metrics_repository
from app.core.config import Settings
from app.repositories.metrics_repository import MetricsRepository
from app.schemas.common import HealthChecks, HealthResponse
from app.schemas.metrics import MetricsResponse
from app.services.email_service import EmailService

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Проверить состояние сервиса")
async def health(
    request: Request,
    email_service: EmailService = Depends(get_email_service),
) -> HealthResponse:
    settings: Settings = request.app.state.container.settings
    storage_available = await asyncio.to_thread(_storage_is_writable, settings)
    email_status = email_service.configuration_status()
    ai_status = "openai" if settings.openai_api_key_value else "local_fallback"
    status = "ok" if storage_available and email_status != "misconfigured" else "degraded"

    return HealthResponse(
        status=status,
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
        checks=HealthChecks(
            storage="available" if storage_available else "unavailable",
            ai=ai_status,
            email=email_status,
        ),
    )


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Получить обезличенную статистику",
)
async def metrics(
    repository: MetricsRepository = Depends(get_metrics_repository),
) -> MetricsResponse:
    return MetricsResponse.model_validate(await repository.snapshot())


def _storage_is_writable(settings: Settings) -> bool:
    directories: set[Path] = {
        settings.rate_limit_file.parent,
        settings.metrics_file.parent,
        settings.log_file.parent,
    }
    try:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".health-", delete=True):
                pass
        return True
    except OSError:
        return False
