"""Server-side internal-agent authentication (F1 fix).

Internal agents cross MCP transport carrying a short-lived, EdDSA-signed
capability token in the Authorization bearer header. The gateway must:

1. Verify the token signature against the configured public verify key and build
   an ``agent_host`` caller from the *signed claims* (NOT from request headers).
2. Reject self-declared identity: a caller who only controls request headers,
   without a validly signed token, must never become ``agent_host``.
3. Fall through to API-key verification for any non-internal token.
4. Construct an ``agent_host`` CallerContext in ``call_via_runtime`` for trusted
   internal callers, while external callers keep ``external_client`` + scopes.
"""

import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _keypair() -> tuple[str, str]:
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


def test_signed_token_resolves_to_agent_host_from_claims(monkeypatch):
    from ai.mcp_gateway.middleware import core
    from ai.mcp_gateway.internal_auth import mint_internal_token

    private_pem, public_pem = _keypair()
    monkeypatch.setenv("MCP_INTERNAL_VERIFY_KEY", public_pem)

    token = mint_internal_token(
        user_id=7,
        role="student",
        agent_type="tutor",
        scopes=["problem:read"],
        task_id="task-1",
        conversation_id="conv-1",
        signing_key=private_pem,
    )

    caller = core.resolve_caller_from_bearer(token)

    assert caller is not None
    assert caller["actor_type"] == "agent_host"
    assert caller["agent_type"] == "tutor"
    assert caller["user_id"] == 7
    assert caller["role"] == "student"
    assert caller["task_id"] == "task-1"
    assert caller["conversation_id"] == "conv-1"
    assert caller["scopes"] == ["problem:read"]
    assert caller["api_key_id"]


def test_forged_identity_without_valid_token_cannot_become_agent_host(monkeypatch):
    """F1 regression: controlling headers/role without a signed token is useless.

    A caller who does not hold the Host signing key cannot produce a token that
    verifies, so they fall through to API-key verification and never get
    agent_host / admin.
    """
    from ai.mcp_gateway.middleware import core
    from ai.mcp_gateway.internal_auth import mint_internal_token

    _, real_public = _keypair()
    attacker_private, _ = _keypair()
    monkeypatch.setenv("MCP_INTERNAL_VERIFY_KEY", real_public)
    monkeypatch.setattr(
        "mcp_gateway.middleware.auth.verify_api_key", lambda token: None
    )

    forged = mint_internal_token(
        user_id=1,
        role="admin",
        agent_type="tutor",
        scopes=["problem:write"],
        signing_key=attacker_private,
    )

    assert core.resolve_caller_from_bearer(forged) is None


def test_external_token_falls_through_to_api_key_verification(monkeypatch):
    from ai.mcp_gateway.middleware import core

    _, public_pem = _keypair()
    monkeypatch.setenv("MCP_INTERNAL_VERIFY_KEY", public_pem)
    monkeypatch.setattr(
        "mcp_gateway.middleware.auth.verify_api_key",
        lambda token: (
            {
                "api_key_id": "k1",
                "user_id": 1,
                "role": "teacher",
                "scopes": ["problem:read"],
                "rate_limit_rpm": 30,
            }
            if token == "ext-key"
            else None
        ),
    )

    caller = core.resolve_caller_from_bearer("ext-key")

    assert caller is not None
    assert caller.get("actor_type") != "agent_host"
    assert caller["api_key_id"] == "k1"


def test_internal_path_disabled_when_verify_key_unset(monkeypatch):
    """With no verify key configured, every token is just an API key candidate."""
    from ai.mcp_gateway.middleware import core

    monkeypatch.delenv("MCP_INTERNAL_VERIFY_KEY", raising=False)
    monkeypatch.setattr(
        "mcp_gateway.middleware.auth.verify_api_key", lambda token: None
    )

    assert core.resolve_caller_from_bearer("anything") is None


def test_call_via_runtime_uses_agent_host_context_for_internal_caller(monkeypatch):
    from ai.mcp_gateway.middleware import core

    captured = {}

    class _FakeResult:
        def to_envelope(self):
            return {"ok": True, "data": {}}

    class _FakeRuntime:
        def call_sync(self, tool, args, ctx):
            captured["ctx"] = ctx
            return _FakeResult()

    monkeypatch.setattr(core, "get_tool_runtime", lambda: _FakeRuntime())
    core.set_caller_info({
        "actor_type": "agent_host",
        "api_key_id": "internal:tutor",
        "user_id": 7,
        "role": "student",
        "agent_type": "tutor",
        "task_id": "task-1",
        "conversation_id": "conv-1",
        "scopes": ["problem:read"],
    })

    core.call_via_runtime("coderunner.problem.get_detail", {"problem_id": 1})

    ctx = captured["ctx"]
    assert ctx.caller.actor_type == "agent_host"
    assert ctx.caller.agent_type == "tutor"
    assert ctx.caller.user_id == 7
    assert ctx.caller.task_id == "task-1"
    assert ctx.caller.conversation_id == "conv-1"


def test_call_via_runtime_uses_external_client_context_for_api_key_caller(monkeypatch):
    from ai.mcp_gateway.middleware import core

    captured = {}

    class _FakeResult:
        def to_envelope(self):
            return {"ok": True, "data": {}}

    class _FakeRuntime:
        def call_sync(self, tool, args, ctx):
            captured["ctx"] = ctx
            return _FakeResult()

    monkeypatch.setattr(core, "get_tool_runtime", lambda: _FakeRuntime())
    core.set_caller_info({
        "api_key_id": "k1",
        "user_id": 1,
        "role": "teacher",
        "scopes": ["knowledge:read"],
        "rate_limit_rpm": 30,
    })

    core.call_via_runtime("coderunner.knowledge.search", {"query": "loops"})

    ctx = captured["ctx"]
    assert ctx.caller.actor_type == "external_client"
    assert ctx.granted_scopes == ["knowledge:read"]
