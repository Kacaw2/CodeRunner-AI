"""Immutable caller context — never derived from LLM tool args."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CallerContext:
    actor_type: Literal["agent_host", "external_client"] = "agent_host"
    user_id: int = 0
    role: Literal["student", "teacher", "admin"] = "student"
    tenant_id: str | None = None
    api_key_id: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent_type: str = ""


def build_caller_context(
    *,
    user_id: int,
    role: str,
    agent_type: str = "",
    task_id: str | None = None,
    conversation_id: str | None = None,
    trace_id: str | None = None,
) -> CallerContext:
    return CallerContext(
        actor_type="agent_host",
        user_id=user_id,
        role=role,
        agent_type=agent_type,
        task_id=task_id,
        conversation_id=conversation_id,
        trace_id=trace_id or uuid.uuid4().hex,
    )
