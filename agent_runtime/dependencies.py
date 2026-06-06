"""FastAPI dependencies: AsyncSession, Redis, and internal-command auth.

Internal command routes are guarded by ``require_service_token``: a valid
short-lived signed internal JWT with the dedicated audience (see
``core.auth.service_tokens``). Self-reported headers like ``X-User-Id`` /
``X-Role`` are never trusted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from core.auth.service_tokens import ServiceTokenError, verify_service_token


async def get_session() -> AsyncIterator:
    """Yield an AsyncSession bound to the runtime's async engine.

    Lazily imports the async session factory so importing this module never
    requires the async driver (tests override this dependency with a sqlite
    session instead).
    """
    from core.db.async_session import get_async_session_factory

    factory = get_async_session_factory()
    async with factory() as session:
        yield session


def get_redis():
    """Return a Redis client for the runtime, or None if unavailable.

    Best-effort: a missing/unreachable Redis degrades to None so the runtime
    still executes tasks (events are simply not buffered), matching the embedded
    worker's tolerance. Tests override this dependency with a fake.
    """
    try:
        import redis

        from core.config import get_settings

        return redis.Redis.from_url(
            get_settings().REDIS_URL, decode_responses=True
        )
    except Exception:  # pragma: no cover - optional infra
        return None


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
        )
    return parts[1].strip()


def require_service_token(
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Verify the internal service token; return its claims or raise 401.

    Task-id binding is enforced per-route via :func:`require_task_token`.
    """
    token = _extract_bearer(authorization)
    try:
        return verify_service_token(token)
    except ServiceTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid service token: {exc}",
        ) from exc


def require_task_token(task_id: str, authorization: Optional[str] = Header(default=None)) -> dict:
    """Like :func:`require_service_token` but also binds the token to ``task_id``.

    Used by routes that act on a specific task; rejects a token minted for a
    different task even if otherwise valid.
    """
    token = _extract_bearer(authorization)
    try:
        return verify_service_token(token, expected_task_id=task_id)
    except ServiceTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid service token: {exc}",
        ) from exc
