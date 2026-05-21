"""Tests for AI agents and orchestrator."""
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


def _make_llm_response(content="test response", tool_calls=None):
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls or []
    return resp


class TestBaseAgent:
    def test_inject_security_submission_detail(self):
        from app.agents.agents.base import BaseAgent

        state = {"user_id": 42, "user_role": "student"}
        args = {"submission_id": 1, "user_id": 999, "user_role": "teacher"}
        result = BaseAgent._inject_security("get_submission_detail", args, state)
        assert result["user_id"] == 42
        assert result["user_role"] == "student"

    def test_inject_security_student_submissions(self):
        from app.agents.agents.base import BaseAgent

        state = {"user_id": 42, "user_role": "student"}
        args = {"student_id": 999}
        result = BaseAgent._inject_security("get_student_submissions", args, state)
        assert result["student_id"] == 42

    def test_inject_security_teacher_can_query_any_student(self):
        from app.agents.agents.base import BaseAgent

        state = {"user_id": 10, "user_role": "teacher"}
        args = {"student_id": 42}
        result = BaseAgent._inject_security("get_student_submissions", args, state)
        assert result["student_id"] == 42  # not overridden for teacher

    def test_run_tools_handles_unknown_tool(self):
        from app.agents.agents.base import BaseAgent

        agent = type("ConcreteAgent", (BaseAgent,), {"invoke": lambda s, st: st})()
        tool_calls = [{"name": "nonexistent", "args": {}, "id": "tc1"}]
        results = agent._run_tools(tool_calls, [], {"user_id": 1})
        assert len(results) == 1
        assert "Unknown tool" in results[0].content

    def test_run_tools_handles_tool_exception(self, app):
        with app.app_context():
            from app.agents.agents.base import BaseAgent
            from langchain_core.tools import tool

            @tool
            def broken_tool(x: int) -> str:
                """A tool that always fails."""
                raise RuntimeError("sandbox down")

            agent = type("ConcreteAgent", (BaseAgent,), {"invoke": lambda s, st: st})()
            tool_calls = [{"name": "broken_tool", "args": {"x": 1}, "id": "tc1"}]
            results = agent._run_tools(tool_calls, [broken_tool], {"user_id": 1})
            assert "error" in results[0].content.lower()


class TestTutorAgent:
    @patch("app.agents.agents.base.AIConfig")
    def test_invoke_returns_response(self, mock_config, app):
        with app.app_context():
            from app.agents.agents.tutor import TutorAgent

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response("Here's a hint about your loop.")
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            agent = TutorAgent()
            state = {
                "messages": [HumanMessage(content="Why is my code wrong?")],
                "agent_type": "tutor",
                "user_id": 1,
                "user_role": "student",
                "context": {"question_id": 1, "error_status": "WA"},
                "tool_results": [],
                "final_response": "",
            }
            result = agent.invoke(state)

            assert result["final_response"] == "Here's a hint about your loop."
            assert len(result["messages"]) > 1

    @patch("app.agents.agents.base.AIConfig")
    def test_invoke_with_tool_calls(self, mock_config, app):
        with app.app_context():
            from app.agents.agents.tutor import TutorAgent

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm

            tool_call_resp = _make_llm_response("", tool_calls=[{
                "name": "get_question_detail",
                "args": {"question_id": 1},
                "id": "tc1",
            }])
            final_resp = _make_llm_response("Based on the problem, check your loop.")
            mock_llm.invoke.side_effect = [tool_call_resp, final_resp]
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            with patch("app.agents.tools.question_query.get_question_detail") as mock_tool:
                mock_tool.name = "get_question_detail"
                mock_tool.invoke.return_value = {"id": 1, "title": "Two Sum", "test_cases": []}

                agent = TutorAgent()
                state = {
                    "messages": [HumanMessage(content="Help me")],
                    "agent_type": "tutor",
                    "user_id": 1,
                    "user_role": "student",
                    "context": {"question_id": 1},
                    "tool_results": [],
                    "final_response": "",
                }
                result = agent.invoke(state)

            assert "loop" in result["final_response"]


class TestReviewerAgent:
    @patch("app.agents.agents.base.AIConfig")
    def test_invoke_returns_review(self, mock_config, app):
        with app.app_context():
            from app.agents.agents.reviewer import ReviewerAgent

            review_json = '```json\n{"overall_score": "B", "summary": "Good", "issues": [], "strengths": ["Clean"]}\n```'
            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response(review_json)
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            agent = ReviewerAgent()
            state = {
                "messages": [HumanMessage(content="Review this code")],
                "agent_type": "reviewer",
                "user_id": 1,
                "user_role": "student",
                "context": {"code": "int main(){return 0;}", "language": "c"},
                "tool_results": [],
                "final_response": "",
            }
            result = agent.invoke(state)

            assert "overall_score" in result["final_response"]


class TestGeneratorAgent:
    @patch("app.agents.config.AIConfig.validate")
    @patch("app.agents.config.AIConfig.get_llm")
    def test_invoke_with_valid_json(self, mock_get_llm, mock_validate, app):
        with app.app_context():
            from app.agents.agents.generator import GeneratorAgent

            question_json = '''```json
{
  "title": "Add Two Numbers",
  "description": "Given two integers, print their sum.",
  "programming_language": "python",
  "difficulty": "easy",
  "solution": "a, b = map(int, input().split())\\nprint(a + b)",
  "solution_explanation": "Read two ints and print sum",
  "test_cases": [
    {"input": "1 2", "expected_output": "3", "is_hidden": false, "weight": 1.0},
    {"input": "0 0", "expected_output": "0", "is_hidden": true, "weight": 1.0}
  ]
}
```'''
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = _make_llm_response(question_json)
            mock_get_llm.return_value = mock_llm

            with patch("app.agents.agents.generator._validate_solution") as mock_val:
                mock_val.return_value = [
                    {"index": 0, "passed": True, "input": "1 2", "expected": "3", "actual": "3", "error": "", "status": "AC"},
                    {"index": 1, "passed": True, "input": "0 0", "expected": "0", "actual": "0", "error": "", "status": "AC"},
                ]

                agent = GeneratorAgent()
                state = {
                    "messages": [HumanMessage(content="Create a simple addition problem")],
                    "agent_type": "generator",
                    "user_id": 1,
                    "user_role": "teacher",
                    "context": {"language": "python", "difficulty": "easy"},
                    "tool_results": [],
                    "final_response": "",
                }
                result = agent.invoke(state)

            assert result["context"].get("generated_question") is not None
            assert result["context"]["generated_question"]["verified"] is True

    @patch("app.agents.config.AIConfig.validate")
    @patch("app.agents.config.AIConfig.get_llm")
    def test_invoke_retries_on_validation_failure(self, mock_get_llm, mock_validate, app):
        with app.app_context():
            from app.agents.agents.generator import GeneratorAgent

            question_json = '''```json
{
  "title": "Test",
  "description": "Test",
  "programming_language": "python",
  "solution": "print(1)",
  "test_cases": [{"input": "", "expected_output": "1", "is_hidden": false, "weight": 1.0}]
}
```'''
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = _make_llm_response(question_json)
            mock_get_llm.return_value = mock_llm

            call_count = 0

            def validation_side_effect(*args):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return [{"index": 0, "passed": False, "input": "", "expected": "1",
                             "actual": "2", "error": "", "status": "WA"}]
                return [{"index": 0, "passed": True, "input": "", "expected": "1",
                         "actual": "1", "error": "", "status": "AC"}]

            with patch("app.agents.agents.generator._validate_solution", side_effect=validation_side_effect):
                agent = GeneratorAgent()
                state = {
                    "messages": [HumanMessage(content="Create a problem")],
                    "agent_type": "generator",
                    "user_id": 1,
                    "user_role": "teacher",
                    "context": {"language": "python"},
                    "tool_results": [],
                    "final_response": "",
                }
                result = agent.invoke(state)

            assert call_count == 2
            assert result["context"]["generated_question"]["verified"] is True


class TestAnalyticsAgent:
    @patch("app.agents.agents.base.AIConfig")
    def test_invoke_returns_report(self, mock_config, app):
        with app.app_context():
            from app.agents.agents.analytics import AnalyticsAgent

            report = '```json\n{"summary": "Good progress", "progress": {"trend": "improving"}}\n```'
            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response(report)
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            agent = AnalyticsAgent()
            state = {
                "messages": [HumanMessage(content="Analyze student 1")],
                "agent_type": "analytics",
                "user_id": 10,
                "user_role": "teacher",
                "context": {"target_student_id": 1, "period": "30d"},
                "tool_results": [],
                "final_response": "",
            }
            result = agent.invoke(state)

            assert "progress" in result["final_response"]


class TestOrchestrator:
    def test_routes_to_correct_agent(self, app):
        with app.app_context():
            from app.agents.orchestrator import _route

            state = {
                "messages": [],
                "agent_type": "reviewer",
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _route(state)
            assert result["agent_type"] == "reviewer"

    def test_defaults_to_tutor_for_unknown(self, app):
        with app.app_context():
            from app.agents.orchestrator import _route

            state = {
                "messages": [],
                "agent_type": "nonexistent",
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _route(state)
            assert result["agent_type"] == "tutor"

    def test_defaults_to_tutor_when_missing(self, app):
        with app.app_context():
            from app.agents.orchestrator import _route

            state = {
                "messages": [],
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _route(state)
            assert result["agent_type"] == "tutor"

    @patch("app.agents.agents.base.AIConfig")
    def test_run_agent_catches_ai_error(self, mock_config, app):
        with app.app_context():
            from app.agents.orchestrator import _run_agent
            from app.agents.exceptions import LLMError

            mock_config.get_llm.side_effect = LLMError("API down")
            mock_config.validate.side_effect = LLMError("API down")

            state = {
                "messages": [HumanMessage(content="test")],
                "agent_type": "tutor",
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _run_agent("tutor", state)
            assert "temporarily unavailable" in result["final_response"]

    @patch("app.agents.agents.base.AIConfig")
    def test_run_agent_catches_unexpected_error(self, mock_config, app):
        with app.app_context():
            from app.agents.orchestrator import _run_agent

            mock_config.get_llm.side_effect = RuntimeError("unexpected")
            mock_config.validate.side_effect = RuntimeError("unexpected")

            state = {
                "messages": [HumanMessage(content="test")],
                "agent_type": "tutor",
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _run_agent("tutor", state)
            assert "unexpected error" in result["final_response"]
