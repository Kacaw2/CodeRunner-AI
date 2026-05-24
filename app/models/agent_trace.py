from uuid import uuid4

from app.core.extensions import db
from app.core.timezone import now_china


class AgentRun(db.Model):
    __tablename__ = "agent_runs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"), nullable=True)
    message_id = db.Column(db.Integer, db.ForeignKey("ai_messages.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    agent_type = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="running")

    input_message = db.Column(db.Text)
    input_context = db.Column(db.JSON)
    output_response = db.Column(db.Text)

    total_latency_ms = db.Column(db.Integer)
    llm_latency_ms = db.Column(db.Integer)
    tool_latency_ms = db.Column(db.Integer)
    tokens_input = db.Column(db.Integer)
    tokens_output = db.Column(db.Integer)

    tool_call_count = db.Column(db.Integer, default=0)
    tool_calls_json = db.Column(db.JSON)

    error_type = db.Column(db.String(50), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    llm_retries = db.Column(db.Integer, default=0)
    tool_retries = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=now_china)

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "total_latency_ms": self.total_latency_ms,
            "llm_latency_ms": self.llm_latency_ms,
            "tool_latency_ms": self.tool_latency_ms,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tool_call_count": self.tool_call_count,
            "tool_calls_json": self.tool_calls_json,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentRunStep(db.Model):
    __tablename__ = "agent_run_steps"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(36), db.ForeignKey("agent_runs.id"), nullable=False)
    step_index = db.Column(db.Integer, nullable=False)
    step_type = db.Column(db.String(20))

    tool_name = db.Column(db.String(50), nullable=True)
    tool_input = db.Column(db.JSON, nullable=True)
    tool_output_preview = db.Column(db.Text, nullable=True)
    tool_success = db.Column(db.Boolean, nullable=True)

    llm_prompt_tokens = db.Column(db.Integer, nullable=True)
    llm_completion_tokens = db.Column(db.Integer, nullable=True)

    latency_ms = db.Column(db.Integer)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=now_china)

    run = db.relationship("AgentRun", backref=db.backref("steps", lazy=True, order_by="AgentRunStep.step_index"))

    def to_dict(self):
        return {
            "id": self.id,
            "run_id": self.run_id,
            "step_index": self.step_index,
            "step_type": self.step_type,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output_preview": self.tool_output_preview,
            "tool_success": self.tool_success,
            "llm_prompt_tokens": self.llm_prompt_tokens,
            "llm_completion_tokens": self.llm_completion_tokens,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
