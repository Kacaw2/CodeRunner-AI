"""Phase 4: agent contracts are the source of truth.

These tests prevent silent drift between ``core.definitions`` (declarative
``input_fields``) and ``agents.contracts`` (Pydantic context models), and prove
that the stricter ``extra="forbid"`` mode surfaces unexpected context keys as
warn-only contract violations.
"""

import pytest

from agents.contracts import (
    RUNTIME_CONTEXT_FIELDS,
    AnalyticsContext,
    GeneratorContext,
    ReviewerContext,
    TutorContext,
    validate_agent_input,
)
from core.definitions import AGENT_DEFINITIONS

# Agent name -> Pydantic context model.
CONTEXT_MODELS = {
    "tutor": TutorContext,
    "reviewer": ReviewerContext,
    "generator": GeneratorContext,
    "analytics": AnalyticsContext,
}


@pytest.mark.parametrize("agent_name", sorted(CONTEXT_MODELS))
def test_input_fields_match_context_model(agent_name):
    """Every declared input field exists on the context model, and any extra
    model field is an allowlisted runtime-injected key (not silent drift)."""
    defn = AGENT_DEFINITIONS[agent_name]
    model = CONTEXT_MODELS[agent_name]

    declared = set(defn.input_fields)
    model_fields = set(model.model_fields)

    missing = declared - model_fields
    assert not missing, (
        f"{agent_name}: input_fields not present on {model.__name__}: {sorted(missing)}"
    )

    extra = model_fields - declared
    assert extra <= RUNTIME_CONTEXT_FIELDS, (
        f"{agent_name}: {model.__name__} has fields neither declared in "
        f"input_fields nor allowlisted as runtime: {sorted(extra - RUNTIME_CONTEXT_FIELDS)}"
    )


def test_valid_context_passes_without_warning():
    """A well-formed context (including runtime keys) produces no violations."""
    state = {
        "user_id": 1,
        "user_role": "student",
        "agent_type": "reviewer",
        "context": {"question_id": 42, "code": "print(1)", "language": "python",
                    "conversation_id": 7},
    }
    assert validate_agent_input("reviewer", state) == []


def test_unexpected_context_key_surfaces_warning():
    """Stricter mode: an unknown context key is reported (warn-only)."""
    state = {
        "user_id": 1,
        "user_role": "student",
        "agent_type": "reviewer",
        "context": {"question_id": 42, "problem_id": 99},  # problem_id is stale/unknown
    }
    errors = validate_agent_input("reviewer", state)
    assert any("problem_id" in e for e in errors), errors


def test_generator_runtime_keys_allowed():
    """generated_problem + conversation_id are runtime keys, not violations."""
    state = {
        "user_id": 1,
        "user_role": "teacher",
        "agent_type": "generator",
        "context": {"topic": "loops", "difficulty": "easy", "language": "python",
                    "test_case_count": 5, "quiz_id": 3,
                    "conversation_id": 11, "generated_problem": {"id": 1}},
    }
    assert validate_agent_input("generator", state) == []


def test_validate_never_raises_on_bad_payload():
    """Warn-only guarantee: malformed payloads return a list, never raise."""
    state = {"user_id": "not-an-int", "context": {"unknown": 1}}
    result = validate_agent_input("tutor", state)
    assert isinstance(result, list)
