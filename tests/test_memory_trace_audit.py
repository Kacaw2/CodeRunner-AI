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
