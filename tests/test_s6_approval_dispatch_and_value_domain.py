"""S6 — F8 descriptor-driven approval dispatch + F9 cross-boundary value domain.

F8: the post-approval executor must dispatch any catalog tool through its
registered transport handler (no per-tool hardcoding) and inject only the
trusted approval identity, never the LLM-supplied identity in tool_args.

F9: the runtime input validation must reject out-of-range values (e.g.
problem_id <= 0, empty query/code, oversized limit/days), not just wrong types.
"""

import pytest

from ai.mcp_gateway import bootstrap
from ai.tools.protocol.runtime import ToolRuntime
from ai.tools.protocol.schemas.catalog import TOOL_CATALOG
from ai.tools.protocol.errors import MCPArgumentInvalid


# ── Test doubles ─────────────────────────────────────────────────


class _FakeRegistry:
    def __init__(self, known):
        self._known = set(known)

    def get(self, name):
        # Return the real descriptor so post-approval policy re-checks
        # (internal_only / RBAC) see the genuine tool contract.
        return TOOL_CATALOG.get(name) if name in self._known else None


class _FakeTransport:
    def __init__(self, known):
        self._known = set(known)
        self.calls = []

    def has_handler(self, name):
        return name in self._known

    def invoke(self, name, args):
        self.calls.append((name, args))
        return {"status": "AC", "echo": args}


class _Role:
    def __init__(self, value):
        self.value = value


class _Requester:
    def __init__(self, role):
        self.role = _Role(role)


class _Approval:
    def __init__(self, tool_name, tool_args, user_id, requester=None, api_key_id=None):
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.user_id = user_id
        self.requester = requester
        self.api_key_id = api_key_id


# ── F8 — dynamic dispatch ────────────────────────────────────────


def test_external_short_name_is_normalized_and_dispatched():
    canonical = "coderunner.code.execute"
    transport = _FakeTransport({canonical})
    registry = _FakeRegistry({canonical})
    approval = _Approval("execute_code", {"code": "print(1)", "language": "python"}, user_id=7)

    result = bootstrap._execute_approved_tool(approval, transport=transport, registry=registry)

    assert result["status"] == "AC"
    name, args = transport.calls[0]
    assert name == canonical
    assert args["code"] == "print(1)"


def test_llm_supplied_identity_is_stripped_and_trusted_identity_injected():
    canonical = "coderunner.problem.save_generated"
    transport = _FakeTransport({canonical})
    registry = _FakeRegistry({canonical})
    approval = _Approval(
        canonical,
        {"question_data": {"title": "x"}, "teacher_id": 999},  # 999 is LLM-supplied, untrusted
        user_id=42,
        requester=_Requester("teacher"),
    )

    bootstrap._execute_approved_tool(approval, transport=transport, registry=registry)

    _, args = transport.calls[0]
    assert args["teacher_id"] == 42  # overwritten with trusted approval identity
    assert args["_caller_user_id"] == 42
    assert args["_caller_role"] == "teacher"


def test_student_requester_does_not_get_teacher_id():
    canonical = "coderunner.code.execute"
    transport = _FakeTransport({canonical})
    registry = _FakeRegistry({canonical})
    approval = _Approval(
        canonical,
        {"code": "print(1)", "language": "python", "teacher_id": 5},
        user_id=7,
        requester=_Requester("student"),
    )

    bootstrap._execute_approved_tool(approval, transport=transport, registry=registry)

    _, args = transport.calls[0]
    assert "teacher_id" not in args  # student role: no teacher_id, LLM-supplied 5 stripped
    assert args["student_id"] == 7


def test_unknown_tool_returns_explicit_error_not_silent():
    transport = _FakeTransport(set())
    registry = _FakeRegistry(set())
    approval = _Approval("some_new_high_risk_tool", {}, user_id=1)

    result = bootstrap._execute_approved_tool(approval, transport=transport, registry=registry)

    assert "error" in result
    assert "some_new_high_risk_tool" in result["error"]


def test_handler_exception_is_surfaced_as_error():
    canonical = "coderunner.code.execute"
    registry = _FakeRegistry({canonical})

    class _Boom(_FakeTransport):
        def invoke(self, name, args):
            raise RuntimeError("boom")

    transport = _Boom({canonical})
    approval = _Approval(canonical, {"code": "x", "language": "python"}, user_id=1)

    result = bootstrap._execute_approved_tool(approval, transport=transport, registry=registry)

    assert "error" in result
    assert "boom" in result["error"]


# ── F9 — value-domain validation ─────────────────────────────────


@pytest.mark.parametrize("bad_value", [-9999, 0, -1])
def test_nonpositive_problem_id_rejected(bad_value):
    d = TOOL_CATALOG["coderunner.problem.get_detail"]
    with pytest.raises(MCPArgumentInvalid):
        ToolRuntime._validate_input(d, {"problem_id": bad_value}, "trace")


def test_positive_problem_id_accepted():
    d = TOOL_CATALOG["coderunner.problem.get_detail"]
    ToolRuntime._validate_input(d, {"problem_id": 1}, "trace")


def test_empty_query_rejected():
    d = TOOL_CATALOG["coderunner.knowledge.search"]
    with pytest.raises(MCPArgumentInvalid):
        ToolRuntime._validate_input(d, {"query": ""}, "trace")


def test_empty_code_rejected():
    d = TOOL_CATALOG["coderunner.code.execute"]
    with pytest.raises(MCPArgumentInvalid):
        ToolRuntime._validate_input(d, {"code": "", "language": "python"}, "trace")


def test_oversized_limit_rejected():
    d = TOOL_CATALOG["coderunner.submission.list_for_student"]
    with pytest.raises(MCPArgumentInvalid):
        ToolRuntime._validate_input(d, {"student_id": 1, "limit": 9999}, "trace")


def test_oversized_days_rejected():
    d = TOOL_CATALOG["coderunner.analytics.student_activity"]
    with pytest.raises(MCPArgumentInvalid):
        ToolRuntime._validate_input(d, {"student_id": 1, "days": 100000}, "trace")


def test_question_id_zero_still_allowed_as_no_filter():
    d = TOOL_CATALOG["coderunner.submission.list_for_student"]
    ToolRuntime._validate_input(d, {"student_id": 1, "question_id": 0}, "trace")
