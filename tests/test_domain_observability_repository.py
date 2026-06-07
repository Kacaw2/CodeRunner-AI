"""Observability domain and repository migration contracts."""

from __future__ import annotations

from datetime import datetime


def test_observability_mappings_use_the_shared_domain_metadata():
    from domain.base import DomainBase
    from domain.models.observability import AgentTraceRun, EvalCaseRun, EvalRun

    assert AgentTraceRun.metadata is DomainBase.metadata
    assert EvalCaseRun.metadata is DomainBase.metadata
    assert EvalRun.metadata is DomainBase.metadata


def test_trace_store_delegates_to_an_injected_repository():
    from core.observability.trace_schema import TraceRunRecord
    from core.observability.trace_store import TraceStore

    captured = {}

    class FakeTraceRepository:
        def save_trace(self, run, *, spans, events, artifacts, links):
            captured["run"] = run
            captured["spans"] = spans
            captured["events"] = events
            captured["artifacts"] = artifacts
            captured["links"] = links

    now = datetime(2026, 6, 7, 12, 0, 0)
    record = TraceRunRecord(
        id="run-1",
        trace_id="trace-1",
        source="test",
        status="completed",
        started_at=now,
        created_at=now,
    )

    TraceStore(repository=FakeTraceRepository()).save_run(record)

    assert captured["run"] is record
    assert captured["spans"] == []
    assert captured["events"] == []
    assert captured["artifacts"] == []
    assert captured["links"] == []


def test_sync_trace_repository_persists_a_complete_trace(db_session):
    from core.observability.trace_schema import (
        TraceRunRecord,
        TraceSpanRecord,
    )
    from domain.repositories.traces import SyncTraceRepository

    now = datetime(2026, 6, 7, 12, 0, 0)
    repo = SyncTraceRepository(db_session)
    repo.save_trace(
        TraceRunRecord(
            id="run-2",
            trace_id="trace-2",
            source="test",
            status="completed",
            started_at=now,
            created_at=now,
        ),
        spans=[
            TraceSpanRecord(
                id="span-2",
                trace_id="trace-2",
                span_type="llm",
                name="model",
                status="completed",
                started_at=now,
            )
        ],
        events=[],
        artifacts=[],
        links=[],
    )
    db_session.flush()

    run = repo.get_run("trace-2")
    bundle = repo.get_trace_bundle("trace-2")
    assert run is not None
    assert run.source == "test"
    assert [span.id for span in bundle["spans"]] == ["span-2"]


def test_sync_eval_repository_owns_eval_row_access(db_session):
    from domain.repositories.evals import SyncEvalRepository

    repo = SyncEvalRepository(db_session)
    run = repo.create_run(
        suite_name="tutor",
        model_name="deepseek-chat",
        total_cases=1,
        passed_cases=0,
        pass_rate=0.0,
    )
    db_session.flush()
    case = repo.create_case_run(
        eval_run_id=run.id,
        case_id="tutor::1",
        case_type="golden",
        suite="tutor",
        agent_type="tutor",
        trace_id="trace-3",
        status="passed",
        passed=True,
    )
    db_session.flush()
    repo.create_grader_result(
        case_run_id=case.id,
        grader_type="deterministic",
        grader_name="contains",
        passed=True,
        score=1.0,
    )
    repo.finalize_run(
        run.id,
        total_cases=1,
        passed_cases=1,
        pass_rate=1.0,
        duration_seconds=0.1,
        results_json=[{"case_id": "tutor::1", "passed": True}],
    )
    db_session.flush()

    saved_run, cases = repo.load_run_with_cases(run.id)
    graders = repo.list_grader_results([case.id])
    assert saved_run.pass_rate == 1.0
    assert [row.case_id for row in cases] == ["tutor::1"]
    assert [row.grader_name for row in graders] == ["contains"]


def test_core_session_no_longer_exports_base_alias():
    import core.db.session as core_session

    assert not hasattr(core_session, "Base")
