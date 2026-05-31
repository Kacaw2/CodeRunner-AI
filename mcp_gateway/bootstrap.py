"""Bootstrap — register all tool handlers with the ToolRuntime.

Called once at process startup. Wires core implementation functions
to the MCP transport and registers descriptors in the registry.
"""

from __future__ import annotations

import logging
import uuid

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
    _register_approval_handlers(transport, registry)

    _assert_rbac_consistent(registry)
    runtime = ToolRuntime(
        registry=registry,
        transport=transport,
        approval_store=_DbApprovalStore(session_factory),
    )
    set_tool_runtime(runtime)

    logger.info("MCP ToolRuntime bootstrapped with %d tools", len(registry))
    return runtime


class _DbApprovalStore:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def create(self, descriptor, caller, args: dict) -> str:
        if self._session_factory is None:
            return ""

        from app.core.timezone import now_china
        from core.db.models.mcp_approval import McpToolApproval

        session = self._session_factory()
        approval_id = str(uuid.uuid4())
        try:
            approval = McpToolApproval(
                id=approval_id,
                api_key_id=caller.api_key_id,
                user_id=caller.user_id,
                tool_name=descriptor.name,
                tool_args=args,
                risk_level=descriptor.risk_level.value,
                status="pending",
                expires_at=McpToolApproval.default_expiry(),
                created_at=now_china(),
            )
            session.add(approval)
            session.commit()
            return approval_id
        finally:
            close = getattr(session, "close", None)
            if close:
                close()


def _assert_rbac_consistent(registry: ToolRegistry) -> None:
    from core.definitions import AGENT_DEFINITIONS

    known = {descriptor.name for descriptor in registry.list_tools()}
    for agent, definition in AGENT_DEFINITIONS.items():
        missing = set(definition.allowed_tools) - known
        if missing:
            raise RuntimeError(
                f"Agent '{agent}' references unknown tools: {sorted(missing)}"
            )


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
        from mcp_gateway.middleware.sanitizer import sanitize_student_summary

        raw = get_student_summary_impl(student_id, session=_get_session())
        if "error" in raw:
            return raw
        return sanitize_student_summary(student_id, raw["profile"], raw["stats"])

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
        from mcp_gateway.middleware.sanitizer import sanitize_agent_trace

        raw = get_agent_trace_impl(run_id, session=_get_session())
        if "error" in raw:
            return raw
        return sanitize_agent_trace(raw["run"], raw["steps"])

    transport.register_handler("coderunner.analytics.student_activity", student_activity)
    transport.register_handler("coderunner.analytics.student_stats", student_stats)
    transport.register_handler("coderunner.analytics.class_statistics", class_statistics)
    transport.register_handler("coderunner.analytics.problem_difficulty", problem_difficulty)
    transport.register_handler("coderunner.trace.get_agent_trace", agent_trace)


def _approved_caller_context(approval):
    """Rebuild the trusted CallerContext from the stored approval.

    Identity comes only from the approval row (user_id + the requester's
    DB role), never from the LLM-supplied tool_args.
    """
    from core.auth.context import CallerContext

    role = "student"
    requester = getattr(approval, "requester", None)
    if requester is not None and getattr(requester, "role", None) is not None:
        role = getattr(requester.role, "value", requester.role)

    return CallerContext(
        user_id=approval.user_id or 0,
        role=role,
        api_key_id=approval.api_key_id,
    )


def _execute_approved_tool(approval, *, transport, registry) -> dict:
    """Re-execute an approved high-risk tool via its registered handler.

    Dispatch is descriptor-driven: any tool present in the catalog and
    transport runs without a per-tool branch here. Identity fields in the
    stored args are overwritten with the trusted approval identity.
    """
    from tools.protocol.runtime import ToolRuntime
    from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP

    raw_name = approval.tool_name
    tool_name = EXTERNAL_TOOL_MAP.get(raw_name, raw_name)

    descriptor = registry.get(tool_name)
    if descriptor is None or not transport.has_handler(tool_name):
        logger.error("approved tool has no registered handler: name=%s", raw_name)
        return {"error": f"Unknown high-risk tool: {raw_name}"}

    # Registered handlers manage their own DB session (via session_factory),
    # exactly as on the live call path — no session is threaded in here.
    args = ToolRuntime._sanitize_args(approval.tool_args or {}, _approved_caller_context(approval))

    try:
        return transport.invoke(tool_name, args)
    except Exception as exc:  # noqa: BLE001 — surface as tool error, not crash
        logger.exception("approved tool execution failed: tool=%s", tool_name)
        return {"error": f"Tool execution failed: {exc}"}


def _register_approval_handlers(transport: LocalTransport, registry: ToolRegistry) -> None:
    from core.db.session import get_session
    from core.db.models.mcp_approval import McpToolApproval

    def approval_check(approval_id: str, **_kw) -> dict:
        session = get_session()
        try:
            approval = session.get(McpToolApproval, approval_id)
            if not approval:
                return {"status": "not_found", "message": "Approval not found"}

            approval.check_expiration()

            if approval.status == "approved":
                if approval.result is None:
                    approval.result = _execute_approved_tool(
                        approval, transport=transport, registry=registry
                    )
                    approval.status = "executed"
                    session.commit()
                return {"status": "executed", "result": approval.result}

            if approval.status == "executed":
                return {"status": "executed", "result": approval.result}

            if approval.status == "rejected":
                session.commit()
                return {"status": "rejected", "reason": approval.review_notes or ""}

            if approval.status == "expired":
                session.commit()
                return {"status": "expired", "message": "审批已超时。请重新发起工具调用。"}

            session.commit()
            return {"status": "pending", "message": "等待教师审批"}
        finally:
            session.close()

    transport.register_handler("coderunner.approval.check", approval_check)
