"""AUTO-GENERATED — DO NOT EDIT BY HAND.

Generated from ai.tools.protocol.schemas.catalog.TOOL_CATALOG and
mcp_gateway.tool_map.EXTERNAL_TOOL_MAP by mcp_gateway/_codegen.py.

Run ``python -m mcp_gateway._codegen`` to regenerate. The contract test in
tests/test_mcp_gateway_catalog_contract.py fails if this file is stale.
"""

from __future__ import annotations

from mcp.server import FastMCP

from ai.mcp_gateway.middleware import _guarded, call_via_runtime, get_caller_info


def register_generated_catalog_tools(mcp: FastMCP) -> None:
    @mcp.tool(name='search_knowledge', description='Search the knowledge base for relevant learning materials.')
    def search_knowledge(query: str, owner_id: int | None = None) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.knowledge.search',
            {"query": query, "owner_id": owner_id},
        ), canonical_tool='coderunner.knowledge.search')

    @mcp.tool(name='search_similar_problems', description='Find problems similar to the query from the knowledge base.')
    def search_similar_problems(query: str, language: str = 'python', limit: int = 5) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.knowledge.search_similar_problems',
            {"query": query, "language": language, "limit": limit},
        ), canonical_tool='coderunner.knowledge.search_similar_problems')

    @mcp.tool(name='search_error_patterns', description='Search for common error patterns matching the query.')
    def search_error_patterns(query: str) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.knowledge.search_error_patterns',
            {"query": query},
        ), canonical_tool='coderunner.knowledge.search_error_patterns')

    @mcp.tool(name='get_problem_detail', description='Get the full detail of a problem including test cases.')
    def get_problem_detail(problem_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.problem.get_detail',
            {"problem_id": problem_id},
        ), canonical_tool='coderunner.problem.get_detail')

    @mcp.tool(name='list_student_submissions', description='Get recent submissions for a student, optionally filtered by question.')
    def list_student_submissions(student_id: int, question_id: int = 0, limit: int = 10) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.submission.list_for_student',
            {"student_id": student_id, "question_id": question_id, "limit": limit},
        ), canonical_tool='coderunner.submission.list_for_student')

    @mcp.tool(name='get_submission_detail', description='Get full detail of a single submission including test results.')
    def get_submission_detail(submission_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.submission.get_detail',
            {"submission_id": submission_id},
        ), canonical_tool='coderunner.submission.get_detail')

    @mcp.tool(name='get_problem_difficulty_stats', description='Get difficulty statistics for a specific problem.')
    def get_problem_difficulty_stats(problem_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.analytics.problem_difficulty',
            {"problem_id": problem_id},
        ), canonical_tool='coderunner.analytics.problem_difficulty')

    @mcp.tool(name='get_student_activity', description="Get a student's submission activity timeline.")
    def get_student_activity(student_id: int, days: int = 30) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.analytics.student_activity',
            {"student_id": student_id, "days": days},
        ), canonical_tool='coderunner.analytics.student_activity')

    @mcp.tool(name='get_student_stats', description="Get aggregated statistics for a teacher's classrooms.")
    def get_student_stats(teacher_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.analytics.student_stats',
            {"teacher_id": teacher_id},
        ), canonical_tool='coderunner.analytics.student_stats')

    @mcp.tool(name='get_class_statistics', description='Get per-classroom statistics for a teacher.')
    def get_class_statistics(teacher_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.analytics.class_statistics',
            {"teacher_id": teacher_id},
        ), canonical_tool='coderunner.analytics.class_statistics')

    @mcp.tool(name='get_agent_trace', description='Retrieve the trace of a past agent run.')
    def get_agent_trace(run_id: str) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.trace.get_agent_trace',
            {"run_id": run_id},
        ), canonical_tool='coderunner.trace.get_agent_trace')

    @mcp.tool(name='get_student_summary', description="Get a student's profile and overall stats.")
    def get_student_summary(student_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.student.get_summary',
            {"student_id": student_id},
        ), canonical_tool='coderunner.student.get_summary')

    @mcp.tool(name='execute_code', description='Execute code in a sandboxed environment.')
    def execute_code(code: str, language: str, stdin_text: str = '', expected_output: str = '') -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.code.execute',
            {"code": code, "language": language, "stdin_text": stdin_text, "expected_output": expected_output},
        ), canonical_tool='coderunner.code.execute')

    @mcp.tool(name='execute_internal', description='Execute trusted agent-authored code for self-validation (internal only).')
    def execute_internal(code: str, language: str, stdin_text: str = '', expected_output: str = '') -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.code.execute_internal',
            {"code": code, "language": language, "stdin_text": stdin_text, "expected_output": expected_output},
        ), canonical_tool='coderunner.code.execute_internal')

    @mcp.tool(name='save_generated_problem', description='Save a generated problem as a draft pending teacher review.')
    def save_generated_problem(question_data: dict) -> str:
        def _call():
            _caller = get_caller_info() or {}
            return call_via_runtime(
                'coderunner.problem.save_generated',
                {"question_data": question_data, "teacher_id": _caller.get("user_id", 0)},
            )
        return _guarded(_call, canonical_tool='coderunner.problem.save_generated')

    @mcp.tool(name='delegate', description="Delegate the conversation to another agent. Call this when a different agent would clearly handle the user's request better. Provide a concise summary so the next agent can continue without re-deriving context.")
    def delegate(target: str, reason: str, summary: str = '') -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.agent.delegate',
            {"target": target, "reason": reason, "summary": summary},
        ), canonical_tool='coderunner.agent.delegate')

    @mcp.tool(name='check_approval', description='Check the status of a pending tool approval and retrieve the result if approved.')
    def check_approval(approval_id: str) -> str:
        return _guarded(lambda: call_via_runtime(
            'coderunner.approval.check',
            {"approval_id": approval_id},
        ), canonical_tool='coderunner.approval.check')
