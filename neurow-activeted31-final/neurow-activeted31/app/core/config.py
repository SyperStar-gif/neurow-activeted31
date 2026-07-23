from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_RATE_LIMIT_SALT = "developer-landing-rate-limit"
_EXAMPLE_RATE_LIMIT_SALT = "replace-with-a-random-secret"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and `.env`."""

    app_name: str = "Developer Landing API"
    app_version: str = "1.0.0"
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = False
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    trust_proxy_headers: bool = False
    max_request_body_bytes: int = Field(default=32_768, ge=1_024, le=1_048_576)

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = Field(default=12.0, gt=0, le=120)
    ai_max_output_tokens: int = Field(default=350, ge=64, le=2_000)

    email_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65_535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: EmailStr = "no-reply@example.com"
    smtp_from_name: str = Field(default="Developer Landing", min_length=1, max_length=100)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    owner_email: EmailStr = "owner@example.com"

    rate_limit_requests: int = Field(default=5, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=3_600, ge=1, le=86_400)
    rate_limit_fail_open: bool = True
    rate_limit_file: Path = Path("data/rate_limits.json")
    rate_limit_hash_salt: SecretStr = SecretStr(_DEFAULT_RATE_LIMIT_SALT)

    metrics_file: Path = Path("data/metrics.json")
    log_file: Path = Path("logs/app.log")
    file_lock_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("openai_api_key", "smtp_password", mode="before")
    @classmethod
    def blank_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("smtp_host", "smtp_username", mode="before")
    @classmethod
    def blank_string_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("openai_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("OPENAI_BASE_URL must start with http:// or https://")
        return normalized

    @field_validator("rate_limit_hash_salt", mode="before")
    @classmethod
    def validate_rate_limit_salt(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("RATE_LIMIT_HASH_SALT must not be blank")
            return normalized
        return value

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
        if self.app_env == "production" and self.app_debug:
            raise ValueError("APP_DEBUG must be false in production")
        if (
            self.app_env == "production"
            and self.smtp_username
            and self.smtp_security == "none"
        ):
            raise ValueError(
                "SMTP_SECURITY=none cannot be used with authentication in production"
            )
        if self.app_env == "production":
            salt = self.rate_limit_salt
            if len(salt) < 24 or salt in {
                _DEFAULT_RATE_LIMIT_SALT,
                _EXAMPLE_RATE_LIMIT_SALT,
            }:
                raise ValueError(
                    "RATE_LIMIT_HASH_SALT must be a random secret of at least "
                    "24 characters in production"
                )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [
            item.strip().rstrip("/")
            for item in self.cors_origins.split(",")
            if item.strip()
        ]
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must use an explicit allowlist")
        return list(dict.fromkeys(origins))

    @property
    def openai_api_key_value(self) -> str | None:
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    @property
    def smtp_password_value(self) -> str | None:
        return self.smtp_password.get_secret_value() if self.smtp_password else None

    @property
    def rate_limit_salt(self) -> str:
        return self.rate_limit_hash_salt.get_secret_value()

    def ensure_directories(self) -> None:
        for path in (self.rate_limit_file, self.metrics_file, self.log_file):
            path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
