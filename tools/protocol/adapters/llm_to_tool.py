"""Parse LLM tool-call responses into MCP call requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MCPCallRequest:
    tool_name: str
    args: dict[str, Any]
    tool_call_id: str


def parse_llm_tool_call(tool_call: dict | Any) -> MCPCallRequest:
    """Accept an AIMessage tool_call dict or LangChain ToolCall and normalize."""
    if hasattr(tool_call, "get"):
        return MCPCallRequest(
            tool_name=tool_call["name"],
            args=tool_call.get("args", {}),
            tool_call_id=tool_call.get("id", ""),
        )
    return MCPCallRequest(
        tool_name=getattr(tool_call, "name", ""),
        args=getattr(tool_call, "args", {}),
        tool_call_id=getattr(tool_call, "id", ""),
    )
