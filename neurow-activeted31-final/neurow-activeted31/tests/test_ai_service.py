from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.schemas.contact import ContactRequest
from app.services.ai_service import AIService


def contact() -> ContactRequest:
    return ContactRequest(
        name="Иван Иванов",
        phone="+79991234567",
        email="ivan@example.com",
        comment="Хочу обсудить разработку API, спасибо!",
    )


@pytest.mark.asyncio
async def test_no_api_key_uses_local_fallback() -> None:
    settings = Settings(_env_file=None, app_env="test", openai_api_key=None)
    result = await AIService(settings).analyze(contact(), "request-id")

    assert result.fallback_used is True
    assert result.provider == "local_fallback"
    assert result.category == "project"
    assert result.sentiment == "positive"


@pytest.mark.asyncio
async def test_structured_openai_response_is_validated_and_excludes_pii() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        serialized = request.content.decode("utf-8")
        assert "ivan@example.com" not in serialized
        assert "+79991234567" not in serialized
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "category": "project",
                        "sentiment": "positive",
                        "priority": "normal",
                        "summary": "Запрос на разработку API",
                        "suggested_reply": "Спасибо! Я изучу задачу и свяжусь с вами.",
                    },
                    ensure_ascii=False,
                )
            },
        )

    settings = Settings(
        _env_file=None,
        app_env="test",
        openai_api_key="test-key",
    )
    service = AIService(settings, transport=httpx.MockTransport(handler))

    result = await service.analyze(contact(), "request-id")

    assert result.category == "project"
    assert result.fallback_used is False
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_ai_service_reads_nested_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "category": "consultation",
                                        "sentiment": "neutral",
                                        "priority": "normal",
                                        "summary": "Нужна консультация",
                                        "suggested_reply": "Спасибо! Я свяжусь с вами.",
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ]
                    }
                ]
            },
        )

    settings = Settings(_env_file=None, app_env="test", openai_api_key="test-key")
    result = await AIService(
        settings,
        transport=httpx.MockTransport(handler),
    ).analyze(contact(), "request-id")

    assert result.category == "consultation"
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_ai_service_falls_back_on_invalid_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "not-json"})

    settings = Settings(_env_file=None, app_env="test", openai_api_key="test-key")
    service = AIService(settings, transport=httpx.MockTransport(handler))

    result = await service.analyze(contact(), "request-id")

    assert result.fallback_used is True
    assert result.category == "project"


@pytest.mark.asyncio
async def test_ai_service_falls_back_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    settings = Settings(_env_file=None, app_env="test", openai_api_key="test-key")
    service = AIService(settings, transport=httpx.MockTransport(handler))

    result = await service.analyze(contact(), "request-id")

    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_ai_service_falls_back_on_refusal() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": [{"content": [{"type": "refusal", "refusal": "no"}]}]},
        )

    settings = Settings(_env_file=None, app_env="test", openai_api_key="test-key")
    result = await AIService(
        settings,
        transport=httpx.MockTransport(handler),
    ).analyze(contact(), "request-id")

    assert result.provider == "local_fallback"


def test_strip_code_fence() -> None:
    assert AIService.strip_code_fence("```json\n{\"a\": 1}\n```") == '{"a": 1}'


def test_support_fallback_is_high_priority() -> None:
    result = AIService.fallback("Срочно: сайт не работает, ужасная проблема")

    assert result.category == "support"
    assert result.sentiment == "negative"
    assert result.priority == "high"


def test_spam_fallback_is_low_priority() -> None:
    result = AIService.fallback("Лучшее казино и быстрый заработок")

    assert result.category == "spam"
    assert result.priority == "low"


def test_fallback_prefers_job_over_generic_development_keyword() -> None:
    result = AIService.fallback(
        "Есть вакансия Python-разработчика, хотим пригласить вас в команду."
    )

    assert result.category == "job"
