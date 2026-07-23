from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


class EmailConfigurationError(AppError):
    status_code = 503
    code = "email_configuration_error"


class EmailDeliveryError(AppError):
    status_code = 503
    code = "email_delivery_failed"


class RateLimitStorageError(AppError):
    status_code = 503
    code = "rate_limit_storage_error"
