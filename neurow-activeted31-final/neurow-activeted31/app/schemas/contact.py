from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ContactCategory = Literal["project", "consultation", "job", "support", "spam", "other"]
ContactSentiment = Literal["positive", "neutral", "negative"]
ContactPriority = Literal["low", "normal", "high"]


def _contains_forbidden_control(value: str, *, allow_newlines: bool = False) -> bool:
    for character in value:
        if allow_newlines and character in {"\n", "\t"}:
            continue
        if unicodedata.category(character) in {"Cc", "Cf"}:
            return True
    return False


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=100, examples=["Иван Иванов"])
    phone: str = Field(min_length=7, max_length=25, examples=["+7 999 123-45-67"])
    email: EmailStr = Field(examples=["ivan@example.com"])
    comment: str = Field(
        min_length=5,
        max_length=3_000,
        examples=["Хочу обсудить разработку интернет-магазина."],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _contains_forbidden_control(value):
            raise ValueError("name contains forbidden control characters")
        normalized = " ".join(value.split())
        if sum(character.isalpha() for character in normalized) < 2:
            raise ValueError("name must contain at least two letters")
        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not re.fullmatch(r"[+()\-\s\d]{7,25}", normalized):
            raise ValueError("phone contains unsupported characters")
        digits = re.sub(r"\D", "", normalized)
        if not 7 <= len(digits) <= 15:
            raise ValueError("phone must contain between 7 and 15 digits")
        return normalized

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if _contains_forbidden_control(normalized, allow_newlines=True):
            raise ValueError("comment contains forbidden control characters")
        lines = [" ".join(line.split()) for line in normalized.splitlines()]
        cleaned = "\n".join(line for line in lines if line).strip()
        if len(cleaned) < 5:
            raise ValueError("comment must contain at least 5 characters")
        return cleaned


class AIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ContactCategory
    sentiment: ContactSentiment
    priority: ContactPriority
    summary: str = Field(min_length=1, max_length=300)
    suggested_reply: str = Field(min_length=1, max_length=500)
    fallback_used: bool = False
    provider: Literal["openai", "local_fallback"]


class EmailDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["smtp", "simulation"]
    owner: Literal["sent", "simulated"]
    user: Literal["sent", "simulated"]


class ContactResponse(BaseModel):
    success: bool = True
    message: str
    request_id: str
    ai: AIResult
    delivery: EmailDelivery
