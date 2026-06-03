"""RBAC boundary for external_client callers.

For external clients, role enforcement is carried by _ROLE_OVERRIDES plus
scope checks; the per-agent allowlist applies only to internal agent_host
callers. These tests pin that boundary so it can't drift silently.
"""

import json

from mcp_gateway.middleware import set_caller_info


def test_external_client_role_override_still_enforced(monkeypatch):
    """A scope alone must not unlock a teacher-only tool for a student."""
    from mcp_gateway.middleware.core import call_via_runtime
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr("mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)
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
    from mcp_gateway.middleware.core import call_via_runtime
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr("mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)
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
