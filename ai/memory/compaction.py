from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# Character heuristic: ~4 chars ≈ 1 token. Internal budget metric only, not an exact token promise.
DEFAULT_CONTEXT_TOKEN_BUDGET = 12000
DEFAULT_RECENT_TOKEN_BUDGET = 8000
DEFAULT_MAX_RECENT_MESSAGES = 20


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def message_tokens(message) -> int:
    total = estimate_tokens(getattr(message, "content", ""))
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        try:
            total += estimate_tokens(json.dumps(tool_calls, default=str))
        except (TypeError, ValueError):
            total += estimate_tokens(str(tool_calls))
    return total
