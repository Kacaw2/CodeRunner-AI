"""MCP audit logging — every tool call gets an audit entry."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("mcp.audit")


@dataclass
class AuditEntry:
    trace_id: str = ""
    task_id: str = ""
    conversation_id: str = ""
    agent_type: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    server_name: str = ""
    user_id: int = 0
    role: str = ""
    status: str = "pending"
    latency_ms: int = 0
    error_code: str = ""
    approval_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "agent_type": self.agent_type,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "server_name": self.server_name,
            "user_id": self.user_id,
            "role": self.role,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "approval_id": self.approval_id,
            "timestamp": self.timestamp,
        }


def emit_audit(entry: AuditEntry) -> None:
    logger.info(
        "tool_call tool=%s user=%d role=%s status=%s latency=%dms trace=%s",
        entry.tool_name,
        entry.user_id,
        entry.role,
        entry.status,
        entry.latency_ms,
        entry.trace_id,
    )
