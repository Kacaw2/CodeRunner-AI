"""Both tool entry paths share one policy core.

For the same tool and the same effective identity, the in-process MCP client
(agent path) and the gateway tool wrapper (external/transport path) must reach
the same ToolRuntime verdict and produce the same envelope shape. This pins the
Phase 3 "equal permission semantics across paths" guarantee against drift.
"""

import json

import pytest

from mcp_gateway.bootstrap import bootstrap_tool_runtime
from mcp_gateway.middleware import set_caller_info


@pytest.fixture(autouse=True)
def _runtime_and_no_rate_limit(app, monkeypatch):
    # Real registry + guard, not a mock — the whole point is to test the shared core.
    with app.app_context():
        bootstrap_tool_runtime()
        monkeypatch.setattr(
            "mcp_gateway.middleware.core.check_rate_limit", lambda *_: True
        )
        yield


def _inproc_envelope(tool: str, args: dict, *, user_id: int, role: str, agent: str) -> dict:
    from mcp_gateway.client import InProcessMCPToolClient, MCPClientIdentity

    identity = MCPClientIdentity(user_id=user_id, role=role, agent_type=agent)
    return InProcessMCPToolClient().call_tool(tool, args, identity)


def _gateway_envelope(tool: str, args: dict, *, user_id: int, role: str, agent: str) -> dict:
    from mcp_gateway.middleware.core import call_via_runtime
    from tools.protocol.policies.scopes import scopes_for_agent

    # agent_host caller mirrors what the verified internal token would yield.
    set_caller_info({
        "actor_type": "agent_host",
        "api_key_id": f"internal:{agent}",
        "user_id": user_id,
        "role": role,
        "agent_type": agent,
        "scopes": scopes_for_agent(agent),
        "rate_limit_rpm": 600,
    })
    try:
        return json.loads(call_via_runtime(tool, args))
    finally:
        set_caller_info(None)


def test_allowed_call_agrees_across_paths():
    kw = dict(user_id=1, role="student", agent="tutor")
    a = _inproc_envelope("coderunner.knowledge.search", {"query": "loops"}, **kw)
    b = _gateway_envelope("coderunner.knowledge.search", {"query": "loops"}, **kw)
    assert a["ok"] == b["ok"] is True
    assert set(a) >= {"ok", "tool", "data"}
    assert set(a) == set(b), f"envelope keys diverged: {set(a) ^ set(b)}"


def test_rbac_denied_call_agrees_across_paths():
    # student.get_summary is teacher/admin-only (_ROLE_OVERRIDES); a student
    # caller must be denied identically on both paths, at the RBAC step.
    kw = dict(user_id=1, role="student", agent="tutor")
    a = _inproc_envelope("coderunner.student.get_summary", {"student_id": 99}, **kw)
    b = _gateway_envelope("coderunner.student.get_summary", {"student_id": 99}, **kw)
    assert a["ok"] == b["ok"] is False
    assert a["error"]["code"] == b["error"]["code"]
    assert a["status"] == b["status"]
