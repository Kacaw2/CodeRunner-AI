"""Boundary tests: internal agents must call tools through an MCP client
adapter, not by importing ToolRuntime directly (Task 6)."""

import inspect


def test_base_agent_does_not_import_tool_runtime_for_tool_execution():
    from agents.executor import ToolCallExecutor

    # Tool execution lives in ToolCallExecutor (extracted from BaseAgent); the
    # boundary guarantee applies wherever the runtime call actually happens.
    source = inspect.getsource(ToolCallExecutor.run)
    assert "get_tool_runtime" not in source
    assert "call_sync" not in source


def test_base_agent_delegates_tool_execution_to_executor():
    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._run_mcp_tool)
    assert "_tool_executor" in source


def test_base_agent_uses_mcp_client_adapter_for_tool_execution():
    from agents.executor import ToolCallExecutor

    source = inspect.getsource(ToolCallExecutor.run)
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


def _signing_keypair() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def test_configure_from_env_selects_transport_client(monkeypatch):
    from mcp_gateway.client import (
        configure_mcp_client_from_env,
        StreamableHTTPMCPToolClient,
        set_mcp_tool_client,
    )

    private_pem, _ = _signing_keypair()
    monkeypatch.setenv("MCP_AGENT_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_INTERNAL_SIGNING_KEY", private_pem)
    monkeypatch.setenv("MCP_GATEWAY_URL", "http://gw:8200/mcp")
    try:
        client = configure_mcp_client_from_env()
        assert isinstance(client, StreamableHTTPMCPToolClient)
    finally:
        set_mcp_tool_client(None)


def test_configure_transport_requires_signing_key(monkeypatch):
    import pytest
    from mcp_gateway.client import configure_mcp_client_from_env, set_mcp_tool_client

    monkeypatch.setenv("MCP_AGENT_TRANSPORT", "streamable-http")
    monkeypatch.delenv("MCP_INTERNAL_SIGNING_KEY", raising=False)
    try:
        with pytest.raises(RuntimeError, match="MCP_INTERNAL_SIGNING_KEY"):
            configure_mcp_client_from_env()
    finally:
        set_mcp_tool_client(None)


def test_transport_client_mints_verifiable_token_with_minimal_scopes():
    """The transport client signs identity + minimal scopes; the role is in the
    signature, so the agent cannot self-elevate via headers."""
    from mcp_gateway.client import StreamableHTTPMCPToolClient, MCPClientIdentity
    from mcp_gateway.internal_auth import verify_internal_token

    private_pem, public_pem = _signing_keypair()
    client = StreamableHTTPMCPToolClient("http://gw:8200/mcp", private_pem)
    identity = MCPClientIdentity(
        user_id=7, role="student", agent_type="tutor",
        task_id="task-1", conversation_id="conv-1",
    )

    header = client._build_auth_header(identity)
    assert header.startswith("Bearer ")
    claims = verify_internal_token(header[len("Bearer "):], verify_key=public_pem)

    assert claims is not None
    assert claims["sub"] == "7"
    assert claims["role"] == "student"
    assert claims["agent_type"] == "tutor"
    assert claims["task_id"] == "task-1"
    assert set(claims["scopes"]) == {
        "code:execute", "problem:read", "submission:read", "knowledge:read",
        "agent:delegate",
    }
