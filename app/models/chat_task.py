import uuid
from app.core.extensions import db
from app.core.timezone import now_china


class ChatTask(db.Model):
    """Async chat task that decouples AI processing from HTTP connection lifetime.

    Lifecycle: pending -> processing -> completed | failed
    """
    __tablename__ = "chat_tasks"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user_message_id = db.Column(db.Integer, db.ForeignKey("ai_messages.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    agent_type = db.Column(db.String(20), nullable=False, default="auto")
    routed_agent = db.Column(db.String(20), nullable=True)
    result_message_id = db.Column(db.Integer, db.ForeignKey("ai_messages.id"), nullable=True)
    error_detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    conversation = db.relationship(
        "AIConversation",
        backref=db.backref("tasks", lazy=True),
    )
    user = db.relationship(
        "User",
        backref=db.backref("chat_tasks", lazy=True),
    )
    user_message = db.relationship(
        "AIMessage",
        foreign_keys=[user_message_id],
    )
    result_message = db.relationship(
        "AIMessage",
        foreign_keys=[result_message_id],
    )

    def to_dict(self):
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

    def __repr__(self):
        return f"<ChatTask {self.id} [{self.status}]>"
