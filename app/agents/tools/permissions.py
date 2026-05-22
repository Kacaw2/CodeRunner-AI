TOOL_PERMISSIONS: dict[tuple[str, str], set[str]] = {
    # Tutor agent tools
    ("tutor", "execute_code"):            {"student", "teacher", "admin"},
    ("tutor", "get_question_detail"):     {"student", "teacher", "admin"},
    ("tutor", "get_student_submissions"): {"student", "teacher", "admin"},
    ("tutor", "get_submission_detail"):   {"student", "teacher", "admin"},

    # Reviewer agent tools
    ("reviewer", "execute_code"):         {"student", "teacher", "admin"},
    ("reviewer", "get_question_detail"):  {"student", "teacher", "admin"},

    # Generator agent tools (teacher/admin only)
    ("generator", "execute_code"):        {"teacher", "admin"},
    ("generator", "get_question_detail"): {"teacher", "admin"},

    # Generator knowledge tools (teacher/admin only)
    ("generator", "search_similar_questions"): {"teacher", "admin"},

    # Tutor knowledge tools
    ("tutor", "search_knowledge"):             {"student", "teacher", "admin"},
    ("tutor", "search_error_patterns"):        {"student", "teacher", "admin"},

    # Analytics agent tools
    ("analytics", "get_question_detail"):      {"student", "teacher", "admin"},
    ("analytics", "get_student_submissions"):  {"student", "teacher", "admin"},
    ("analytics", "get_submission_detail"):    {"student", "teacher", "admin"},
    ("analytics", "get_student_stats"):        {"teacher", "admin"},

    # Phase 4: Expanded analytics tools
    ("analytics", "get_student_activity"):        {"student", "teacher", "admin"},
    ("analytics", "get_class_statistics"):         {"teacher", "admin"},
    ("analytics", "get_question_difficulty_stats"):{"student", "teacher", "admin"},
}


def check_tool_permission(agent_type: str, tool_name: str, user_role: str) -> bool:
    allowed_roles = TOOL_PERMISSIONS.get((agent_type, tool_name))
    if allowed_roles is None:
        return False
    return user_role in allowed_roles
