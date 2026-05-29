"""MCP tool wrappers for analytics operations."""

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime


def register_analytics_tools(mcp: FastMCP):
    @mcp.tool(
        name="get_student_activity",
        description=(
            "Get a student's submission activity over time for trend analysis. "
            "Returns day-by-day submission counts, acceptance rates, streaks, "
            "and engagement trends."
        ),
    )
    def get_student_activity(student_id: int, days: int = 30) -> str:
        return _guarded(lambda: call_via_runtime(
            "coderunner.analytics.student_activity",
            {"student_id": student_id, "days": days},
        ))

    @mcp.tool(
        name="get_class_statistics",
        description=(
            "Get aggregate statistics across all classrooms managed by a "
            "teacher. Returns per-classroom summaries including student counts, "
            "submission stats, and acceptance rates."
        ),
    )
    def get_class_statistics(teacher_id: int) -> str:
        return _guarded(lambda: call_via_runtime(
            "coderunner.analytics.class_statistics",
            {"teacher_id": teacher_id},
        ))
