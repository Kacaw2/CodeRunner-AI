"""Declarative agent definitions (Phase C).

Each agent is described as a data structure rather than scattered across
class attributes, permission tables, and orchestrator logic.  The
orchestrator and tool layer read these definitions at runtime to enforce
routing, tool filtering, and role access.

Adding a new agent only requires adding an entry here — the orchestrator,
permission checks, and documentation can all be derived from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.model_router.tiers import ModelTier


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    default_model_tier: ModelTier
    allowed_roles: frozenset[str]
    allowed_tools: tuple[str, ...]
    risk_level: str  # "low", "medium", "high"
    input_fields: tuple[str, ...]  # expected context keys
    output_format: str  # "free_text", "json_schema"
    output_schema_name: str | None = None  # key in schemas.py if json_schema


TUTOR_DEFINITION = AgentDefinition(
    name="tutor",
    description="Guide students through coding problems using Socratic method. "
                "Provides graduated hints without giving away full answers.",
    default_model_tier=ModelTier.BALANCED,
    allowed_roles=frozenset({"student", "teacher", "admin"}),
    allowed_tools=(
        "execute_code",
        "get_problem_detail",
        "get_student_submissions",
        "get_submission_detail",
        "search_knowledge",
        "search_error_patterns",
    ),
    risk_level="low",
    input_fields=("question_id", "submission_id", "code", "error_status", "language"),
    output_format="free_text",
)

REVIEWER_DEFINITION = AgentDefinition(
    name="reviewer",
    description="Review student code for correctness, readability, efficiency, "
                "security, and best practices.  Output structured JSON.",
    default_model_tier=ModelTier.BALANCED,
    allowed_roles=frozenset({"student", "teacher", "admin"}),
    allowed_tools=(
        "execute_code",
        "get_problem_detail",
    ),
    risk_level="low",
    input_fields=("question_id", "code", "language"),
    output_format="json_schema",
    output_schema_name="REVIEW_SCHEMA",
)

GENERATOR_DEFINITION = AgentDefinition(
    name="generator",
    description="Generate new coding problems with test cases and a verified "
                "reference solution.  Teacher/admin only.",
    default_model_tier=ModelTier.STRONG,
    allowed_roles=frozenset({"teacher", "admin"}),
    allowed_tools=(
        "execute_code",
        "search_similar_problems",
    ),
    risk_level="high",
    input_fields=("topic", "difficulty", "language", "test_case_count", "prompt"),
    output_format="json_schema",
    output_schema_name="QUESTION_SCHEMA",
)

ANALYTICS_DEFINITION = AgentDefinition(
    name="analytics",
    description="Analyse student learning data — error patterns, progress "
                "trends, and class-level statistics.",
    default_model_tier=ModelTier.STRONG,
    allowed_roles=frozenset({"student", "teacher", "admin"}),
    allowed_tools=(
        "get_problem_detail",
        "get_student_submissions",
        "get_submission_detail",
        "get_student_stats",
        "get_student_activity",
        "get_class_statistics",
        "get_problem_difficulty_stats",
    ),
    risk_level="low",
    input_fields=("target_student_id", "question_id", "period"),
    output_format="json_schema",
    output_schema_name="ANALYTICS_SCHEMA",
)

# ── Registry ────────────────────────────────────────────────────────

AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    d.name: d
    for d in [TUTOR_DEFINITION, REVIEWER_DEFINITION, GENERATOR_DEFINITION, ANALYTICS_DEFINITION]
}


def get_definition(agent_name: str) -> AgentDefinition | None:
    return AGENT_DEFINITIONS.get(agent_name)


def can_route_to(agent_name: str, user_role: str) -> bool:
    """Check whether *user_role* is allowed to invoke *agent_name*."""
    defn = AGENT_DEFINITIONS.get(agent_name)
    if defn is None:
        return False
    return user_role in defn.allowed_roles


def allowed_tools_for(agent_name: str) -> tuple[str, ...]:
    """Return the tool allowlist declared by *agent_name*."""
    defn = AGENT_DEFINITIONS.get(agent_name)
    if defn is None:
        return ()
    return defn.allowed_tools
