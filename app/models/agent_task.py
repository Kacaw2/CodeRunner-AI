from datetime import datetime
from uuid import uuid4

from app.core.extensions import db


class AgentTask(db.Model):
    __tablename__ = "agent_tasks"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"), nullable=True)
    task_type = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), default="pending")
    agent_type = db.Column(db.String(20), nullable=False)

    input_params = db.Column(db.JSON, nullable=False)
    plan_steps = db.Column(db.JSON, nullable=True)
    current_step = db.Column(db.Integer, default=0)
    result = db.Column(db.JSON, nullable=True)
    error_detail = db.Column(db.Text, nullable=True)

    attempt = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=3)

    review_status = db.Column(db.String(20), nullable=True)
    review_feedback = db.Column(db.Text, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("agent_tasks", lazy=True))
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "task_type": self.task_type,
            "status": self.status,
            "agent_type": self.agent_type,
            "input_params": self.input_params,
            "plan_steps": self.plan_steps,
            "current_step": self.current_step,
            "result": self.result,
            "error_detail": self.error_detail,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "review_status": self.review_status,
            "review_feedback": self.review_feedback,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
