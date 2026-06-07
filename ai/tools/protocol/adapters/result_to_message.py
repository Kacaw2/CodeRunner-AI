"""Convert MCP ToolResult into LangChain ToolMessage or plain dict."""

from __future__ import annotations

import json
from typing import Any


def tool_result_to_message(
    result: dict[str, Any],
    tool_call_id: str,
) -> "ToolMessage":
    """Wrap an MCP result envelope into a LangChain ToolMessage."""
    from langchain_core.messages import ToolMessage

    if result.get("ok", True):
        content = json.dumps(result.get("data", result), ensure_ascii=False)
    else:
        err = result.get("error", {})
        content = json.dumps(
            {"error": err.get("code", "MCP_INTERNAL_ERROR"),
             "message": err.get("message", "Unknown error")},
            ensure_ascii=False,
        )

    return ToolMessage(content=content, tool_call_id=tool_call_id)


def tool_result_to_dict(result: dict[str, Any]) -> dict[str, Any]:
    """Extract the data payload from an MCP result envelope."""
    if result.get("ok", True):
        return result.get("data", result)
    return {"error": result.get("error", {}).get("message", "Unknown error")}
