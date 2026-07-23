from __future__ import annotations

from app.schemas.contact import ContactRequest, ContactResponse
from app.services.contact_service import ContactService


class ContactController:
    def __init__(self, contact_service: ContactService) -> None:
        self.contact_service = contact_service

    async def create(self, payload: ContactRequest, request_id: str) -> ContactResponse:
        result = await self.contact_service.process(payload, request_id)
        return ContactResponse(
            message="Обращение успешно обработано",
            request_id=request_id,
            ai=result.ai,
            delivery=result.delivery,
        )
