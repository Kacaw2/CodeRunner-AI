"""Short-lived signed internal service tokens for the FastAPI agent runtime.

These are a DEDICATED internal-command credential, distinct from the user JWT:

- They carry a dedicated audience (``Settings.SERVICE_TOKEN_AUDIENCE``) and a
  dedicated issuer; the runtime rejects any token that lacks the audience, so a
  leaked or replayed *user* JWT can never invoke the internal command API.
- They are short-lived (``Settings.SERVICE_TOKEN_TTL`` seconds, default 60), so
  the blast radius of a captured token is a few seconds.
- They are minted by the Flask dispatcher (the only caller that needs to reach
  the runtime) and verified by the runtime. Both sides share ``SECRET_KEY``
  via config, signed with HS256 — the same algorithm the user JWT uses, but a
  separate audience namespace.

This module has no Flask/FastAPI import: it reads ``core.config.get_settings``
so both processes can use it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

import jwt

from app.core.timezone import aware_now_china
from core.config import get_settings


class ServiceTokenError(Exception):
    """Raised when an internal service token fails verification."""


def mint_service_token(
    *,
    subject: str,
    task_id: Optional[str] = None,
    ttl: Optional[int] = None,
) -> str:
    """Mint a short-lived signed internal command token.

    ``subject`` identifies the calling service (e.g. ``"coderunner-web"``).
    ``task_id``, when given, binds the token to a specific chat task so it
    cannot be replayed against a different task.
    """
    settings = get_settings()
    now = aware_now_china()
    lifetime = ttl if ttl is not None else settings.SERVICE_TOKEN_TTL
    payload = {
        "sub": subject,
        "aud": settings.SERVICE_TOKEN_AUDIENCE,
        "iss": settings.SERVICE_TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=lifetime),
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_service_token(token: str, *, expected_task_id: Optional[str] = None) -> dict:
    """Verify a signed internal command token; return its claims.

    Raises :class:`ServiceTokenError` on any failure (bad signature, expired,
    wrong audience, or a task-id mismatch). Audience is enforced by PyJWT, so a
    user JWT (no audience / different audience) is rejected.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.SERVICE_TOKEN_AUDIENCE,
            issuer=settings.SERVICE_TOKEN_ISSUER,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.InvalidTokenError as exc:  # covers expired, bad-aud, bad-sig, ...
        raise ServiceTokenError(str(exc)) from exc

    if expected_task_id is not None and claims.get("task_id") != expected_task_id:
        raise ServiceTokenError("service token task_id does not match the request")
    return claims
