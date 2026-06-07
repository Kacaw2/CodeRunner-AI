"""Trace and eval mappings on the single shared DomainBase registry."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.timezone import now_china
from domain.base import DomainBase

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


def _uuid() -> str:
    return str(uuid.uuid4())


class AgentTraceRun(DomainBase):
    __tablename__ = "agent_trace_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    legacy_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    trace_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    agent_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chat_task_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    workflow_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    eval_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    eval_case_id: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    input_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_cny: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    total_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tool_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mcp_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sandbox_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    budget_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )


class AgentTraceSpan(DomainBase):
    __tablename__ = "agent_trace_spans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_span_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    span_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_cny: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AgentTraceEvent(DomainBase):
    __tablename__ = "agent_trace_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    span_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )


class AgentTraceArtifact(DomainBase):
    __tablename__ = "agent_trace_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    span_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    artifact_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    storage_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    preview_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )


class AgentTraceLink(DomainBase):
    __tablename__ = "agent_trace_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_table: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )


class EvalRun(DomainBase):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suite_name: Mapped[str] = mapped_column(String(50), nullable=False)
    run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=now_china)
    model_name: Mapped[Optional[str]] = mapped_column(String(50))
    total_cases: Mapped[Optional[int]] = mapped_column(Integer)
    passed_cases: Mapped[Optional[int]] = mapped_column(Integer)
    pass_rate: Mapped[Optional[float]] = mapped_column(Float)
    results_json: Mapped[Optional[object]] = mapped_column(JSON)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "suite_name": self.suite_name,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "model_name": self.model_name,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "pass_rate": self.pass_rate,
            "results_json": self.results_json,
            "duration_seconds": self.duration_seconds,
        }


class EvalCaseRun(DomainBase):
    __tablename__ = "eval_case_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    eval_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    case_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True
    )
    suite: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    agent_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    failure_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    input_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_cny: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )


class EvalCaseGraderResult(DomainBase):
    __tablename__ = "eval_case_grader_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_run_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    grader_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    grader_name: Mapped[str] = mapped_column(String(80), nullable=False)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_cny: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    trace_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )


__all__ = [
    "AgentTraceRun",
    "AgentTraceSpan",
    "AgentTraceEvent",
    "AgentTraceArtifact",
    "AgentTraceLink",
    "EvalRun",
    "EvalCaseRun",
    "EvalCaseGraderResult",
]
