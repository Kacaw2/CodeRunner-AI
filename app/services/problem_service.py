import re
from typing import Any, Dict, Optional

from flask_smorest import abort
from sqlalchemy import func, select

from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.quiz import QuizProblem
from app.models.submission import Submission


LANGUAGE_ORDER = {"python": 0, "c": 1}


def slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or "problem"


class ProblemService:
    @staticmethod
    def _variant_summary(question: Question) -> Dict[str, Any]:
        return {
            "question_id": question.id,
            "language": question.programming_language,
            "starter_code": question.starter_code or "",
            "solution": question.solution or "",
            "solution_explanation": question.solution_explanation or "",
        }

    @staticmethod
    def teacher_owns_problem(teacher_id: int, problem_id: int) -> bool:
        problem = Problem.query.get(problem_id)
        if not problem:
            return False
        if problem.created_by == teacher_id:
            return True
        return any(qp.quiz and qp.quiz.created_by == teacher_id for qp in problem.quiz_associations)

    @staticmethod
    def verify_teacher_owns_problem(teacher_id: int, problem_id: int) -> Problem:
        problem = Problem.query.get(problem_id)
        if not problem:
            abort(404, message="Problem not found")
        if not ProblemService.teacher_owns_problem(teacher_id, problem_id):
            abort(403, message="You don't own this problem")
        return problem

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
    def list_teacher_problems(
        teacher_id: int,
        quiz_id: Optional[int] = None,
        created_by_me: bool = False,
    ) -> Dict[str, Any]:
        query = select(Problem)
        if quiz_id:
            quiz_ids = db.session.execute(
                select(QuizProblem.problem_id).where(QuizProblem.quiz_id == quiz_id)
            ).scalars().all()
            if not quiz_ids:
                return {"items": [], "total": 0}
            query = query.where(Problem.id.in_(quiz_ids))
        else:
            query = query.where(Problem.created_by == teacher_id)

        if created_by_me:
            query = query.where(Problem.created_by == teacher_id)

        problems = db.session.execute(query.order_by(Problem.order, Problem.id)).scalars().all()
        items = []
        for problem in problems:
            quiz_ids = [qp.quiz_id for qp in problem.quiz_associations]
            items.append({
                "id": problem.id,
                "title": problem.title,
                "description": problem.description,
                "difficulty": problem.difficulty,
                "order": problem.order,
                "points": problem.points,
                "quiz_ids": quiz_ids,
                "creator": {"id": problem.created_by, "name": "You" if problem.created_by == teacher_id else "Teacher"},
                "test_case_count": len(problem.test_cases),
                "variants": [
                    {
                        "question_id": q.id,
                        "language": q.programming_language,
                    }
                    for q in ProblemService._ordered_variants(problem)
                ],
            })
        return {"items": items, "total": len(items)}

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
    def get_teacher_problem_detail(problem_id: int, teacher_id: int) -> Dict[str, Any]:
        problem = ProblemService.verify_teacher_owns_problem(teacher_id, problem_id)
        quiz_info = None
        if problem.quiz_associations:
            qp = sorted(problem.quiz_associations, key=lambda assoc: assoc.order)[0]
            quiz_info = {"id": qp.quiz_id, "title": qp.quiz.title if qp.quiz else None}

        return {
            "id": problem.id,
            "slug": problem.slug,
            "title": problem.title,
            "description": problem.description,
            "difficulty": problem.difficulty,
            "order": problem.order,
            "points": problem.points,
            "created_at": problem.created_at.isoformat() if problem.created_at else None,
            "updated_at": problem.updated_at.isoformat() if problem.updated_at else None,
            "quiz": quiz_info,
            "variants": [
                ProblemService._variant_summary(q)
                for q in ProblemService._ordered_variants(problem)
            ],
            "test_cases": [
                {
                    "id": tc.id,
                    "problem_id": tc.problem_id,
                    "input": tc.input,
                    "expected_output": tc.expected_output,
                    "weight": tc.weight,
                    "is_hidden": tc.is_hidden,
                }
                for tc in problem.test_cases
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

    @staticmethod
    def update_problem(teacher_id: int, problem_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        problem = ProblemService.verify_teacher_owns_problem(teacher_id, problem_id)

        for field in ("title", "description", "difficulty", "points", "order"):
            if field in payload:
                value = payload[field]
                if field == "title":
                    value = (value or "").strip()
                    if not value:
                        abort(400, message="Title is required")
                setattr(problem, field, value)

        variant_payloads = {
            "python": {
                "starter_code": payload.get("python_starter_code"),
                "solution": payload.get("python_solution"),
                "solution_explanation": payload.get("python_solution_explanation"),
            },
            "c": {
                "starter_code": payload.get("c_starter_code"),
                "solution": payload.get("c_solution"),
                "solution_explanation": payload.get("c_solution_explanation"),
            },
        }

        for language, values in variant_payloads.items():
            if not any(v is not None for v in values.values()):
                continue
            variant = problem.variant_for(language)
            if not variant:
                variant = Question(problem_id=problem.id, programming_language=language)
                db.session.add(variant)
            for field, value in values.items():
                if value is not None:
                    setattr(variant, field, value)

        db.session.commit()
        return ProblemService.get_teacher_problem_detail(problem.id, teacher_id)

    @staticmethod
    def delete_problem(teacher_id: int, problem_id: int) -> int:
        problem = ProblemService.verify_teacher_owns_problem(teacher_id, problem_id)
        db.session.delete(problem)
        db.session.commit()
        return problem_id

    @staticmethod
    def add_test_case(teacher_id: int, problem_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        problem = ProblemService.verify_teacher_owns_problem(teacher_id, problem_id)
        if "input" not in payload:
            abort(400, message="'input' field is required")
        expected = payload.get("expected", payload.get("expected_output"))
        if expected is None:
            abort(400, message="'expected' field is required")

        testcase = TestCase(
            problem_id=problem.id,
            input=str(payload["input"]),
            expected_output=str(expected),
            is_hidden=bool(payload.get("is_hidden", False)),
            weight=float(payload.get("weight", 1.0)),
        )
        db.session.add(testcase)
        db.session.commit()
        return {
            "id": testcase.id,
            "problem_id": testcase.problem_id,
            "input": testcase.input,
            "expected_output": testcase.expected_output,
            "expected": testcase.expected_output,
            "is_hidden": testcase.is_hidden,
            "weight": testcase.weight,
        }

    @staticmethod
    def delete_test_case(teacher_id: int, tc_id: int) -> int:
        testcase = TestCase.query.get(tc_id)
        if not testcase:
            abort(404, message="Test case not found")
        ProblemService.verify_teacher_owns_problem(teacher_id, testcase.problem_id)
        db.session.delete(testcase)
        db.session.commit()
        return tc_id
