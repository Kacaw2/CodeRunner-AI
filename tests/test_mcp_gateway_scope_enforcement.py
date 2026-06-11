"""External clients must satisfy a tool's required_scopes through the gateway."""

import json

from ai.mcp_gateway.middleware import set_caller_info


def test_external_gateway_enforces_required_scopes(monkeypatch):
    from ai.mcp_gateway.middleware.core import call_via_runtime
    from ai.mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    set_caller_info({
        "api_key_id": "key-1",
        "user_id": 10,
        "role": "teacher",
        "scopes": ["knowledge:read"],
        "rate_limit_rpm": 30,
    })
    monkeypatch.setattr("ai.mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)

    payload = json.loads(call_via_runtime(
        "coderunner.problem.get_detail",
        {"problem_id": 1},
    ))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "MCP_SCOPE_DENIED"


def test_external_gateway_allows_call_with_matching_scope(monkeypatch):
    from ai.mcp_gateway.middleware.core import call_via_runtime
    from ai.mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    set_caller_info({
        "api_key_id": "key-1",
        "user_id": 10,
        "role": "teacher",
        "scopes": ["problem:read"],
        "rate_limit_rpm": 30,
    })
    monkeypatch.setattr("ai.mcp_gateway.middleware.core.check_rate_limit", lambda *_: True)

    payload = json.loads(call_via_runtime(
        "coderunner.problem.get_detail",
        {"problem_id": 1},
    ))

    # The matching scope must clear the scope gate; the call may still fail
    # downstream (no DB session in this harness) but never on scope.
    if not payload["ok"]:
        assert payload["error"]["code"] != "MCP_SCOPE_DENIED"
