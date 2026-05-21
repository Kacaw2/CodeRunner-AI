from langchain_core.tools import tool


@tool
def get_student_stats(teacher_id: int) -> dict:
    """Get aggregated statistics for a teacher's classroom."""
    from app.services.teacher_stats_service import TeacherStatsService
    return TeacherStatsService.get_teacher_stats(teacher_id)
