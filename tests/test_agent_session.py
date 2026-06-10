"""Unit tests for AgentSession: lossless state<->session and identity build."""

from langchain_core.messages import HumanMessage


def _state():
    return {
        "messages": [HumanMessage(content="help me")],
        "agent_type": "tutor",
        "user_id": 7,
        "user_role": "student",
        "context": {"conversation_id": 10, "task_id": "t-1", "question_id": 3},
        "tool_results": [],
        "final_response": "",
    }


def test_from_state_pulls_core_fields():
    from ai.agents.session import AgentSession

    s = AgentSession.from_state(_state(), agent_name="tutor")
    assert s.agent_name == "tutor"
    assert s.user_id == 7
    assert s.user_role == "student"
    assert s.context["conversation_id"] == 10
    assert s.definition is not None and s.definition.name == "tutor"


def test_to_state_roundtrip_preserves_messages_and_context():
    from ai.agents.session import AgentSession

    original = _state()
    s = AgentSession.from_state(original, agent_name="tutor")
    rebuilt = s.to_state()
    assert rebuilt["agent_type"] == "tutor"
    assert rebuilt["user_id"] == 7
    assert rebuilt["context"]["question_id"] == 3
    assert rebuilt["messages"] == original["messages"]


def test_session_carries_memory_selection_without_public_state_leak():
    from unittest.mock import MagicMock
    from ai.agents.session import AgentSession

    selection = MagicMock()
    state = {
        "messages": [],
        "agent_type": "tutor",
        "user_id": 1,
        "user_role": "student",
        "context": {},
        "tool_results": [],
        "final_response": "",
        "_memory_selection": selection,
    }

    session = AgentSession.from_state(state)

    assert session.memory_selection is selection
    assert "_memory_selection" not in session.to_state()


def test_mcp_identity_uses_session_trace_id_not_context():
    from ai.agents.session import AgentSession

    s = AgentSession.from_state(_state(), agent_name="tutor")
    s.trace_id = "trace-abc"  # set once the trace is acquired
    identity = s.mcp_identity()
    assert identity.trace_id == "trace-abc"
    assert identity.user_id == 7
    assert identity.role == "student"
    assert identity.agent_type == "tutor"
    assert identity.task_id == "t-1"
    assert identity.conversation_id == 10
