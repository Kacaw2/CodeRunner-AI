"""Pydantic input contracts for the four agents (Phase 4.2).

These models describe the *input* slice of ``AgentState`` each agent expects.
Validation is **warn-only**: :func:`validate_agent_input` logs a structured
warning on mismatch and never raises, mirroring the warn-only output_schema
policy from S7. The goal is observability of malformed calls, not a new
rejection path that could regress live traffic.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

_ROLES = {"student", "teacher", "admin", "agent_host"}


class AgentInput(BaseModel):
    """Fields shared by every agent invocation."""

    model_config = ConfigDict(extra="ignore")

    user_id: int = Field(ge=0)
    user_role: str = "student"
    agent_type: str
    context: dict = Field(default_factory=dict)


class TutorContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question_id: int | None = None
    submission_id: int | None = None
    error_status: str | None = None
    code: str | None = None
    topic: str | None = None


class TutorInput(AgentInput):
    context: TutorContext = Field(default_factory=TutorContext)


class ReviewerContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    problem_id: int | None = None
    code: str | None = None


class ReviewerInput(AgentInput):
    context: ReviewerContext = Field(default_factory=ReviewerContext)


class GeneratorContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    difficulty: str | None = None
    programming_language: str | None = None
    topic: str | None = None


class GeneratorInput(AgentInput):
    context: GeneratorContext = Field(default_factory=GeneratorContext)


class AnalyticsContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    student_id: int | None = None
    question_id: int | None = None


class AnalyticsInput(AgentInput):
    context: AnalyticsContext = Field(default_factory=AnalyticsContext)


AGENT_INPUT_MODELS: dict[str, type[AgentInput]] = {
    "tutor": TutorInput,
    "reviewer": ReviewerInput,
    "generator": GeneratorInput,
    "analytics": AnalyticsInput,
}


def validate_agent_input(agent_name: str, state: dict) -> list[str]:
    """Warn-only validation of an agent's input state.

    Returns a list of human-readable error strings (empty when the input is
    valid or no contract is registered for *agent_name*). Never raises.
    """
    model = AGENT_INPUT_MODELS.get(agent_name)
    if model is None:
        return []

    payload = {
        "user_id": state.get("user_id"),
        "user_role": state.get("user_role", "student"),
        "agent_type": state.get("agent_type", agent_name),
        "context": state.get("context") or {},
    }
    errors: list[str] = []
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]

    role = payload["user_role"]
    if role not in _ROLES:
        errors.append(f"user_role: unexpected value '{role}'")

    if errors:
        logger.warning(
            "agent input contract violated (agent=%s, warn-only): %s",
            agent_name,
            "; ".join(errors),
        )
    return errors
