"""Scope-based access control for API key callers."""

from __future__ import annotations

from core.auth.context import CallerContext
from tools.protocol.schemas.descriptors import ToolDescriptor
from tools.protocol.errors import MCPScopeDenied


def scopes_for_agent(agent_type: str) -> list[str]:
    """Minimal scopes for an internal agent: the union of ``required_scopes``
    across the tools the agent is allowed to call. Unknown agent -> ``[]``."""
    from core.definitions import AGENT_DEFINITIONS
    from tools.protocol.schemas.catalog import TOOL_CATALOG

    defn = AGENT_DEFINITIONS.get(agent_type)
    if defn is None:
        return []

    granted: set[str] = set()
    for tool_name in defn.allowed_tools:
        descriptor = TOOL_CATALOG.get(tool_name)
        if descriptor is not None:
            granted.update(descriptor.required_scopes)
    return sorted(granted)


def check_scope(
    tool: ToolDescriptor,
    ctx: CallerContext,
    *,
    granted_scopes: list[str] | None = None,
) -> None:
    """Raise MCPScopeDenied if the caller lacks a required scope.

    All callers — including internal ``agent_host`` agents — are enforced from
    their granted scopes. Internal agents carry the minimal scopes their tools
    require (see ``scopes_for_agent``); there is no actor_type bypass.
    """
    if not tool.required_scopes:
        return

    effective = set(granted_scopes or [])
    missing = set(tool.required_scopes) - effective
    if missing:
        raise MCPScopeDenied(
            f"Missing scopes: {', '.join(sorted(missing))}",
            trace_id=ctx.trace_id,
        )
