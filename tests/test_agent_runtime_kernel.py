"""Phase 1 runtime-kernel regressions: trace join, prompt isolation, limits."""

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage


def test_executor_uses_session_trace_id_for_identity():
    """The tool identity must carry the run's real trace_id, not context's None."""
    from agents.executor import ToolCallExecutor
    from agents.session import AgentSession
    from mcp_gateway import client as client_mod

    captured = {}

    class _FakeClient:
        def call_tool(self, name, args, identity, tool_call_id=""):
            captured["trace_id"] = identity.trace_id
            captured["agent_type"] = identity.agent_type
            return {"ok": True, "data": {"title": "Two Sum"}}

    client_mod.set_mcp_tool_client(_FakeClient())
    try:
        state = {
            "messages": [HumanMessage(content="x")],
            "agent_type": "tutor",
            "user_id": 7,
            "user_role": "student",
            "context": {"conversation_id": 10},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        session.trace_id = "trace-xyz"

        tool_call = {"name": "coderunner.problem.get_detail", "args": {"problem_id": 1}, "id": "tc1"}
        msg = ToolCallExecutor().run(tool_call, state, "tutor", session=session)

        assert captured["trace_id"] == "trace-xyz"
        assert captured["agent_type"] == "tutor"
        assert "Two Sum" in msg.content
    finally:
        client_mod.set_mcp_tool_client(None)
