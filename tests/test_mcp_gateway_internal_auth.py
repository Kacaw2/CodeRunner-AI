"""Server-side internal-agent authentication (Task 5/6 completion).

Internal agents cross MCP transport carrying a shared service token in the
Authorization bearer header plus X-MCP-* identity headers. The gateway must:

1. Recognize the internal service token and build an ``agent_host`` caller from
   the request headers (NOT treat it as an external API key).
2. Fall through to API-key verification for any non-internal token.
3. Construct an ``agent_host`` CallerContext in ``call_via_runtime`` so scope
   checks are bypassed for trusted internal callers, while external callers keep
   ``external_client`` + granted scopes.
"""

import json


def test_internal_service_token_resolves_to_agent_host(monkeypatch):
    from mcp_gateway.middleware import core

    monkeypatch.setenv("MCP_INTERNAL_AUTH_TOKEN", "secret-internal")
    headers = {
        "x-mcp-agent-type": "tutor",
        "x-mcp-user-id": "7",
        "x-mcp-user-role": "student",
        "x-mcp-task-id": "task-1",
        "x-mcp-conversation-id": "conv-1",
    }

    caller = core.resolve_caller_from_bearer("secret-internal", headers)

    assert caller is not None
    assert caller["actor_type"] == "agent_host"
    assert caller["agent_type"] == "tutor"
    assert caller["user_id"] == 7
    assert caller["role"] == "student"
    assert caller["task_id"] == "task-1"
    assert caller["conversation_id"] == "conv-1"
    # Must carry a rate-limit key so _guarded can rate-limit internal callers.
    assert caller["api_key_id"]


def test_external_token_falls_through_to_api_key_verification(monkeypatch):
    from mcp_gateway.middleware import core

    monkeypatch.setenv("MCP_INTERNAL_AUTH_TOKEN", "secret-internal")
    monkeypatch.setattr(
        "mcp_gateway.middleware.auth.verify_api_key",
        lambda token: (
            {
                "api_key_id": "k1",
                "user_id": 1,
                "role": "teacher",
                "scopes": ["problem:read"],
                "rate_limit_rpm": 30,
            }
            if token == "ext-key"
            else None
        ),
    )

    caller = core.resolve_caller_from_bearer("ext-key", {})

    assert caller is not None
    assert caller.get("actor_type") != "agent_host"
    assert caller["api_key_id"] == "k1"


def test_internal_token_disabled_when_env_unset(monkeypatch):
    """With no internal token configured, the same string is just an API key."""
    from mcp_gateway.middleware import core

    monkeypatch.delenv("MCP_INTERNAL_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "mcp_gateway.middleware.auth.verify_api_key",
        lambda token: None,
    )

    caller = core.resolve_caller_from_bearer("secret-internal", {})

    assert caller is None


def test_call_via_runtime_uses_agent_host_context_for_internal_caller(monkeypatch):
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
        "task_id": "task-1",
        "conversation_id": "conv-1",
        "scopes": None,
    })

    core.call_via_runtime("coderunner.problem.get_detail", {"problem_id": 1})

    ctx = captured["ctx"]
    assert ctx.caller.actor_type == "agent_host"
    assert ctx.caller.agent_type == "tutor"
    assert ctx.caller.user_id == 7
    assert ctx.caller.task_id == "task-1"
    assert ctx.caller.conversation_id == "conv-1"


def test_call_via_runtime_uses_external_client_context_for_api_key_caller(monkeypatch):
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
        "api_key_id": "k1",
        "user_id": 1,
        "role": "teacher",
        "scopes": ["knowledge:read"],
        "rate_limit_rpm": 30,
    })

    core.call_via_runtime("coderunner.knowledge.search", {"query": "loops"})

    ctx = captured["ctx"]
    assert ctx.caller.actor_type == "external_client"
    assert ctx.granted_scopes == ["knowledge:read"]


def test_internal_agent_bypasses_scope_check_end_to_end(monkeypatch):
    """An agent_host caller with no scopes still passes a scoped tool's guard."""
    from mcp_gateway.middleware import core
    from mcp_gateway.bootstrap import bootstrap_tool_runtime

    bootstrap_tool_runtime()
    monkeypatch.setattr(core, "check_rate_limit", lambda *_: True)
    core.set_caller_info({
        "actor_type": "agent_host",
        "api_key_id": "internal:tutor",
        "user_id": 7,
        "role": "student",
        "agent_type": "tutor",
        "scopes": None,
        "rate_limit_rpm": 600,
    })

    payload = json.loads(core._guarded(
        lambda: core.call_via_runtime("coderunner.problem.get_detail", {"problem_id": 1})
    ))

    # The guard must NOT reject on scope grounds for a trusted internal caller.
    if payload["ok"] is False:
        assert payload["error"]["code"] != "MCP_SCOPE_DENIED"
