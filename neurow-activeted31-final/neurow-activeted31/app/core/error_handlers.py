from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


def request_id_from(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request.state.error_code = code
    response_headers = {"X-Request-ID": request_id_from(request), **(headers or {})}
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details if details is not None else {},
            },
            "request_id": request_id_from(request),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "Handled application error",
            extra={
                "request_id": request_id_from(request),
                "event": exc.code,
                "status_code": exc.status_code,
            },
        )
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details: list[dict[str, Any]] = []
        for error in exc.errors():
            location = tuple(error.get("loc") or ("unknown",))
            details.append(
                {
                    "location": [str(part) for part in location],
                    "field": str(location[-1]),
                    "message": error.get("msg", "Invalid value"),
                    "type": error.get("type", "value_error"),
                }
            )
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Некорректные входные данные",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if exc.status_code == 404:
            code, message = "not_found", "Ресурс не найден"
        elif exc.status_code == 405:
            code, message = "method_not_allowed", "Метод не поддерживается"
        else:
            code, message = "http_error", "Ошибка HTTP-запроса"
        return error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            headers=dict(exc.headers or {}),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception",
            extra={
                "request_id": request_id_from(request),
                "event": "internal_error",
                "exception_type": type(exc).__name__,
            },
        )
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Внутренняя ошибка сервера",
        )
