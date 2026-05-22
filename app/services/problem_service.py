import re
from typing import Any, Dict, Optional

from flask_smorest import abort
from sqlalchemy import func, select

from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question
from app.models.quiz import QuizProblem
from app.models.submission import Submission


LANGUAGE_ORDER = {"python": 0, "c": 1}


def slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or "problem"


class ProblemService:
    @staticmethod
    def _ordered_variants(problem: Problem):
        return sorted(
            problem.variants,
            key=lambda q: LANGUAGE_ORDER.get((q.programming_language or "").lower(), 99),
        )

    @staticmethod
    def _default_language(problem: Problem) -> Optional[str]:
        if problem.variant_for("python"):
            return "python"
        variants = ProblemService._ordered_variants(problem)
        return variants[0].programming_language if variants else None

    @staticmethod
    def is_problem_completed(student_id: int, problem_id: int) -> bool:
        variant_ids = db.session.execute(
            select(Question.id).where(Question.problem_id == problem_id)
        ).scalars().all()
        if not variant_ids:
            return False
        count = db.session.execute(
            select(func.count(Submission.id)).where(
                Submission.student_id == student_id,
                Submission.question_id.in_(variant_ids),
                Submission.status == "completed",
                Submission.score >= 100,
            )
        ).scalar()
        return bool(count)

    @staticmethod
    def list_public_problems(
        limit: int = 100,
        offset: int = 0,
        quiz_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        query = select(Problem)
        if quiz_id:
            query = (
                query.join(QuizProblem, QuizProblem.problem_id == Problem.id)
                .where(QuizProblem.quiz_id == quiz_id)
                .order_by(QuizProblem.order, Problem.id)
            )
        else:
            query = query.order_by(Problem.order, Problem.id)

        total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
        problems = db.session.execute(query.offset(offset).limit(limit)).scalars().all()

        items = []
        for problem in problems:
            variants = ProblemService._ordered_variants(problem)
            items.append({
                "id": problem.id,
                "slug": problem.slug,
                "title": problem.title,
                "description": problem.description,
                "difficulty": problem.difficulty,
                "points": problem.points,
                "order": problem.order,
                "default_language": ProblemService._default_language(problem),
                "completed": ProblemService.is_problem_completed(user_id, problem.id) if user_id else False,
                "variants": [
                    {
                        "question_id": q.id,
                        "language": q.programming_language,
                        "starter_code": q.starter_code,
                    }
                    for q in variants
                ],
            })
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def get_problem_detail(
        problem_id: int,
        language: str = "python",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        problem = Problem.query.get(problem_id)
        if not problem:
            abort(404, message="Problem not found")

        variant = problem.variant_for(language) or problem.variant_for("python")
        if not variant:
            variants = ProblemService._ordered_variants(problem)
            variant = variants[0] if variants else None
        if not variant:
            abort(404, message="No language variant available for this problem")

        has_submission = False
        if user_id:
            has_submission = db.session.execute(
                select(Submission.id)
                .where(Submission.student_id == user_id, Submission.question_id == variant.id)
                .limit(1)
            ).first() is not None

        return {
            "id": problem.id,
            "slug": problem.slug,
            "title": problem.title,
            "description": problem.description,
            "difficulty": problem.difficulty,
            "points": problem.points,
            "selected_language": variant.programming_language,
            "selected_question_id": variant.id,
            "starter_code": variant.starter_code,
            "solution": variant.solution if has_submission else None,
            "solution_explanation": variant.solution_explanation if has_submission else None,
            "variants": [
                {"language": q.programming_language, "question_id": q.id}
                for q in ProblemService._ordered_variants(problem)
            ],
            "test_cases": [
                {
                    "id": tc.id,
                    "input": tc.input,
                    "expected_output": tc.expected_output,
                    "weight": tc.weight,
                    "is_hidden": tc.is_hidden,
                }
                for tc in problem.test_cases
                if not tc.is_hidden
            ],
        }

    @staticmethod
    def create_problem(teacher_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        title = payload["title"].strip()
        base_slug = slugify(title)
        slug = base_slug
        suffix = 2
        while Problem.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        problem = Problem(
            slug=slug,
            title=title,
            description=payload.get("description", ""),
            difficulty=payload.get("difficulty", "easy"),
            points=payload.get("points", 10),
            order=payload.get("order", 1),
            created_by=teacher_id,
        )
        db.session.add(problem)
        db.session.flush()

        variants = [
            (
                "python",
                payload.get("python_starter_code", ""),
                payload.get("python_solution", ""),
                payload.get("python_solution_explanation", ""),
            ),
            (
                "c",
                payload.get("c_starter_code", ""),
                payload.get("c_solution", ""),
                payload.get("c_solution_explanation", ""),
            ),
        ]

        created_any_variant = False
        for language, starter_code, solution, explanation in variants:
            if language == "python" or starter_code or solution or explanation:
                db.session.add(
                    Question(
                        problem_id=problem.id,
                        programming_language=language,
                        starter_code=starter_code,
                        solution=solution,
                        solution_explanation=explanation,
                    )
                )
                created_any_variant = True

        if not created_any_variant:
            db.session.add(Question(problem_id=problem.id, programming_language="python"))

        quiz_id = payload.get("quiz_id")
        if quiz_id:
            db.session.add(
                QuizProblem(
                    quiz_id=quiz_id,
                    problem_id=problem.id,
                    order=payload.get("order", 1),
                    points=payload.get("points", 10),
                )
            )

        db.session.commit()
        return ProblemService.get_problem_detail(problem.id, language="python", user_id=None)
