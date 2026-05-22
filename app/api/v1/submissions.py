# app/api/v1/submissions.py
from flask import g, request
from flask_smorest import Blueprint

from app.auth import require_auth, require_student
from app.schemas.submissions_schema import (
    SubmitIn, SubmitOut,
    MySubmissionsOut, SubmissionDetailOut
)
from app.schemas.questions_schema import ProblemSubmitIn
from app.services.submission_service import SubmissionService


blp = Blueprint(
    "submissions",
    __name__,
    description="Submission APIs",
    url_prefix="/api/v1"
)


@blp.post("/questions/<int:question_id>/submit")
@blp.arguments(SubmitIn)
@blp.response(201, SubmitOut)
@require_student
def submit_code(payload, question_id):
    """
    Submit code and execute tests
    
    Requires student permission
    
    Request Body:
    - code: Code to submit
    - time_limit_sec: Time limit in seconds (default: 2.0)
    
    Returns:
    - id: Submission ID
    - status: Status (completed/error)
    - score: Score (0-100)
    - cases: List of test case results
    """
    current_user = g.current_user
    
    result = SubmissionService.submit_code(
        student_id=current_user.id,
        question_id=question_id,
        code=payload["code"],
        time_limit_sec=payload.get("time_limit_sec", 2.0)
    )
    
    return result


@blp.post("/problems/<int:problem_id>/submit")
@blp.arguments(ProblemSubmitIn)
@blp.response(201, SubmitOut)
@require_student
def submit_problem_code(payload, problem_id):
    current_user = g.current_user
    return SubmissionService.submit_problem_code(
        student_id=current_user.id,
        problem_id=problem_id,
        language=payload.get("language", "python"),
        code=payload["code"],
        time_limit_sec=payload.get("time_limit_sec", 2.0),
    )


@blp.get("/submissions/mine")
@blp.response(200, MySubmissionsOut)
@require_student
def my_submissions():
    """
    Get submission list for current student
    
    Requires student permission
    
    Query Parameters:
    - question_id: Optional, filter submissions for specific question
    - limit: Optional, number of submissions to return (default: 50)
    
    Returns recent submission records
    """
    current_user = g.current_user
    
    # Support filtering by question_id
    question_id = request.args.get('question_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    
    result = SubmissionService.get_student_submissions(
        student_id=current_user.id,
        question_id=question_id,
        limit=limit,
        offset=0
    )
    
    return result


@blp.get("/submissions/<int:submission_id>")
@blp.response(200, SubmissionDetailOut)
@require_auth
def submission_detail(submission_id):
    """
    Get submission details
    
    Students can only view their own submissions
    Teachers can view all submissions
    
    Returns:
    - Complete submission information
    - Code
    - All test case execution results
    """
    current_user = g.current_user
    user_role = current_user.role.value if hasattr(current_user.role, 'value') else current_user.role
    
    result = SubmissionService.get_submission_detail(
        submission_id=submission_id,
        user_id=current_user.id,
        user_role=user_role
    )
    
    return result


@blp.get("/submissions/check")
@blp.response(200)
@require_student
def check_submissions():
    """
    Check if user has submission records for a specific question
    
    Query Parameters:
    - question_id: Required, question ID
    
    Returns:
    {
        "items": [...],  # Submission list (simplified)
        "submission_count": count
    }
    """
    current_user = g.current_user
    question_id = request.args.get('question_id', type=int)
    
    if not question_id:
        return {"error": "question_id is required"}, 400
    
    # Get submission history
    result = SubmissionService.get_student_submissions(
        student_id=current_user.id,
        question_id=question_id,
        limit=10, 
        offset=0
    )
    
    return {
        "items": result.get("items", []),
        "submission_count": result.get("total", 0)
    }
