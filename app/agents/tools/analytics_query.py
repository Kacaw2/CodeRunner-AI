"""
Expanded analytics query tools (Phase 4, Task 19).

New tools for the Analytics agent to provide richer data analysis:
- get_student_activity: time-series activity data for a student
- get_class_statistics: aggregate statistics across a teacher's classrooms
- get_problem_difficulty_stats: per-problem success rate analysis
"""

from langchain_core.tools import tool

from app.agents.tools.core.analytics import (
    get_student_activity_impl,
    get_class_statistics_impl,
    get_problem_difficulty_stats_impl,
)
from app.agents.tools.db_context import get_current_session


@tool
def get_student_activity(student_id: int, days: int = 30) -> dict:
    """Get a student's submission activity over time for trend analysis.

    Returns day-by-day submission counts and acceptance rates.
    Use this to identify activity patterns, streaks, and engagement trends.
    """
    return get_student_activity_impl(
        student_id, days=days, session=get_current_session()
    )


@tool
def get_class_statistics(teacher_id: int) -> dict:
    """Get aggregate statistics across all classrooms managed by this teacher.

    Returns per-classroom summaries including student counts, submission stats,
    and class-level acceptance rates. Teacher/admin only.
    """
    return get_class_statistics_impl(
        teacher_id, session=get_current_session()
    )


@tool
def get_problem_difficulty_stats(problem_id: int) -> dict:
    """Get success rate and error distribution for a specific problem.

    Returns how many students attempted it, pass/fail rates, and common error types.
    Useful for understanding whether a problem is appropriately calibrated.
    """
    return get_problem_difficulty_stats_impl(
        problem_id, session=get_current_session()
    )
