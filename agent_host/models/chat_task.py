"""Standalone SQLAlchemy model mapping to the existing chat_tasks table.

This mirrors app/models/chat_task.py but uses plain SQLAlchemy (no Flask-SQLAlchemy)
so the FastAPI service can read/write the same table without Flask context.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped

from agent_host.core.db import Base

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


class ChatTask(Base):
    __tablename__ = "chat_tasks"

    id: Mapped[str] = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[int | None] = Column(Integer, nullable=True)
    user_id: Mapped[int] = Column(Integer, nullable=False)
    user_message_id: Mapped[int | None] = Column(Integer, nullable=True)
    status: Mapped[str] = Column(String(20), nullable=False, default="pending")
    agent_type: Mapped[str] = Column(String(20), nullable=False, default="auto")
    routed_agent: Mapped[str | None] = Column(String(20), nullable=True)
    result_message_id: Mapped[int | None] = Column(Integer, nullable=True)
    error_detail: Mapped[str | None] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime, default=_now_china)
    started_at: Mapped[datetime | None] = Column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "status": self.status,
            "agent_type": self.agent_type,
            "routed_agent": self.routed_agent,
            "result_message_id": self.result_message_id,
            "error_detail": self.error_detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
