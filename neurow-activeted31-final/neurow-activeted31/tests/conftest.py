from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        app_debug=False,
        cors_origins="https://frontend.example",
        openai_api_key=None,
        email_enabled=False,
        rate_limit_requests=100,
        rate_limit_window_seconds=60,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate_limits.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def valid_payload() -> dict[str, str]:
    return {
        "name": "Иван Иванов",
        "phone": "+7 999 123-45-67",
        "email": "ivan@example.com",
        "comment": "Хочу обсудить разработку интернет-магазина, спасибо!",
    }
