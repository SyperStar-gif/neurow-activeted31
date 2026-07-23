from __future__ import annotations

import logging
from dataclasses import dataclass

from app.repositories.metrics_repository import MetricsRepository
from app.schemas.contact import AIResult, ContactRequest, EmailDelivery
from app.services.ai_service import AIService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContactProcessingResult:
    ai: AIResult
    delivery: EmailDelivery


class ContactService:
    def __init__(
        self,
        ai_service: AIService,
        email_service: EmailService,
        metrics_repository: MetricsRepository,
    ) -> None:
        self.ai_service = ai_service
        self.email_service = email_service
        self.metrics_repository = metrics_repository

    async def process(
        self,
        contact: ContactRequest,
        request_id: str,
    ) -> ContactProcessingResult:
        await self._record_attempt_safely(request_id)
        try:
            ai = await self.ai_service.analyze(contact, request_id)
            delivery = await self.email_service.send_contact_emails(
                contact,
                ai,
                request_id,
            )
            await self._record_success_safely(ai, delivery, request_id)
            return ContactProcessingResult(ai=ai, delivery=delivery)
        except Exception:
            await self._record_failure_safely(request_id)
            raise

    async def _record_attempt_safely(self, request_id: str) -> None:
        try:
            await self.metrics_repository.record_contact_attempt()
        except Exception as exc:
            logger.exception(
                "Contact attempt metric failed; request continues",
                extra={
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                },
            )

    async def _record_success_safely(
        self,
        ai: AIResult,
        delivery: EmailDelivery,
        request_id: str,
    ) -> None:
        try:
            await self.metrics_repository.record_contact_success(ai, delivery)
        except Exception as exc:
            logger.exception(
                "Contact success metric failed; response is not affected",
                extra={
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                },
            )

    async def _record_failure_safely(self, request_id: str) -> None:
        try:
            await self.metrics_repository.record_contact_failure()
        except Exception as exc:
            logger.exception(
                "Contact failure metric failed",
                extra={
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                },
            )
