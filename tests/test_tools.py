"""Tests for AI agent tools."""
from unittest.mock import patch, MagicMock

import pytest


class TestExecuteCodeTool:
    def test_returns_structured_result(self, app):
        with app.app_context():
            from app.agents.tools.code_executor import execute_code

            mock_result = {
                "status": "AC",
                "stdout": "Hello World\n",
                "stderr": "",
                "time_ms": 15,
            }
            with patch("app.services.executor_service.ExecutorService.run_code", return_value=mock_result):
                result = execute_code.invoke({"code": 'print("Hello World")', "language": "python"})

            assert result["status"] == "AC"
            assert result["stdout"] == "Hello World\n"
            assert result["stderr"] == ""

    def test_truncates_long_output(self, app):
        with app.app_context():
            from app.agents.tools.code_executor import execute_code

            mock_result = {
                "status": "AC",
                "stdout": "x" * 5000,
                "stderr": "w" * 3000,
                "time_ms": 10,
            }
            with patch("app.services.executor_service.ExecutorService.run_code", return_value=mock_result):
                result = execute_code.invoke({"code": "x", "language": "c"})

            assert len(result["stdout"]) == 2000
            assert len(result["stderr"]) == 1000

    def test_default_language_is_c(self, app):
        with app.app_context():
            from app.agents.tools.code_executor import execute_code

            with patch("app.services.executor_service.ExecutorService.run_code") as mock_run:
                mock_run.return_value = {"status": "AC", "stdout": "", "stderr": "", "time_ms": 0}
                execute_code.invoke({"code": "int main(){return 0;}"})
                args = mock_run.call_args
                assert args.kwargs.get("language") == "c" or args[1].get("language") == "c"


class TestQuestionQueryTool:
    def test_returns_question_detail(self, app, db_session):
        with app.app_context():
            from app.agents.tools.question_query import get_question_detail
            from app.models.problem import Problem
            from app.models.question import Question, TestCase

            problem = Problem(
                slug="test-q",
                title="Test Q",
                description="Desc",
                created_by=1,
            )
            db_session.add(problem)
            db_session.flush()
            q = Question(
                problem_id=problem.id,
                programming_language="python",
            )
            db_session.add(q)
            db_session.flush()

            tc_visible = TestCase(problem_id=problem.id, input="1", expected_output="1", is_hidden=False)
            tc_hidden = TestCase(problem_id=problem.id, input="2", expected_output="2", is_hidden=True)
            db_session.add_all([tc_visible, tc_hidden])
            db_session.flush()

            result = get_question_detail.invoke({"question_id": q.id})

            assert result["id"] == q.id
            assert result["title"] == "Test Q"
            assert len(result["test_cases"]) == 1  # hidden excluded
            assert result["test_cases"][0]["input"] == "1"

    def test_returns_error_for_missing_question(self, app, db_session):
        with app.app_context():
            from app.agents.tools.question_query import get_question_detail

            result = get_question_detail.invoke({"question_id": 99999})
            assert "error" in result


class TestSubmissionQueryTool:
    def test_get_student_submissions_delegates(self, app):
        with app.app_context():
            from app.agents.tools.submission_query import get_student_submissions

            mock_return = {"submissions": [], "total": 0}
            with patch("app.services.submission_service.SubmissionService.get_student_submissions",
                       return_value=mock_return) as mock_svc:
                result = get_student_submissions.invoke({"student_id": 1, "question_id": 0, "limit": 5})
                mock_svc.assert_called_once()

            assert result == mock_return

    def test_get_submission_detail_delegates(self, app):
        with app.app_context():
            from app.agents.tools.submission_query import get_submission_detail

            mock_return = {"id": 1, "status": "AC"}
            with patch("app.services.submission_service.SubmissionService.get_submission_detail",
                       return_value=mock_return) as mock_svc:
                result = get_submission_detail.invoke({
                    "submission_id": 1, "user_id": 1, "user_role": "student"
                })
                mock_svc.assert_called_once()

            assert result["status"] == "AC"


class TestStatsQueryTool:
    def test_get_student_stats_delegates(self, app):
        with app.app_context():
            from app.agents.tools.stats_query import get_student_stats

            mock_return = {"total_students": 10, "avg_score": 85.0}
            with patch("app.services.teacher_stats_service.TeacherStatsService.get_teacher_stats",
                       return_value=mock_return):
                result = get_student_stats.invoke({"teacher_id": 1})

            assert result["total_students"] == 10
