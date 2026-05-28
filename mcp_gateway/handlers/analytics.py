"""MCP tool wrappers for analytics operations."""

import json

from mcp.server import FastMCP

from tools.analytics.queries import (
    get_student_activity_impl,
    get_class_statistics_impl,
)
from core.db.session import get_session
from mcp_gateway.middleware import run_mcp_guard


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
        args = {"student_id": student_id, "days": days}
        guard = run_mcp_guard("get_student_activity", args)
        if guard.rejected:
            return guard.error_json
        session = get_session()
        try:
            result = get_student_activity_impl(
                student_id, days=days, session=session
            )
            guard.record_success("get_student_activity", args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            guard.record_error("get_student_activity", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()

    @mcp.tool(
        name="get_class_statistics",
        description=(
            "Get aggregate statistics across all classrooms managed by a "
            "teacher. Returns per-classroom summaries including student counts, "
            "submission stats, and acceptance rates."
        ),
    )
    def get_class_statistics(teacher_id: int) -> str:
        args = {"teacher_id": teacher_id}
        guard = run_mcp_guard("get_class_statistics", args)
        if guard.rejected:
            return guard.error_json
        session = get_session()
        try:
            result = get_class_statistics_impl(
                teacher_id, session=session
            )
            guard.record_success("get_class_statistics", args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            guard.record_error("get_class_statistics", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()
