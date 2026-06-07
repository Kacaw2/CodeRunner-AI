"""External FastMCP tool names mapped to canonical ToolRuntime tool names.

Single source of truth for the gateway surface. Handlers and the catalog
contract test both import EXTERNAL_TOOL_MAP so the external names and their
canonical targets cannot drift apart.
"""

EXTERNAL_TOOL_MAP: dict[str, str] = {
    "search_knowledge": "coderunner.knowledge.search",
    "search_similar_problems": "coderunner.knowledge.search_similar_problems",
    "search_error_patterns": "coderunner.knowledge.search_error_patterns",
    "get_problem_detail": "coderunner.problem.get_detail",
    "list_student_submissions": "coderunner.submission.list_for_student",
    "get_submission_detail": "coderunner.submission.get_detail",
    "get_problem_difficulty_stats": "coderunner.analytics.problem_difficulty",
    "get_student_activity": "coderunner.analytics.student_activity",
    "get_student_stats": "coderunner.analytics.student_stats",
    "get_class_statistics": "coderunner.analytics.class_statistics",
    "get_agent_trace": "coderunner.trace.get_agent_trace",
    "get_student_summary": "coderunner.student.get_summary",
    "execute_code": "coderunner.code.execute",
    # Internal-only (descriptor internal_only=True): registered on the surface so
    # agent_host callers reach it via the gateway, but the guard rejects any
    # external_client regardless of scope.
    "execute_internal": "coderunner.code.execute_internal",
    "save_generated_problem": "coderunner.problem.save_generated",
    "delegate": "coderunner.agent.delegate",
    "check_approval": "coderunner.approval.check",
}
