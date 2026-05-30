"""Workflow state definitions for the LangGraph-based workflow engine."""

from typing import TypedDict, Literal


class WorkflowStepDef(TypedDict, total=False):
    """A single step in a structured workflow plan."""
    step_index: int
    step_type: Literal["agent_call", "tool_call", "validation", "llm_call", "human_gate"]
    agent_type: str
    instruction: str
    risk_level: Literal["low", "medium", "high"]
    requires_approval: bool
    depends_on: list[int]
    validates_step: int
    validation_criteria: str


class WorkflowPlan(TypedDict, total=False):
    """Structured plan produced by the planner."""
    goal: str
    workflow_type: str
    steps: list[WorkflowStepDef]
    context: dict


class WorkflowState(TypedDict, total=False):
    """Runtime state for a workflow execution."""
    workflow_run_id: str
    user_id: int
    user_role: str
    goal: str
    workflow_type: str
    plan: WorkflowPlan
    current_step_index: int
    step_outputs: dict  # step_index -> output
    status: str
    error: str
    final_result: dict
    context: dict  # shared context passed between steps
