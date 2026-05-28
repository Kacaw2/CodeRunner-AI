"""Shared middleware for MCP tool calls: auth check, permission, rate limit, audit.

Changed in §0.2/§0.3 fix:
- Decorator pattern replaced by callable ``run_mcp_guard()`` to avoid
  decorator-order ambiguity with ``@mcp.tool()``.
- ``_caller_info`` moved from global to ``contextvars.ContextVar`` so that
  a future per-request SSE auth layer can set per-connection identity.

Phase 4 additions:
- TOOL_RISK_LEVELS for risk-based routing (low / medium / high).
- High-risk tools require Human Gate approval before execution.
"""

import contextvars
import json
import logging
import time

from mcp_gateway.middleware.rate_limit import check_rate_limit
from core.observability.audit import log_tool_call


_LEGACY_TO_MCP = {
    "get_agent_trace": "coderunner.trace.get_agent_trace",
    "get_student_summary": "coderunner.student.get_summary",
    "execute_code": "coderunner.code.execute",
    "save_generated_problem": "coderunner.problem.save_generated",
    "get_student_stats": "coderunner.analytics.student_stats",
    "get_class_statistics": "coderunner.analytics.class_statistics",
    "get_problem_difficulty_stats": "coderunner.analytics.problem_difficulty",
}


def check_tool_permission(agent_type: str, tool_name: str, user_role: str) -> bool:
    """Compatibility shim — delegates to tools.protocol.policies.rbac."""
    from tools.protocol.policies.rbac import _ROLE_OVERRIDES
    mcp_name = _LEGACY_TO_MCP.get(tool_name, f"coderunner.{tool_name}")
    override = _ROLE_OVERRIDES.get(mcp_name)
    if override is not None:
        return user_role in override
    return True

logger = logging.getLogger(__name__)

TOOL_RISK_LEVELS: dict[str, str] = {
    "search_knowledge":             "low",
    "search_similar_problems":      "low",
    "get_problem_detail":           "low",
    "get_problem_difficulty_stats": "low",
    "get_student_activity":         "low",
    "get_class_statistics":         "low",
    "get_agent_trace":              "medium",
    "get_student_summary":          "medium",
    "execute_code":                 "high",
    "save_generated_problem":       "high",
    "check_approval":               "low",
}

CODE_MAX_LENGTH = 10_000
ALLOWED_LANGUAGES = {"python", "c"}


_caller_info_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "mcp_caller_info", default=None
)


def set_caller_info(info: dict | None):
    _caller_info_var.set(info)


def get_caller_info() -> dict | None:
    return _caller_info_var.get()


class GuardResult:
    """Result of ``run_mcp_guard``. Check ``.rejected`` before proceeding."""

    __slots__ = ("rejected", "error_json", "_start", "_caller")

    def __init__(self, rejected: bool, error_json: str | None, start: float, caller: dict | None):
        self.rejected = rejected
        self.error_json = error_json
        self._start = start
        self._caller = caller

    # ── call after tool body succeeds ──
    def record_success(self, tool_name: str, tool_args: dict | None = None):
        latency_ms = int((time.monotonic() - self._start) * 1000)
        c = self._caller or {}
        log_tool_call(c.get("api_key_id"), c.get("user_id"), tool_name, tool_args, "success", latency_ms)

    def record_error(self, tool_name: str, tool_args: dict | None, exc: Exception):
        latency_ms = int((time.monotonic() - self._start) * 1000)
        c = self._caller or {}
        log_tool_call(c.get("api_key_id"), c.get("user_id"), tool_name, tool_args, "error", latency_ms)


def run_mcp_guard(tool_name: str, tool_args: dict | None = None) -> GuardResult:
    """Pre-flight check: auth → permission → scope → rate-limit.

    Usage inside an ``@mcp.tool()`` function::

        guard = run_mcp_guard("search_knowledge", {"query": query})
        if guard.rejected:
            return guard.error_json
        result = search_knowledge_impl(query)
        guard.record_success("search_knowledge", {"query": query})
        return json.dumps(result)
    """
    caller = get_caller_info()
    start = time.monotonic()

    if not caller:
        log_tool_call(None, None, tool_name, tool_args, "denied")
        return GuardResult(True, json.dumps({"error": "Authentication required"}), start, None)

    api_key_id = caller["api_key_id"]
    user_id = caller["user_id"]
    role = caller["role"]
    scopes = caller.get("scopes")
    rpm_limit = caller.get("rate_limit_rpm", 30)

    if not check_tool_permission("mcp", tool_name, role):
        log_tool_call(api_key_id, user_id, tool_name, tool_args, "denied")
        return GuardResult(True, json.dumps({"error": f"Permission denied for role '{role}'"}), start, caller)

    if scopes is not None and tool_name not in scopes:
        log_tool_call(api_key_id, user_id, tool_name, tool_args, "denied")
        return GuardResult(True, json.dumps({"error": f"Tool '{tool_name}' not in key scopes"}), start, caller)

    if not check_rate_limit(api_key_id, rpm_limit):
        log_tool_call(api_key_id, user_id, tool_name, tool_args, "rate_limited")
        return GuardResult(True, json.dumps({"error": "Rate limit exceeded"}), start, caller)

    return GuardResult(False, None, start, caller)


# ── backward-compat: decorator form kept for existing tests ──

def mcp_tool_middleware(tool_name: str):
    """Decorator form (kept for test compatibility). Prefer ``run_mcp_guard``."""
    from functools import wraps
    from typing import Callable

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            guard = run_mcp_guard(tool_name, kwargs.copy())
            if guard.rejected:
                return guard.error_json
            try:
                result = fn(*args, **kwargs)
                guard.record_success(tool_name, kwargs.copy())
                return result
            except Exception as e:
                guard.record_error(tool_name, kwargs.copy(), e)
                logger.exception("Tool %s failed", tool_name)
                return json.dumps({"error": str(e)})
        return wrapper
    return decorator
