from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import get_contact_controller
from app.controllers.contact_controller import ContactController
from app.schemas.common import ErrorResponse
from app.schemas.contact import ContactRequest, ContactResponse

router = APIRouter(prefix="/api", tags=["contact"])


@router.post(
    "/contact",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Отправить обращение",
    description=(
        "Проверяет данные, применяет rate limit, выполняет AI-анализ, "
        "отправляет два SMTP-письма и возвращает результат."
    ),
    responses={
        413: {"model": ErrorResponse, "description": "Слишком большое тело запроса"},
        422: {"model": ErrorResponse, "description": "Ошибка валидации"},
        429: {"model": ErrorResponse, "description": "Превышен rate limit"},
        500: {"model": ErrorResponse, "description": "Внутренняя ошибка"},
        503: {"model": ErrorResponse, "description": "SMTP временно недоступен"},
    },
)
async def create_contact(
    payload: ContactRequest,
    request: Request,
    controller: ContactController = Depends(get_contact_controller),
) -> ContactResponse:
    return await controller.create(payload, request.state.request_id)
