"""RBAC policy — role-based access control for MCP tools.

Migrated from app/agents/tools/permissions.py and mcp_server/middleware.py.
This is the single source of truth for tool-level role checks.
"""

from __future__ import annotations

from mcp.auth.context import CallerContext
from mcp.schemas.descriptors import ToolDescriptor
from mcp.errors import MCPPermissionDenied

_ROLE_OVERRIDES: dict[str, set[str]] = {
    "coderunner.analytics.student_stats": {"teacher", "admin"},
    "coderunner.analytics.class_statistics": {"teacher", "admin"},
    "coderunner.analytics.problem_difficulty": {"teacher", "admin"},
    "coderunner.trace.get_agent_trace": {"teacher", "admin"},
    "coderunner.student.get_summary": {"teacher", "admin"},
    "coderunner.problem.save_generated": {"teacher", "admin"},
    "coderunner.code.execute": {"student", "teacher", "admin"},
}

_AGENT_TOOL_ALLOW: dict[str, set[str]] = {
    "tutor": {
        "coderunner.code.execute",
        "coderunner.problem.get_detail",
        "coderunner.submission.list_for_student",
        "coderunner.submission.get_detail",
        "coderunner.knowledge.search",
        "coderunner.knowledge.search_error_patterns",
    },
    "reviewer": {
        "coderunner.code.execute",
        "coderunner.problem.get_detail",
    },
    "generator": {
        "coderunner.code.execute",
        "coderunner.knowledge.search_similar_problems",
        "coderunner.problem.save_generated",
    },
    "analytics": {
        "coderunner.problem.get_detail",
        "coderunner.submission.list_for_student",
        "coderunner.submission.get_detail",
        "coderunner.analytics.student_stats",
        "coderunner.analytics.student_activity",
        "coderunner.analytics.class_statistics",
        "coderunner.analytics.problem_difficulty",
    },
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
    if agent and agent in _AGENT_TOOL_ALLOW:
        if tool_name not in _AGENT_TOOL_ALLOW[agent]:
            raise MCPPermissionDenied(
                f"Agent '{agent}' is not allowed to use tool '{tool_name}'.",
                trace_id=ctx.trace_id,
            )
