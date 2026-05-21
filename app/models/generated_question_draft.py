from datetime import datetime

from app.core.extensions import db


class GeneratedQuestionDraft(db.Model):
    """Staging area for AI-generated questions before teacher approval."""
    __tablename__ = "generated_question_drafts"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(36), db.ForeignKey("agent_tasks.id"), nullable=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    question_data = db.Column(db.JSON, nullable=False)
    validation_status = db.Column(db.String(20), nullable=True)
    validation_details = db.Column(db.JSON, nullable=True)

    status = db.Column(db.String(20), default="pending_review")
    review_notes = db.Column(db.Text, nullable=True)
    revision_count = db.Column(db.Integer, default=0)

    published_question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher = db.relationship("User", foreign_keys=[teacher_id])
    published_question = db.relationship("Question", foreign_keys=[published_question_id])

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "teacher_id": self.teacher_id,
            "question_data": self.question_data,
            "validation_status": self.validation_status,
            "validation_details": self.validation_details,
            "status": self.status,
            "review_notes": self.review_notes,
            "revision_count": self.revision_count,
            "published_question_id": self.published_question_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
