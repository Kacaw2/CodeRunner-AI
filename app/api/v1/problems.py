from flask import g, request
from flask_smorest import Blueprint

from app.auth import optional_auth, require_teacher
from app.schemas.questions_schema import ProblemCreateIn, ProblemListResponse
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
