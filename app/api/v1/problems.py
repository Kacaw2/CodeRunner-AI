from flask import g, request
from flask_smorest import Blueprint

from app.auth import optional_auth, require_teacher
from app.schemas.questions_schema import IdOut, ProblemCreateIn, ProblemListResponse, TestCaseIn
from app.services.problem_service import ProblemService


blp = Blueprint("problems", __name__, description="Problem APIs", url_prefix="/api/v1")


@blp.get("/problems")
@blp.response(200, ProblemListResponse)
@optional_auth
def list_problems():
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    quiz_id = request.args.get("quiz_id", type=int)
    current_user = getattr(g, "current_user", None)
    user_id = current_user.id if current_user else None
    return ProblemService.list_public_problems(
        limit=limit,
        offset=offset,
        quiz_id=quiz_id,
        user_id=user_id,
    )


@blp.get("/teacher/problems")
@require_teacher
def list_teacher_problems():
    quiz_id = request.args.get("quiz_id", type=int)
    created_by_me = request.args.get("created_by_me", "").lower() == "true"
    return ProblemService.list_teacher_problems(
        teacher_id=g.current_user.id,
        quiz_id=quiz_id,
        created_by_me=created_by_me,
    )


@blp.get("/problems/<int:problem_id>")
@optional_auth
def get_problem(problem_id):
    language = request.args.get("language", "python", type=str)
    current_user = getattr(g, "current_user", None)
    user_id = current_user.id if current_user else None
    return ProblemService.get_problem_detail(problem_id, language=language, user_id=user_id)


@blp.post("/problems")
@blp.arguments(ProblemCreateIn)
@require_teacher
def create_problem(payload):
    return ProblemService.create_problem(g.current_user.id, payload), 201


@blp.get("/problems/<int:problem_id>/manage")
@require_teacher
def get_problem_for_teacher(problem_id):
    return ProblemService.get_teacher_problem_detail(problem_id, g.current_user.id)


@blp.patch("/problems/<int:problem_id>")
@require_teacher
def update_problem(problem_id):
    return ProblemService.update_problem(g.current_user.id, problem_id, request.get_json() or {})


@blp.delete("/problems/<int:problem_id>")
@blp.response(200, IdOut)
@require_teacher
def delete_problem(problem_id):
    deleted_id = ProblemService.delete_problem(g.current_user.id, problem_id)
    return {"id": deleted_id}


@blp.post("/problems/<int:problem_id>/test-cases")
@blp.arguments(TestCaseIn)
@require_teacher
def add_problem_test_case(payload, problem_id):
    return ProblemService.add_test_case(g.current_user.id, problem_id, payload), 201

