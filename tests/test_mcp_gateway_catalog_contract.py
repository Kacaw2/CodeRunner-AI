"""Contract tests for external MCP gateway surface.

EXPECTED_EXTERNAL_TOOL_MAP is an independent oracle: it is intentionally NOT
imported from mcp_gateway.tool_map so that a wrong edit to the source map is
caught by test_source_map_matches_declared_contract rather than silently
accepted.
"""

import pytest

from mcp_gateway.server import create_mcp_server
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP
from tools.protocol.schemas.catalog import TOOL_CATALOG
from tools.protocol.schemas.descriptors import RiskLevel, ApprovalPolicy

# Canonical scope vocabulary (docs/MCP_RUNTIME_ARCHITECTURE.md §3). A required
# scope outside this set is a drift bug — external API keys are minted against
# this vocabulary.
CANONICAL_SCOPES = {
    "problem:read",
    "problem:write",
    "submission:read",
    "student:read",
    "code:execute",
    "knowledge:read",
    "analytics:read",
    "trace:read",
}

# Internal-only scope vocabulary. These scopes back tools marked
# internal_only=True (agent self-validation paths). They are NOT part of the
# external API-key vocabulary — the guard's actor-type gate, not scope alone,
# is what keeps external clients out. Kept separate so the comment above stays
# accurate about what API keys are minted against.
INTERNAL_SCOPES = {
    "code:execute_internal",
}

ALL_SCOPES = CANONICAL_SCOPES | INTERNAL_SCOPES


EXPECTED_EXTERNAL_TOOL_MAP = {
    "search_knowledge": "coderunner.knowledge.search",
    "search_similar_problems": "coderunner.knowledge.search_similar_problems",
    "search_error_patterns": "coderunner.knowledge.search_error_patterns",
    "get_problem_detail": "coderunner.problem.get_detail",
    "list_student_submissions": "coderunner.submission.list_for_student",
    "get_submission_detail": "coderunner.submission.get_detail",
    "get_problem_difficulty_stats": "coderunner.analytics.problem_difficulty",
    "get_student_activity": "coderunner.analytics.student_activity",
    "get_student_stats": "coderunner.analytics.student_stats",
    "get_class_statistics": "coderunner.analytics.class_statistics",
    "get_agent_trace": "coderunner.trace.get_agent_trace",
    "get_student_summary": "coderunner.student.get_summary",
    "execute_code": "coderunner.code.execute",
    "execute_internal": "coderunner.code.execute_internal",
    "save_generated_problem": "coderunner.problem.save_generated",
    "check_approval": "coderunner.approval.check",
}


def test_source_map_matches_declared_contract():
    assert EXTERNAL_TOOL_MAP == EXPECTED_EXTERNAL_TOOL_MAP


def test_external_tool_map_targets_existing_catalog_tools():
    missing = set(EXPECTED_EXTERNAL_TOOL_MAP.values()) - set(TOOL_CATALOG)
    assert missing == set()


def test_every_catalog_tool_is_exposed_by_mcp_server():
    assert set(EXPECTED_EXTERNAL_TOOL_MAP.values()) == set(TOOL_CATALOG)


def test_external_gateway_registers_exact_declared_tools():
    mcp = create_mcp_server()
    actual = set(mcp._tool_manager._tools)
    assert actual == set(EXPECTED_EXTERNAL_TOOL_MAP)


def test_expected_tool_count_matches_registered_tools():
    from mcp_gateway.server import EXPECTED_TOOL_COUNT

    mcp = create_mcp_server()
    assert EXPECTED_TOOL_COUNT == len(mcp._tool_manager._tools)


def test_generated_tools_module_is_not_stale():
    """The committed generated_tools.py must equal a fresh render.

    Run ``python -m mcp_gateway._codegen`` to fix a failure here.
    """
    import os
    from mcp_gateway._codegen import render_generated_tools_module

    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "mcp_gateway",
        "generated_tools.py",
    )
    with open(path, encoding="utf-8") as fh:
        committed = fh.read()
    assert committed == render_generated_tools_module(), (
        "mcp_gateway/generated_tools.py is stale — regenerate with "
        "`python -m mcp_gateway._codegen`"
    )


def test_generated_signatures_never_expose_caller_identity_fields():
    """Caller-injected identity fields must not appear as client parameters.

    Exposing them would let an API-key holder spoof another user's identity.
    """
    import inspect
    from mcp_gateway._codegen import CALLER_INJECTED_FIELDS

    mcp = create_mcp_server()
    for external_name, canonical in EXPECTED_EXTERNAL_TOOL_MAP.items():
        injected = CALLER_INJECTED_FIELDS.get(canonical, set())
        if not injected:
            continue
        tool = mcp._tool_manager._tools[external_name]
        params = set(inspect.signature(tool.fn).parameters)
        assert params.isdisjoint(injected), (
            f"{external_name} exposes caller-identity field(s) "
            f"{params & injected}"
        )


# ── Schema completeness contract ─────────────────────────────────────
# Every served tool must carry a complete, well-formed descriptor so the guard
# pipeline (schema validation, scope, risk, approval) has something to enforce.


@pytest.mark.parametrize("name", sorted(TOOL_CATALOG), ids=sorted(TOOL_CATALOG))
def test_descriptor_is_complete(name):
    d = TOOL_CATALOG[name]

    assert d.version, f"{name}: missing version"
    assert d.server, f"{name}: missing server"
    assert isinstance(d.risk_level, RiskLevel), f"{name}: bad risk_level"

    assert isinstance(d.input_schema, dict), f"{name}: input_schema not a dict"
    assert d.input_schema.get("type") == "object", (
        f"{name}: input_schema must be a JSON object schema"
    )
    assert isinstance(d.output_schema, dict), f"{name}: output_schema not a dict"

    assert isinstance(d.required_scopes, list), f"{name}: required_scopes not a list"
    unknown = set(d.required_scopes) - ALL_SCOPES
    assert unknown == set(), f"{name}: non-canonical scope(s) {unknown}"


@pytest.mark.parametrize("name", sorted(TOOL_CATALOG), ids=sorted(TOOL_CATALOG))
def test_high_risk_tools_require_approval(name):
    """A HIGH-risk tool with no approval policy would execute unguarded."""
    d = TOOL_CATALOG[name]
    if d.risk_level == RiskLevel.HIGH:
        assert d.approval_policy != ApprovalPolicy.NONE, (
            f"{name}: HIGH risk but no approval policy"
        )


def test_only_approval_check_may_omit_scopes():
    """Every tool requires a scope except the caller-bound approval poll."""
    scopeless = {n for n, d in TOOL_CATALOG.items() if not d.required_scopes}
    assert scopeless == {"coderunner.approval.check"}, (
        f"unexpected scopeless tools: {scopeless - {'coderunner.approval.check'}}"
    )
