"""Shared middleware for MCP tool calls: auth check, permission, rate limit, audit.

Gateway handlers keep connection-level auth/rate-limit here, then delegate all
tool policy, auditing, validation, and approval behavior to ToolRuntime.
"""

import contextvars
import json
import logging
import os

from mcp_gateway.middleware.rate_limit import check_rate_limit
from tools.protocol import get_tool_runtime, ToolCallContext
from core.auth.context import CallerContext

logger = logging.getLogger(__name__)

CODE_MAX_LENGTH = 10_000
ALLOWED_LANGUAGES = {"python", "c"}
INTERNAL_RATE_LIMIT_RPM_DEFAULT = 600


_caller_info_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_caller_info", default=None
)


def set_caller_info(info: dict | None):
    _caller_info_var.set(info)


def get_caller_info() -> dict | None:
    return _caller_info_var.get()


def _error_envelope(code: str, message: str) -> str:
    return json.dumps({
        "ok": False,
        "error": {"code": code, "message": message, "retryable": False},
    }, ensure_ascii=False)


def _resolve_request_caller() -> dict | None:
    """Resolve caller identity from the current MCP request's bearer token.

    Production auth is per-request: each HTTP request carries its own
    ``Authorization: Bearer <mcp-api-key>`` header. We read it from the active
    MCP request context so identity is never shared between concurrent callers.
    Returns ``None`` when there is no request context (e.g. local stdio dev) or
    no valid bearer token — the dev-mode startup fallback then applies.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
        rc = request_ctx.get(None)
    except Exception:
        return None
    if rc is None:
        return None

    request = getattr(rc, "request", None)
    headers = getattr(request, "headers", None)
    if not headers:
        return None

    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None

    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    return resolve_caller_from_bearer(token.strip())


def _internal_caller_from_claims(claims: dict) -> dict:
    """Build a trusted agent_host caller dict from verified token claims.

    Identity comes from the signed token, never from request headers, so an
    agent cannot self-declare its user_id/role/scopes.
    """
    agent_type = claims.get("agent_type") or ""
    try:
        user_id = int(claims.get("sub") or 0)
    except (ValueError, TypeError):
        user_id = 0

    rpm = os.environ.get("MCP_INTERNAL_RATE_LIMIT_RPM", "").strip()
    try:
        rate_limit_rpm = int(rpm) if rpm else INTERNAL_RATE_LIMIT_RPM_DEFAULT
    except ValueError:
        rate_limit_rpm = INTERNAL_RATE_LIMIT_RPM_DEFAULT

    return {
        "actor_type": "agent_host",
        "api_key_id": f"internal:{agent_type or 'agent'}",
        "user_id": user_id,
        "role": claims.get("role") or "student",
        "agent_type": agent_type,
        "task_id": claims.get("task_id") or None,
        "conversation_id": claims.get("conversation_id") or None,
        "scopes": list(claims.get("scopes") or []),
        "rate_limit_rpm": rate_limit_rpm,
    }


def resolve_caller_from_bearer(token: str) -> dict | None:
    """Resolve a bearer token to caller info.

    A token that verifies against the configured internal public key
    (``MCP_INTERNAL_VERIFY_KEY``) is a trusted internal agent and yields an
    ``agent_host`` caller built from the signed claims. Any other token is
    verified as an external MCP API key.
    """
    from mcp_gateway.internal_auth import verify_internal_token, load_verify_key_from_env

    verify_key = load_verify_key_from_env()
    if verify_key:
        claims = verify_internal_token(token, verify_key=verify_key)
        if claims is not None:
            return _internal_caller_from_claims(claims)

    from mcp_gateway.middleware.auth import verify_api_key
    return verify_api_key(token)


def _guarded(fn):
    # Per-request identity (production) takes precedence over any startup
    # dev-mode fallback and is isolated to this single call via a finally clear.
    request_caller = _resolve_request_caller()
    set_locally = request_caller is not None
    if set_locally:
        set_caller_info(request_caller)

    try:
        caller = get_caller_info()
        if not caller:
            return _error_envelope("MCP_AUTH_REQUIRED", "Authentication required")

        api_key_id = caller["api_key_id"]
        rpm_limit = caller.get("rate_limit_rpm", 30)
        if not check_rate_limit(api_key_id, rpm_limit):
            return _error_envelope("MCP_RATE_LIMITED", "Rate limit exceeded")

        return fn()
    finally:
        if set_locally:
            set_caller_info(None)


def call_via_runtime(mcp_tool: str, args: dict) -> str:
    """Bridge gateway tool wrappers into the canonical ToolRuntime pipeline."""
    caller = get_caller_info()
    if not caller:
        return _error_envelope("MCP_AUTH_REQUIRED", "Authentication required")

    if caller.get("actor_type") == "agent_host":
        ctx = ToolCallContext(
            caller=CallerContext(
                actor_type="agent_host",
                user_id=caller["user_id"],
                role=caller["role"],
                agent_type=caller.get("agent_type", ""),
                task_id=caller.get("task_id"),
                conversation_id=caller.get("conversation_id"),
            ),
            granted_scopes=caller.get("scopes") or [],
        )
    else:
        ctx = ToolCallContext(
            caller=CallerContext(
                actor_type="external_client",
                user_id=caller["user_id"],
                role=caller["role"],
                api_key_id=caller.get("api_key_id"),
            ),
            granted_scopes=caller.get("scopes") or [],
        )
    result = get_tool_runtime().call_sync(mcp_tool, args, ctx)
    return json.dumps(result.to_envelope(), ensure_ascii=False, default=str)
