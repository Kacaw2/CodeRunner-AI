"""Declarative agent definitions (Phase C, updated for Phase E MCP).

Each agent is described as a data structure.  Tool names now use the
MCP namespace convention (coderunner.*) instead of LangChain function names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ai.llm.tiers import ModelTier


class MemoryProfileKind(str, Enum):
    NONE = "none"
    ACTOR = "actor"
    STUDENT = "student"
    TEACHER = "teacher"


@dataclass(frozen=True)
class MemoryPolicy:
    profile_kind: MemoryProfileKind = MemoryProfileKind.NONE
    include_recent_summaries: bool = False
    recent_summary_agent_types: frozenset[str] = frozenset()
    max_recent_summaries: int = 3
    allow_target_student: bool = False


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
    max_tool_iterations: int = 5          # per-agent tool-loop ceiling
    rate_limit: int = 20                  # requests/minute (was AGENT_RATE_LIMITS)
    handoff_targets: frozenset[str] = frozenset()
    prompt_ref: str | None = None         # dotted path to the base system prompt
    memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)


TUTOR_MEMORY_POLICY = MemoryPolicy(
    profile_kind=MemoryProfileKind.STUDENT,
    include_recent_summaries=True,
    recent_summary_agent_types=frozenset({"tutor"}),
    max_recent_summaries=3,
)

REVIEWER_MEMORY_POLICY = MemoryPolicy()

GENERATOR_MEMORY_POLICY = MemoryPolicy(
    profile_kind=MemoryProfileKind.TEACHER,
    include_recent_summaries=True,
    recent_summary_agent_types=frozenset({"generator"}),
    max_recent_summaries=3,
)

ANALYTICS_MEMORY_POLICY = MemoryPolicy(
    profile_kind=MemoryProfileKind.ACTOR,
    include_recent_summaries=True,
    recent_summary_agent_types=frozenset({"analytics"}),
    max_recent_summaries=3,
    allow_target_student=True,
)


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
        "coderunner.agent.delegate",
    ),
    risk_level="low",
    input_fields=("question_id", "submission_id", "code", "error_status", "topic"),
    output_format="free_text",
    max_tool_iterations=5,
    rate_limit=20,
    handoff_targets=frozenset({"reviewer", "analytics"}),
    prompt_ref="agents.tutor.prompt.TUTOR_SYSTEM_PROMPT",
    memory_policy=TUTOR_MEMORY_POLICY,
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
        "coderunner.agent.delegate",
    ),
    risk_level="low",
    input_fields=("question_id", "code", "language"),
    output_format="json_schema",
    output_schema_name="REVIEW_SCHEMA",
    max_tool_iterations=5,
    rate_limit=10,
    handoff_targets=frozenset({"tutor", "analytics"}),
    prompt_ref="agents.reviewer.prompt.REVIEWER_SYSTEM_PROMPT",
    memory_policy=REVIEWER_MEMORY_POLICY,
)

GENERATOR_DEFINITION = AgentDefinition(
    name="generator",
    description="Generate new coding problems with test cases and a verified "
                "reference solution.  Teacher/admin only.",
    default_model_tier=ModelTier.STRONG,
    allowed_roles=frozenset({"teacher", "admin"}),
    allowed_tools=(
        "coderunner.code.execute_internal",
        "coderunner.knowledge.search_similar_problems",
        "coderunner.problem.save_generated",
        "coderunner.agent.delegate",
    ),
    risk_level="high",
    input_fields=("topic", "difficulty", "language", "test_case_count", "prompt", "quiz_id"),
    output_format="json_schema",
    output_schema_name="QUESTION_SCHEMA",
    max_tool_iterations=5,
    rate_limit=5,
    handoff_targets=frozenset({"analytics"}),
    prompt_ref="agents.generator.prompt.GENERATOR_SYSTEM_PROMPT",
    memory_policy=GENERATOR_MEMORY_POLICY,
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
        "coderunner.agent.delegate",
    ),
    risk_level="low",
    input_fields=("target_student_id", "question_id", "period"),
    output_format="json_schema",
    output_schema_name="ANALYTICS_SCHEMA",
    max_tool_iterations=5,
    rate_limit=10,
    handoff_targets=frozenset({"tutor", "reviewer"}),
    prompt_ref="agents.analytics.prompt.ANALYTICS_SYSTEM_PROMPT",
    memory_policy=ANALYTICS_MEMORY_POLICY,
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
