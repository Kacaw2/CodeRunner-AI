"""Bootstrap — register all tool handlers with the ToolRuntime.

Called once at process startup. Wires core implementation functions
to the MCP transport and registers descriptors in the registry.
"""

from __future__ import annotations

import logging

from tools.protocol.runtime import ToolRuntime, set_tool_runtime
from tools.protocol.registry import ToolRegistry
from tools.protocol.schemas.catalog import TOOL_CATALOG
from tools.protocol.transports.inproc import LocalTransport

logger = logging.getLogger(__name__)


def bootstrap_tool_runtime(*, session_factory=None) -> ToolRuntime:
    """Create and install the global ToolRuntime with all handlers."""
    registry = ToolRegistry()
    transport = LocalTransport()

    for name, descriptor in TOOL_CATALOG.items():
        registry.register(descriptor)

    _register_db_handlers(transport, session_factory)
    _register_code_handlers(transport)
    _register_knowledge_handlers(transport)
    _register_analytics_handlers(transport, session_factory)

    runtime = ToolRuntime(registry=registry, transport=transport)
    set_tool_runtime(runtime)

    logger.info("MCP ToolRuntime bootstrapped with %d tools", len(registry))
    return runtime


def _register_db_handlers(transport: LocalTransport, session_factory) -> None:
    from tools.problems.queries import get_problem_detail_impl
    from tools.students.summary import get_student_summary_impl
    from tools.problems.write import save_generated_problem_impl

    def _get_session():
        if session_factory:
            return session_factory()
        return None

    def problem_get_detail(problem_id: int, **_kw) -> dict:
        return get_problem_detail_impl(problem_id, session=_get_session())

    def submission_list(student_id: int, question_id: int = 0, limit: int = 10, **_kw) -> dict:
        from app.services.submission_service import SubmissionService
        return SubmissionService.get_student_submissions(
            student_id=student_id,
            question_id=question_id or None,
            limit=limit,
        )

    def submission_detail(submission_id: int, _caller_user_id: int = 0, _caller_role: str = "student", **_kw) -> dict:
        from app.services.submission_service import SubmissionService
        return SubmissionService.get_submission_detail(
            submission_id=submission_id,
            user_id=_caller_user_id,
            user_role=_caller_role,
        )

    def student_summary(student_id: int, **_kw) -> dict:
        return get_student_summary_impl(student_id, session=_get_session())

    def save_generated(question_data: dict, teacher_id: int, **_kw) -> dict:
        return save_generated_problem_impl(question_data, teacher_id, session=_get_session())

    transport.register_handler("coderunner.problem.get_detail", problem_get_detail)
    transport.register_handler("coderunner.submission.list_for_student", submission_list)
    transport.register_handler("coderunner.submission.get_detail", submission_detail)
    transport.register_handler("coderunner.student.get_summary", student_summary)
    transport.register_handler("coderunner.problem.save_generated", save_generated)


def _register_code_handlers(transport: LocalTransport) -> None:
    from tools.code.executor import execute_code_impl

    def execute_code(code: str, language: str = "python", stdin_text: str = "", expected_output: str = "", **_kw) -> dict:
        return execute_code_impl(code, language, stdin_text, expected_output)

    transport.register_handler("coderunner.code.execute", execute_code)


def _register_knowledge_handlers(transport: LocalTransport) -> None:
    from tools.knowledge_search.search import (
        search_knowledge_impl,
        search_similar_problems_impl,
        search_error_patterns_impl,
    )

    def search_knowledge(query: str, owner_id: int = None, **_kw) -> dict:
        return search_knowledge_impl(query, owner_id)

    def search_similar(query: str, language: str = "python", limit: int = 5, **_kw) -> dict:
        return search_similar_problems_impl(query, language, limit)

    def search_errors(query: str, **_kw) -> dict:
        return search_error_patterns_impl(query)

    transport.register_handler("coderunner.knowledge.search", search_knowledge)
    transport.register_handler("coderunner.knowledge.search_similar_problems", search_similar)
    transport.register_handler("coderunner.knowledge.search_error_patterns", search_errors)


def _register_analytics_handlers(transport: LocalTransport, session_factory) -> None:
    from tools.analytics.queries import (
        get_student_activity_impl,
        get_class_statistics_impl,
        get_problem_difficulty_stats_impl,
    )
    from tools.traces.queries import get_agent_trace_impl

    def _get_session():
        if session_factory:
            return session_factory()
        return None

    def student_activity(student_id: int, days: int = 30, **_kw) -> dict:
        return get_student_activity_impl(student_id, days, session=_get_session())

    def student_stats(teacher_id: int, **_kw) -> dict:
        from app.services.teacher_stats_service import TeacherStatsService
        return TeacherStatsService.get_teacher_stats(teacher_id)

    def class_statistics(teacher_id: int, **_kw) -> dict:
        return get_class_statistics_impl(teacher_id, session=_get_session())

    def problem_difficulty(problem_id: int, **_kw) -> dict:
        return get_problem_difficulty_stats_impl(problem_id, session=_get_session())

    def agent_trace(run_id: str, **_kw) -> dict:
        return get_agent_trace_impl(run_id, session=_get_session())

    transport.register_handler("coderunner.analytics.student_activity", student_activity)
    transport.register_handler("coderunner.analytics.student_stats", student_stats)
    transport.register_handler("coderunner.analytics.class_statistics", class_statistics)
    transport.register_handler("coderunner.analytics.problem_difficulty", problem_difficulty)
    transport.register_handler("coderunner.trace.get_agent_trace", agent_trace)
