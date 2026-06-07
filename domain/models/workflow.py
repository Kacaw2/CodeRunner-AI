"""Runtime-neutral workflow mappings on the shared DomainBase registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DynamicMapped, Mapped, mapped_column, relationship

from app.core.timezone import now_china
from domain.base import DomainBase


class WorkflowRun(DomainBase):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    conversation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_conversations.id"), nullable=True
    )
    chat_task_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("chat_tasks.id"), nullable=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planning"
    )
    plan_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    current_step_index: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    total_steps: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_steps: Mapped[Optional[int]] = mapped_column(Integer, default=10)
    max_retries_per_step: Mapped[Optional[int]] = mapped_column(Integer, default=2)
    timeout_seconds: Mapped[Optional[int]] = mapped_column(Integer, default=300)
    total_tokens_used: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user = relationship("User", backref="workflow_runs")
    steps: DynamicMapped["WorkflowStep"] = relationship(
        "WorkflowStep",
        back_populates="workflow_run",
        order_by="WorkflowStep.step_index",
        lazy="dynamic",
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
        }


class WorkflowStep(DomainBase):
    __tablename__ = "workflow_steps"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workflow_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id"), nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    agent_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    risk_level: Mapped[Optional[str]] = mapped_column(String(10), default="low")
    requires_approval: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    attempt: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    max_attempts: Mapped[Optional[int]] = mapped_column(Integer, default=2)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    depends_on: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    workflow_run: Mapped[WorkflowRun] = relationship(
        "WorkflowRun", back_populates="steps"
    )

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
            "trace_id": self.trace_id,
            "attempt": self.attempt,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "depends_on": self.depends_on,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class WorkflowApproval(DomainBase):
    __tablename__ = "workflow_approvals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id"),
        nullable=False,
        index=True,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=now_china
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_run_id": self.workflow_run_id,
            "step_index": self.step_index,
            "approver_user_id": self.approver_user_id,
            "decision": self.decision,
            "feedback": self.feedback,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


__all__ = ["WorkflowRun", "WorkflowStep", "WorkflowApproval"]
