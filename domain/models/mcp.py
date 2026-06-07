"""MCP persistence mappings on the shared DomainBase registry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domain.base import DomainBase

APPROVAL_TIMEOUT_MINUTES = 30
_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


class McpApiKey(DomainBase):
    __tablename__ = "mcp_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    scopes: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    rate_limit_rpm: Mapped[Optional[int]] = mapped_column(Integer, default=30)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=_now_china
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    user = relationship("User", backref="mcp_api_keys")


class McpAuditLog(DomainBase):
    __tablename__ = "mcp_audit_logs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    api_key_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mcp_api_keys.id"), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_args: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=_now_china
    )


class McpToolApproval(DomainBase):
    __tablename__ = "mcp_tool_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    api_key_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mcp_api_keys.id"), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_args: Mapped[dict] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[Optional[str]] = mapped_column(
        String(10), default="high"
    )
    status: Mapped[Optional[str]] = mapped_column(
        String(20), default="pending"
    )
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=_now_china
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    requester = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])

    @staticmethod
    def default_expiry() -> datetime:
        return _now_china() + timedelta(minutes=APPROVAL_TIMEOUT_MINUTES)

    def check_expiration(self) -> None:
        if (
            self.status == "pending"
            and self.expires_at
            and _now_china() > self.expires_at
        ):
            self.status = "expired"

    def to_dict(self) -> dict:
        self.check_expiration()
        return {
            "id": self.id,
            "api_key_id": self.api_key_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "risk_level": self.risk_level,
            "status": self.status,
            "reviewer_id": self.reviewer_id,
            "review_notes": self.review_notes,
            "result": self.result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": (
                self.reviewed_at.isoformat() if self.reviewed_at else None
            ),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


__all__ = [
    "APPROVAL_TIMEOUT_MINUTES",
    "McpApiKey",
    "McpAuditLog",
    "McpToolApproval",
]
