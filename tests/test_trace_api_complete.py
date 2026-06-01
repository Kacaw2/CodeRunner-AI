"""Phase 3: /api/v1/ai/traces must read the new agent_trace_* tables.

These tests assert the complete trace API contract:
- ``GET /api/v1/ai/traces`` lists runs from ``agent_trace_runs`` with filters.
- ``GET /api/v1/ai/traces/<trace_id>`` returns the full tree
  (run / spans / events / artifacts / links) with cost.
- legacy ``agent_runs.id`` stays viewable through a read-only fallback.

Seeding goes through the runtime-neutral models on ``core.db.session`` so the
test exercises the same physical tables the workers write to.
"""

from datetime import datetime, timedelta

import pytest


def _seed_complete_trace(trace_id="trace-complete-1", **overrides):
    """Insert one run plus a span/event/artifact/link via plain SQLAlchemy."""
    from decimal import Decimal

    from core.db.models.agent_trace import (
        AgentTraceArtifact,
        AgentTraceEvent,
        AgentTraceLink,
        AgentTraceRun,
        AgentTraceSpan,
    )
    from core.db.session import db_session

    started = datetime(2026, 6, 1, 10, 0, 0)
    run_kwargs = dict(
        id=trace_id,
        trace_id=trace_id,
        source="workers",
        agent_type="tutor",
        user_id=2,
        conversation_id=123,
        chat_task_id="task-1",
        status="completed",
        input_preview="help me",
        output_preview="here is a hint",
        model_name="deepseek-chat",
        tokens_input=10,
        tokens_output=5,
        cost_cny=Decimal("0.001234"),
        total_latency_ms=420,
        llm_latency_ms=300,
        tool_latency_ms=120,
        started_at=started,
        ended_at=started + timedelta(milliseconds=420),
        created_at=started,
    )
    run_kwargs.update(overrides)

    with db_session() as session:
        session.add(AgentTraceRun(**run_kwargs))
        session.add(
            AgentTraceSpan(
                id=f"{trace_id}-span-llm",
                trace_id=trace_id,
                span_type="llm",
                name="llm_call",
                status="completed",
                sequence=0,
                tokens_input=10,
                tokens_output=5,
                latency_ms=300,
                started_at=started,
                ended_at=started + timedelta(milliseconds=300),
            )
        )
        session.add(
            AgentTraceSpan(
                id=f"{trace_id}-span-tool",
                trace_id=trace_id,
                span_type="tool",
                name="coderunner.problem.save_generated",
                status="completed",
                sequence=1,
                input_preview='{"title": "x"}',
                output_preview="ok",
                latency_ms=120,
                started_at=started,
                ended_at=started + timedelta(milliseconds=120),
            )
        )
        session.add(
            AgentTraceEvent(
                id=f"{trace_id}-evt",
                trace_id=trace_id,
                span_id=f"{trace_id}-span-tool",
                event_type="tool_call",
                payload_json={"name": "save"},
                created_at=started,
            )
        )
        session.add(
            AgentTraceArtifact(
                id=f"{trace_id}-art",
                trace_id=trace_id,
                span_id=f"{trace_id}-span-tool",
                artifact_type="tool_output",
                name="generated_problem.json",
                mime_type="application/json",
                preview_text='{"ok": true}',
                created_at=started,
            )
        )
        session.add(
            AgentTraceLink(
                id=f"{trace_id}-link",
                trace_id=trace_id,
                link_type="chat_task",
                target_table="chat_tasks",
                target_id="task-1",
                created_at=started,
            )
        )
    return trace_id


def test_trace_list_returns_new_table_runs(client, mock_auth_teacher):
    trace_id = _seed_complete_trace("trace-list-1")

    resp = client.get("/api/v1/ai/traces?limit=20&offset=0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "traces" in data
    assert data["total"] >= 1
    ids = {t["id"] for t in data["traces"]}
    assert trace_id in ids
    row = next(t for t in data["traces"] if t["id"] == trace_id)
    assert row["agent_type"] == "tutor"
    assert row["status"] == "completed"
    assert row["source"] == "workers"
    assert float(row["cost_cny"]) == pytest.approx(0.001234)


def test_trace_list_filters_by_agent_and_status(client, mock_auth_teacher):
    _seed_complete_trace("trace-f-tutor", agent_type="tutor", status="completed")
    _seed_complete_trace("trace-f-rev", agent_type="reviewer", status="failed")

    resp = client.get("/api/v1/ai/traces?agent_type=reviewer&status=failed")
    assert resp.status_code == 200
    rows = resp.get_json()["traces"]
    assert all(r["agent_type"] == "reviewer" for r in rows)
    assert any(r["id"] == "trace-f-rev" for r in rows)
    assert all(r["id"] != "trace-f-tutor" for r in rows)


def test_trace_detail_returns_tree_cost_artifacts_and_links(client, mock_auth_teacher):
    trace_id = _seed_complete_trace("trace-detail-1")

    resp = client.get(f"/api/v1/ai/traces/{trace_id}")
    assert resp.status_code == 200
    data = resp.get_json()

    assert "run" in data
    assert "spans" in data
    assert "events" in data
    assert "artifacts" in data
    assert "links" in data

    assert data["run"]["trace_id"] == trace_id
    assert data["run"]["cost_cny"] is not None
    assert {s["span_type"] for s in data["spans"]} == {"llm", "tool"}
    assert len(data["events"]) == 1
    assert data["artifacts"][0]["artifact_type"] == "tool_output"
    assert data["links"][0]["link_type"] == "chat_task"


def test_trace_detail_unknown_id_returns_404(client, mock_auth_teacher):
    resp = client.get("/api/v1/ai/traces/does-not-exist")
    assert resp.status_code == 404


def test_trace_detail_falls_back_to_legacy_agent_run(client, mock_auth_teacher, db_session):
    """A historical agent_runs row stays viewable until backfill (Phase 7)."""
    from app.models.agent_trace import AgentRun

    legacy = AgentRun(
        id="legacy-run-1",
        user_id=2,
        agent_type="tutor",
        status="completed",
        input_message="legacy in",
        output_response="legacy out",
        total_latency_ms=100,
        tokens_input=3,
        tokens_output=4,
        tool_call_count=0,
    )
    db_session.add(legacy)
    db_session.commit()

    resp = client.get("/api/v1/ai/traces/legacy-run-1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["run"]["trace_id"] == "legacy-run-1"
    assert data["run"]["legacy"] is True
    assert "spans" in data
