from __future__ import annotations

from fastapi import Request

from app.container import ApplicationContainer
from app.controllers.contact_controller import ContactController
from app.repositories.metrics_repository import MetricsRepository
from app.services.email_service import EmailService


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def get_contact_controller(request: Request) -> ContactController:
    return get_container(request).contact_controller


def get_metrics_repository(request: Request) -> MetricsRepository:
    return get_container(request).metrics_repository


def get_email_service(request: Request) -> EmailService:
    return get_container(request).email_service
