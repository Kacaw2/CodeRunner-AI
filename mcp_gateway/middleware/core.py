"""Shared middleware for MCP tool calls: auth check, permission, rate limit, audit.

Gateway handlers keep connection-level auth/rate-limit here, then delegate all
tool policy, auditing, validation, and approval behavior to ToolRuntime.
"""

import contextvars
import json

from mcp_gateway.middleware.rate_limit import check_rate_limit
from tools.protocol import get_tool_runtime, ToolCallContext
from core.auth.context import CallerContext

CODE_MAX_LENGTH = 10_000
ALLOWED_LANGUAGES = {"python", "c"}


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


def _guarded(fn):
    caller = get_caller_info()
    if not caller:
        return _error_envelope("MCP_AUTH_REQUIRED", "Authentication required")

    api_key_id = caller["api_key_id"]
    rpm_limit = caller.get("rate_limit_rpm", 30)
    if not check_rate_limit(api_key_id, rpm_limit):
        return _error_envelope("MCP_RATE_LIMITED", "Rate limit exceeded")

    return fn()


def call_via_runtime(mcp_tool: str, args: dict) -> str:
    """Bridge gateway tool wrappers into the canonical ToolRuntime pipeline."""
    caller = get_caller_info()
    if not caller:
        return _error_envelope("MCP_AUTH_REQUIRED", "Authentication required")

    ctx = ToolCallContext(caller=CallerContext(
        # Phase 1 transition: existing API keys still store legacy tool-name
        # scopes. Use agent_host actor semantics until scope migration lands.
        actor_type="agent_host",
        user_id=caller["user_id"],
        role=caller["role"],
        api_key_id=caller.get("api_key_id"),
    ))
    result = get_tool_runtime().call_sync(mcp_tool, args, ctx)
    return json.dumps(result.to_envelope(), ensure_ascii=False, default=str)
