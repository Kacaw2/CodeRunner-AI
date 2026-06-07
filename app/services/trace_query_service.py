"""Read-only Flask query layer over the complete trace tables.

The runtime-neutral models in ``domain.models.observability`` are the single
canonical mapping; workers/evals/MCP write through domain repositories. This
service uses the same repository boundary from the Flask request path and
shapes desensitized view dicts for the trace API. It never writes and never
re-declares a Flask ``db.Model``.

Legacy ``agent_runs`` rows stay viewable through a read-only fallback in
``get_trace`` until the Phase 7 backfill copies them into the new tables.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.extensions import db
from domain.models.observability import (
    AgentTraceArtifact,
    AgentTraceEvent,
    AgentTraceLink,
    AgentTraceRun,
    AgentTraceSpan,
)
from domain.repositories.traces import SyncTraceRepository

def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _role_of(viewer) -> str:
    if viewer is None:
        return "student"
    role = getattr(viewer, "role", None)
    return role.value if hasattr(role, "value") else str(role)


def _run_to_dict(run: AgentTraceRun) -> dict:
    return {
        "id": run.trace_id,
        "trace_id": run.trace_id,
        "legacy_run_id": run.legacy_run_id,
        "source": run.source,
        "agent_type": run.agent_type,
        "user_id": run.user_id,
        "conversation_id": run.conversation_id,
        "message_id": run.message_id,
        "chat_task_id": run.chat_task_id,
        "workflow_run_id": run.workflow_run_id,
        "eval_run_id": run.eval_run_id,
        "eval_case_id": run.eval_case_id,
        "status": run.status,
        "input_preview": run.input_preview,
        "output_preview": run.output_preview,
        "error_type": run.error_type,
        "error_message": run.error_message,
        "model_name": run.model_name,
        "tokens_input": run.tokens_input,
        "tokens_output": run.tokens_output,
        "cost_cny": _jsonable(run.cost_cny),
        "total_latency_ms": run.total_latency_ms,
        "llm_latency_ms": run.llm_latency_ms,
        "tool_latency_ms": run.tool_latency_ms,
        "mcp_latency_ms": run.mcp_latency_ms,
        "sandbox_latency_ms": run.sandbox_latency_ms,
        "budget_json": run.budget_json,
        "metadata_json": run.metadata_json,
        "started_at": _jsonable(run.started_at),
        "ended_at": _jsonable(run.ended_at),
        "created_at": _jsonable(run.created_at),
        "legacy": False,
    }


def _span_to_dict(span: AgentTraceSpan, *, redact_io: bool) -> dict:
    return {
        "id": span.id,
        "trace_id": span.trace_id,
        "parent_span_id": span.parent_span_id,
        "span_type": span.span_type,
        "name": span.name,
        "status": span.status,
        "sequence": span.sequence,
        "input_preview": None if redact_io else span.input_preview,
        "output_preview": None if redact_io else span.output_preview,
        "error_type": span.error_type,
        "error_message": span.error_message,
        "tokens_input": span.tokens_input,
        "tokens_output": span.tokens_output,
        "cost_cny": _jsonable(span.cost_cny),
        "latency_ms": span.latency_ms,
        "metadata_json": None if redact_io else span.metadata_json,
        "started_at": _jsonable(span.started_at),
        "ended_at": _jsonable(span.ended_at),
    }


def _event_to_dict(event: AgentTraceEvent, *, redact_io: bool) -> dict:
    return {
        "id": event.id,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "event_type": event.event_type,
        "payload_json": None if redact_io else event.payload_json,
        "created_at": _jsonable(event.created_at),
    }


def _artifact_to_dict(artifact: AgentTraceArtifact, *, redact_io: bool) -> dict:
    return {
        "id": artifact.id,
        "trace_id": artifact.trace_id,
        "span_id": artifact.span_id,
        "artifact_type": artifact.artifact_type,
        "name": artifact.name,
        "mime_type": artifact.mime_type,
        "storage_uri": artifact.storage_uri,
        "preview_text": None if redact_io else artifact.preview_text,
        "payload_json": None if redact_io else artifact.payload_json,
        "size_bytes": artifact.size_bytes,
        "created_at": _jsonable(artifact.created_at),
    }


def _link_to_dict(link: AgentTraceLink) -> dict:
    return {
        "id": link.id,
        "trace_id": link.trace_id,
        "link_type": link.link_type,
        "target_table": link.target_table,
        "target_id": link.target_id,
        "metadata_json": link.metadata_json,
        "created_at": _jsonable(link.created_at),
    }


class TraceQueryService:
    """Read-only aggregator returning desensitized trace views."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or SyncTraceRepository(db.session)

    def list_traces(self, *, viewer=None, filters=None, limit=20, offset=0) -> dict:
        filters = filters or {}
        role = _role_of(viewer)
        viewer_user_id = (
            viewer.id
            if role not in ("teacher", "admin") and viewer is not None
            else None
        )
        runs, total = self.repository.list_runs(
            filters=filters,
            viewer_user_id=viewer_user_id,
            limit=limit,
            offset=offset,
        )
        tool_counts = self.repository.tool_span_counts(
            [row.trace_id for row in runs]
        )
        traces = []
        for run in runs:
            row = _run_to_dict(run)
            row["tool_call_count"] = tool_counts.get(run.trace_id, 0)
            traces.append(row)

        return {"traces": traces, "total": total, "limit": limit, "offset": offset}

    def get_trace(self, trace_id: str, *, viewer=None) -> dict | None:
        role = _role_of(viewer)
        run = self.repository.get_run(trace_id)

        if run is None:
            return self._legacy_trace(trace_id, viewer=viewer, role=role)

        is_owner = viewer is not None and run.user_id == viewer.id
        if role not in ("teacher", "admin") and not is_owner:
            return None
        redact_io = role not in ("teacher", "admin")

        bundle = self.repository.get_trace_bundle(run.trace_id)
        spans = bundle["spans"]
        events = bundle["events"]
        artifacts = bundle["artifacts"]
        links = bundle["links"]

        run_dict = _run_to_dict(run)
        run_dict["tool_call_count"] = sum(
            1 for s in spans if s.span_type in ("tool", "mcp")
        )
        if redact_io:
            run_dict["input_preview"] = None

        return {
            "run": run_dict,
            "spans": [_span_to_dict(s, redact_io=redact_io) for s in spans],
            "events": [_event_to_dict(e, redact_io=redact_io) for e in events],
            "artifacts": [
                _artifact_to_dict(a, redact_io=redact_io) for a in artifacts
            ],
            "links": [_link_to_dict(link) for link in links],
        }

    def _legacy_trace(self, run_id: str, *, viewer, role) -> dict | None:
        """Read-only view of a historical ``agent_runs`` row (pre-backfill)."""
        from app.models.agent_trace import AgentRun, AgentRunStep

        session = self.repository.session
        run = session.get(AgentRun, run_id)
        if run is None:
            return None

        is_owner = viewer is not None and run.user_id == viewer.id
        if role not in ("teacher", "admin") and not is_owner:
            return None
        redact_io = role not in ("teacher", "admin")

        steps = (
            session.execute(
                select(AgentRunStep)
                .where(AgentRunStep.run_id == run_id)
                .order_by(AgentRunStep.step_index)
            )
            .scalars()
            .all()
        )

        spans = []
        for step in steps:
            span_type = "llm" if step.step_type == "llm_call" else "tool"
            spans.append(
                {
                    "id": f"{run_id}-{step.step_index}",
                    "trace_id": run_id,
                    "parent_span_id": None,
                    "span_type": span_type,
                    "name": step.tool_name or step.step_type or "step",
                    "status": "failed" if step.tool_success is False else "completed",
                    "sequence": step.step_index,
                    "input_preview": None
                    if redact_io
                    else (str(step.tool_input) if step.tool_input is not None else None),
                    "output_preview": None if redact_io else step.tool_output_preview,
                    "error_type": None,
                    "error_message": step.error,
                    "tokens_input": step.llm_prompt_tokens,
                    "tokens_output": step.llm_completion_tokens,
                    "cost_cny": None,
                    "latency_ms": step.latency_ms,
                    "metadata_json": None,
                    "started_at": _jsonable(step.created_at),
                    "ended_at": _jsonable(step.created_at),
                }
            )

        run_dict = {
            "id": run.id,
            "trace_id": run.id,
            "legacy_run_id": run.id,
            "source": "agent",
            "agent_type": run.agent_type,
            "user_id": run.user_id,
            "conversation_id": run.conversation_id,
            "message_id": run.message_id,
            "chat_task_id": None,
            "workflow_run_id": None,
            "eval_run_id": None,
            "eval_case_id": None,
            "status": run.status,
            "input_preview": None if redact_io else run.input_message,
            "output_preview": run.output_response,
            "error_type": run.error_type,
            "error_message": run.error_message,
            "model_name": None,
            "tokens_input": run.tokens_input,
            "tokens_output": run.tokens_output,
            "cost_cny": None,
            "total_latency_ms": run.total_latency_ms,
            "llm_latency_ms": run.llm_latency_ms,
            "tool_latency_ms": run.tool_latency_ms,
            "mcp_latency_ms": None,
            "sandbox_latency_ms": None,
            "budget_json": None,
            "metadata_json": None,
            "started_at": _jsonable(run.created_at),
            "ended_at": None,
            "created_at": _jsonable(run.created_at),
            "tool_call_count": run.tool_call_count or 0,
            "legacy": True,
        }

        return {
            "run": run_dict,
            "spans": spans,
            "events": [],
            "artifacts": [],
            "links": [],
        }
