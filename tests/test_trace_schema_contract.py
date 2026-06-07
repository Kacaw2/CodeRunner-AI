"""Schema contract for the complete trace/eval tables.

These tables are runtime-neutral mappings on ``DomainBase.metadata``. The test
inspects the Flask test engine because Flask uses the same shared metadata
(``create_all`` is test-only; production schema remains Alembic-owned).
"""


def test_trace_tables_have_complete_columns(app, _setup_db):
    from sqlalchemy import inspect
    from app.core.extensions import db

    with app.app_context():
        inspector = inspect(db.engine)
        columns = {
            table: {c["name"] for c in inspector.get_columns(table)}
            for table in [
                "agent_trace_runs",
                "agent_trace_spans",
                "agent_trace_events",
                "agent_trace_artifacts",
                "agent_trace_links",
                "eval_case_runs",
                "eval_case_grader_results",
            ]
        }

    assert {"id", "trace_id", "agent_type", "status", "started_at", "ended_at", "total_latency_ms", "cost_cny"} <= columns["agent_trace_runs"]
    assert {"id", "trace_id", "parent_span_id", "span_type", "name", "started_at", "ended_at", "latency_ms", "status"} <= columns["agent_trace_spans"]
    assert {"id", "trace_id", "span_id", "event_type", "payload_json", "created_at"} <= columns["agent_trace_events"]
    assert {"id", "trace_id", "span_id", "artifact_type", "name", "mime_type", "storage_uri", "preview_text", "payload_json"} <= columns["agent_trace_artifacts"]
    assert {"id", "trace_id", "link_type", "target_table", "target_id"} <= columns["agent_trace_links"]
    assert {"id", "eval_run_id", "case_id", "trace_id", "status", "passed", "duration_ms", "cost_cny"} <= columns["eval_case_runs"]
    assert {"id", "case_run_id", "grader_type", "grader_name", "passed", "score", "reason", "latency_ms", "cost_cny"} <= columns["eval_case_grader_results"]
