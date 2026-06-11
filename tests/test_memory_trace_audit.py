"""Integration tests for memory selection plumbing: session carry-through,
runtime trace audit (added in later tasks)."""


def test_base_agent_memory_helper_stashes_selection(app):
    from unittest.mock import patch
    from ai.agents.tutor.agent import TutorAgent

    state = {
        "messages": [],
        "agent_type": "tutor",
        "user_id": 1,
        "user_role": "student",
        "context": {},
        "tool_results": [],
        "final_response": "",
    }
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.prepare_memory_context"
    ) as prepare:
        prepare.return_value.rendered = "Student Background: test"

        rendered = TutorAgent()._prepare_memory_for_state(state)

    assert rendered == "Student Background: test"
    assert state["_memory_selection"] is prepare.return_value


def test_trace_collector_persists_memory_event(app, db_session):
    from core.observability.tracing import TraceCollector
    from domain.models.observability import AgentTraceEvent

    with app.app_context():
        trace = TraceCollector(agent_type="tutor", user_id=1)
        trace.add_event(
            event_type="memory_context_selected",
            payload_json={"included_count": 2, "filtered_count": 1},
        )
        trace.save(status="completed", response="ok")

        row = (
            db_session.query(AgentTraceEvent)
            .filter_by(trace_id=trace.run_id)
            .one()
        )
        assert row.event_type == "memory_context_selected"
        assert row.payload_json["filtered_count"] == 1


def test_runtime_records_memory_selection_on_trace():
    from unittest.mock import MagicMock
    from ai.agents.runtime import _record_memory_selection

    trace = MagicMock()
    decision = MagicMock(
        source="profile:1",
        key="learning_summary",
        included=True,
        reason=MagicMock(value="included"),
        rendered_chars=32,
        estimated_tokens=8,
        priority=80,
    )
    selection = MagicMock(
        decisions=(decision,),
        rendered_chars=32,
        estimated_tokens=8,
        snapshot_hash="a" * 64,
    )

    _record_memory_selection(trace, selection)

    trace.add_event.assert_called_once()
    trace.add_artifact.assert_called_once()
    payload = trace.add_event.call_args.kwargs["payload_json"]
    assert payload["included_count"] == 1
    assert payload["snapshot_hash"] == "a" * 64
