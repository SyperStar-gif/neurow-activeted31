from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import contact, system
from app.container import ApplicationContainer
from app.core.config import Settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.middleware.request_context import RequestContextMiddleware

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    *,
    container: ApplicationContainer | None = None,
) -> FastAPI:
    settings.ensure_directories()
    configure_logging(settings)
    application_container = container or ApplicationContainer.build(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info(
            "Application started",
            extra={
                "app_name": settings.app_name,
                "app_version": settings.app_version,
                "environment": settings.app_env,
            },
        )
        yield
        logger.info("Application stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.app_debug,
        description=(
            "Backend API для формы обратной связи лендинга разработчика: "
            "валидация, AI-анализ, SMTP, rate limiting, метрики и файловое логирование."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.container = application_container

    app.add_middleware(GZipMiddleware, minimum_size=1_000)
    app.add_middleware(
        RequestContextMiddleware,
        settings=settings,
        rate_limit_service=application_container.rate_limit_service,
        metrics_repository=application_container.metrics_repository,
    )
    # Added last so CORS is outermost and also covers middleware-generated 413/429 responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-Process-Time-Ms",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-RateLimit-Status",
        ],
        max_age=600,
    )

    register_exception_handlers(app)
    app.include_router(contact.router)
    app.include_router(system.router)

    frontend_directory = Path(__file__).resolve().parent.parent / "frontend"
    static_directory = frontend_directory / "static"
    if static_directory.is_dir():
        app.mount("/static", StaticFiles(directory=static_directory), name="static")

    @app.get("/", include_in_schema=False)
    async def landing_page():
        index_file = frontend_directory / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return JSONResponse(
            {
                "name": settings.app_name,
                "version": settings.app_version,
                "docs": "/docs",
                "health": "/api/health",
            }
        )

    return app
