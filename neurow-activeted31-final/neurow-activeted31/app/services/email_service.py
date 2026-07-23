from __future__ import annotations

import asyncio
import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Literal

from app.core.config import Settings
from app.core.exceptions import EmailConfigurationError, EmailDeliveryError
from app.core.security import safe_header_text
from app.schemas.contact import AIResult, ContactRequest, EmailDelivery

logger = logging.getLogger(__name__)

EmailConfigurationStatus = Literal["disabled", "configured", "misconfigured"]


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configuration_status(self) -> EmailConfigurationStatus:
        if not self.settings.email_enabled:
            return "disabled"
        if not self.settings.smtp_host:
            return "misconfigured"
        if bool(self.settings.smtp_username) != bool(self.settings.smtp_password_value):
            return "misconfigured"
        return "configured"

    async def send_contact_emails(
        self,
        contact: ContactRequest,
        ai: AIResult,
        request_id: str,
    ) -> EmailDelivery:
        status = self.configuration_status()
        if status == "disabled":
            logger.info(
                "Email delivery disabled; both messages simulated",
                extra={"request_id": request_id, "event": "email_simulated"},
            )
            return EmailDelivery(mode="simulation", owner="simulated", user="simulated")
        if status == "misconfigured":
            raise EmailConfigurationError(
                "Email-сервис настроен не полностью",
                details={"required": ["SMTP_HOST"]},
            )

        try:
            return await asyncio.to_thread(self._send_sync, contact, ai, request_id)
        except EmailDeliveryError:
            raise
        except Exception as exc:
            logger.exception(
                "Unexpected email delivery failure",
                extra={
                    "request_id": request_id,
                    "event": "email_failed",
                    "exception_type": type(exc).__name__,
                },
            )
            raise EmailDeliveryError(
                "Не удалось отправить email-уведомления"
            ) from exc

    def _send_sync(
        self,
        contact: ContactRequest,
        ai: AIResult,
        request_id: str,
    ) -> EmailDelivery:
        owner_message, user_message = self._build_messages(contact, ai, request_id)
        failures: list[str] = []

        try:
            with self._open_connection() as smtp:
                if self.settings.smtp_security != "ssl":
                    smtp.ehlo()
                if self.settings.smtp_security == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if self.settings.smtp_username:
                    smtp.login(
                        self.settings.smtp_username,
                        self.settings.smtp_password_value or "",
                    )

                for kind, message, recipient in (
                    ("owner", owner_message, str(self.settings.owner_email)),
                    ("user", user_message, str(contact.email)),
                ):
                    try:
                        refused = smtp.send_message(
                            message,
                            from_addr=str(self.settings.smtp_from_email),
                            to_addrs=[recipient],
                        )
                        if refused:
                            raise smtplib.SMTPRecipientsRefused(refused)
                        logger.info(
                            "Email message sent",
                            extra={
                                "request_id": request_id,
                                "event": "email_sent",
                                "email_kind": kind,
                            },
                        )
                    except Exception as exc:
                        failures.append(kind)
                        logger.exception(
                            "Email message failed",
                            extra={
                                "request_id": request_id,
                                "event": "email_failed",
                                "email_kind": kind,
                                "exception_type": type(exc).__name__,
                            },
                        )
        except EmailDeliveryError:
            raise
        except Exception as exc:
            logger.exception(
                "SMTP connection or authentication failed",
                extra={
                    "request_id": request_id,
                    "event": "smtp_failed",
                    "exception_type": type(exc).__name__,
                },
            )
            raise EmailDeliveryError(
                "SMTP-сервис временно недоступен",
                details={"failed_messages": ["owner", "user"]},
            ) from exc

        if failures:
            raise EmailDeliveryError(
                "Не удалось отправить одно или несколько email-уведомлений",
                details={"failed_messages": failures},
            )
        return EmailDelivery(mode="smtp", owner="sent", user="sent")

    def _open_connection(self) -> smtplib.SMTP:
        host = self.settings.smtp_host
        if not host:
            raise EmailConfigurationError("SMTP_HOST не настроен")
        if self.settings.smtp_security == "ssl":
            return smtplib.SMTP_SSL(
                host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
                context=ssl.create_default_context(),
            )
        return smtplib.SMTP(
            host,
            self.settings.smtp_port,
            timeout=self.settings.smtp_timeout_seconds,
        )

    def _build_messages(
        self,
        contact: ContactRequest,
        ai: AIResult,
        request_id: str,
    ) -> tuple[EmailMessage, EmailMessage]:
        from_value = formataddr(
            (
                safe_header_text(self.settings.smtp_from_name, max_length=100),
                str(self.settings.smtp_from_email),
            )
        )

        owner = EmailMessage()
        owner["Subject"] = safe_header_text(
            f"Новое обращение: {contact.name} [{ai.category}]"
        )
        owner["From"] = from_value
        owner["To"] = str(self.settings.owner_email)
        owner["Reply-To"] = str(contact.email)
        owner["Date"] = formatdate(localtime=False)
        owner["Message-ID"] = make_msgid()
        owner["X-Request-ID"] = safe_header_text(request_id, max_length=128)
        owner_plain = (
            f"Request ID: {request_id}\n"
            f"Имя: {contact.name}\n"
            f"Телефон: {contact.phone}\n"
            f"Email: {contact.email}\n"
            f"Категория: {ai.category}\n"
            f"Тональность: {ai.sentiment}\n"
            f"Приоритет: {ai.priority}\n"
            f"Кратко: {ai.summary}\n\n"
            f"Комментарий:\n{contact.comment}\n"
        )
        owner.set_content(owner_plain)
        owner.add_alternative(
            "<h2>Новое обращение</h2>"
            f"<p><strong>Request ID:</strong> {html.escape(request_id)}</p>"
            f"<p><strong>Имя:</strong> {html.escape(contact.name)}<br>"
            f"<strong>Телефон:</strong> {html.escape(contact.phone)}<br>"
            f"<strong>Email:</strong> {html.escape(str(contact.email))}<br>"
            f"<strong>Категория:</strong> {html.escape(ai.category)}<br>"
            f"<strong>Тональность:</strong> {html.escape(ai.sentiment)}<br>"
            f"<strong>Приоритет:</strong> {html.escape(ai.priority)}</p>"
            f"<p><strong>Кратко:</strong> {html.escape(ai.summary)}</p>"
            f"<p><strong>Комментарий:</strong><br>"
            f"{html.escape(contact.comment).replace(chr(10), '<br>')}</p>",
            subtype="html",
        )

        user = EmailMessage()
        user["Subject"] = "Ваше обращение получено"
        user["From"] = from_value
        user["To"] = str(contact.email)
        user["Date"] = formatdate(localtime=False)
        user["Message-ID"] = make_msgid()
        user["X-Request-ID"] = safe_header_text(request_id, max_length=128)
        user_plain = (
            f"Здравствуйте, {contact.name}!\n\n"
            f"{ai.suggested_reply}\n\n"
            f"Номер обращения: {request_id}\n"
        )
        user.set_content(user_plain)
        user.add_alternative(
            f"<p>Здравствуйте, {html.escape(contact.name)}!</p>"
            f"<p>{html.escape(ai.suggested_reply)}</p>"
            f"<p><strong>Номер обращения:</strong> {html.escape(request_id)}</p>",
            subtype="html",
        )
        return owner, user
