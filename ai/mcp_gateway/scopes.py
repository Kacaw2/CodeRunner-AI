"""Scope normalization for MCP API keys."""

LEGACY_SCOPE_TO_CANONICAL = {
    "search_knowledge": "knowledge:read",
    "search_similar_problems": "knowledge:read",
    "get_problem_detail": "problem:read",
    "get_problem_difficulty_stats": "analytics:read",
    "get_student_activity": "analytics:read",
    "get_class_statistics": "analytics:read",
    "get_agent_trace": "trace:read",
    "get_student_summary": "student:read",
    "execute_code": "code:execute",
    "save_generated_problem": "problem:write",
}


def normalize_scopes(scopes: list[str] | None) -> list[str] | None:
    if scopes is None:
        return None
    normalized = {
        LEGACY_SCOPE_TO_CANONICAL.get(scope, scope)
        for scope in scopes
    }
    return sorted(normalized)
