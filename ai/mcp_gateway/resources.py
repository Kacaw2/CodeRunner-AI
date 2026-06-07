"""MCP resource registration for the gateway.

Tools are the only *actions* the server exposes; resources are the read-only
static artifacts a client may fetch by URI. Until now the gateway shipped no
resources (F5), so prompt templates and shared prompt addenda could only be
reached by importing Python — not over the MCP protocol. This module exposes
them as proper ``prompt://`` resources.

Resources are read-only and side-effect free, so they do not participate in the
tool RBAC/scope/approval guard chain.
"""

import logging

logger = logging.getLogger(__name__)

AGENT_NAMES = ("tutor", "reviewer", "generator", "analytics")


def register_resources(mcp) -> int:
    """Register read-only resources on *mcp*. Returns the count registered."""
    from ai.agents.prompts import get_prompt, get_prompt_version

    count = 0

    @mcp.resource(
        "prompt://agents/{agent}",
        name="agent_system_prompt",
        description=(
            "Versioned system prompt for a CodeRunner agent "
            f"(one of: {', '.join(AGENT_NAMES)})."
        ),
        mime_type="text/markdown",
    )
    def _agent_prompt(agent: str) -> str:
        if agent not in AGENT_NAMES:
            raise ValueError(f"unknown agent '{agent}'; expected one of {AGENT_NAMES}")
        version = get_prompt_version(agent)
        return f"<!-- agent={agent} version={version} -->\n{get_prompt(agent)}"

    count += 1

    @mcp.resource(
        "prompt://addenda/security",
        name="security_prompt_addendum",
        description="Absolute security rules appended to every agent system prompt.",
        mime_type="text/markdown",
    )
    def _security_addendum() -> str:
        from core.security import SECURITY_PROMPT_ADDENDUM
        return SECURITY_PROMPT_ADDENDUM

    count += 1

    @mcp.resource(
        "prompt://addenda/handoff",
        name="handoff_prompt_addendum",
        description="Handoff protocol instructions appended to every agent system prompt.",
        mime_type="text/markdown",
    )
    def _handoff_addendum() -> str:
        from ai.graph.handoff import HANDOFF_PROMPT_ADDENDUM
        return HANDOFF_PROMPT_ADDENDUM

    count += 1

    logger.info("MCP Server registered %d resources", count)
    return count
