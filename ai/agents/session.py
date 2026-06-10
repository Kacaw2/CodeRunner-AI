"""AgentSession — the single in-memory carrier of per-run runtime context.

Replaces ad-hoc reads of trace/identity/budget from a raw AgentState dict.
``from_state`` / ``to_state`` keep the dict as the public boundary type so the
specialist agents, hooks, executor, and harness signatures stay unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSession:
    agent_name: str
    user_id: int
    user_role: str
    messages: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    tool_results: list = field(default_factory=list)
    final_response: str = ""
    definition: Any = None
    trace: Any = None
    trace_id: str | None = None
    memory_selection: Any = None
    budget: dict = field(default_factory=dict)
    source: str = "agent"
    tool_client: Any = None
    # Carry through any extra AgentState keys untouched for a lossless round-trip.
    extra_state: dict = field(default_factory=dict)

    _CORE_KEYS = (
        "messages", "agent_type", "user_id", "user_role",
        "context", "tool_results", "final_response",
    )

    @classmethod
    def from_state(cls, state: dict, agent_name: str | None = None) -> "AgentSession":
        from core.definitions import get_definition

        name = state.get("agent_type") or agent_name or ""
        extra = {k: v for k, v in state.items() if k not in cls._CORE_KEYS}
        return cls(
            agent_name=name,
            user_id=state.get("user_id", 0),
            user_role=state.get("user_role", "student"),
            messages=list(state.get("messages", [])),
            context=dict(state.get("context", {})),
            tool_results=list(state.get("tool_results", [])),
            final_response=state.get("final_response", ""),
            definition=get_definition(name),
            trace_id=extra.get("trace_id"),
            memory_selection=extra.get("_memory_selection"),
            extra_state={k: v for k, v in extra.items() if k not in ("trace_id", "_memory_selection")},
        )

    def to_state(self) -> dict:
        state = dict(self.extra_state)
        state.update({
            "messages": self.messages,
            "agent_type": self.agent_name,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "context": self.context,
            "tool_results": self.tool_results,
            "final_response": self.final_response,
        })
        if self.trace_id is not None:
            state["trace_id"] = self.trace_id
        return state

    def mcp_identity(self):
        from ai.mcp_gateway.client import MCPClientIdentity

        return MCPClientIdentity(
            user_id=self.user_id,
            role=self.user_role,
            agent_type=self.agent_name,
            task_id=self.context.get("task_id"),
            conversation_id=self.context.get("conversation_id"),
            trace_id=self.trace_id or self.context.get("trace_id"),
        )
