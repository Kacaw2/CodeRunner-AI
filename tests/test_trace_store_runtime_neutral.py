"""TraceCollector must persist through the runtime-neutral TraceStore.

The key property: saving a trace writes to ``agent_trace_runs`` via plain
SQLAlchemy (``core.db.session``) WITHOUT importing any Flask-SQLAlchemy model,
so worker processes never trigger Flask mapper configuration (the historical
``TRACE_SAVE_FAIL`` root cause).

``app`` / ``_setup_db`` are required so the conftest bridge has pointed
``core.db.session`` at the test engine and created the trace tables on it.
"""


def test_trace_collector_saves_without_flask_mapper(app, _setup_db):
    from core.observability.tracing import TraceCollector
    from domain.models.observability import AgentTraceRun, AgentTraceSpan
    from core.db.session import db_session

    trace = TraceCollector(
        agent_type="tutor",
        user_id=2,
        conversation_id=123,
        source="workers",
        links={"chat_task_id": "task-1"},
    )
    trace.input_message = "help me"
    with trace.trace_llm_call() as step:
        # Callers set the run-level totals directly (mirrors agents/base.py)
        # and annotate the step for span-level display.
        trace.total_input_tokens += 10
        trace.total_output_tokens += 5
        step["prompt_tokens"] = 10
        step["completion_tokens"] = 5

    trace.save(status="completed", response="hint")

    with db_session() as session:
        run = session.query(AgentTraceRun).filter_by(trace_id=trace.run_id).one()
        assert run.source == "workers"
        assert run.agent_type == "tutor"
        assert run.conversation_id == 123
        assert run.status == "completed"
        assert run.chat_task_id == "task-1"
        assert run.tokens_input == 10
        assert run.tokens_output == 5
        assert run.output_preview == "hint"

        spans = session.query(AgentTraceSpan).filter_by(trace_id=trace.run_id).all()
        assert any(s.span_type == "llm" for s in spans)
