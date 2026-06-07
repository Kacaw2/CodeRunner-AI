"""Tests for the legacy agent_runs -> agent_trace_* backfill (Task 11)."""

from __future__ import annotations

from sqlalchemy import select

from app.core.extensions import db
from app.models.agent_trace import AgentRun, AgentRunStep
from core.db.session import db_session as core_db_session
from domain.models.observability import AgentTraceRun, AgentTraceSpan


def _seed_legacy_run(run_id: str, user_id: int = 1) -> str:
    run = AgentRun(
        id=run_id,
        user_id=user_id,
        agent_type="tutor",
        status="completed",
        input_message="explain recursion",
        output_response="Recursion is …",
        tokens_input=120,
        tokens_output=80,
        total_latency_ms=1500,
        tool_call_count=1,
    )
    db.session.add(run)
    db.session.add(
        AgentRunStep(
            run_id=run_id,
            step_index=0,
            step_type="llm_call",
            llm_prompt_tokens=120,
            llm_completion_tokens=80,
            latency_ms=900,
        )
    )
    db.session.add(
        AgentRunStep(
            run_id=run_id,
            step_index=1,
            step_type="tool_call",
            tool_name="coderunner.search",
            tool_success=True,
            latency_ms=600,
        )
    )
    db.session.commit()
    return run_id


def test_backfill_copies_legacy_agent_runs(app, db_session):
    from scripts.backfill_agent_traces import backfill

    copied = backfill(limit=100)
    assert copied >= 0


def test_backfill_maps_run_and_steps(app, db_session):
    from scripts.backfill_agent_traces import backfill

    _seed_legacy_run("legacy-run-aaa")
    copied = backfill(limit=100)
    assert copied == 1

    with core_db_session() as session:
        trace = (
            session.query(AgentTraceRun).filter_by(trace_id="legacy-run-aaa").first()
        )
        assert trace is not None
        assert trace.legacy_run_id == "legacy-run-aaa"
        assert trace.tokens_input == 120
        assert trace.status == "completed"

        spans = (
            session.query(AgentTraceSpan)
            .filter_by(trace_id="legacy-run-aaa")
            .order_by(AgentTraceSpan.sequence)
            .all()
        )
        assert [s.span_type for s in spans] == ["llm", "tool"]
        assert spans[1].name == "coderunner.search"


def test_backfill_is_idempotent(app, db_session):
    from scripts.backfill_agent_traces import backfill

    _seed_legacy_run("legacy-run-bbb")
    first = backfill(limit=100)
    second = backfill(limit=100)
    assert first == 1
    assert second == 0

    with core_db_session() as session:
        traces = (
            session.query(AgentTraceRun).filter_by(trace_id="legacy-run-bbb").all()
        )
        assert len(traces) == 1
