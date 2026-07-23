from __future__ import annotations

import smtplib
from typing import ClassVar

import pytest

from app.core.config import Settings
from app.core.exceptions import EmailConfigurationError, EmailDeliveryError
from app.schemas.contact import AIResult, ContactRequest
from app.services.email_service import EmailService


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host, port, timeout, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.kwargs = kwargs
        self.ehlo_calls = 0
        self.starttls_calls = 0
        self.login_calls = []
        self.messages = []
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def ehlo(self):
        self.ehlo_calls += 1
        return 250, b"ok"

    def starttls(self, *, context):
        assert context is not None
        self.starttls_calls += 1
        return 220, b"ready"

    def login(self, username, password):
        self.login_calls.append((username, password))
        return 235, b"ok"

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.messages.append((message, from_addr, to_addrs))
        return {}


@pytest.fixture
def contact() -> ContactRequest:
    return ContactRequest(
        name="Ivan Ivanov",
        phone="+79991234567",
        email="ivan@example.com",
        comment="I would like to discuss an API project.",
    )


@pytest.fixture
def ai() -> AIResult:
    return AIResult(
        category="project",
        sentiment="positive",
        priority="normal",
        summary="API project request",
        suggested_reply="Thank you for the details.",
        fallback_used=False,
        provider="openai",
    )


def enabled_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "email_enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "smtp-user",
        "smtp_password": "smtp-password",
        "smtp_from_email": "sender@example.com",
        "smtp_from_name": "Developer",
        "owner_email": "owner@example.com",
        "smtp_security": "starttls",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_email_service_sends_owner_and_user_messages(monkeypatch, contact, ai) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr("app.services.email_service.smtplib.SMTP", FakeSMTP)
    service = EmailService(enabled_settings())

    result = await service.send_contact_emails(contact, ai, "request-id")

    assert result.mode == "smtp"
    assert result.owner == "sent"
    assert result.user == "sent"
    smtp = FakeSMTP.instances[0]
    assert smtp.starttls_calls == 1
    assert smtp.ehlo_calls == 2
    assert smtp.login_calls == [("smtp-user", "smtp-password")]
    assert len(smtp.messages) == 2
    assert smtp.messages[0][1:] == ("sender@example.com", ["owner@example.com"])
    assert smtp.messages[1][1:] == ("sender@example.com", ["ivan@example.com"])
    assert smtp.messages[0][0]["Reply-To"] == "ivan@example.com"
    assert smtp.messages[0][0]["X-Request-ID"] == "request-id"
    assert smtp.messages[0][0]["Date"]
    assert smtp.messages[0][0]["Message-ID"]


@pytest.mark.asyncio
async def test_email_service_simulates_when_disabled(contact, ai) -> None:
    service = EmailService(Settings(_env_file=None, app_env="test", email_enabled=False))

    result = await service.send_contact_emails(contact, ai, "request-id")

    assert result.mode == "simulation"
    assert result.owner == "simulated"
    assert result.user == "simulated"


@pytest.mark.asyncio
async def test_ssl_uses_smtp_ssl_without_starttls(monkeypatch, contact, ai) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr("app.services.email_service.smtplib.SMTP_SSL", FakeSMTP)
    service = EmailService(enabled_settings(smtp_security="ssl", smtp_port=465))

    result = await service.send_contact_emails(contact, ai, "request-id")

    assert result.mode == "smtp"
    smtp = FakeSMTP.instances[0]
    assert smtp.starttls_calls == 0
    assert smtp.kwargs["context"] is not None


@pytest.mark.asyncio
async def test_no_auth_mode_does_not_login(monkeypatch, contact, ai) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr("app.services.email_service.smtplib.SMTP", FakeSMTP)
    service = EmailService(
        enabled_settings(
            smtp_username=None,
            smtp_password=None,
            smtp_security="none",
        )
    )

    await service.send_contact_emails(contact, ai, "request-id")

    smtp = FakeSMTP.instances[0]
    assert smtp.login_calls == []
    assert smtp.starttls_calls == 0


@pytest.mark.asyncio
async def test_misconfigured_email_raises_before_connection(contact, ai) -> None:
    service = EmailService(enabled_settings(smtp_host=None))

    with pytest.raises(EmailConfigurationError):
        await service.send_contact_emails(contact, ai, "request-id")


@pytest.mark.asyncio
async def test_email_service_attempts_both_messages_and_wraps_failures(
    monkeypatch,
    contact,
    ai,
) -> None:
    class PartiallyFailingSMTP(FakeSMTP):
        def send_message(self, message, from_addr=None, to_addrs=None):
            self.messages.append((message, from_addr, to_addrs))
            if to_addrs == ["owner@example.com"]:
                raise smtplib.SMTPServerDisconnected("connection lost")
            return {}

    PartiallyFailingSMTP.instances.clear()
    monkeypatch.setattr("app.services.email_service.smtplib.SMTP", PartiallyFailingSMTP)
    service = EmailService(enabled_settings())

    with pytest.raises(EmailDeliveryError) as exc_info:
        await service.send_contact_emails(contact, ai, "request-id")

    assert len(PartiallyFailingSMTP.instances[0].messages) == 2
    assert exc_info.value.details == {"failed_messages": ["owner"]}


@pytest.mark.asyncio
async def test_connection_failure_is_public_503(monkeypatch, contact, ai) -> None:
    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr("app.services.email_service.smtplib.SMTP", BrokenSMTP)
    service = EmailService(enabled_settings())

    with pytest.raises(EmailDeliveryError) as exc_info:
        await service.send_contact_emails(contact, ai, "request-id")

    assert exc_info.value.status_code == 503
    assert "connection refused" not in exc_info.value.message


def test_email_content_escapes_html(contact, ai) -> None:
    malicious = ContactRequest(
        name="Ivan Ivanov",
        phone="+79991234567",
        email="ivan@example.com",
        comment="<script>alert('x')</script>",
    )
    owner, user = EmailService(enabled_settings())._build_messages(
        malicious,
        ai,
        "request-id",
    )

    owner_html = owner.get_payload()[1].get_content()
    assert "<script>" not in owner_html
    assert "&lt;script&gt;" in owner_html
    assert user["To"] == "ivan@example.com"
