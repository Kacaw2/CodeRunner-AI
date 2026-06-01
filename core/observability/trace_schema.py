"""Runtime-neutral trace schema (dataclasses, no ORM, no Flask).

These describe the rows the trace store persists. They are pure data so any
runtime (workers, MCP gateway, eval harness, Flask) can build them without
importing SQLAlchemy models or pulling in Flask app context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass
class TraceContext:
    """Identity + linkage for a single agent/eval execution."""

    trace_id: str
    source: str
    agent_type: str | None = None
    user_id: int | None = None
    conversation_id: int | None = None
    message_id: int | None = None
    chat_task_id: str | None = None
    workflow_run_id: str | None = None
    eval_run_id: int | None = None
    eval_case_id: str | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRunRecord:
    id: str
    trace_id: str
    source: str
    status: str
    started_at: datetime
    created_at: datetime
    legacy_run_id: str | None = None
    agent_type: str | None = None
    user_id: int | None = None
    conversation_id: int | None = None
    message_id: int | None = None
    chat_task_id: str | None = None
    workflow_run_id: str | None = None
    eval_run_id: int | None = None
    eval_case_id: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    model_name: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_cny: Decimal | None = None
    total_latency_ms: int | None = None
    llm_latency_ms: int | None = None
    tool_latency_ms: int | None = None
    mcp_latency_ms: int | None = None
    sandbox_latency_ms: int | None = None
    budget_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    ended_at: datetime | None = None


@dataclass
class TraceSpanRecord:
    id: str
    trace_id: str
    span_type: str
    name: str
    status: str
    started_at: datetime
    sequence: int = 0
    parent_span_id: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_cny: Decimal | None = None
    latency_ms: int | None = None
    metadata_json: dict[str, Any] | None = None
    ended_at: datetime | None = None


@dataclass
class TraceEventRecord:
    id: str
    trace_id: str
    event_type: str
    created_at: datetime
    span_id: str | None = None
    payload_json: dict[str, Any] | None = None


@dataclass
class TraceArtifactRecord:
    id: str
    trace_id: str
    artifact_type: str
    name: str
    created_at: datetime
    span_id: str | None = None
    mime_type: str | None = None
    storage_uri: str | None = None
    preview_text: str | None = None
    payload_json: dict[str, Any] | None = None
    size_bytes: int | None = None


@dataclass
class TraceLinkRecord:
    id: str
    trace_id: str
    link_type: str
    target_table: str
    target_id: str
    created_at: datetime
    metadata_json: dict[str, Any] | None = None
