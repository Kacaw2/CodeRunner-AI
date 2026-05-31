"""agent_host callers are scope-enforced like everyone else (F1 defense in depth).

The old ``actor_type == "agent_host"`` god-mode scope bypass is removed: an
internal caller must carry the scopes its tools require, supplied as signed
claims (transport) or derived minimal scopes (in-process).
"""

import pytest

from core.auth.context import CallerContext
from tools.protocol.schemas.descriptors import ToolDescriptor
from tools.protocol.errors import MCPScopeDenied
from tools.protocol.policies.scopes import check_scope


def _scoped_tool() -> ToolDescriptor:
    return ToolDescriptor(
        name="coderunner.problem.get_detail",
        version="1.0.0",
        description="",
        input_schema={},
        output_schema={},
        required_scopes=["problem:read"],
        server="db",
    )


def test_agent_host_without_required_scope_is_denied():
    ctx = CallerContext(actor_type="agent_host", user_id=7, role="student", agent_type="tutor")
    with pytest.raises(MCPScopeDenied):
        check_scope(_scoped_tool(), ctx, granted_scopes=[])


def test_agent_host_with_required_scope_passes():
    ctx = CallerContext(actor_type="agent_host", user_id=7, role="student", agent_type="tutor")
    check_scope(_scoped_tool(), ctx, granted_scopes=["problem:read"])


def test_in_process_client_grants_agent_minimal_scopes():
    """The in-process client must attach the agent's minimal scopes so scoped
    tools pass without the bypass."""
    from unittest.mock import MagicMock
    from mcp_gateway.client import InProcessMCPToolClient, MCPClientIdentity
    from tools.protocol.runtime import (
        ToolRuntime, ToolResult, set_tool_runtime, reset_tool_runtime,
    )

    mock_runtime = MagicMock(spec=ToolRuntime)
    mock_runtime.call_sync.return_value = ToolResult(
        ok=True, tool="coderunner.problem.get_detail", data={}
    )
    set_tool_runtime(mock_runtime)
    try:
        client = InProcessMCPToolClient()
        identity = MCPClientIdentity(user_id=1, role="student", agent_type="tutor")
        client.call_tool("coderunner.problem.get_detail", {"problem_id": 1}, identity)
        _, _, ctx = mock_runtime.call_sync.call_args[0]
        assert "problem:read" in (ctx.granted_scopes or [])
    finally:
        reset_tool_runtime()


def test_call_via_runtime_passes_agent_host_granted_scopes(monkeypatch):
    from mcp_gateway.middleware import core

    captured = {}

    class _FakeResult:
        def to_envelope(self):
            return {"ok": True, "data": {}}

    class _FakeRuntime:
        def call_sync(self, tool, args, ctx):
            captured["ctx"] = ctx
            return _FakeResult()

    monkeypatch.setattr(core, "get_tool_runtime", lambda: _FakeRuntime())
    core.set_caller_info({
        "actor_type": "agent_host",
        "api_key_id": "internal:tutor",
        "user_id": 7,
        "role": "student",
        "agent_type": "tutor",
        "scopes": ["problem:read"],
    })

    core.call_via_runtime("coderunner.problem.get_detail", {"problem_id": 1})

    assert captured["ctx"].granted_scopes == ["problem:read"]
