from app.core.extensions import db
from app.core.timezone import now_china


class AIConversation(db.Model):
    __tablename__ = "ai_conversations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    agent_type = db.Column(db.String(20), nullable=False)
    context_type = db.Column(db.String(20), nullable=True)
    context_id = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(200), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)
    updated_at = db.Column(db.DateTime, default=now_china, onupdate=now_china)

    messages = db.relationship("AIMessage", back_populates="conversation", lazy=True, cascade="all, delete-orphan")
    user = db.relationship("User", backref=db.backref("ai_conversations", lazy=True))

    def __repr__(self):
        return f"<AIConversation {self.id} [{self.agent_type}]>"


class AIMessage(db.Model):
    __tablename__ = "ai_messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    tool_calls = db.Column(db.JSON, nullable=True)
    tokens_used = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)

    conversation = db.relationship("AIConversation", back_populates="messages")

    def __repr__(self):
        return f"<AIMessage {self.id} [{self.role}]>"
