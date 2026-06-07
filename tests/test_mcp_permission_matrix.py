"""Data-driven MCP authorization matrix.

Every authorization decision lives in ``evals/mcp/permission_matrix.yaml`` and is
exercised here through the real guard pipeline (RBAC -> scope -> risk). Adding a
tool or changing a policy means editing the YAML, not this file.

The guard level is chosen deliberately: it is the pure authorization decision
(no DB, no transport, no bootstrap), so the matrix is deterministic and fast and
belongs in the MCP fast suite.
"""

from __future__ import annotations

import os

import pytest
import yaml

from core.auth.context import CallerContext
from ai.tools.protocol.schemas.catalog import TOOL_CATALOG
from ai.tools.protocol.policies.guard import run_guard
from ai.tools.protocol.policies.scopes import scopes_for_agent

_MATRIX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "ai",
    "evals",
    "mcp",
    "permission_matrix.yaml",
)


def _load_cases() -> list[dict]:
    with open(_MATRIX_PATH, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return doc["cases"]


_CASES = _load_cases()


def _resolve_scopes(case: dict) -> list[str]:
    raw = case.get("scopes")
    if raw == "AGENT_MINIMAL":
        return scopes_for_agent(case["agent_type"])
    if raw is None:
        return []
    return list(raw)


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_permission_matrix(case: dict):
    tool = TOOL_CATALOG[case["tool"]]
    ctx = CallerContext(
        actor_type=case["caller_type"],
        user_id=1,
        role=case["role"],
        agent_type=case.get("agent_type") or "",
    )
    result = run_guard(tool, ctx, granted_scopes=_resolve_scopes(case))

    if case["expected"] == "ok":
        assert result.passed, (
            f"{case['id']}: expected ok but got "
            f"{result.error.code.value if result.error else '??'}"
        )
    else:
        assert result.rejected, f"{case['id']}: expected denial, but it passed"
        assert result.error.code.value == case["expected"], (
            f"{case['id']}: expected {case['expected']} "
            f"but got {result.error.code.value}"
        )


def test_matrix_tool_names_exist_in_catalog():
    referenced = {c["tool"] for c in _CASES}
    unknown = referenced - set(TOOL_CATALOG)
    assert unknown == set(), f"matrix references unknown tools: {unknown}"


def test_matrix_covers_every_catalog_tool():
    """A new tool must come with at least one matrix row — fail loudly if not."""
    referenced = {c["tool"] for c in _CASES}
    uncovered = set(TOOL_CATALOG) - referenced
    assert uncovered == set(), (
        f"tools missing from permission_matrix.yaml: {sorted(uncovered)}"
    )


def test_matrix_case_ids_are_unique():
    ids = [c["id"] for c in _CASES]
    assert len(ids) == len(set(ids)), "duplicate case id in permission_matrix.yaml"
