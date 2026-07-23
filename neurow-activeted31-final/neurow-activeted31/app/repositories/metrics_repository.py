from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.repositories.json_file_repository import JsonFileRepository
from app.schemas.contact import AIResult, EmailDelivery

DEFAULT_METRICS: dict[str, Any] = {
    "schema_version": 1,
    "http": {
        "total_requests": 0,
        "status_codes": {},
        "total_response_time_ms": 0.0,
        "last_request_at": None,
    },
    "contacts": {
        "attempts": 0,
        "successful": 0,
        "failed": 0,
        "ai_fallbacks": 0,
        "email_messages_sent": 0,
        "emails_simulated": 0,
        "categories": {},
        "sentiments": {},
        "last_contact_at": None,
    },
    "errors": {},
}


class MetricsRepository:
    def __init__(self, path: Path, *, lock_timeout: float = 5.0) -> None:
        self.storage = JsonFileRepository(
            path,
            DEFAULT_METRICS,
            lock_timeout=lock_timeout,
        )

    async def record_http_request(
        self,
        *,
        status_code: int,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            http = data.setdefault("http", {})
            http["total_requests"] = int(http.get("total_requests", 0)) + 1
            http["total_response_time_ms"] = round(
                float(http.get("total_response_time_ms", 0.0)) + duration_ms,
                4,
            )
            http["last_request_at"] = datetime.now(UTC).isoformat()
            status_codes = http.setdefault("status_codes", {})
            key = str(status_code)
            status_codes[key] = int(status_codes.get(key, 0)) + 1
            if error_code:
                errors = data.setdefault("errors", {})
                errors[error_code] = int(errors.get(error_code, 0)) + 1

        await self.storage.update(mutate)

    async def record_contact_attempt(self) -> None:
        await self.storage.update(
            lambda data: data.setdefault("contacts", {}).__setitem__(
                "attempts",
                int(data.setdefault("contacts", {}).get("attempts", 0)) + 1,
            )
        )

    async def record_contact_success(
        self,
        ai: AIResult,
        delivery: EmailDelivery,
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            contacts = data.setdefault("contacts", {})
            contacts["successful"] = int(contacts.get("successful", 0)) + 1
            contacts["last_contact_at"] = datetime.now(UTC).isoformat()
            if ai.fallback_used:
                contacts["ai_fallbacks"] = int(contacts.get("ai_fallbacks", 0)) + 1

            categories = contacts.setdefault("categories", {})
            categories[ai.category] = int(categories.get(ai.category, 0)) + 1
            sentiments = contacts.setdefault("sentiments", {})
            sentiments[ai.sentiment] = int(sentiments.get(ai.sentiment, 0)) + 1

            if delivery.mode == "smtp":
                contacts["email_messages_sent"] = (
                    int(contacts.get("email_messages_sent", 0)) + 2
                )
            else:
                contacts["emails_simulated"] = int(contacts.get("emails_simulated", 0)) + 2

        await self.storage.update(mutate)

    async def record_contact_failure(self) -> None:
        await self.storage.update(
            lambda data: data.setdefault("contacts", {}).__setitem__(
                "failed",
                int(data.setdefault("contacts", {}).get("failed", 0)) + 1,
            )
        )

    async def snapshot(self) -> dict[str, Any]:
        data = await self.storage.read()
        http = data.get("http", {})
        contacts = data.get("contacts", {})
        total_requests = int(http.get("total_requests", 0))
        total_time = float(http.get("total_response_time_ms", 0.0))
        categories = dict(contacts.get("categories", {}))
        top_category = (
            max(categories.items(), key=lambda item: item[1])[0]
            if categories
            else None
        )
        return {
            "http": {
                "total_requests": total_requests,
                "status_codes": dict(http.get("status_codes", {})),
                "average_response_time_ms": (
                    round(total_time / total_requests, 2) if total_requests else 0.0
                ),
                "last_request_at": http.get("last_request_at"),
            },
            "contacts": {
                "attempts": int(contacts.get("attempts", 0)),
                "successful": int(contacts.get("successful", 0)),
                "failed": int(contacts.get("failed", 0)),
                "ai_fallbacks": int(contacts.get("ai_fallbacks", 0)),
                "email_messages_sent": int(contacts.get("email_messages_sent", 0)),
                "emails_simulated": int(contacts.get("emails_simulated", 0)),
                "categories": categories,
                "sentiments": dict(contacts.get("sentiments", {})),
                "top_category": top_category,
                "last_contact_at": contacts.get("last_contact_at"),
            },
            "errors": dict(data.get("errors", {})),
            "metadata": {
                "schema_version": int(data.get("schema_version", 1)),
                "contains_personal_data": False,
            },
        }
