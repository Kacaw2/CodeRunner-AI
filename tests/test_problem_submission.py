from unittest.mock import patch

from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.user import User, UserRole
from app.services.submission_service import SubmissionService


def test_submit_problem_uses_shared_problem_test_cases(app, db_session):
    with app.app_context():
        student = User(
            username="student_problem_submit",
            password="hashed",
            email="student_ps@example.com",
            role=UserRole.STUDENT,
        )
        teacher = User(
            username="teacher_problem_submit",
            password="hashed",
            email="teacher_ps@example.com",
            role=UserRole.TEACHER,
        )
        db.session.add_all([student, teacher])
        db.session.flush()

        problem = Problem(slug="submit-shared", title="Shared", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        py = Question(problem_id=problem.id, programming_language="python", starter_code="", solution="")
        c = Question(problem_id=problem.id, programming_language="c", starter_code="", solution="")
        case = TestCase(problem_id=problem.id, input="2 3", expected_output="5", is_hidden=False, weight=1.0)
        db.session.add_all([py, c, case])
        db.session.commit()

        with patch("app.services.submission_service.ExecutorService.run_code") as run_code:
            run_code.return_value = {"status": "AC", "passed": True, "stdout": "5\n", "stderr": "", "time_ms": 5}
            result = SubmissionService.submit_problem_code(
                student_id=student.id,
                problem_id=problem.id,
                language="c",
                code="int main(){return 0;}",
                time_limit_sec=2.0,
            )

        assert result["score"] == 100.0
        assert result["question_id"] == c.id
        run_code.assert_called_once()
        assert run_code.call_args.kwargs["language"] == "c"
        assert run_code.call_args.kwargs["stdin_text"] == "2 3"
