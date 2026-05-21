from langchain_core.tools import tool


@tool
def get_student_submissions(student_id: int, question_id: int = 0, limit: int = 10) -> dict:
    """Get recent submissions for a student, optionally filtered by question."""
    from app.services.submission_service import SubmissionService
    return SubmissionService.get_student_submissions(
        student_id=student_id,
        question_id=question_id or None,
        limit=limit,
    )


@tool
def get_submission_detail(submission_id: int, user_id: int, user_role: str = "student") -> dict:
    """Get full detail of a single submission including test results."""
    from app.services.submission_service import SubmissionService
    return SubmissionService.get_submission_detail(
        submission_id=submission_id,
        user_id=user_id,
        user_role=user_role,
    )
