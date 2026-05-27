"""Unified guard pipeline — runs all policy checks in order."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.auth.context import CallerContext
from mcp.schemas.descriptors import ToolDescriptor
from mcp.errors import MCPError
from .rbac import check_rbac
from .risk import check_risk_policy
from .scopes import check_scope


@dataclass
class GuardResult:
    passed: bool
    error: MCPError | None = None

    @property
    def rejected(self) -> bool:
        return not self.passed


def run_guard(
    tool: ToolDescriptor,
    ctx: CallerContext,
    *,
    granted_scopes: list[str] | None = None,
) -> GuardResult:
    """Run auth -> rbac -> scope -> risk checks. Returns GuardResult."""
    try:
        check_rbac(tool, ctx)
        check_scope(tool, ctx, granted_scopes=granted_scopes)
        check_risk_policy(tool, ctx)
        return GuardResult(passed=True)
    except MCPError as exc:
        return GuardResult(passed=False, error=exc)
