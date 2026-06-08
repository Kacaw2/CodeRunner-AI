"""Phase 1 architecture unification regression tests."""

import json


def test_agent_tool_allowlists_derive_from_definitions():
    from ai.agents.analytics.agent import AnalyticsAgent
    from ai.agents.generator.agent import GeneratorAgent
    from ai.agents.reviewer.agent import ReviewerAgent
    from ai.agents.tutor.agent import TutorAgent
    from core.definitions import AGENT_DEFINITIONS, allowed_tools_for
    from ai.tools.protocol.policies.rbac import _agent_tool_allow
    from ai.tools.protocol.schemas.catalog import TOOL_CATALOG

    agents = {
        "analytics": AnalyticsAgent(),
        "generator": GeneratorAgent(),
        "reviewer": ReviewerAgent(),
        "tutor": TutorAgent(),
    }

    for name, agent in agents.items():
        assert agent.mcp_tool_names == list(allowed_tools_for(name))
        assert _agent_tool_allow()[name] == frozenset(AGENT_DEFINITIONS[name].allowed_tools)
        assert set(agent.mcp_tool_names) <= set(TOOL_CATALOG)


def test_runtime_validates_input_schema_before_transport():
    from core.auth.context import CallerContext
    from ai.tools.protocol.registry import ToolRegistry
    from ai.tools.protocol.runtime import ToolCallContext, ToolRuntime
    from ai.tools.protocol.schemas.descriptors import RiskLevel, ToolDescriptor
    from ai.tools.protocol.transports.inproc import LocalTransport

    registry = ToolRegistry()
    transport = LocalTransport()
    descriptor = ToolDescriptor(
        name="coderunner.problem.get_detail",
        version="1.0.0",
        description="Get problem",
        server="db",
        risk_level=RiskLevel.LOW,
        required_scopes=[],
        input_schema={
            "type": "object",
            "properties": {"problem_id": {"type": "integer"}},
            "required": ["problem_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
    )
    registry.register(descriptor)
    called = {"value": False}

    def handler(**_kwargs):
        called["value"] = True
        return {"unexpected": True}

    transport.register_handler(descriptor.name, handler)
    runtime = ToolRuntime(registry=registry, transport=transport)
    ctx = ToolCallContext(caller=CallerContext(user_id=1, role="teacher"))

    result = runtime.call_sync(descriptor.name, {"problem_id": "not-int"}, ctx)

    assert result.ok is False
    assert result.error["code"] == "MCP_ARGUMENT_INVALID"
    assert called["value"] is False


def test_gateway_bridge_returns_runtime_envelope(monkeypatch):
    from ai.mcp_gateway.middleware.core import call_via_runtime
    from ai.tools.protocol.runtime import ToolResult

    captured = {}

    class FakeRuntime:
        def call_sync(self, tool_name, args, ctx):
            captured["tool_name"] = tool_name
            captured["args"] = args
            captured["ctx"] = ctx
            return ToolResult(
                ok=True,
                tool=tool_name,
                data={"items": [1]},
                trace_id="trace-1",
                tool_call_id=ctx.tool_call_id,
            )

    monkeypatch.setattr("ai.mcp_gateway.middleware.core.get_caller_info", lambda: {
        "api_key_id": "key-1",
        "user_id": 7,
        "role": "teacher",
        "scopes": ["search_knowledge"],
        "rate_limit_rpm": 30,
    })
    monkeypatch.setattr("ai.mcp_gateway.middleware.core.get_tool_runtime", lambda: FakeRuntime())

    payload = json.loads(call_via_runtime("coderunner.knowledge.search", {"query": "dp"}))

    assert payload["ok"] is True
    assert payload["data"] == {"items": [1]}
    assert captured["tool_name"] == "coderunner.knowledge.search"
    assert captured["ctx"].caller.actor_type == "external_client"
    assert captured["ctx"].caller.api_key_id == "key-1"
    assert captured["ctx"].granted_scopes == ["search_knowledge"]


def test_gateway_registered_tool_invokes_runtime_pipeline(monkeypatch):
    from ai.mcp_gateway.middleware import set_caller_info
    from ai.mcp_gateway.server import create_mcp_server
    from ai.tools.protocol.runtime import ToolResult

    captured = {}

    class FakeRuntime:
        def call_sync(self, tool_name, args, ctx):
            captured["tool_name"] = tool_name
            captured["args"] = args
            return ToolResult(ok=True, tool=tool_name, data={"ok": "runtime"})

    set_caller_info({
        "api_key_id": "key-1",
        "user_id": 7,
        "role": "teacher",
        "scopes": ["search_knowledge"],
        "rate_limit_rpm": 30,
    })
    monkeypatch.setattr(
        "ai.mcp_gateway.middleware.core.check_rate_limit",
        lambda *_, **__: True,
    )
    monkeypatch.setattr("ai.mcp_gateway.middleware.core.get_tool_runtime", lambda: FakeRuntime())

    tool = create_mcp_server()._tool_manager._tools["search_knowledge"]
    payload = json.loads(tool.fn(query="dp"))

    assert payload["ok"] is True
    assert payload["data"] == {"ok": "runtime"}
    assert captured == {
        "tool_name": "coderunner.knowledge.search",
        "args": {"query": "dp", "owner_id": None},
    }


def test_runtime_persists_high_risk_approval_request():
    from core.auth.context import CallerContext
    from ai.tools.protocol.registry import ToolRegistry
    from ai.tools.protocol.runtime import ToolCallContext, ToolRuntime
    from ai.tools.protocol.schemas.descriptors import (
        ApprovalPolicy,
        RiskLevel,
        ToolDescriptor,
    )
    from ai.tools.protocol.transports.inproc import LocalTransport

    class FakeApprovalStore:
        def __init__(self):
            self.created = []

        def create(self, descriptor, caller, args):
            self.created.append((descriptor.name, caller.user_id, args))
            return "approval-1"

    registry = ToolRegistry()
    descriptor = ToolDescriptor(
        name="coderunner.code.execute",
        version="1.0.0",
        description="Execute code",
        server="code",
        risk_level=RiskLevel.HIGH,
        approval_policy=ApprovalPolicy.TEACHER_REQUIRED,
        required_scopes=[],
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "maxLength": 10000},
                "language": {"type": "string", "enum": ["python", "c"]},
            },
            "required": ["code", "language"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
    )
    registry.register(descriptor)
    store = FakeApprovalStore()
    runtime = ToolRuntime(
        registry=registry,
        transport=LocalTransport(),
        approval_store=store,
    )
    ctx = ToolCallContext(caller=CallerContext(user_id=42, role="teacher"))

    result = runtime.call_sync(
        descriptor.name,
        {"code": "print(1)", "language": "python"},
        ctx,
    )

    assert result.ok is False
    assert result.status == "approval_required"
    assert result.approval_id == "approval-1"
    assert store.created == [
        ("coderunner.code.execute", 42, {"code": "print(1)", "language": "python"})
    ]
