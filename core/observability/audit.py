"""Unified audit logging.

Merged from former mcp/observability/audit.py (in-memory AuditEntry +
logger emission) and mcp_gateway/audit.py (DB-persisted McpAuditLog write).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from core.db.session import get_session

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


def log_tool_call(
    api_key_id: str | None,
    user_id: int | None,
    tool_name: str,
    tool_args: dict | None,
    status: str,
    latency_ms: int | None = None,
):
    """Persist a tool-call entry to the McpAuditLog table."""
    from core.db.models.mcp_audit_log import McpAuditLog
    from app.core.timezone import now_china

    session = get_session()
    try:
        entry = McpAuditLog(
            api_key_id=api_key_id,
            user_id=user_id,
            tool_name=tool_name,
            tool_args=tool_args,
            status=status,
            latency_ms=latency_ms,
            created_at=now_china(),
        )
        session.add(entry)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to write audit log")
    finally:
        session.close()
