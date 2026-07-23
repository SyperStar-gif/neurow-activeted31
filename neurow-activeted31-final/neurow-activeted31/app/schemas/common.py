from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorBody
    request_id: str


class HealthChecks(BaseModel):
    storage: Literal["available", "unavailable"]
    ai: Literal["openai", "local_fallback"]
    email: Literal["disabled", "configured", "misconfigured"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    timestamp: datetime
    checks: HealthChecks
