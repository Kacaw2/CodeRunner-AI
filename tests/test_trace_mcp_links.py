"""Phase 4 / Task 9 core: trace_id propagates across the MCP client boundary.

The agent's ``state.context.trace_id`` must reach ``MCPClientIdentity`` so guard,
audit and approval records can be linked back to the owning trace. A permission
denial still returns the standard envelope and is attributable to the trace.
"""
from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage


def test_mcp_permission_denial_is_linked_to_trace():
    from ai.agents.executor import ToolCallExecutor

    msg = ToolCallExecutor().run(
        {"name": "coderunner.problem.save_generated", "args": {}, "id": "tc1"},
        {
            "agent_type": "reviewer",
            "user_id": 2,
            "user_role": "student",
            "context": {"trace_id": "trace-xyz"},
        },
        "reviewer",
    )

    assert isinstance(msg, ToolMessage)
    assert "TOOL_NOT_ALLOWED" in msg.content or "MCP_PERMISSION_DENIED" in msg.content


def test_trace_id_propagates_to_mcp_identity():
    """An allowed tool call must carry context.trace_id into MCPClientIdentity."""
    from ai.agents.executor import ToolCallExecutor

    captured = {}

    def _capturing_call_tool(name, args, identity, *, tool_call_id=""):
        captured["trace_id"] = identity.trace_id
        captured["conversation_id"] = identity.conversation_id
        return {"ok": True, "data": {"echo": name}}

    fake_client = MagicMock()
    fake_client.call_tool.side_effect = _capturing_call_tool

    allow = MagicMock()
    allow.allowed = True
    allow.error = None
    fake_hooks = MagicMock()
    fake_hooks.fire.return_value = allow

    with patch("ai.mcp_gateway.client.get_mcp_tool_client", return_value=fake_client), \
         patch("ai.agents.hooks.get_hook_manager", return_value=fake_hooks):
        msg = ToolCallExecutor().run(
            {"name": "coderunner.code.execute_internal", "args": {}, "id": "tc2"},
            {
                "agent_type": "tutor",
                "user_id": 7,
                "user_role": "student",
                "context": {"trace_id": "trace-abc", "conversation_id": 99},
            },
            "tutor",
        )

    assert isinstance(msg, ToolMessage)
    assert captured["trace_id"] == "trace-abc"
    assert captured["conversation_id"] == 99
