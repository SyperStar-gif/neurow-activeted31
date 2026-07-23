from __future__ import annotations

import json
from typing import ClassVar
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app


def test_root_serves_frontend(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Backend, который доводит запрос" in response.text


def test_health_reports_fallback_and_disabled_email(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {
        "storage": "available",
        "ai": "local_fallback",
        "email": "disabled",
    }


def test_contact_success_with_ai_fallback_and_simulated_email(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    response = client.post("/api/contact", json=valid_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["ai"]["category"] == "project"
    assert body["ai"]["sentiment"] == "positive"
    assert body["ai"]["fallback_used"] is True
    assert body["ai"]["provider"] == "local_fallback"
    assert body["delivery"] == {
        "mode": "simulation",
        "owner": "simulated",
        "user": "simulated",
    }
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert int(response.headers["X-RateLimit-Remaining"]) == 99
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


def test_contact_uses_safe_client_request_id(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    request_id = "postman-demo-001"
    response = client.post(
        "/api/contact",
        json=valid_payload,
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["request_id"] == request_id


def test_invalid_request_id_is_replaced(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    response = client.post(
        "/api/contact",
        json=valid_payload,
        headers={"X-Request-ID": "bad id\r\nInjected: yes"},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] != "bad id\r\nInjected: yes"
    UUID(response.headers["X-Request-ID"])


def test_contact_validation_error_has_safe_shape(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    payload = {**valid_payload, "email": "not-an-email"}
    response = client.post("/api/contact", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["field"] == "email"
    assert "input" not in body["error"]["details"][0]


def test_contact_rejects_extra_fields(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    response = client.post(
        "/api/contact",
        json={**valid_payload, "admin": True},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_contact_rejects_header_injection_in_name(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    response = client.post(
        "/api/contact",
        json={**valid_payload, "name": "Ivan\r\nBcc: victim@example.com"},
    )

    assert response.status_code == 422


def test_contact_rejects_control_character_in_comment(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    response = client.post(
        "/api/contact",
        json={**valid_payload, "comment": "Нормальный текст\u0000скрытый"},
    )

    assert response.status_code == 422


def test_rate_limit_returns_429_with_headers(
    tmp_path,
    valid_payload: dict[str, str],
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins="https://frontend.example",
        email_enabled=False,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    app = create_app(settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post("/api/contact", json=valid_payload)
        second = client.post(
            "/api/contact",
            json=valid_payload,
            headers={"Origin": "https://frontend.example"},
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(second.headers["Retry-After"]) >= 1
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert second.headers["Access-Control-Allow-Origin"] == "https://frontend.example"


def test_request_body_limit_returns_413(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins="https://frontend.example",
        email_enabled=False,
        max_request_body_bytes=1_024,
        rate_limit_requests=100,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    app = create_app(settings)
    payload = {
        "name": "Иван Иванов",
        "phone": "+79991234567",
        "email": "ivan@example.com",
        "comment": "а" * 2_000,
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/contact", json=payload)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_cors_preflight(client: TestClient) -> None:
    response = client.options(
        "/api/contact",
        headers={
            "Origin": "https://frontend.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://frontend.example"


def test_metrics_include_contact_and_http_stats(
    client: TestClient,
    valid_payload: dict[str, str],
) -> None:
    assert client.post("/api/contact", json=valid_payload).status_code == 201
    response = client.get("/api/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["contacts"]["attempts"] == 1
    assert body["contacts"]["successful"] == 1
    assert body["contacts"]["ai_fallbacks"] == 1
    assert body["contacts"]["emails_simulated"] == 2
    assert body["contacts"]["top_category"] == "project"
    assert body["http"]["total_requests"] >= 1
    assert body["metadata"]["contains_personal_data"] is False


def test_unknown_route_uses_global_error_shape(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.headers["X-Request-ID"]


def test_method_not_allowed_preserves_allow_header(client: TestClient) -> None:
    response = client.get("/api/contact")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert "POST" in response.headers["Allow"]


def test_email_misconfiguration_returns_503(
    tmp_path,
    valid_payload: dict[str, str],
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        email_enabled=True,
        smtp_host=None,
        smtp_from_email="no-reply@example.com",
        owner_email="owner@example.com",
        rate_limit_requests=100,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    app = create_app(settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/api/health")
        response = client.post("/api/contact", json=valid_payload)

    assert health.json()["status"] == "degraded"
    assert health.json()["checks"]["email"] == "misconfigured"
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "email_configuration_error"


def test_unexpected_controller_error_returns_safe_500(
    app,
    valid_payload: dict[str, str],
) -> None:
    class BrokenController:
        async def create(self, payload, request_id):
            raise RuntimeError("sensitive internal detail")

    app.state.container.contact_controller = BrokenController()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/contact", json=valid_payload)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive" not in response.text


def test_request_is_written_to_json_log(
    client: TestClient,
    settings: Settings,
) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200

    records = [
        json.loads(line)
        for line in settings.log_file.read_text(encoding="utf-8").splitlines()
    ]
    request_records = [
        record for record in records if record["message"] == "HTTP request completed"
    ]
    assert request_records
    assert request_records[-1]["path"] == "/api/health"
    assert request_records[-1]["status_code"] == 200
    assert "client_hash" in request_records[-1]
    assert "ivan@example.com" not in settings.log_file.read_text(encoding="utf-8")



def test_openapi_contains_required_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    contact = schema["paths"]["/api/contact"]["post"]
    assert contact["responses"]["201"]
    assert contact["responses"]["422"]
    assert contact["responses"]["429"]
    assert contact["responses"]["503"]
    assert "/api/health" in schema["paths"]
    assert "/api/metrics" in schema["paths"]


def test_malformed_json_uses_validation_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/contact",
        content=b'{"name":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_rate_limit_storage_fail_closed_returns_503(
    tmp_path,
    valid_payload: dict[str, str],
) -> None:
    class BrokenRepository:
        async def consume(self, *args, **kwargs):
            raise OSError("disk unavailable")

    settings = Settings(
        _env_file=None,
        app_env="test",
        email_enabled=False,
        rate_limit_requests=100,
        rate_limit_fail_open=False,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    app = create_app(settings)
    app.state.container.rate_limit_service.repository = BrokenRepository()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/contact", json=valid_payload)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rate_limit_storage_error"


def test_rate_limit_storage_fail_open_marks_degraded(
    tmp_path,
    valid_payload: dict[str, str],
) -> None:
    class BrokenRepository:
        async def consume(self, *args, **kwargs):
            raise OSError("disk unavailable")

    settings = Settings(
        _env_file=None,
        app_env="test",
        email_enabled=False,
        rate_limit_requests=100,
        rate_limit_fail_open=True,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    app = create_app(settings)
    app.state.container.rate_limit_service.repository = BrokenRepository()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/contact", json=valid_payload)

    assert response.status_code == 201
    assert response.headers["X-RateLimit-Status"] == "degraded"


def test_contact_full_cycle_sends_two_smtp_messages(
    tmp_path,
    monkeypatch,
    valid_payload: dict[str, str],
) -> None:
    class FakeSMTP:
        instances: ClassVar[list["FakeSMTP"]] = []

        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.messages = []
            self.__class__.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def ehlo(self):
            return 250, b"ok"

        def starttls(self, context=None):
            return 220, b"ready"

        def login(self, username, password):
            return 235, b"authenticated"

        def send_message(self, message, from_addr=None, to_addrs=None):
            self.messages.append((message, from_addr, to_addrs))
            return {}

    monkeypatch.setattr("app.services.email_service.smtplib.SMTP", FakeSMTP)
    settings = Settings(
        _env_file=None,
        app_env="test",
        email_enabled=True,
        smtp_host="smtp.example.com",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
        smtp_from_email="sender@example.com",
        owner_email="owner@example.com",
        rate_limit_requests=100,
        rate_limit_hash_salt="test-only-salt",
        rate_limit_file=tmp_path / "rate.json",
        metrics_file=tmp_path / "metrics.json",
        log_file=tmp_path / "app.log",
    )
    app = create_app(settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/contact", json=valid_payload)

    assert response.status_code == 201
    assert response.json()["delivery"] == {
        "mode": "smtp",
        "owner": "sent",
        "user": "sent",
    }
    assert len(FakeSMTP.instances) == 1
    assert [message[2] for message in FakeSMTP.instances[0].messages] == [
        ["owner@example.com"],
        ["ivan@example.com"],
    ]
