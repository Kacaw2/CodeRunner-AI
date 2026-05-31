"""Unified guard pipeline — runs all policy checks in order."""

from __future__ import annotations

from dataclasses import dataclass

from core.auth.context import CallerContext
from tools.protocol.schemas.descriptors import ToolDescriptor
from tools.protocol.errors import MCPError, MCPPermissionDenied
from .rbac import check_rbac
from .risk import check_risk_policy
from .scopes import check_scope


def check_internal_only(tool: ToolDescriptor, ctx: CallerContext) -> None:
    """Reject external callers for internal-only tools.

    The actor_type is set from a verified internal signature (agent_host) or an
    external API key (external_client) — it cannot be self-declared. This is the
    structural gate that keeps an API key from reaching a non-approval executor,
    independent of which scopes the key happens to carry.
    """
    if tool.internal_only and ctx.actor_type != "agent_host":
        raise MCPPermissionDenied(
            f"Tool '{tool.name}' is internal-only and not callable by external clients.",
            trace_id=ctx.trace_id,
        )


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
    """Run internal-only -> rbac -> scope -> risk checks. Returns GuardResult."""
    try:
        check_internal_only(tool, ctx)
        check_rbac(tool, ctx)
        check_scope(tool, ctx, granted_scopes=granted_scopes)
        check_risk_policy(tool, ctx)
        return GuardResult(passed=True)
    except MCPError as exc:
        return GuardResult(passed=False, error=exc)
