"""
Expanded analytics query tools (Phase 4, Task 19).

New tools for the Analytics agent to provide richer data analysis:
- get_student_activity: time-series activity data for a student
- get_class_statistics: aggregate statistics across a teacher's classrooms
- get_problem_difficulty_stats: per-problem success rate analysis
"""

from langchain_core.tools import tool

from app.agents.tools.core.analytics import get_problem_difficulty_stats_impl
from app.agents.tools.db_context import get_current_session


@tool
def get_student_activity(student_id: int, days: int = 30) -> dict:
    """Get a student's submission activity over time for trend analysis.

    Returns day-by-day submission counts and acceptance rates.
    Use this to identify activity patterns, streaks, and engagement trends.
    """
    from datetime import datetime, timedelta
    from app.models.submission import Submission
    from app.core.timezone import now_china

    cutoff = now_china() - timedelta(days=days)

    try:
        session = get_current_session()
        if session:
            submissions = (
                session.query(Submission)
                .filter(
                    Submission.student_id == student_id,
                    Submission.submitted_at >= cutoff,
                )
                .order_by(Submission.submitted_at.asc())
                .all()
            )
        else:
            submissions = (
                Submission.query
                .filter(
                    Submission.student_id == student_id,
                    Submission.submitted_at >= cutoff,
                )
                .order_by(Submission.submitted_at.asc())
                .all()
            )

        daily = {}
        for s in submissions:
            day_key = s.submitted_at.strftime("%Y-%m-%d") if s.submitted_at else "unknown"
            if day_key not in daily:
                daily[day_key] = {"total": 0, "accepted": 0, "errors": {}}
            daily[day_key]["total"] += 1
            status = (s.status or "").upper()
            if status in ("COMPLETED", "AC"):
                daily[day_key]["accepted"] += 1
            else:
                err_key = status or "UNKNOWN"
                daily[day_key]["errors"][err_key] = daily[day_key]["errors"].get(err_key, 0) + 1

        activity_timeline = []
        for day, stats in sorted(daily.items()):
            rate = stats["accepted"] / stats["total"] if stats["total"] > 0 else 0
            activity_timeline.append({
                "date": day,
                "submissions": stats["total"],
                "accepted": stats["accepted"],
                "acceptance_rate": round(rate, 2),
                "errors": stats["errors"],
            })

        total = len(submissions)
        accepted = sum(1 for s in submissions if (s.status or "").upper() in ("COMPLETED", "AC"))
        active_days = len(daily)

        current_streak = 0
        if activity_timeline:
            today = now_china().date()
            for i in range(len(activity_timeline) - 1, -1, -1):
                entry_date = datetime.strptime(activity_timeline[i]["date"], "%Y-%m-%d").date()
                if entry_date == today - timedelta(days=current_streak):
                    current_streak += 1
                else:
                    break

        return {
            "student_id": student_id,
            "period_days": days,
            "total_submissions": total,
            "total_accepted": accepted,
            "overall_acceptance_rate": round(accepted / total, 2) if total > 0 else 0,
            "active_days": active_days,
            "current_streak_days": current_streak,
            "daily_activity": activity_timeline,
        }

    except Exception as e:
        return {"error": str(e), "student_id": student_id}


@tool
def get_class_statistics(teacher_id: int) -> dict:
    """Get aggregate statistics across all classrooms managed by this teacher.

    Returns per-classroom summaries including student counts, submission stats,
    and class-level acceptance rates. Teacher/admin only.
    """
    from app.models.classroom import Classroom, Enrollment
    from app.models.submission import Submission

    try:
        session = get_current_session()
        if session:
            classrooms = session.query(Classroom).filter_by(teacher_id=teacher_id).all()
        else:
            classrooms = Classroom.query.filter_by(teacher_id=teacher_id).all()

        if not classrooms:
            return {"teacher_id": teacher_id, "classrooms": [], "message": "No classrooms found"}

        result_classrooms = []
        total_students = 0
        total_submissions = 0
        total_accepted = 0

        for classroom in classrooms:
            if session:
                enrollments = session.query(Enrollment).filter_by(classroom_id=classroom.id).all()
            else:
                enrollments = Enrollment.query.filter_by(classroom_id=classroom.id).all()
            student_ids = [e.student_id for e in enrollments]

            if not student_ids:
                result_classrooms.append({
                    "classroom_id": classroom.id,
                    "name": classroom.name,
                    "student_count": 0,
                    "total_submissions": 0,
                    "acceptance_rate": 0,
                })
                continue

            if session:
                submissions = (
                    session.query(Submission)
                    .filter(Submission.student_id.in_(student_ids))
                    .all()
                )
            else:
                submissions = (
                    Submission.query
                    .filter(Submission.student_id.in_(student_ids))
                    .all()
                )

            sub_count = len(submissions)
            accepted_count = sum(
                1 for s in submissions if (s.status or "").upper() in ("COMPLETED", "AC")
            )

            result_classrooms.append({
                "classroom_id": classroom.id,
                "name": classroom.name,
                "student_count": len(student_ids),
                "total_submissions": sub_count,
                "accepted_submissions": accepted_count,
                "acceptance_rate": round(accepted_count / sub_count, 2) if sub_count > 0 else 0,
            })

            total_students += len(student_ids)
            total_submissions += sub_count
            total_accepted += accepted_count

        return {
            "teacher_id": teacher_id,
            "classroom_count": len(classrooms),
            "total_students": total_students,
            "total_submissions": total_submissions,
            "overall_acceptance_rate": round(total_accepted / total_submissions, 2) if total_submissions > 0 else 0,
            "classrooms": result_classrooms,
        }

    except Exception as e:
        return {"error": str(e), "teacher_id": teacher_id}


@tool
def get_problem_difficulty_stats(problem_id: int) -> dict:
    """Get success rate and error distribution for a specific problem.

    Returns how many students attempted it, pass/fail rates, and common error types.
    Useful for understanding whether a problem is appropriately calibrated.
    """
    return get_problem_difficulty_stats_impl(
        problem_id, session=get_current_session()
    )
