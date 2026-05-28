"""Standalone SQLAlchemy models for ai_conversations and ai_messages tables.

Mirrors app/models/ai_conversation.py without Flask-SQLAlchemy dependency.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, relationship

from core.db.session import Base

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = Column(Integer, primary_key=True)
    user_id: Mapped[int] = Column(Integer, nullable=False)
    agent_type: Mapped[str] = Column(String(20), nullable=False)
    context_type: Mapped[str | None] = Column(String(20), nullable=True)
    context_id: Mapped[int | None] = Column(Integer, nullable=True)
    title: Mapped[str | None] = Column(String(200), nullable=True)
    summary: Mapped[str | None] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime, default=_now_china)
    updated_at: Mapped[datetime] = Column(DateTime, default=_now_china, onupdate=_now_china)

    messages = relationship(
        "AIMessage",
        back_populates="conversation",
        lazy="selectin",
        order_by="AIMessage.id",
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = Column(Integer, primary_key=True)
    conversation_id: Mapped[int] = Column(
        Integer, ForeignKey("ai_conversations.id"), nullable=False
    )
    role: Mapped[str] = Column(String(10), nullable=False)
    content: Mapped[str] = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    tokens_used: Mapped[int | None] = Column(Integer, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime, default=_now_china)

    conversation = relationship("AIConversation", back_populates="messages")
