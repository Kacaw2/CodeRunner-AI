"""Standalone SQLAlchemy models for workflow_runs and workflow_steps tables.

Mirrors app/models/workflow.py without Flask-SQLAlchemy dependency.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, relationship

from agent_host.core.db import Base

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[int] = Column(Integer, nullable=False)
    conversation_id: Mapped[int | None] = Column(Integer, nullable=True)
    chat_task_id: Mapped[str | None] = Column(String(36), nullable=True)

    goal: Mapped[str] = Column(Text, nullable=False)
    workflow_type: Mapped[str] = Column(String(50), nullable=False, default="general")
    status: Mapped[str] = Column(String(20), nullable=False, default="planning")

    plan_json = Column(JSON, nullable=True)
    current_step_index: Mapped[int] = Column(Integer, default=0)
    total_steps: Mapped[int] = Column(Integer, default=0)

    result = Column(JSON, nullable=True)
    error_detail: Mapped[str | None] = Column(Text, nullable=True)

    max_steps: Mapped[int] = Column(Integer, default=10)
    max_retries_per_step: Mapped[int] = Column(Integer, default=2)
    timeout_seconds: Mapped[int] = Column(Integer, default=300)

    total_tokens_used: Mapped[int] = Column(Integer, default=0)
    total_latency_ms: Mapped[int] = Column(Integer, default=0)

    created_at: Mapped[datetime] = Column(DateTime, default=_now_china)
    started_at: Mapped[datetime | None] = Column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = Column(DateTime, nullable=True)

    steps = relationship(
        "WorkflowStep",
        back_populates="workflow_run",
        order_by="WorkflowStep.step_index",
        lazy="selectin",
    )

    def to_dict(self) -> dict:
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
            "steps": [s.to_dict() for s in (self.steps or [])],
        }


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[str] = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workflow_run_id: Mapped[str] = Column(String(36), nullable=False)
    step_index: Mapped[int] = Column(Integer, nullable=False)

    step_type: Mapped[str] = Column(String(30), nullable=False)
    agent_type: Mapped[str | None] = Column(String(30), nullable=True)
    instruction: Mapped[str] = Column(Text, nullable=False)

    status: Mapped[str] = Column(String(20), nullable=False, default="pending")

    risk_level: Mapped[str] = Column(String(10), default="low")
    requires_approval: Mapped[bool] = Column(Boolean, default=False)

    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_detail: Mapped[str | None] = Column(Text, nullable=True)

    attempt: Mapped[int] = Column(Integer, default=0)
    max_attempts: Mapped[int] = Column(Integer, default=2)

    tokens_used: Mapped[int] = Column(Integer, default=0)
    latency_ms: Mapped[int] = Column(Integer, default=0)

    depends_on = Column(JSON, nullable=True)

    started_at: Mapped[datetime | None] = Column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = Column(DateTime, nullable=True)

    workflow_run = relationship("WorkflowRun", back_populates="steps")

    def to_dict(self) -> dict:
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
