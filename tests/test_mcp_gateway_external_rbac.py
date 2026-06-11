"""RBAC boundary for external_client callers.

For external clients, role enforcement is carried by _ROLE_OVERRIDES plus
scope checks; the per-agent allowlist applies only to internal agent_host
callers. These tests pin that boundary so it can't drift silently.
"""

import json

from ai.mcp_gateway.middleware import set_caller_info


def test_external_client_role_override_still_enforced(monkeypatch):
    """A scope alone must not unlock a teacher-only tool for a student."""
    from ai.mcp_gateway.middleware.core import call_via_runtime
    from ai.mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr("ai.mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)
    set_caller_info({
        "api_key_id": "key-1",
        "user_id": 10,
        "role": "student",
        "scopes": ["student:read"],
        "rate_limit_rpm": 30,
    })

    payload = json.loads(call_via_runtime(
        "coderunner.student.get_summary",
        {"student_id": 99},
    ))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "MCP_PERMISSION_DENIED"


def test_external_client_unrestricted_tool_passes_with_scope(monkeypatch):
    """A tool with no role override is gated by scope only — document that."""
    from ai.mcp_gateway.middleware.core import call_via_runtime
    from ai.mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr("ai.mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)
    set_caller_info({
        "api_key_id": "key-2",
        "user_id": 11,
        "role": "student",
        "scopes": ["knowledge:read"],
        "rate_limit_rpm": 30,
    })

    payload = json.loads(call_via_runtime(
        "coderunner.knowledge.search",
        {"query": "loops"},
    ))

    assert payload["ok"] is True


def test_external_path_has_no_agent_allowlist_layer():
    """Invariant: the agent-allowlist hook (BEFORE_TOOL_CALL) is an agent-path
    concept only. External API-key callers are gated by RBAC + scope, never by a
    per-agent tool allowlist — there is no agent in that flow. The gateway tool
    wrapper must therefore NOT invoke the hook manager.

    If this breaks, do not add the hook to the external path; revisit the design.
    """
    import inspect

    from ai.mcp_gateway.middleware import core

    src = inspect.getsource(core.call_via_runtime)
    assert "HookEvent" not in src
    assert "get_hook_manager" not in src
    assert "BEFORE_TOOL_CALL" not in src
