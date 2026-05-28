"""Scope-based access control for API key callers."""

from __future__ import annotations

from core.auth.context import CallerContext
from tools.protocol.schemas.descriptors import ToolDescriptor
from tools.protocol.errors import MCPScopeDenied


def check_scope(
    tool: ToolDescriptor,
    ctx: CallerContext,
    *,
    granted_scopes: list[str] | None = None,
) -> None:
    """Raise MCPScopeDenied if the caller lacks a required scope."""
    if not tool.required_scopes:
        return
    if ctx.actor_type == "agent_host":
        return

    effective = set(granted_scopes or [])
    missing = set(tool.required_scopes) - effective
    if missing:
        raise MCPScopeDenied(
            f"Missing scopes: {', '.join(sorted(missing))}",
            trace_id=ctx.trace_id,
        )
