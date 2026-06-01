"""Runtime-neutral trace/eval ORM models (plain SQLAlchemy).

These are the single canonical mapping for the complete trace tree and eval
case tables. Workers, the MCP gateway, the eval harness and the trace store
write through these models on ``core.db.session.Base`` so they never trigger
Flask-SQLAlchemy mapper configuration (the root cause of the historical
``TRACE_SAVE_FAIL`` issue). The Flask service layer reads the same physical
tables via ``db.session.execute(select(...))`` against these models.

Production schema is owned by the Alembic migration
``20260601_complete_traces_evals``; this module must stay column-compatible
with it.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import JSON

from core.db.session import Base

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


def _uuid() -> str:
    return str(uuid.uuid4())


class AgentTraceRun(Base):
    __tablename__ = "agent_trace_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    legacy_run_id = Column(String(36), nullable=True, index=True)
    trace_id = Column(String(64), nullable=False, unique=True, index=True)
    source = Column(String(30), nullable=False)
    agent_type = Column(String(30), nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    conversation_id = Column(Integer, nullable=True, index=True)
    message_id = Column(Integer, nullable=True)
    chat_task_id = Column(String(36), nullable=True, index=True)
    workflow_run_id = Column(String(36), nullable=True, index=True)
    eval_run_id = Column(Integer, nullable=True, index=True)
    eval_case_id = Column(String(120), nullable=True, index=True)
    status = Column(String(30), nullable=False, index=True)
    input_preview = Column(Text, nullable=True)
    output_preview = Column(Text, nullable=True)
    error_type = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    model_name = Column(String(80), nullable=True)
    tokens_input = Column(Integer, nullable=False, default=0)
    tokens_output = Column(Integer, nullable=False, default=0)
    cost_cny = Column(Numeric(12, 6), nullable=True)
    total_latency_ms = Column(Integer, nullable=True)
    llm_latency_ms = Column(Integer, nullable=True)
    tool_latency_ms = Column(Integer, nullable=True)
    mcp_latency_ms = Column(Integer, nullable=True)
    sandbox_latency_ms = Column(Integer, nullable=True)
    budget_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=False, default=_now_china)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now_china)


class AgentTraceSpan(Base):
    __tablename__ = "agent_trace_spans"

    id = Column(String(36), primary_key=True, default=_uuid)
    trace_id = Column(String(64), nullable=False, index=True)
    parent_span_id = Column(String(36), nullable=True, index=True)
    span_type = Column(String(40), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    status = Column(String(30), nullable=False)
    sequence = Column(Integer, nullable=False, default=0)
    input_preview = Column(Text, nullable=True)
    output_preview = Column(Text, nullable=True)
    error_type = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    cost_cny = Column(Numeric(12, 6), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=False, default=_now_china)
    ended_at = Column(DateTime, nullable=True)


class AgentTraceEvent(Base):
    __tablename__ = "agent_trace_events"

    id = Column(String(36), primary_key=True, default=_uuid)
    trace_id = Column(String(64), nullable=False, index=True)
    span_id = Column(String(36), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    payload_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now_china)


class AgentTraceArtifact(Base):
    __tablename__ = "agent_trace_artifacts"

    id = Column(String(36), primary_key=True, default=_uuid)
    trace_id = Column(String(64), nullable=False, index=True)
    span_id = Column(String(36), nullable=True, index=True)
    artifact_type = Column(String(50), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    mime_type = Column(String(80), nullable=True)
    storage_uri = Column(String(500), nullable=True)
    preview_text = Column(Text, nullable=True)
    payload_json = Column(JSON, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now_china)


class AgentTraceLink(Base):
    __tablename__ = "agent_trace_links"

    id = Column(String(36), primary_key=True, default=_uuid)
    trace_id = Column(String(64), nullable=False, index=True)
    link_type = Column(String(50), nullable=False, index=True)
    target_table = Column(String(80), nullable=False)
    target_id = Column(String(120), nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now_china)


class EvalCaseRun(Base):
    __tablename__ = "eval_case_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    eval_run_id = Column(Integer, nullable=False, index=True)
    case_id = Column(String(120), nullable=False, index=True)
    case_type = Column(String(30), nullable=True, index=True)
    suite = Column(String(50), nullable=True, index=True)
    agent_type = Column(String(30), nullable=True)
    trace_id = Column(String(64), nullable=True, index=True)
    status = Column(String(30), nullable=False, index=True)
    passed = Column(Boolean, nullable=True)
    failure_type = Column(String(50), nullable=True, index=True)
    input_preview = Column(Text, nullable=True)
    output_preview = Column(Text, nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    cost_cny = Column(Numeric(12, 6), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now_china)


class EvalCaseGraderResult(Base):
    __tablename__ = "eval_case_grader_results"

    id = Column(String(36), primary_key=True, default=_uuid)
    case_run_id = Column(String(36), nullable=False, index=True)
    grader_type = Column(String(50), nullable=False, index=True)
    grader_name = Column(String(80), nullable=False)
    passed = Column(Boolean, nullable=True)
    score = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    cost_cny = Column(Numeric(12, 6), nullable=True)
    trace_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=_now_china)
