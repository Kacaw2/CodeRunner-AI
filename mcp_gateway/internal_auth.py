"""Signed internal capability tokens for the internal agent transport (F1).

Internal agents authenticate to the gateway with a short-lived, EdDSA-signed
JWT minted by the Host. The token's claims (user_id / role / agent_type /
scopes) are inside the signature, so:

- the gateway trusts the *signed* identity, never self-declared request headers;
- an agent cannot elevate its own role (it does not hold the signing key);
- a holder of the public verify key cannot forge a token.

The Host holds the Ed25519 private key (``MCP_INTERNAL_SIGNING_KEY``); the
gateway holds only the public key (``MCP_INTERNAL_VERIFY_KEY``).
"""

from __future__ import annotations

import os
import time
import uuid

import jwt

ALGORITHM = "EdDSA"
AUDIENCE = "mcp-gateway"
DEFAULT_TTL_SECONDS = 120


def mint_internal_token(
    *,
    user_id: int,
    role: str,
    agent_type: str,
    scopes: list[str],
    task_id: str | None = None,
    conversation_id: str | None = None,
    trace_id: str | None = None,
    signing_key: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> str:
    """Mint a short-lived signed capability token."""
    iat = int(now if now is not None else time.time())
    claims = {
        "sub": str(user_id),
        "role": role,
        "agent_type": agent_type,
        "scopes": list(scopes),
        "task_id": task_id,
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "aud": AUDIENCE,
        "iat": iat,
        "exp": iat + ttl_seconds,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, signing_key, algorithm=ALGORITHM)


def verify_internal_token(token: str, *, verify_key: str) -> dict | None:
    """Verify a capability token; return its claims, or ``None`` if invalid.

    Invalid covers: bad/forged signature, expired, wrong audience, malformed.
    """
    if not token:
        return None
    try:
        return jwt.decode(
            token,
            verify_key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["exp", "iat", "aud"]},
        )
    except jwt.InvalidTokenError:
        return None


def load_signing_key_from_env() -> str | None:
    """Host-side Ed25519 private key (PEM). ``\\n`` escapes are unescaped."""
    return _load_pem("MCP_INTERNAL_SIGNING_KEY")


def load_verify_key_from_env() -> str | None:
    """Gateway-side Ed25519 public key (PEM). ``\\n`` escapes are unescaped."""
    return _load_pem("MCP_INTERNAL_VERIFY_KEY")


def _load_pem(env_name: str) -> str | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    return raw.replace("\\n", "\n")
