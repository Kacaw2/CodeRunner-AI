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


def test_handoff_records_source_agent():
    state = _state_with_residue()
    _check_handoff(state)
    assert state["handoff_source"] == "tutor"


def test_validate_handoff_target_allows_declared_edge():
    from graph.handoff import validate_handoff_target

    # tutor declares {reviewer, analytics}; a student may use reviewer.
    assert validate_handoff_target("tutor", "reviewer", "student") is None


def test_validate_handoff_target_rejects_undeclared_edge():
    from graph.handoff import validate_handoff_target

    # generator declares {analytics} only — generator->tutor is not allowed.
    error = validate_handoff_target("generator", "tutor", "teacher")
    assert error is not None
    assert "generator" in error


def test_validate_handoff_target_rejects_self_handoff():
    from graph.handoff import validate_handoff_target

    assert validate_handoff_target("tutor", "tutor", "student") is not None


def test_validate_handoff_target_rejects_unknown_target():
    from graph.handoff import validate_handoff_target

    assert validate_handoff_target("tutor", "nonexistent", "student") is not None


def _bootstrapped_runtime():
    from mcp_gateway.bootstrap import bootstrap_tool_runtime
    from tools.protocol.runtime import get_tool_runtime, set_tool_runtime, reset_tool_runtime

    return bootstrap_tool_runtime, get_tool_runtime, set_tool_runtime, reset_tool_runtime


def test_delegate_tool_call_populates_handoff_fields():
    """End-to-end: the delegate tool, called as an agent through the real
    pipeline, returns the structured handoff fields (no free-text marker)."""
    from mcp_gateway.client import InProcessMCPToolClient, MCPClientIdentity

    boot, get_rt, set_rt, reset_rt = _bootstrapped_runtime()
    previous = get_rt()
    try:
        boot()
        client = InProcessMCPToolClient()
        identity = MCPClientIdentity(user_id=1, role="student", agent_type="tutor")
        envelope = client.call_tool(
            "coderunner.agent.delegate",
            {"target": "reviewer", "reason": "needs structured review",
             "summary": "off-by-one in inner loop"},
            identity,
        )
        assert envelope["ok"] is True
        data = envelope["data"]
        assert data["handoff_to"] == "reviewer"
        assert data["handoff_source"] == "tutor"
        assert data["handoff_summary"] == "off-by-one in inner loop"
    finally:
        reset_rt()
        set_rt(previous)


def test_delegate_tool_call_rejects_undeclared_target():
    """An edge the source agent does not declare is denied at the tool boundary,
    not silently dropped — the agent cannot route to an unintended agent."""
    from mcp_gateway.client import InProcessMCPToolClient, MCPClientIdentity

    boot, get_rt, set_rt, reset_rt = _bootstrapped_runtime()
    previous = get_rt()
    try:
        boot()
        client = InProcessMCPToolClient()
        # tutor does not declare generator as a handoff target.
        identity = MCPClientIdentity(user_id=1, role="teacher", agent_type="tutor")
        envelope = client.call_tool(
            "coderunner.agent.delegate",
            {"target": "generator", "reason": "make a problem"},
            identity,
        )
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "MCP_PERMISSION_DENIED"
    finally:
        reset_rt()
        set_rt(previous)


def test_apply_handoff_worker_mode_replaces_list_without_remove_markers():
    """Worker state is a plain list: no RemoveMessage markers, direct replace."""
    from graph.handoff import apply_handoff

    state = _state_with_residue()
    apply_handoff(state, use_reducer=False)

    msgs = state["messages"]
    assert not any(isinstance(m, RemoveMessage) for m in msgs)
    assert all(isinstance(m, HumanMessage) for m in msgs)
    assert any("bubble sort" in m.content for m in msgs)
    assert any("off-by-one" in m.content for m in msgs)
    assert not any(isinstance(m, (AIMessage, ToolMessage)) for m in msgs)

    assert state["agent_type"] == "reviewer"
    assert state["handoff_source"] == "tutor"
    assert state["handoff_to"] is None
    assert state.get("handoff_summary") is None
