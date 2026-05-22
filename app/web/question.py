"""Problem runner page."""
from flask import Blueprint, abort, render_template, request

from app.models.problem import Problem


question_bp = Blueprint("question", __name__)


@question_bp.route("/problem/<int:problem_id>")
def run_problem(problem_id):
    problem = Problem.query.get(problem_id)
    if not problem:
        abort(404, description="Problem not found")

    selected_language = request.args.get("language", "python")
    return render_template(
        "problem_runner.html",
        problem=problem,
        selected_language=selected_language,
    )
