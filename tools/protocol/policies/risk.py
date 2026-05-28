"""Risk-level policy enforcement."""

from __future__ import annotations

from core.auth.context import CallerContext
from tools.protocol.schemas.descriptors import ToolDescriptor, RiskLevel, ApprovalPolicy
from tools.protocol.errors import MCPApprovalRequired, MCPPermissionDenied


def check_risk_policy(
    tool: ToolDescriptor,
    ctx: CallerContext,
) -> None:
    """Raise MCPApprovalRequired for high-risk tools that need teacher approval."""
    if tool.risk_level == RiskLevel.HIGH:
        if tool.approval_policy != ApprovalPolicy.NONE:
            raise MCPApprovalRequired(
                f"Tool '{tool.name}' requires approval before execution.",
                trace_id=ctx.trace_id,
            )

    if tool.risk_level == RiskLevel.MEDIUM:
        if ctx.role == "student":
            raise MCPPermissionDenied(
                f"Tool '{tool.name}' is not available for students.",
                trace_id=ctx.trace_id,
            )
