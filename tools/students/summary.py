"""Core student summary logic — no framework dependency."""


def get_student_summary_impl(student_id: int, session=None) -> dict:
    from app.models.student_profile import StudentProfile
    from app.models.submission import Submission
    from app.models.user import User

    try:
        if session:
            user = session.get(User, student_id)
        else:
            from app.core.extensions import db as _fdb
            user = _fdb.session.get(User, student_id)

        if not user:
            return {"error": "Student not found"}

        if session:
            profile = (
                session.query(StudentProfile)
                .filter_by(student_id=student_id)
                .first()
            )
        else:
            profile = StudentProfile.query.filter_by(student_id=student_id).first()

        if session:
            submissions = (
                session.query(Submission)
                .filter_by(student_id=student_id)
                .all()
            )
        else:
            submissions = Submission.query.filter_by(student_id=student_id).all()

        total = len(submissions)
        accepted = sum(
            1 for s in submissions
            if (s.status or "").upper() in ("COMPLETED", "AC")
        )

        unique_days = len({
            s.submitted_at.strftime("%Y-%m-%d")
            for s in submissions
            if s.submitted_at
        })

        profile_dict = profile.to_dict() if profile else {}

        return {
            "student_id": student_id,
            "profile": profile_dict,
            "stats": {
                "total_submissions": total,
                "acceptance_rate": round(accepted / total, 2) if total > 0 else 0,
                "active_days": unique_days,
                "current_streak": 0,
            },
        }

    except Exception as e:
        return {"error": str(e), "student_id": student_id}
