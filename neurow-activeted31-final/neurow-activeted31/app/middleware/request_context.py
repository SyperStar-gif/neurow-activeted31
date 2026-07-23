from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import Settings
from app.core.error_handlers import error_response
from app.core.exceptions import AppError
from app.core.security import get_client_ip, normalize_request_id
from app.repositories.metrics_repository import MetricsRepository
from app.services.rate_limit_service import RateLimitDecision, RateLimitService

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        settings: Settings,
        rate_limit_service: RateLimitService,
        metrics_repository: MetricsRepository,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.rate_limit_service = rate_limit_service
        self.metrics_repository = metrics_repository

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        started_at = time.perf_counter()
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        client_ip = get_client_ip(
            request.scope,
            trust_proxy_headers=self.settings.trust_proxy_headers,
        )
        request.state.request_id = request_id
        request.state.client_ip = client_ip
        request.state.error_code = None
        rate_limit: RateLimitDecision | None = None

        try:
            if self._content_length_is_too_large(request):
                response = self._request_too_large_response(request)
            elif request.method == "POST" and request.url.path == "/api/contact":
                if await self._actual_body_is_too_large(request):
                    response = self._request_too_large_response(request)
                else:
                    rate_limit = await self.rate_limit_service.check(client_ip, request_id)
                    if not rate_limit.allowed:
                        response = error_response(
                            request,
                            status_code=429,
                            code="rate_limit_exceeded",
                            message="Слишком много запросов. Повторите позже.",
                            details={"retry_after": rate_limit.retry_after},
                            headers={"Retry-After": str(rate_limit.retry_after)},
                        )
                    else:
                        response = await call_next(request)
            else:
                response = await call_next(request)
        except AppError as exc:
            logger.warning(
                "Application error intercepted by request middleware",
                extra={
                    "request_id": request_id,
                    "event": exc.code,
                    "status_code": exc.status_code,
                },
            )
            response = error_response(
                request,
                status_code=exc.status_code,
                code=exc.code,
                message=exc.message,
                details=exc.details,
                headers=exc.headers,
            )
        except Exception as exc:
            logger.exception(
                "Unhandled exception intercepted by request middleware",
                extra={
                    "request_id": request_id,
                    "event": "internal_error",
                    "exception_type": type(exc).__name__,
                },
            )
            response = error_response(
                request,
                status_code=500,
                code="internal_error",
                message="Внутренняя ошибка сервера",
            )

        duration_ms = round((time.perf_counter() - started_at) * 1_000, 2)
        self._add_response_headers(response, request_id, duration_ms, rate_limit)
        self._log_request(request, response.status_code, duration_ms, client_ip, request_id)
        await self._record_metrics_safely(
            response.status_code,
            duration_ms,
            getattr(request.state, "error_code", None),
            request_id,
        )
        return response

    def _content_length_is_too_large(self, request: Request) -> bool:
        value = request.headers.get("Content-Length")
        if not value:
            return False
        try:
            return int(value) > self.settings.max_request_body_bytes
        except ValueError:
            return False

    async def _actual_body_is_too_large(self, request: Request) -> bool:
        body = await request.body()
        return len(body) > self.settings.max_request_body_bytes

    def _request_too_large_response(self, request: Request) -> Response:
        return error_response(
            request,
            status_code=413,
            code="request_too_large",
            message="Тело запроса превышает допустимый размер",
            details={"max_bytes": self.settings.max_request_body_bytes},
        )

    @staticmethod
    def _add_response_headers(
        response: Response,
        request_id: str,
        duration_ms: float,
        rate_limit: RateLimitDecision | None,
    ) -> None:
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"

        if rate_limit is not None:
            response.headers["X-RateLimit-Limit"] = str(rate_limit.limit)
            response.headers["X-RateLimit-Remaining"] = str(rate_limit.remaining)
            response.headers["X-RateLimit-Reset"] = str(rate_limit.reset_epoch)
            if rate_limit.degraded:
                response.headers["X-RateLimit-Status"] = "degraded"

    def _log_request(
        self,
        request: Request,
        status_code: int,
        duration_ms: float,
        client_ip: str,
        request_id: str,
    ) -> None:
        client_hash = self.rate_limit_service.hash_identifier(client_ip)[:16]
        logger.info(
            "HTTP request completed",
            extra={
                "request_id": request_id,
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_hash": client_hash,
            },
        )

    async def _record_metrics_safely(
        self,
        status_code: int,
        duration_ms: float,
        error_code: str | None,
        request_id: str,
    ) -> None:
        try:
            await self.metrics_repository.record_http_request(
                status_code=status_code,
                duration_ms=duration_ms,
                error_code=error_code,
            )
        except Exception as exc:
            logger.exception(
                "HTTP metrics update failed; response is not affected",
                extra={
                    "request_id": request_id,
                    "event": "metrics_failed",
                    "exception_type": type(exc).__name__,
                },
            )
