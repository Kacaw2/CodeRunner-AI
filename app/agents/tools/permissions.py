from app.agents.definitions import AGENT_DEFINITIONS

# Static permission overrides for per-role tool access within an agent.
# If an entry exists here it takes precedence; otherwise the tool is
# allowed for every role listed in the agent's definition.
_ROLE_OVERRIDES: dict[tuple[str, str], set[str]] = {
    # Analytics: some tools are teacher/admin only
    ("analytics", "get_student_stats"):            {"teacher", "admin"},
    ("analytics", "get_class_statistics"):          {"teacher", "admin"},

    # MCP Server tools (external clients — teacher/admin only)
    ("mcp", "search_knowledge"):              {"teacher", "admin"},
    ("mcp", "search_similar_problems"):       {"teacher", "admin"},
    ("mcp", "get_problem_detail"):            {"teacher", "admin"},
    ("mcp", "get_problem_difficulty_stats"):  {"teacher", "admin"},
    ("mcp", "get_student_activity"):            {"teacher", "admin"},
    ("mcp", "get_class_statistics"):            {"teacher", "admin"},
    ("mcp", "get_agent_trace"):               {"teacher", "admin"},
    ("mcp", "get_student_summary"):           {"teacher", "admin"},
    ("mcp", "execute_code"):                  {"teacher", "admin"},
    ("mcp", "save_generated_problem"):        {"teacher", "admin"},
    ("mcp", "check_approval"):                {"teacher", "admin"},
}


def check_tool_permission(agent_type: str, tool_name: str, user_role: str) -> bool:
    """Check whether *user_role* may invoke *tool_name* on *agent_type*.

    Resolution order:
    1. Explicit role override in _ROLE_OVERRIDES
    2. Tool must be in the agent definition's allowed_tools list,
       and user_role must be in the definition's allowed_roles.
    """
    override = _ROLE_OVERRIDES.get((agent_type, tool_name))
    if override is not None:
        return user_role in override

    defn = AGENT_DEFINITIONS.get(agent_type)
    if defn is None:
        return False

    if tool_name not in defn.allowed_tools:
        return False

    return user_role in defn.allowed_roles
