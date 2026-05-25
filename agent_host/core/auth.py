import logging

import jwt
from fastapi import Depends, HTTPException, Request

from agent_host.core.config import get_settings

logger = logging.getLogger(__name__)


class TokenPayload:
    __slots__ = ("user_id", "username", "role")

    def __init__(self, user_id: int, username: str, role: str):
        self.user_id = user_id
        self.username = username
        self.role = role


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("auth_token")


def decode_jwt(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    return TokenPayload(
        user_id=user_id,
        username=payload.get("username", ""),
        role=payload.get("role", "student"),
    )


def require_auth(request: Request) -> TokenPayload:
    """FastAPI dependency: extract and validate JWT from header or cookie."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    return decode_jwt(token)


def require_teacher(user: TokenPayload = Depends(require_auth)) -> TokenPayload:
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teacher or admin role required")
    return user
