import uuid

from app.core.extensions import db
from app.core.timezone import now_china


class WorkflowRun(db.Model):
    """A multi-step workflow execution coordinated by the Supervisor."""
    __tablename__ = "workflow_runs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"), nullable=True)
    chat_task_id = db.Column(db.String(36), db.ForeignKey("chat_tasks.id"), nullable=True)

    goal = db.Column(db.Text, nullable=False)
    workflow_type = db.Column(db.String(50), nullable=False, default="general")
    status = db.Column(db.String(20), nullable=False, default="planning")
    # planning -> executing -> validating -> completed | failed | cancelled
    # also: waiting_approval (human gate)

    plan_json = db.Column(db.JSON, nullable=True)
    current_step_index = db.Column(db.Integer, default=0)
    total_steps = db.Column(db.Integer, default=0)

    result = db.Column(db.JSON, nullable=True)
    error_detail = db.Column(db.Text, nullable=True)

    max_steps = db.Column(db.Integer, default=10)
    max_retries_per_step = db.Column(db.Integer, default=2)
    timeout_seconds = db.Column(db.Integer, default=300)

    total_tokens_used = db.Column(db.Integer, default=0)
    total_latency_ms = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=now_china)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("workflow_runs", lazy=True))
    steps = db.relationship("WorkflowStep", back_populates="workflow_run",
                            order_by="WorkflowStep.step_index", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "goal": self.goal,
            "workflow_type": self.workflow_type,
            "status": self.status,
            "plan": self.plan_json,
            "current_step_index": self.current_step_index,
            "total_steps": self.total_steps,
            "result": self.result,
            "error_detail": self.error_detail,
            "total_tokens_used": self.total_tokens_used,
            "total_latency_ms": self.total_latency_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class WorkflowStep(db.Model):
    """A single step within a workflow run."""
    __tablename__ = "workflow_steps"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_run_id = db.Column(db.String(36), db.ForeignKey("workflow_runs.id"), nullable=False)
    step_index = db.Column(db.Integer, nullable=False)

    step_type = db.Column(db.String(30), nullable=False)
    # agent_call, tool_call, validation, llm_call, human_gate
    agent_type = db.Column(db.String(30), nullable=True)
    instruction = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), nullable=False, default="pending")
    # pending -> running -> completed | failed | skipped | waiting_approval

    risk_level = db.Column(db.String(10), default="low")  # low, medium, high
    requires_approval = db.Column(db.Boolean, default=False)

    input_data = db.Column(db.JSON, nullable=True)
    output_data = db.Column(db.JSON, nullable=True)
    error_detail = db.Column(db.Text, nullable=True)

    attempt = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=2)

    tokens_used = db.Column(db.Integer, default=0)
    latency_ms = db.Column(db.Integer, default=0)

    depends_on = db.Column(db.JSON, nullable=True)  # list of step_indexes this depends on

    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    workflow_run = db.relationship("WorkflowRun", back_populates="steps")

    def to_dict(self):
        return {
            "id": self.id,
            "workflow_run_id": self.workflow_run_id,
            "step_index": self.step_index,
            "step_type": self.step_type,
            "agent_type": self.agent_type,
            "instruction": self.instruction,
            "status": self.status,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error_detail": self.error_detail,
            "attempt": self.attempt,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "depends_on": self.depends_on,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
