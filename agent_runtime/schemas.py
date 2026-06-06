"""Pydantic 2 request/response schemas for the agent runtime command API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatTaskStartResponse(BaseModel):
    """Returned by ``POST /internal/v1/chat-tasks/{task_id}:start``."""

    task_id: str
    status: str
    claimed: bool = Field(
        description="True if this call won the pending->processing CAS and "
        "executed the task; False if the task was already claimed."
    )
    agent_type: Optional[str] = None
    result_message_id: Optional[int] = None


class ChatTaskStatusResponse(BaseModel):
    """Returned by ``GET /internal/v1/chat-tasks/{task_id}``."""

    task_id: str
    conversation_id: int
    status: str
    agent_type: str
    routed_agent: Optional[str] = None
    result_message_id: Optional[int] = None
    error_detail: Optional[str] = None


class ChatTaskEventsResponse(BaseModel):
    """Returned by ``GET /internal/v1/chat-tasks/{task_id}/events``.

    Mirrors the Redis SSE buffer the Flask stream endpoint reads.
    """

    task_id: str
    status: Optional[str] = None
    agent: Optional[str] = None
    events: list[dict] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
