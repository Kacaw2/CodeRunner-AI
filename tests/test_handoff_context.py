"""Tests for handoff context rebuild: drop tool residue, keep original + summary."""
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, RemoveMessage

from graph.runner import _check_handoff


def _state_with_residue():
    original = HumanMessage(content="Review my bubble sort and explain the bug.", id="h1")
    ai = AIMessage(content="Let me run the code.", id="a1")
    tool = ToolMessage(content="exit code 1, IndexError", tool_call_id="tc1", id="t1")
    ai2 = AIMessage(content="The loop overruns the array.", id="a2")
    return {
        "messages": [original, ai, tool, ai2],
        "agent_type": "tutor",
        "user_role": "student",
        "handoff_to": "reviewer",
        "handoff_summary": "The bug is an off-by-one in the inner loop bound.",
        "previous_agents": ["tutor"],
    }


def test_handoff_routes_to_target():
    state = _state_with_residue()
    assert _check_handoff(state) == "reviewer"
    assert state["agent_type"] == "reviewer"


def test_handoff_clears_transient_fields():
    state = _state_with_residue()
    _check_handoff(state)
    assert state["handoff_to"] is None
    assert state.get("handoff_reason") is None
    assert state.get("handoff_summary") is None


def test_handoff_rebuilds_messages_without_tool_residue():
    state = _state_with_residue()
    _check_handoff(state)
    msgs = state["messages"]

    removals = [m for m in msgs if isinstance(m, RemoveMessage)]
    kept = [m for m in msgs if not isinstance(m, RemoveMessage)]

    # Every prior message (which had an id) is explicitly removed.
    assert {m.id for m in removals} == {"h1", "a1", "t1", "a2"}

    # What's handed forward is only HumanMessages: original question + summary.
    assert all(isinstance(m, HumanMessage) for m in kept)
    assert any("bubble sort" in m.content for m in kept)
    assert any("off-by-one" in m.content for m in kept)

    # No AIMessage/ToolMessage residue survives into the next agent's context.
    assert not any(isinstance(m, (AIMessage, ToolMessage)) for m in kept)


def test_handoff_blocked_when_already_processed_by_target():
    state = _state_with_residue()
    state["previous_agents"] = ["tutor", "reviewer"]
    assert _check_handoff(state) == "respond"
