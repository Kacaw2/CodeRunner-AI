from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question
from app.models.submission import Submission
from app.models.user import User, UserRole
from app.services.problem_service import ProblemService


def test_problem_list_contains_variants_and_default_python(app, db_session):
    with app.app_context():
        teacher = User(
            username="teacher_problem_service",
            password="hashed",
            email="teacher_ps@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add(teacher)
        db.session.flush()

        problem = Problem(slug="service-two-sum", title="Two Sum", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        db.session.add_all([
            Question(problem_id=problem.id, programming_language="c", starter_code="c", solution="c"),
            Question(problem_id=problem.id, programming_language="python", starter_code="py", solution="py"),
        ])
        db.session.commit()

        result = ProblemService.list_public_problems()
        item = next(p for p in result["items"] if p["id"] == problem.id)
        assert item["default_language"] == "python"
        assert [v["language"] for v in item["variants"]] == ["python", "c"]


def test_problem_completed_when_any_variant_has_accepted_submission(app, db_session):
    with app.app_context():
        student = User(
            username="student_done",
            password="hashed",
            email="student_done@example.com",
            role=UserRole.STUDENT,
        )
        teacher = User(
            username="teacher_done",
            password="hashed",
            email="teacher_done@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add_all([student, teacher])
        db.session.flush()

        problem = Problem(slug="done-problem", title="Done", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        variant = Question(problem_id=problem.id, programming_language="c", starter_code="", solution="")
        db.session.add(variant)
        db.session.flush()
        db.session.add(Submission(student_id=student.id, question_id=variant.id, code="x", score=100, status="completed"))
        db.session.commit()

        assert ProblemService.is_problem_completed(student.id, problem.id) is True
