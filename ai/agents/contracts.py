"""Pydantic input contracts for the four agents (Phase 4.2 / Phase 4).

These models describe the *input* slice of ``AgentState`` each agent expects.
Validation is **warn-only**: :func:`validate_agent_input` logs a structured
warning on mismatch and never raises, mirroring the warn-only output_schema
policy from S7. The goal is observability of malformed calls, not a new
rejection path that could regress live traffic.

Context fields are split into two groups:

* **Input fields** — the user-supplied keys declared by each agent's
  :class:`~core.definitions.AgentDefinition`. These are the contract the
  caller is responsible for, and ``tests/test_agent_contracts.py`` proves
  they stay aligned with the definitions.
* **Runtime fields** — keys the platform injects into ``context`` before the
  agent runs (e.g. ``conversation_id`` for every agent, ``generated_problem``
  for the generator's revise flow). They are declared on the models so that
  the stricter ``extra="forbid"`` mode does not flag legitimate runtime keys
  as drift; they are intentionally absent from ``input_fields``.

The context models use ``extra="forbid"`` so that genuinely unexpected keys
surface as warnings via :func:`validate_agent_input`.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

_ROLES = {"student", "teacher", "admin", "agent_host"}

#: Context keys the platform injects at runtime (not part of any agent's
#: declared ``input_fields``). Declared on context models so ``extra="forbid"``
#: does not flag them as drift.
RUNTIME_CONTEXT_FIELDS = frozenset({"conversation_id", "generated_problem"})


class AgentInput(BaseModel):
    """Fields shared by every agent invocation."""

    model_config = ConfigDict(extra="ignore")

    user_id: int = Field(ge=0)
    user_role: str = "student"
    agent_type: str
    context: dict = Field(default_factory=dict)


class _BaseContext(BaseModel):
    """Common runtime-injected context fields shared by every agent."""

    model_config = ConfigDict(extra="forbid")
    conversation_id: int | str | None = None


class TutorContext(_BaseContext):
    question_id: int | None = None
    submission_id: int | None = None
    error_status: str | None = None
    code: str | None = None
    topic: str | None = None


class TutorInput(AgentInput):
    context: TutorContext = Field(default_factory=TutorContext)


class ReviewerContext(_BaseContext):
    question_id: int | None = None
    code: str | None = None
    language: str | None = None


class ReviewerInput(AgentInput):
    context: ReviewerContext = Field(default_factory=ReviewerContext)


class GeneratorContext(_BaseContext):
    topic: str | None = None
    difficulty: str | None = None
    language: str | None = None
    test_case_count: int | None = None
    prompt: str | None = None
    quiz_id: int | None = None
    generated_problem: dict | None = None


class GeneratorInput(AgentInput):
    context: GeneratorContext = Field(default_factory=GeneratorContext)


class AnalyticsContext(_BaseContext):
    target_student_id: int | None = None
    question_id: int | None = None
    period: str | None = None


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
