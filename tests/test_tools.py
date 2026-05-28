"""Tests for core tool implementations (Phase E — MCP architecture)."""
from unittest.mock import patch, MagicMock

import pytest


class TestExecuteCodeImpl:
    def test_returns_structured_result(self, app):
        with app.app_context():
            from tools.code.executor import execute_code_impl

            mock_result = {
                "status": "AC",
                "stdout": "Hello World\n",
                "stderr": "",
                "time_ms": 15,
            }
            with patch("app.services.executor_service.ExecutorService.run_code", return_value=mock_result):
                result = execute_code_impl(code='print("Hello World")', language="python")

            assert result["status"] == "AC"
            assert result["stdout"] == "Hello World\n"
            assert result["stderr"] == ""

    def test_truncates_long_output(self, app):
        with app.app_context():
            from tools.code.executor import execute_code_impl

            mock_result = {
                "status": "AC",
                "stdout": "x" * 5000,
                "stderr": "w" * 3000,
                "time_ms": 10,
            }
            with patch("app.services.executor_service.ExecutorService.run_code", return_value=mock_result):
                result = execute_code_impl(code="x", language="c")

            assert len(result["stdout"]) == 2000
            assert len(result["stderr"]) == 1000

    def test_default_language_is_python(self, app):
        with app.app_context():
            from tools.code.executor import execute_code_impl

            with patch("app.services.executor_service.ExecutorService.run_code") as mock_run:
                mock_run.return_value = {"status": "AC", "stdout": "", "stderr": "", "time_ms": 0}
                execute_code_impl(code="print(1)")
                args = mock_run.call_args
                assert args.kwargs.get("language") == "python" or args[1].get("language") == "python"


class TestProblemDetailImpl:
    def test_returns_problem_detail(self, app, db_session):
        with app.app_context():
            from tools.problems.queries import get_problem_detail_impl
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

            result = get_problem_detail_impl(problem.id)

            assert result["problem_id"] == problem.id
            assert result["title"] == "Test Q"
            assert len(result["test_cases"]) == 1
            assert result["test_cases"][0]["input"] == "1"

    def test_returns_error_for_missing_problem(self, app, db_session):
        with app.app_context():
            from tools.problems.queries import get_problem_detail_impl

            result = get_problem_detail_impl(99999)
            assert "error" in result
