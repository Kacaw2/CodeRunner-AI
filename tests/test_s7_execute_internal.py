"""S7 — internal execute path for agent self-validation.

Three guarantees:
1. ``coderunner.code.execute_internal`` is internal-only: an external_client is
   rejected regardless of scope, while an agent_host passes the gate.
2. The generator's derived scopes include ``code:execute_internal`` so its self
   -validation call is not scope-denied.
3. output_schema validation is warn-only — a mismatching tool result logs but
   never raises.
"""

import pytest

from core.auth.context import CallerContext
from tools.protocol.schemas.catalog import TOOL_CATALOG
from tools.protocol.schemas.descriptors import RiskLevel, ApprovalPolicy
from tools.protocol.errors import MCPPermissionDenied
from tools.protocol.policies.guard import check_internal_only, run_guard
from tools.protocol.policies.scopes import scopes_for_agent


INTERNAL_TOOL = "coderunner.code.execute_internal"


def test_execute_internal_descriptor_shape():
    d = TOOL_CATALOG[INTERNAL_TOOL]
    assert d.internal_only is True
    assert d.risk_level == RiskLevel.MEDIUM
    assert d.approval_policy == ApprovalPolicy.NONE
    assert d.required_scopes == ["code:execute_internal"]


def test_external_client_cannot_call_internal_tool_even_with_scope():
    d = TOOL_CATALOG[INTERNAL_TOOL]
    ctx = CallerContext(
        actor_type="external_client", user_id=1, role="teacher",
    )
    with pytest.raises(MCPPermissionDenied):
        check_internal_only(d, ctx)
    # And the full pipeline rejects too, even if the key carries the scope.
    result = run_guard(d, ctx, granted_scopes=["code:execute_internal"])
    assert result.rejected
    assert isinstance(result.error, MCPPermissionDenied)


def test_agent_host_passes_internal_gate_and_full_guard():
    """The generator runs as teacher/admin (both entry points are teacher-gated),
    so a teacher agent_host clears the internal gate and the MEDIUM risk policy."""
    d = TOOL_CATALOG[INTERNAL_TOOL]
    ctx = CallerContext(
        actor_type="agent_host", user_id=7, role="teacher", agent_type="generator",
    )
    check_internal_only(d, ctx)  # does not raise
    result = run_guard(d, ctx, granted_scopes=["code:execute_internal"])
    assert result.passed


def test_student_agent_host_still_blocked_by_medium_risk():
    """Defense in depth: the internal gate passes for any agent_host, but the
    MEDIUM risk policy independently blocks a student caller."""
    d = TOOL_CATALOG[INTERNAL_TOOL]
    ctx = CallerContext(
        actor_type="agent_host", user_id=7, role="student", agent_type="generator",
    )
    check_internal_only(d, ctx)  # internal gate alone does not block agent_host
    result = run_guard(d, ctx, granted_scopes=["code:execute_internal"])
    assert result.rejected
    assert isinstance(result.error, MCPPermissionDenied)


def test_generator_scopes_include_execute_internal():
    granted = scopes_for_agent("generator")
    assert "code:execute_internal" in granted


def test_output_schema_validation_is_warn_only(caplog):
    """A result that violates output_schema must not raise."""
    import logging
    from tools.protocol.runtime import ToolRuntime

    d = TOOL_CATALOG[INTERNAL_TOOL]
    bad_result = {"status": 123}  # status should be a string per schema
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="tools.protocol.runtime"):
        ToolRuntime._validate_output(d, bad_result, trace_id="t-1")
    assert any("output_schema mismatch" in r.message for r in caplog.records)
