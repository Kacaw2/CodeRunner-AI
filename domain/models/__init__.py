"""Domain mapped models (pure SQLAlchemy 2.0, runtime-neutral).

Every class here inherits :class:`domain.base.DomainBase` — the single
mapped-class registry shared with the remaining Flask ``db.Model`` classes.
"""

from domain.models.user import User, UserRole
from domain.models.chat import AIConversation, AIMessage, ChatTask
from domain.models.mcp import McpApiKey, McpAuditLog, McpToolApproval
from domain.models.workflow import WorkflowApproval, WorkflowRun, WorkflowStep
from domain.models.memory import MemoryItemRecord
from domain.models.observability import (
    AgentTraceArtifact,
    AgentTraceEvent,
    AgentTraceLink,
    AgentTraceRun,
    AgentTraceSpan,
    EvalCaseGraderResult,
    EvalCaseRun,
    EvalRun,
)

__all__ = [
    "User",
    "UserRole",
    "AIConversation",
    "AIMessage",
    "ChatTask",
    "McpApiKey",
    "McpAuditLog",
    "McpToolApproval",
    "WorkflowRun",
    "WorkflowStep",
    "WorkflowApproval",
    "MemoryItemRecord",
    "AgentTraceRun",
    "AgentTraceSpan",
    "AgentTraceEvent",
    "AgentTraceArtifact",
    "AgentTraceLink",
    "EvalRun",
    "EvalCaseRun",
    "EvalCaseGraderResult",
]
