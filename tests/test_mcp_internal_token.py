"""Signed internal capability tokens (F1 fix).

The internal agent transport must stop trusting a single static shared secret
plus self-declared X-MCP-* identity headers. Instead the Host mints a short-lived
EdDSA-signed token whose claims (user_id / role / agent_type / scopes) the gateway
verifies with a public key. A holder of the public verify key cannot forge a token,
and an agent cannot self-elevate its role because the role is inside the signature.
"""

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _keypair() -> tuple[str, str]:
    """Return (private_pem, public_pem) for an Ed25519 signing keypair."""
    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def test_mint_then_verify_round_trips_claims():
    from ai.mcp_gateway.internal_auth import mint_internal_token, verify_internal_token

    private_pem, public_pem = _keypair()
    token = mint_internal_token(
        user_id=7,
        role="student",
        agent_type="tutor",
        scopes=["problem:read", "code:execute"],
        task_id="task-1",
        conversation_id="conv-1",
        signing_key=private_pem,
    )

    claims = verify_internal_token(token, verify_key=public_pem)

    assert claims is not None
    assert claims["sub"] == "7"
    assert claims["role"] == "student"
    assert claims["agent_type"] == "tutor"
    assert claims["scopes"] == ["problem:read", "code:execute"]
    assert claims["task_id"] == "task-1"
    assert claims["conversation_id"] == "conv-1"


def test_token_signed_by_a_different_key_is_rejected():
    """A party without the Host signing key cannot forge a valid token."""
    from ai.mcp_gateway.internal_auth import mint_internal_token, verify_internal_token

    attacker_private, _ = _keypair()
    _, real_public = _keypair()

    forged = mint_internal_token(
        user_id=1,
        role="admin",
        agent_type="tutor",
        scopes=["problem:write"],
        signing_key=attacker_private,
    )

    assert verify_internal_token(forged, verify_key=real_public) is None


def test_tampered_token_bytes_fail_verification():
    """Flipping bytes in a signed token (e.g. to elevate role) breaks the signature."""
    from ai.mcp_gateway.internal_auth import mint_internal_token, verify_internal_token

    private_pem, public_pem = _keypair()
    token = mint_internal_token(
        user_id=7,
        role="student",
        agent_type="tutor",
        scopes=[],
        signing_key=private_pem,
    )

    header, payload, signature = token.split(".")
    tampered = ".".join([header, payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB"), signature])

    assert verify_internal_token(tampered, verify_key=public_pem) is None


def test_expired_token_is_rejected():
    from ai.mcp_gateway.internal_auth import mint_internal_token, verify_internal_token

    private_pem, public_pem = _keypair()
    token = mint_internal_token(
        user_id=7,
        role="student",
        agent_type="tutor",
        scopes=[],
        signing_key=private_pem,
        ttl_seconds=-1,
    )

    assert verify_internal_token(token, verify_key=public_pem) is None


def test_wrong_audience_is_rejected():
    """A token minted for a different audience must not be accepted by the gateway."""
    import jwt
    from ai.mcp_gateway.internal_auth import verify_internal_token

    private_pem, public_pem = _keypair()
    import time
    now = int(time.time())
    token = jwt.encode(
        {"sub": "7", "role": "admin", "aud": "some-other-service",
         "iat": now, "exp": now + 60},
        private_pem,
        algorithm="EdDSA",
    )

    assert verify_internal_token(token, verify_key=public_pem) is None


def test_garbage_token_is_rejected():
    from ai.mcp_gateway.internal_auth import verify_internal_token

    _, public_pem = _keypair()
    assert verify_internal_token("not-a-jwt", verify_key=public_pem) is None
    assert verify_internal_token("", verify_key=public_pem) is None
