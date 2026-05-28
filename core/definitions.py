"""Declarative agent definitions (Phase C, updated for Phase E MCP).

Each agent is described as a data structure.  Tool names now use the
MCP namespace convention (coderunner.*) instead of LangChain function names.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from models.tiers import ModelTier


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
    output_schema_name: str | None = None


TUTOR_DEFINITION = AgentDefinition(
    name="tutor",
    description="Guide students through coding problems using Socratic method. "
                "Provides graduated hints without giving away full answers.",
    default_model_tier=ModelTier.BALANCED,
    allowed_roles=frozenset({"student", "teacher", "admin"}),
    allowed_tools=(
        "coderunner.code.execute",
        "coderunner.problem.get_detail",
        "coderunner.submission.list_for_student",
        "coderunner.submission.get_detail",
        "coderunner.knowledge.search",
        "coderunner.knowledge.search_error_patterns",
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
        "coderunner.code.execute",
        "coderunner.problem.get_detail",
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
        "coderunner.code.execute",
        "coderunner.knowledge.search_similar_problems",
        "coderunner.problem.save_generated",
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
        "coderunner.problem.get_detail",
        "coderunner.submission.list_for_student",
        "coderunner.submission.get_detail",
        "coderunner.analytics.student_stats",
        "coderunner.analytics.student_activity",
        "coderunner.analytics.class_statistics",
        "coderunner.analytics.problem_difficulty",
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
