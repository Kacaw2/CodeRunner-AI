"""The single chat-domain mappings (SQLAlchemy 2.0 typed declarative).

These are the ONLY mapped classes for the ``ai_conversations``, ``ai_messages``
and ``chat_tasks`` tables. ``app/models/ai_conversation.py`` and
``app/models/chat_task.py`` are pure re-exports of these symbols. Columns, FKs,
cascade, nullability, defaults (``now_china`` and the ``uuid4`` id default),
relationships and backrefs are kept byte-for-byte equivalent to the previous
Flask ``db.Model`` definitions so the ORM reorg produces ZERO Alembic diff.

``User`` remains a domain model and ``GeneratedQuestionDraft`` a Flask
``db.Model`` class; both live on the SAME ``DomainBase`` registry/metadata, so
the string-based ``relationship()``/``backref`` targets below still resolve.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.timezone import now_china
from domain.base import DomainBase


class AIConversation(DomainBase):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    context_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    context_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china, onupdate=now_china
    )

    messages = relationship(
        "AIMessage",
        back_populates="conversation",
        lazy=True,
        cascade="all, delete-orphan",
    )
    user = relationship("User", backref="ai_conversations")

    def __repr__(self) -> str:
        return f"<AIConversation {self.id} [{self.agent_type}]>"


class AIMessage(DomainBase):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china
    )

    conversation = relationship("AIConversation", back_populates="messages")

    def __repr__(self) -> str:
        return f"<AIMessage {self.id} [{self.role}]>"


class ChatTask(DomainBase):
    """Async chat task that decouples AI processing from HTTP connection lifetime.

    Lifecycle: pending -> processing -> completed | failed
    """
    __tablename__ = "chat_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_conversations.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    user_message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_messages.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    agent_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto"
    )
    routed_agent: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    result_message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_messages.id"), nullable=True
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    # Relationships
    conversation = relationship("AIConversation", backref="tasks")
    user = relationship("User", backref="chat_tasks")
    user_message = relationship(
        "AIMessage", foreign_keys="ChatTask.user_message_id"
    )
    result_message = relationship(
        "AIMessage", foreign_keys="ChatTask.result_message_id"
    )

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

    def __repr__(self) -> str:
        return f"<ChatTask {self.id} [{self.status}]>"
