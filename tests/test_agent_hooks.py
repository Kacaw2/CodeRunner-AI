"""Tests for the agent lifecycle hook system (Phase 5).

Hooks move reliability checks out of prompt instructions and into in-process
synchronous runtime code. They are registered against lifecycle events and
fire in order; a ``deny`` result from a ``BEFORE_*`` hook blocks the action.
"""
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage

from agents.hooks import (
    Hook,
    HookContext,
    HookEvent,
    HookManager,
    HookResult,
    build_default_hook_manager,
    get_hook_manager,
)


class _RecordingHook(Hook):
    """Test hook that records the order in which it fired."""

    def __init__(self, name, events, log, *, deny=False):
        self.name = name
        self.events = frozenset(events)
        self._log = log
        self._deny = deny

    def run(self, ctx):
        self._log.append(self.name)
        if self._deny:
            return HookResult.deny(f"{self.name} blocked", warnings=[f"w:{self.name}"])
        return HookResult.ok(warnings=[f"w:{self.name}"])


def _ctx(event, **kw):
    base = {"agent_name": "tutor", "state": {}}
    base.update(kw)
    return HookContext(event=event, **base)


class TestHookManager:
    def test_fires_registered_hooks_in_order(self):
        log = []
        mgr = HookManager()
        mgr.register(_RecordingHook("first", [HookEvent.BEFORE_AGENT_RUN], log))
        mgr.register(_RecordingHook("second", [HookEvent.BEFORE_AGENT_RUN], log))
        result = mgr.fire(_ctx(HookEvent.BEFORE_AGENT_RUN))
        assert log == ["first", "second"]
        assert result.allowed is True
        assert result.warnings == ["w:first", "w:second"]

    def test_only_fires_hooks_subscribed_to_event(self):
        log = []
        mgr = HookManager()
        mgr.register(_RecordingHook("before", [HookEvent.BEFORE_AGENT_RUN], log))
        mgr.register(_RecordingHook("after", [HookEvent.AFTER_AGENT_RUN], log))
        mgr.fire(_ctx(HookEvent.BEFORE_AGENT_RUN))
        assert log == ["before"]

    def test_deny_short_circuits_remaining_hooks(self):
        log = []
        mgr = HookManager()
        mgr.register(_RecordingHook("blocker", [HookEvent.BEFORE_TOOL_CALL], log, deny=True))
        mgr.register(_RecordingHook("never", [HookEvent.BEFORE_TOOL_CALL], log))
        result = mgr.fire(_ctx(HookEvent.BEFORE_TOOL_CALL))
        assert log == ["blocker"]
        assert result.allowed is False
        assert "blocker blocked" in result.error


class TestHookResult:
    def test_ok_is_allowed(self):
        assert HookResult.ok().allowed is True

    def test_deny_carries_error(self):
        r = HookResult.deny("nope")
        assert r.allowed is False
        assert r.error == "nope"


class TestDefaultHookManager:
    def test_registers_builtin_hooks_for_each_event(self):
        mgr = build_default_hook_manager()
        for event in HookEvent:
            assert mgr.hooks_for(event), f"no builtin hook for {event}"

    def test_get_hook_manager_is_singleton(self):
        assert get_hook_manager() is get_hook_manager()


class TestContractValidationHook:
    """BEFORE_AGENT_RUN: warn-only contract check, never denies."""

    def test_clean_input_has_no_warnings(self):
        mgr = build_default_hook_manager()
        state = {
            "user_id": 1, "user_role": "student", "agent_type": "tutor",
            "context": {"question_id": 1},
        }
        result = mgr.fire(HookContext(
            event=HookEvent.BEFORE_AGENT_RUN, agent_name="tutor", state=state,
        ))
        assert result.allowed is True
        assert result.warnings == []

    def test_unexpected_context_key_warns_but_allows(self):
        mgr = build_default_hook_manager()
        state = {
            "user_id": 1, "user_role": "student", "agent_type": "tutor",
            "context": {"bogus_key": 1},
        }
        result = mgr.fire(HookContext(
            event=HookEvent.BEFORE_AGENT_RUN, agent_name="tutor", state=state,
        ))
        assert result.allowed is True  # warn-only
        assert any("bogus_key" in w for w in result.warnings)


class TestToolAllowlistHook:
    """BEFORE_TOOL_CALL: deny tools outside the agent's declared allowlist."""

    def test_allows_declared_tool(self):
        mgr = build_default_hook_manager()
        result = mgr.fire(HookContext(
            event=HookEvent.BEFORE_TOOL_CALL, agent_name="reviewer", state={},
            tool_call={"name": "coderunner.code.execute", "args": {}, "id": "tc1"},
        ))
        assert result.allowed is True

    def test_denies_undeclared_tool(self):
        mgr = build_default_hook_manager()
        result = mgr.fire(HookContext(
            event=HookEvent.BEFORE_TOOL_CALL, agent_name="reviewer", state={},
            tool_call={"name": "coderunner.problem.save_generated", "args": {}, "id": "tc1"},
        ))
        assert result.allowed is False
        assert "save_generated" in result.error


class TestOutputValidationHook:
    """AFTER_AGENT_RUN: warn-only schema check, single runtime path."""

    def test_free_text_agent_skips_validation(self):
        mgr = build_default_hook_manager()
        result = mgr.fire(HookContext(
            event=HookEvent.AFTER_AGENT_RUN, agent_name="tutor", state={},
            final_response="Here is a hint, no JSON needed.",
        ))
        assert result.allowed is True
        assert result.warnings == []

    def test_invalid_json_schema_output_warns(self):
        mgr = build_default_hook_manager()
        # Reviewer expects REVIEW_SCHEMA; this JSON is missing required keys.
        result = mgr.fire(HookContext(
            event=HookEvent.AFTER_AGENT_RUN, agent_name="reviewer", state={},
            final_response='```json\n{"unexpected": true}\n```',
        ))
        assert result.allowed is True  # warn-only
        assert result.warnings
        assert result.metadata.get("output_valid") is False


class TestExecutorToolHooks:
    """Executor enforces the allowlist hook at the MCP client boundary."""

    def test_disallowed_tool_blocked_without_calling_mcp(self, monkeypatch):
        from agents.executor import ToolCallExecutor

        called = {"mcp": False}

        def _fake_client():
            called["mcp"] = True
            raise AssertionError("MCP must not be reached for a blocked tool")

        monkeypatch.setattr(
            "mcp_gateway.client.get_mcp_tool_client", _fake_client, raising=False,
        )

        executor = ToolCallExecutor()
        state = {"user_id": 1, "user_role": "student", "agent_type": "reviewer", "context": {}}
        tool_call = {"name": "coderunner.problem.save_generated", "args": {}, "id": "tc9"}
        msg = executor.run(tool_call, state, "reviewer")

        assert isinstance(msg, ToolMessage)
        assert "TOOL_NOT_ALLOWED" in msg.content
        assert called["mcp"] is False

    def test_allowed_tool_reaches_mcp(self, monkeypatch):
        from agents.executor import ToolCallExecutor

        fake_client = MagicMock()
        fake_client.call_tool.return_value = {"ok": True, "data": {"result": 42}}
        monkeypatch.setattr(
            "mcp_gateway.client.get_mcp_tool_client", lambda: fake_client, raising=False,
        )

        executor = ToolCallExecutor()
        state = {"user_id": 1, "user_role": "student", "agent_type": "reviewer", "context": {}}
        tool_call = {"name": "coderunner.code.execute", "args": {}, "id": "tc1"}
        msg = executor.run(tool_call, state, "reviewer")

        assert fake_client.call_tool.called
        assert "42" in msg.content
