"""Session-bound MCP repository. The caller owns commit and rollback."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.models.mcp import McpApiKey, McpAuditLog, McpToolApproval


class SyncMcpRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_api_key(self, key: McpApiKey) -> McpApiKey:
        self.session.add(key)
        return key

    def get_active_api_key_by_hash(
        self, key_hash: str
    ) -> Optional[McpApiKey]:
        return self.session.execute(
            select(McpApiKey).where(
                McpApiKey.key_hash == key_hash,
                McpApiKey.revoked_at.is_(None),
            )
        ).scalar_one_or_none()

    def get_api_key_for_user(
        self, key_id: str, user_id: int
    ) -> Optional[McpApiKey]:
        return self.session.execute(
            select(McpApiKey).where(
                McpApiKey.id == key_id,
                McpApiKey.user_id == user_id,
            )
        ).scalar_one_or_none()

    def list_api_keys_for_user(self, user_id: int) -> list[McpApiKey]:
        return list(
            self.session.execute(
                select(McpApiKey)
                .where(McpApiKey.user_id == user_id)
                .order_by(McpApiKey.created_at.desc())
            ).scalars()
        )

    def create_approval(self, **values) -> McpToolApproval:
        approval = McpToolApproval(**values)
        self.session.add(approval)
        return approval

    def get_approval(
        self, approval_id: str, *, for_update: bool = False
    ) -> Optional[McpToolApproval]:
        stmt = select(McpToolApproval).where(
            McpToolApproval.id == approval_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def list_approvals(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[McpToolApproval]:
        stmt = select(McpToolApproval).order_by(
            McpToolApproval.created_at.desc()
        )
        if status is not None:
            stmt = stmt.where(McpToolApproval.status == status)
        return list(self.session.execute(stmt.limit(limit)).scalars())

    def add_audit_log(self, **values) -> McpAuditLog:
        entry = McpAuditLog(**values)
        self.session.add(entry)
        return entry
