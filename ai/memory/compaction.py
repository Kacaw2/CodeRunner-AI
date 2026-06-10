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


def _select_recent_index(
    body: list, recent_token_budget: int, max_recent_messages: int
) -> int:
    """Return start index of kept tail in body (token budget + count cap, take the later one)."""
    total = 0
    token_start = len(body)
    while token_start > 0:
        t = message_tokens(body[token_start - 1])
        if total + t > recent_token_budget and token_start < len(body):
            break
        total += t
        token_start -= 1
    count_start = max(0, len(body) - max_recent_messages)
    return max(token_start, count_start)


def _earliest_safe_keep_index(body: list, start_index: int) -> int:
    """Back the candidate boundary up so the kept tail does not start with a ToolMessage.

    Tool rounds are contiguous and start with AIMessage(tool_calls), so ensuring
    body[keep] is not a ToolMessage guarantees every kept ToolMessage's parent
    AIMessage is also kept (pairing safe)."""
    i = max(0, min(start_index, len(body)))
    while i > 0 and isinstance(body[i], ToolMessage):
        i -= 1
    return i
