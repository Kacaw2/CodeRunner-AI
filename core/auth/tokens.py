"""Service token and API key verification."""

from __future__ import annotations

import hashlib
import os

_INTERNAL_SERVICE_TOKEN = os.getenv("MCP_INTERNAL_SERVICE_TOKEN", "")


def verify_service_token(token: str) -> bool:
    if not _INTERNAL_SERVICE_TOKEN:
        return False
    return token == _INTERNAL_SERVICE_TOKEN


def verify_api_key(raw_key: str, *, session=None) -> dict | None:
    """Verify an external MCP API key. Returns caller info or None."""
    from mcp_gateway.middleware.auth import verify_api_key as _legacy_verify
    return _legacy_verify(raw_key)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
