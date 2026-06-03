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


def _mock_llm_no_tools(text="Here is a hint."):
    class _Resp:
        content = text
        tool_calls = []
        usage_metadata = {"input_tokens": 5, "output_tokens": 3}
        response_metadata = {}
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = _Resp()
    return llm


def test_runtime_run_sets_trace_id_and_strips_system_prompt(monkeypatch):
    from agents.runtime import AgentRuntime
    from agents.session import AgentSession
    from langchain_core.messages import SystemMessage
    import agents.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm",
                        staticmethod(lambda tier=None: _mock_llm_no_tools()))

    from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    try:
        state = {
            "messages": [HumanMessage(content="help")],
            "agent_type": "tutor",
            "user_id": 7,
            "user_role": "student",
            "context": {},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        result = AgentRuntime().run(session, tool_names=[], system_ctx="SYS")

        assert result["trace_id"]
        assert result["final_response"] == "Here is a hint."
        assert all(not isinstance(m, SystemMessage) for m in result["messages"])
    finally:
        reset_tool_runtime()
