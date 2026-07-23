from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HttpMetrics(BaseModel):
    total_requests: int = 0
    status_codes: dict[str, int] = Field(default_factory=dict)
    average_response_time_ms: float = 0.0
    last_request_at: datetime | None = None


class ContactMetrics(BaseModel):
    attempts: int = 0
    successful: int = 0
    failed: int = 0
    ai_fallbacks: int = 0
    email_messages_sent: int = 0
    emails_simulated: int = 0
    categories: dict[str, int] = Field(default_factory=dict)
    sentiments: dict[str, int] = Field(default_factory=dict)
    top_category: str | None = None
    last_contact_at: datetime | None = None


class MetricsMetadata(BaseModel):
    schema_version: int = 1
    contains_personal_data: bool = False


class MetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    http: HttpMetrics
    contacts: ContactMetrics
    errors: dict[str, int] = Field(default_factory=dict)
    metadata: MetricsMetadata
