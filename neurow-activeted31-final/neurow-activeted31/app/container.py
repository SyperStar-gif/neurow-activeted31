from __future__ import annotations

from dataclasses import dataclass

from app.controllers.contact_controller import ContactController
from app.core.config import Settings
from app.repositories.metrics_repository import MetricsRepository
from app.repositories.rate_limit_repository import RateLimitRepository
from app.services.ai_service import AIService
from app.services.contact_service import ContactService
from app.services.email_service import EmailService
from app.services.rate_limit_service import RateLimitService


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    metrics_repository: MetricsRepository
    rate_limit_service: RateLimitService
    email_service: EmailService
    contact_controller: ContactController

    @classmethod
    def build(cls, settings: Settings) -> "ApplicationContainer":
        metrics_repository = MetricsRepository(
            settings.metrics_file,
            lock_timeout=settings.file_lock_timeout_seconds,
        )
        rate_limit_repository = RateLimitRepository(
            settings.rate_limit_file,
            lock_timeout=settings.file_lock_timeout_seconds,
        )
        rate_limit_service = RateLimitService(rate_limit_repository, settings)
        ai_service = AIService(settings)
        email_service = EmailService(settings)
        contact_service = ContactService(
            ai_service,
            email_service,
            metrics_repository,
        )
        return cls(
            settings=settings,
            metrics_repository=metrics_repository,
            rate_limit_service=rate_limit_service,
            email_service=email_service,
            contact_controller=ContactController(contact_service),
        )
