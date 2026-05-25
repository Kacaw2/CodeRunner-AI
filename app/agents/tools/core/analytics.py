"""Core analytics logic — no framework dependency."""


def get_problem_difficulty_stats_impl(problem_id: int, session=None) -> dict:
    from app.models.question import Question
    from app.models.submission import Submission

    try:
        if session:
            variant_ids = [
                q.id
                for q in session.query(Question)
                .filter_by(problem_id=problem_id)
                .all()
            ]
        else:
            variant_ids = [
                q.id
                for q in Question.query.filter_by(problem_id=problem_id).all()
            ]

        if not variant_ids:
            return {
                "problem_id": problem_id,
                "total_submissions": 0,
                "message": "No variants found for this problem",
            }

        if session:
            submissions = (
                session.query(Submission)
                .filter(Submission.question_id.in_(variant_ids))
                .all()
            )
        else:
            submissions = Submission.query.filter(
                Submission.question_id.in_(variant_ids)
            ).all()

        if not submissions:
            return {
                "problem_id": problem_id,
                "total_submissions": 0,
                "message": "No submissions found for this problem",
            }

        unique_students = len({s.student_id for s in submissions})
        status_counts = {}
        for s in submissions:
            status = (s.status or "UNKNOWN").upper()
            if status == "COMPLETED":
                status = "AC"
            status_counts[status] = status_counts.get(status, 0) + 1

        total = len(submissions)
        accepted = status_counts.get("AC", 0)

        students_who_passed = set()
        for s in submissions:
            if (s.status or "").upper() in ("COMPLETED", "AC"):
                students_who_passed.add(s.student_id)

        return {
            "problem_id": problem_id,
            "total_submissions": total,
            "unique_students": unique_students,
            "students_who_passed": len(students_who_passed),
            "student_pass_rate": (
                round(len(students_who_passed) / unique_students, 2)
                if unique_students > 0
                else 0
            ),
            "submission_acceptance_rate": (
                round(accepted / total, 2) if total > 0 else 0
            ),
            "status_distribution": status_counts,
            "average_attempts_per_student": (
                round(total / unique_students, 1) if unique_students > 0 else 0
            ),
        }

    except Exception as e:
        return {"error": str(e), "problem_id": problem_id}
