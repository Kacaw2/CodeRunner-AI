"""Shared middleware for MCP tool calls: auth check, permission, rate limit, audit."""

import json
import logging
import time
from functools import wraps
from typing import Callable

from mcp_server.rate_limiter import check_rate_limit
from mcp_server.audit import log_tool_call
from app.agents.tools.permissions import check_tool_permission

logger = logging.getLogger(__name__)

_caller_info: dict | None = None


def set_caller_info(info: dict):
    global _caller_info
    _caller_info = info


def get_caller_info() -> dict | None:
    return _caller_info


def mcp_tool_middleware(tool_name: str) -> Callable:
    """Decorator that wraps an MCP tool function with auth/permission/rate-limit/audit."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller = get_caller_info()
            api_key_id = caller["api_key_id"] if caller else None
            user_id = caller["user_id"] if caller else None
            role = caller["role"] if caller else None
            scopes = caller.get("scopes") if caller else None
            rpm_limit = caller.get("rate_limit_rpm", 30) if caller else 30

            tool_args = kwargs.copy()
            start = time.monotonic()

            if not caller:
                log_tool_call(None, None, tool_name, tool_args, "denied")
                return json.dumps({"error": "Authentication required"})

            if not check_tool_permission("mcp", tool_name, role):
                log_tool_call(api_key_id, user_id, tool_name, tool_args, "denied")
                return json.dumps({"error": f"Permission denied for role '{role}'"})

            if scopes is not None and tool_name not in scopes:
                log_tool_call(api_key_id, user_id, tool_name, tool_args, "denied")
                return json.dumps({"error": f"Tool '{tool_name}' not in key scopes"})

            if not check_rate_limit(api_key_id, rpm_limit):
                log_tool_call(api_key_id, user_id, tool_name, tool_args, "rate_limited")
                return json.dumps({"error": "Rate limit exceeded"})

            try:
                result = fn(*args, **kwargs)
                latency_ms = int((time.monotonic() - start) * 1000)
                log_tool_call(api_key_id, user_id, tool_name, tool_args, "success", latency_ms)
                return result
            except Exception as e:
                latency_ms = int((time.monotonic() - start) * 1000)
                log_tool_call(api_key_id, user_id, tool_name, tool_args, "error", latency_ms)
                logger.exception("Tool %s failed", tool_name)
                return json.dumps({"error": str(e)})

        return wrapper
    return decorator
