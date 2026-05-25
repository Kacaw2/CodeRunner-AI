"""Audit logging for MCP tool calls."""

import logging

from mcp_server.db import get_session

logger = logging.getLogger(__name__)


def log_tool_call(
    api_key_id: str | None,
    user_id: int | None,
    tool_name: str,
    tool_args: dict | None,
    status: str,
    latency_ms: int | None = None,
):
    from mcp_server.models.audit_log import McpAuditLog
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
