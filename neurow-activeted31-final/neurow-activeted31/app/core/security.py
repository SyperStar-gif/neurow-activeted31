from __future__ import annotations

import hashlib
import ipaddress
import re
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.types import Scope

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalize_request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def get_client_ip(scope: Scope, *, trust_proxy_headers: bool) -> str:
    headers = Headers(scope=scope)
    candidate = ""
    if trust_proxy_headers:
        candidate = headers.get("x-forwarded-for", "").split(",", maxsplit=1)[0].strip()
    if not candidate:
        client = scope.get("client")
        candidate = str(client[0]) if client else "unknown"

    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        sanitized = re.sub(r"[^A-Za-z0-9_.:-]", "_", candidate)[:128]
        return sanitized or "unknown"


def hash_identifier(identifier: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{identifier}".encode("utf-8")).hexdigest()


def safe_header_text(value: str, *, max_length: int = 200) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:max_length]
