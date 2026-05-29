"""MCP tool wrappers for submission read operations."""

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime
from mcp_gateway.tool_map import EXTERNAL_TOOL_MAP


def register_submission_tools(mcp: FastMCP):
    @mcp.tool(
        name="list_student_submissions",
        description=(
            "List recent submissions for a student, optionally filtered by "
            "question. Returns submission summaries with status, language, "
            "score, and timestamps."
        ),
    )
    def list_student_submissions(
        student_id: int, question_id: int = 0, limit: int = 10
    ) -> str:
        return _guarded(lambda: call_via_runtime(
            EXTERNAL_TOOL_MAP["list_student_submissions"],
            {"student_id": student_id, "question_id": question_id, "limit": limit},
        ))

    @mcp.tool(
        name="get_submission_detail",
        description=(
            "Get full detail of a single submission including code, test "
            "results, and error output. Access is scoped to the caller's role."
        ),
    )
    def get_submission_detail(submission_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            EXTERNAL_TOOL_MAP["get_submission_detail"],
            {"submission_id": submission_id},
        ))
