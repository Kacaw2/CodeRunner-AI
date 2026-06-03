"""RBAC policy — role-based access control for MCP tools.

Migrated from app/agents/tools/permissions.py and mcp_gateway/middleware.py.
This is the single source of truth for tool-level role checks.
"""

from __future__ import annotations

from functools import lru_cache

from core.auth.context import CallerContext
from tools.protocol.schemas.descriptors import ToolDescriptor
from tools.protocol.errors import MCPPermissionDenied

_ROLE_OVERRIDES: dict[str, set[str]] = {
    "coderunner.analytics.student_stats": {"teacher", "admin"},
    "coderunner.analytics.class_statistics": {"teacher", "admin"},
    "coderunner.analytics.problem_difficulty": {"teacher", "admin"},
    "coderunner.trace.get_agent_trace": {"teacher", "admin"},
    "coderunner.student.get_summary": {"teacher", "admin"},
    "coderunner.problem.save_generated": {"teacher", "admin"},
    "coderunner.code.execute": {"student", "teacher", "admin"},
}


@lru_cache(maxsize=1)
def _agent_tool_allow() -> dict[str, frozenset[str]]:
    from core.definitions import AGENT_DEFINITIONS
    return {
        name: frozenset(defn.allowed_tools)
        for name, defn in AGENT_DEFINITIONS.items()
    }


def check_rbac(
    tool: ToolDescriptor,
    ctx: CallerContext,
) -> None:
    """Raise MCPPermissionDenied if the caller's role cannot use this tool."""
    role = ctx.role
    tool_name = tool.name

    override = _ROLE_OVERRIDES.get(tool_name)
    if override is not None:
        if role not in override:
            raise MCPPermissionDenied(
                f"Role '{role}' cannot access tool '{tool_name}'.",
                trace_id=ctx.trace_id,
            )
        return

    agent = ctx.agent_type
    allow = _agent_tool_allow().get(agent)
    if allow is not None and tool_name not in allow:
        raise MCPPermissionDenied(
            f"Agent '{agent}' is not allowed to use tool '{tool_name}'.",
            trace_id=ctx.trace_id,
        )
