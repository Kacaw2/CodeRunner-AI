from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.quiz import Quiz, QuizProblem
from domain.models.user import User, UserRole


def test_problem_owns_language_variants_and_shared_test_cases(app, db_session):
    with app.app_context():
        teacher = User(
            username="teacher_model",
            password="hashed",
            email="teacher_model@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add(teacher)
        db.session.flush()

        problem = Problem(
            slug="two-sum-model",
            title="Two Sum",
            description="Read two integers and output their sum.",
            difficulty="easy",
            points=10,
            order=1,
            created_by=teacher.id,
        )
        db.session.add(problem)
        db.session.flush()

        py = Question(problem_id=problem.id, programming_language="python", starter_code="", solution="")
        c = Question(problem_id=problem.id, programming_language="c", starter_code="", solution="")
        case = TestCase(problem_id=problem.id, input="1 2", expected_output="3", is_hidden=False, weight=1.0)
        db.session.add_all([py, c, case])
        db.session.commit()

        loaded = Problem.query.filter_by(slug="two-sum-model").one()
        assert {q.programming_language for q in loaded.variants} == {"python", "c"}
        assert loaded.test_cases[0].expected_output == "3"


def test_quiz_problem_counts_problem_once(app, db_session):
    with app.app_context():
        teacher = User(
            username="teacher_quiz_problem",
            password="hashed",
            email="teacher_qp@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add(teacher)
        db.session.flush()

        problem = Problem(slug="count-once", title="Count Once", description="Desc", created_by=teacher.id)
        quiz = Quiz(title="Quiz", description="Desc", created_by=teacher.id, is_published=True)
        db.session.add_all([problem, quiz])
        db.session.flush()

        db.session.add(QuizProblem(quiz_id=quiz.id, problem_id=problem.id, order=1, points=15))
        db.session.commit()

        assert quiz.question_count == 1
        assert quiz.total_points == 15
