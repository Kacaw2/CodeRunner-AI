"""Boundary tests: internal agents must call tools through an MCP client
adapter, not by importing ToolRuntime directly (Task 6)."""

import inspect


def test_base_agent_does_not_import_tool_runtime_for_tool_execution():
    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._run_mcp_tool)
    assert "get_tool_runtime" not in source
    assert "call_sync" not in source


def test_base_agent_uses_mcp_client_adapter_for_tool_execution():
    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._run_mcp_tool)
    assert "MCPToolClient" in source or "get_mcp_tool_client" in source


def test_default_client_is_in_process():
    from mcp_gateway import client as client_mod
    from mcp_gateway.client import (
        InProcessMCPToolClient,
        get_mcp_tool_client,
        set_mcp_tool_client,
    )

    set_mcp_tool_client(None)
    try:
        assert isinstance(get_mcp_tool_client(), InProcessMCPToolClient)
    finally:
        set_mcp_tool_client(None)


def test_in_process_client_delegates_to_runtime():
    from unittest.mock import MagicMock
    from mcp_gateway.client import InProcessMCPToolClient, MCPClientIdentity
    from tools.protocol.runtime import (
        ToolRuntime,
        ToolResult,
        set_tool_runtime,
        reset_tool_runtime,
    )

    mock_runtime = MagicMock(spec=ToolRuntime)
    mock_runtime.call_sync.return_value = ToolResult(
        ok=True, tool="coderunner.problem.get_detail", data={"title": "Two Sum"}
    )
    set_tool_runtime(mock_runtime)
    try:
        client = InProcessMCPToolClient()
        identity = MCPClientIdentity(user_id=1, role="student", agent_type="tutor")
        envelope = client.call_tool(
            "coderunner.problem.get_detail", {"problem_id": 1}, identity
        )
        assert envelope["ok"] is True
        assert envelope["data"]["title"] == "Two Sum"
        # The agent_host caller identity crossed the client, not the agent.
        _, _, ctx = mock_runtime.call_sync.call_args[0]
        assert ctx.caller.actor_type == "agent_host"
        assert ctx.caller.agent_type == "tutor"
    finally:
        reset_tool_runtime()


def test_configure_from_env_selects_transport_client(monkeypatch):
    from mcp_gateway.client import (
        configure_mcp_client_from_env,
        StreamableHTTPMCPToolClient,
        set_mcp_tool_client,
    )

    monkeypatch.setenv("MCP_AGENT_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_INTERNAL_AUTH_TOKEN", "svc-token")
    monkeypatch.setenv("MCP_GATEWAY_URL", "http://gw:8200/mcp")
    try:
        client = configure_mcp_client_from_env()
        assert isinstance(client, StreamableHTTPMCPToolClient)
    finally:
        set_mcp_tool_client(None)


def test_configure_transport_requires_auth_token(monkeypatch):
    import pytest
    from mcp_gateway.client import configure_mcp_client_from_env, set_mcp_tool_client

    monkeypatch.setenv("MCP_AGENT_TRANSPORT", "streamable-http")
    monkeypatch.delenv("MCP_INTERNAL_AUTH_TOKEN", raising=False)
    try:
        with pytest.raises(RuntimeError, match="MCP_INTERNAL_AUTH_TOKEN"):
            configure_mcp_client_from_env()
    finally:
        set_mcp_tool_client(None)
