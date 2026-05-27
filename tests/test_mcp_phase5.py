"""Tests for Phase E — MCP as the sole tool boundary.

Covers:
- MCP error codes and exceptions
- Tool descriptor catalog
- Registry (registration, dedup detection, filtering)
- RBAC policy
- Risk policy
- Scope policy
- Guard pipeline
- ToolRuntime (call_sync with mock transport)
- Adapters (MCP ↔ LLM)
- Grep gate (no old tool paths in agents/agent_host)
"""

import json
import subprocess
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ── Error codes ────────────────────────────────────────────────

class TestMCPErrorCodes:
    def test_error_codes_exist(self):
        from mcp.errors.codes import MCPErrorCode

        assert MCPErrorCode.AUTH_REQUIRED == "MCP_AUTH_REQUIRED"
        assert MCPErrorCode.PERMISSION_DENIED == "MCP_PERMISSION_DENIED"
        assert MCPErrorCode.TOOL_NOT_FOUND == "MCP_TOOL_NOT_FOUND"

    def test_retryable_codes(self):
        from mcp.errors.codes import MCPErrorCode

        assert MCPErrorCode.RATE_LIMITED.retryable is True
        assert MCPErrorCode.TRANSPORT_UNAVAILABLE.retryable is True
        assert MCPErrorCode.TOOL_TIMEOUT.retryable is True
        assert MCPErrorCode.PERMISSION_DENIED.retryable is False

    def test_http_status(self):
        from mcp.errors.codes import MCPErrorCode

        assert MCPErrorCode.AUTH_REQUIRED.http_status == 401
        assert MCPErrorCode.TOOL_NOT_FOUND.http_status == 404
        assert MCPErrorCode.RATE_LIMITED.http_status == 429


class TestMCPExceptions:
    def test_error_to_envelope(self):
        from mcp.errors import MCPPermissionDenied

        err = MCPPermissionDenied("Not allowed", trace_id="t1")
        env = err.to_envelope()
        assert env["ok"] is False
        assert env["error"]["code"] == "MCP_PERMISSION_DENIED"
        assert env["error"]["retryable"] is False
        assert env["trace_id"] == "t1"

    def test_approval_required_envelope(self):
        from mcp.errors import MCPApprovalRequired

        err = MCPApprovalRequired(
            "Needs approval", approval_id="a1", resume_token="r1", trace_id="t2"
        )
        env = err.to_envelope()
        assert env["approval_id"] == "a1"
        assert env["resume_token"] == "r1"


# ── Tool descriptors ──────────────────────────────────────────

class TestToolDescriptors:
    def test_descriptor_to_llm_schema(self):
        from mcp.schemas.descriptors import ToolDescriptor

        desc = ToolDescriptor(
            name="test.tool",
            version="1.0.0",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            output_schema={"type": "object"},
        )
        schema = desc.to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test.tool"
        assert schema["function"]["description"] == "A test tool"

    def test_descriptor_to_dict(self):
        from mcp.schemas.descriptors import ToolDescriptor, RiskLevel

        desc = ToolDescriptor(
            name="coderunner.code.execute",
            version="1.0.0",
            description="Execute code",
            risk_level=RiskLevel.HIGH,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        d = desc.to_dict()
        assert d["name"] == "coderunner.code.execute"
        assert d["risk_level"] == "high"


class TestToolCatalog:
    def test_catalog_has_expected_tools(self):
        from mcp.schemas.catalog import TOOL_CATALOG

        expected = {
            "coderunner.problem.get_detail",
            "coderunner.submission.list_for_student",
            "coderunner.submission.get_detail",
            "coderunner.student.get_summary",
            "coderunner.problem.save_generated",
            "coderunner.code.execute",
            "coderunner.knowledge.search",
            "coderunner.knowledge.search_similar_problems",
            "coderunner.knowledge.search_error_patterns",
            "coderunner.analytics.student_activity",
            "coderunner.analytics.student_stats",
            "coderunner.analytics.class_statistics",
            "coderunner.analytics.problem_difficulty",
            "coderunner.trace.get_agent_trace",
        }
        assert expected == set(TOOL_CATALOG.keys())

    def test_high_risk_tools(self):
        from mcp.schemas.catalog import TOOL_CATALOG
        from mcp.schemas.descriptors import RiskLevel

        high_risk = {n for n, d in TOOL_CATALOG.items() if d.risk_level == RiskLevel.HIGH}
        assert "coderunner.code.execute" in high_risk
        assert "coderunner.problem.save_generated" in high_risk


# ── Registry ──────────────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_get(self):
        from mcp.registry.registry import ToolRegistry
        from mcp.schemas.descriptors import ToolDescriptor

        reg = ToolRegistry()
        desc = ToolDescriptor(
            name="test.tool", version="1.0.0", description="test",
            input_schema={}, output_schema={}, server="s1",
        )
        reg.register(desc)
        assert reg.get("test.tool") is desc
        assert len(reg) == 1

    def test_duplicate_name_different_server_raises(self):
        from mcp.registry.registry import ToolRegistry
        from mcp.schemas.descriptors import ToolDescriptor

        reg = ToolRegistry()
        d1 = ToolDescriptor(name="dup", version="1.0.0", description="",
                           input_schema={}, output_schema={}, server="s1")
        d2 = ToolDescriptor(name="dup", version="1.0.0", description="",
                           input_schema={}, output_schema={}, server="s2")
        reg.register(d1)
        with pytest.raises(ValueError, match="Duplicate tool name"):
            reg.register(d2)

    def test_list_tools_with_name_filter(self):
        from mcp.registry.registry import ToolRegistry
        from mcp.schemas.descriptors import ToolDescriptor

        reg = ToolRegistry()
        for name in ["a.b", "c.d", "e.f"]:
            reg.register(ToolDescriptor(name=name, version="1.0.0", description="",
                                       input_schema={}, output_schema={}))
        filtered = reg.list_tools(names=["a.b", "e.f"])
        assert len(filtered) == 2
        assert {t.name for t in filtered} == {"a.b", "e.f"}


# ── RBAC policy ───────────────────────────────────────────────

class TestRBACPolicy:
    def test_analytics_stats_denied_for_student(self):
        from mcp.policies.rbac import check_rbac
        from mcp.auth.context import CallerContext
        from mcp.schemas.descriptors import ToolDescriptor
        from mcp.errors import MCPPermissionDenied

        tool = ToolDescriptor(
            name="coderunner.analytics.class_statistics", version="1.0.0",
            description="", input_schema={}, output_schema={},
        )
        ctx = CallerContext(user_id=1, role="student", agent_type="analytics")
        with pytest.raises(MCPPermissionDenied):
            check_rbac(tool, ctx)

    def test_analytics_stats_allowed_for_teacher(self):
        from mcp.policies.rbac import check_rbac
        from mcp.auth.context import CallerContext
        from mcp.schemas.descriptors import ToolDescriptor

        tool = ToolDescriptor(
            name="coderunner.analytics.class_statistics", version="1.0.0",
            description="", input_schema={}, output_schema={},
        )
        ctx = CallerContext(user_id=1, role="teacher", agent_type="analytics")
        check_rbac(tool, ctx)  # should not raise

    def test_agent_tool_allowlist(self):
        from mcp.policies.rbac import check_rbac
        from mcp.auth.context import CallerContext
        from mcp.schemas.descriptors import ToolDescriptor
        from mcp.errors import MCPPermissionDenied

        tool = ToolDescriptor(
            name="coderunner.knowledge.search_similar_problems", version="1.0.0",
            description="", input_schema={}, output_schema={},
        )
        ctx = CallerContext(user_id=1, role="teacher", agent_type="tutor")
        with pytest.raises(MCPPermissionDenied):
            check_rbac(tool, ctx)


# ── Guard pipeline ────────────────────────────────────────────

class TestGuardPipeline:
    def test_guard_passes_for_valid_call(self):
        from mcp.policies.guard import run_guard
        from mcp.auth.context import CallerContext
        from mcp.schemas.descriptors import ToolDescriptor, RiskLevel

        tool = ToolDescriptor(
            name="coderunner.problem.get_detail", version="1.0.0",
            description="", input_schema={}, output_schema={},
            risk_level=RiskLevel.LOW,
        )
        ctx = CallerContext(user_id=1, role="student", agent_type="tutor")
        result = run_guard(tool, ctx)
        assert result.passed is True

    def test_guard_rejects_unauthorized_role(self):
        from mcp.policies.guard import run_guard
        from mcp.auth.context import CallerContext
        from mcp.schemas.descriptors import ToolDescriptor

        tool = ToolDescriptor(
            name="coderunner.analytics.class_statistics", version="1.0.0",
            description="", input_schema={}, output_schema={},
        )
        ctx = CallerContext(user_id=1, role="student", agent_type="analytics")
        result = run_guard(tool, ctx)
        assert result.rejected is True


# ── Adapters ──────────────────────────────────────────────────

class TestAdapters:
    def test_descriptors_to_llm_tools(self):
        from mcp.adapters import descriptors_to_llm_tools
        from mcp.schemas.descriptors import ToolDescriptor

        descs = [
            ToolDescriptor(name="a.b", version="1.0.0", description="do A",
                          input_schema={"type": "object"}, output_schema={}),
            ToolDescriptor(name="c.d", version="1.0.0", description="do C",
                          input_schema={"type": "object"}, output_schema={}),
        ]
        schemas = descriptors_to_llm_tools(descs)
        assert len(schemas) == 2
        assert schemas[0]["function"]["name"] == "a.b"

    def test_parse_llm_tool_call(self):
        from mcp.adapters import parse_llm_tool_call

        tc = {"name": "coderunner.code.execute", "args": {"code": "print(1)"}, "id": "tc1"}
        req = parse_llm_tool_call(tc)
        assert req.tool_name == "coderunner.code.execute"
        assert req.args == {"code": "print(1)"}
        assert req.tool_call_id == "tc1"

    def test_tool_result_to_message(self):
        from mcp.adapters import tool_result_to_message

        result = {"ok": True, "data": {"status": "AC", "stdout": "hello"}}
        msg = tool_result_to_message(result, "tc1")
        assert msg.tool_call_id == "tc1"
        parsed = json.loads(msg.content)
        assert parsed["status"] == "AC"


# ── CallerContext ─────────────────────────────────────────────

class TestCallerContext:
    def test_build_caller_context(self):
        from mcp.auth.context import build_caller_context

        ctx = build_caller_context(user_id=42, role="teacher", agent_type="generator")
        assert ctx.user_id == 42
        assert ctx.role == "teacher"
        assert ctx.agent_type == "generator"
        assert ctx.actor_type == "agent_host"
        assert len(ctx.trace_id) > 0


# ── ToolRuntime ───────────────────────────────────────────────

class TestToolRuntime:
    def test_call_sync_success(self):
        from mcp.client.runtime import ToolRuntime, ToolCallContext
        from mcp.registry.registry import ToolRegistry
        from mcp.transport.local import LocalTransport
        from mcp.schemas.descriptors import ToolDescriptor, RiskLevel
        from mcp.auth.context import CallerContext

        reg = ToolRegistry()
        transport = LocalTransport()

        desc = ToolDescriptor(
            name="coderunner.problem.get_detail", version="1.0.0",
            description="Get problem", input_schema={}, output_schema={},
            risk_level=RiskLevel.LOW,
        )
        reg.register(desc)
        transport.register_handler(
            "coderunner.problem.get_detail",
            lambda problem_id, **kw: {"problem_id": problem_id, "title": "Two Sum"},
        )

        runtime = ToolRuntime(registry=reg, transport=transport)
        ctx = ToolCallContext(
            caller=CallerContext(user_id=1, role="student", agent_type="tutor"),
        )
        result = runtime.call_sync("coderunner.problem.get_detail", {"problem_id": 1}, ctx)
        assert result.ok is True
        assert result.data["title"] == "Two Sum"

    def test_call_sync_tool_not_found(self):
        from mcp.client.runtime import ToolRuntime, ToolCallContext
        from mcp.registry.registry import ToolRegistry
        from mcp.transport.local import LocalTransport
        from mcp.auth.context import CallerContext

        runtime = ToolRuntime(registry=ToolRegistry(), transport=LocalTransport())
        ctx = ToolCallContext(
            caller=CallerContext(user_id=1, role="student"),
        )
        result = runtime.call_sync("nonexistent.tool", {}, ctx)
        assert result.ok is False
        assert "MCP_TOOL_NOT_FOUND" in (result.error or {}).get("code", "")

    def test_call_sync_permission_denied(self):
        from mcp.client.runtime import ToolRuntime, ToolCallContext
        from mcp.registry.registry import ToolRegistry
        from mcp.transport.local import LocalTransport
        from mcp.schemas.descriptors import ToolDescriptor
        from mcp.auth.context import CallerContext

        reg = ToolRegistry()
        desc = ToolDescriptor(
            name="coderunner.analytics.class_statistics", version="1.0.0",
            description="", input_schema={}, output_schema={},
        )
        reg.register(desc)

        runtime = ToolRuntime(registry=reg, transport=LocalTransport())
        ctx = ToolCallContext(
            caller=CallerContext(user_id=1, role="student", agent_type="analytics"),
        )
        result = runtime.call_sync("coderunner.analytics.class_statistics", {}, ctx)
        assert result.ok is False
        assert "PERMISSION_DENIED" in (result.error or {}).get("code", "")

    def test_sanitize_args_strips_identity(self):
        from mcp.client.runtime import ToolRuntime
        from mcp.auth.context import CallerContext

        ctx = CallerContext(user_id=42, role="student")
        sanitized = ToolRuntime._sanitize_args(
            {"code": "print(1)", "user_id": 999, "role": "admin"}, ctx
        )
        assert sanitized["_caller_user_id"] == 42
        assert sanitized["_caller_role"] == "student"
        assert "user_id" not in sanitized
        assert "role" not in sanitized
        assert sanitized["student_id"] == 42


# ── Agent MCP tool names ─────────────────────────────────────

class TestAgentMCPToolNames:
    def test_tutor_declares_mcp_names(self):
        from agent_host.agents.tutor import TUTOR_MCP_TOOLS

        assert "coderunner.code.execute" in TUTOR_MCP_TOOLS
        assert "coderunner.problem.get_detail" in TUTOR_MCP_TOOLS
        assert all(t.startswith("coderunner.") for t in TUTOR_MCP_TOOLS)

    def test_reviewer_declares_mcp_names(self):
        from agent_host.agents.reviewer import REVIEWER_MCP_TOOLS

        assert "coderunner.code.execute" in REVIEWER_MCP_TOOLS
        assert len(REVIEWER_MCP_TOOLS) == 2

    def test_generator_declares_mcp_names(self):
        from agent_host.agents.generator import GENERATOR_MCP_TOOLS

        assert "coderunner.code.execute" in GENERATOR_MCP_TOOLS
        assert "coderunner.knowledge.search_similar_problems" in GENERATOR_MCP_TOOLS
        assert "coderunner.problem.save_generated" in GENERATOR_MCP_TOOLS

    def test_analytics_declares_mcp_names(self):
        from agent_host.agents.analytics import ANALYTICS_MCP_TOOLS

        assert "coderunner.analytics.student_activity" in ANALYTICS_MCP_TOOLS
        assert "coderunner.analytics.class_statistics" in ANALYTICS_MCP_TOOLS

    def test_definitions_use_mcp_names(self):
        from agent_host.definitions import AGENT_DEFINITIONS

        for name, defn in AGENT_DEFINITIONS.items():
            for tool in defn.allowed_tools:
                assert tool.startswith("coderunner."), (
                    f"Agent '{name}' tool '{tool}' should use MCP namespace"
                )


# ── Grep gate ─────────────────────────────────────────────────

class TestGrepGate:
    """Verify no old tool execution paths remain in agent/agent_host code."""

    def test_no_tool_invoke_in_agents(self):
        """No tool.invoke() calls in agent code."""
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", r"tool\.invoke(", "app/agents/", "agent_host/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found old tool.invoke() calls:\n{result.stdout}"
        )

    def test_no_get_all_tools_in_agents(self):
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "get_all_tools", "app/agents/", "agent_host/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found old get_all_tools() calls:\n{result.stdout}"
        )

    def test_no_check_tool_permission_in_agents(self):
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "check_tool_permission", "app/agents/", "agent_host/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found old check_tool_permission() calls:\n{result.stdout}"
        )

    def test_no_langchain_tool_imports_in_agent_host(self):
        """No LangChain @tool imports in agent_host/."""
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "from langchain_core.tools import tool",
             "agent_host/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found LangChain tool imports:\n{result.stdout}"
        )


# ── Phase E2 boundary checks ─────────────────────────────────

class TestPhaseE2Boundaries:
    def test_agent_host_has_agents_dir(self):
        import os
        assert os.path.isdir("agent_host/agents")

    def test_agent_host_has_model_router(self):
        import os
        assert os.path.isdir("agent_host/model_router")

    def test_agent_host_has_workflow(self):
        import os
        assert os.path.isdir("agent_host/workflow")

    def test_agent_host_has_prompts(self):
        import os
        assert os.path.isdir("agent_host/prompts")

    def test_mcp_is_top_level(self):
        import os
        assert os.path.isdir("mcp")
        assert os.path.isdir("mcp/client")
        assert os.path.isdir("mcp/server")
        assert os.path.isdir("mcp/schemas")
        assert os.path.isdir("mcp/policies")

    def test_no_app_services_in_agent_host(self):
        """agent_host/ should not import from app.services."""
        result = subprocess.run(
            ["grep", "-rn", "from app.services", "agent_host/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found app.services imports in agent_host:\n{result.stdout}"
        )
