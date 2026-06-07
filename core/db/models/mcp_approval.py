"""Compatibility re-export for the MCP approval domain mapping."""

from domain.models.mcp import APPROVAL_TIMEOUT_MINUTES, McpToolApproval

__all__ = ["APPROVAL_TIMEOUT_MINUTES", "McpToolApproval"]
