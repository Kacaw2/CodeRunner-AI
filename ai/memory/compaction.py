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


@dataclass(frozen=True)
class CompactionResult:
    messages: list
    compacted: bool
    dropped_messages: int
    kept_messages: int
    summarized: bool
    fallback_used: bool
    tokens_before: int
    tokens_after: int


def _total_tokens(messages: list) -> int:
    return sum(message_tokens(m) for m in messages)


def _transcript(early: list) -> str:
    parts = []
    for m in early:
        content = getattr(m, "content", "")
        if content:
            role = getattr(m, "type", "unknown")
            parts.append(f"[{role}] {content[:300]}")
    return "\n".join(parts)


def _structured_fallback(early: list) -> str:
    topics = []
    for m in early:
        content = getattr(m, "content", "")
        if content:
            topics.append(content[:100])
    tail = "..." if len(topics) > 5 else ""
    return "Previous conversation summary: discussed " + "; ".join(topics[:5]) + tail


def compact_window(
    messages: list,
    *,
    token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
    recent_token_budget: int = DEFAULT_RECENT_TOKEN_BUDGET,
    max_recent_messages: int = DEFAULT_MAX_RECENT_MESSAGES,
    summarizer: Callable[[str], str | None] | None = None,
) -> CompactionResult:
    tokens_before = _total_tokens(messages)
    if not messages or tokens_before <= token_budget:
        return CompactionResult(
            messages=messages, compacted=False, dropped_messages=0,
            kept_messages=len(messages), summarized=False, fallback_used=False,
            tokens_before=tokens_before, tokens_after=tokens_before,
        )

    system_msg = messages[0]
    body = messages[1:]
    recent_start = _select_recent_index(body, recent_token_budget, max_recent_messages)
    keep = _earliest_safe_keep_index(body, recent_start)
    early, recent = body[:keep], body[keep:]
    if not early:
        return CompactionResult(
            messages=messages, compacted=False, dropped_messages=0,
            kept_messages=len(messages), summarized=False, fallback_used=False,
            tokens_before=tokens_before, tokens_after=tokens_before,
        )

    summary_text = None
    summarized = False
    if summarizer is not None:
        try:
            summary_text = summarizer(_transcript(early))
        except Exception:
            summary_text = None
    if summary_text:
        summarized = True
        body_text = f"Previous conversation summary:\n{summary_text}"
    else:
        body_text = _structured_fallback(early)

    compacted_messages = [system_msg, HumanMessage(content=body_text)] + recent
    return CompactionResult(
        messages=compacted_messages, compacted=True,
        dropped_messages=len(early), kept_messages=len(recent),
        summarized=summarized, fallback_used=not summarized,
        tokens_before=tokens_before, tokens_after=_total_tokens(compacted_messages),
    )
