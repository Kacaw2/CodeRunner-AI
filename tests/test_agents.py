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
    def test_sanitize_args_strips_identity(self):
        from tools.protocol.runtime import ToolRuntime
        from core.auth.context import CallerContext

        caller = CallerContext(
            actor_type="user", user_id=42, role="student",
        )
        args = {"submission_id": 1, "user_id": 999, "user_role": "teacher", "role": "admin"}
        result = ToolRuntime._sanitize_args(args, caller)
        assert result["_caller_user_id"] == 42
        assert result["_caller_role"] == "student"
        assert "user_id" not in result
        assert "user_role" not in result
        assert "role" not in result

    def test_sanitize_args_injects_student_id(self):
        from tools.protocol.runtime import ToolRuntime
        from core.auth.context import CallerContext

        caller = CallerContext(actor_type="user", user_id=42, role="student")
        args = {"student_id": 999}
        result = ToolRuntime._sanitize_args(args, caller)
        assert result["student_id"] == 42

    def test_sanitize_args_preserves_teacher_query(self):
        from tools.protocol.runtime import ToolRuntime
        from core.auth.context import CallerContext

        caller = CallerContext(actor_type="user", user_id=10, role="teacher")
        args = {"some_param": "value"}
        result = ToolRuntime._sanitize_args(args, caller)
        assert result["teacher_id"] == 10

    def test_run_mcp_tool_handles_unknown_tool(self):
        from agents.base import BaseAgent
        from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

        runtime = ToolRuntime()
        set_tool_runtime(runtime)
        try:
            agent = type("ConcreteAgent", (BaseAgent,), {"invoke": lambda s, st: st})()
            tool_call = {"name": "nonexistent.tool", "args": {}, "id": "tc1"}
            state = {"user_id": 1, "user_role": "student", "context": {}}
            result = agent._run_mcp_tool(tool_call, state)
            assert "error" in result.content.lower() or "not_found" in result.content.lower()
        finally:
            reset_tool_runtime()


class TestToolLoopExhaustion:
    """Phase 1: an exhausted tool loop must be explicit, never a blank success."""

    @patch("core.observability.tracing.TraceCollector.save")
    @patch("agents.base.AIConfig")
    def test_sync_exhaustion_is_explicit(self, mock_config, mock_save, app):
        with app.app_context():
            from agents.tutor.agent import TutorAgent
            from tools.protocol.runtime import (
                ToolRuntime, ToolResult, set_tool_runtime, reset_tool_runtime,
            )

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            # The model keeps requesting tools and never returns a final answer.
            mock_llm.invoke.return_value = _make_llm_response("", tool_calls=[{
                "name": "coderunner.problem.get_detail",
                "args": {"problem_id": 1},
                "id": "tc1",
            }])
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            mock_runtime = MagicMock(spec=ToolRuntime)
            mock_runtime.list_tools.return_value = []
            mock_runtime.call_sync.return_value = ToolResult(
                ok=True, tool="coderunner.problem.get_detail", data={"ok": 1},
            )
            set_tool_runtime(mock_runtime)
            try:
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
            finally:
                reset_tool_runtime()

            assert result["final_response"]  # explicit, never blank
            statuses = [c.kwargs.get("status") for c in mock_save.call_args_list]
            assert "limit_exceeded" in statuses
            assert "completed" not in statuses

    @patch("core.observability.tracing.TraceCollector.save")
    @patch("agents.base.AIConfig")
    def test_stream_exhaustion_yields_error(self, mock_config, mock_save, app):
        with app.app_context():
            from agents.tutor.agent import TutorAgent
            from tools.protocol.runtime import (
                ToolRuntime, ToolResult, set_tool_runtime, reset_tool_runtime,
            )

            class ToolChunk:
                content = ""
                usage_metadata = {}
                tool_call_chunks = [{
                    "index": 0,
                    "name": "coderunner.problem.get_detail",
                    "args": "{}",
                    "id": "tc1",
                }]

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.stream.return_value = [ToolChunk()]
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            mock_runtime = MagicMock(spec=ToolRuntime)
            mock_runtime.list_tools.return_value = []
            mock_runtime.call_sync.return_value = ToolResult(
                ok=True, tool="coderunner.problem.get_detail", data={"ok": 1},
            )
            set_tool_runtime(mock_runtime)
            try:
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
                events = list(agent.stream(state))
            finally:
                reset_tool_runtime()

            assert any(e["type"] == "error" for e in events)
            statuses = [c.kwargs.get("status") for c in mock_save.call_args_list]
            assert "limit_exceeded" in statuses
            assert "completed" not in statuses


class TestSystemContextIsolation:
    """Phase 2: the injected system prompt must never be persisted into history."""

    @patch("agents.base.AIConfig")
    def test_invoke_strips_system_message(self, mock_config, app):
        with app.app_context():
            from agents.tutor.agent import TutorAgent

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response("Here is a hint.")
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            agent = TutorAgent()
            state = {
                "messages": [HumanMessage(content="Why is my code wrong?")],
                "agent_type": "tutor",
                "user_id": 1,
                "user_role": "student",
                "context": {"question_id": 1},
                "tool_results": [],
                "final_response": "",
            }
            result = agent.invoke(state)

            assert all(not isinstance(m, SystemMessage) for m in result["messages"])

    @patch("agents.config.AIConfig.validate")
    @patch("agents.config.AIConfig.get_llm")
    def test_generator_retry_does_not_accumulate_system_messages(
        self, mock_get_llm, mock_validate, app,
    ):
        with app.app_context():
            from agents.generator.agent import GeneratorAgent

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
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response(question_json)
            mock_get_llm.return_value = mock_llm

            call_count = 0

            def validation_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                passed = call_count > 1
                return [{"index": 0, "passed": passed, "input": "", "expected": "1",
                         "actual": "1" if passed else "2", "error": "", "status": "AC" if passed else "WA"}]

            with patch("agents.generator.agent._validate_solution", side_effect=validation_side_effect):
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

            assert call_count == 2  # retried once
            system_count = sum(1 for m in result["messages"] if isinstance(m, SystemMessage))
            assert system_count == 0


class TestTutorAgent:
    @patch("agents.base.AIConfig")
    def test_invoke_returns_response(self, mock_config, app):
        with app.app_context():
            from agents.tutor.agent import TutorAgent

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

    @patch("agents.base.AIConfig")
    def test_invoke_with_tool_calls(self, mock_config, app):
        with app.app_context():
            from agents.tutor.agent import TutorAgent
            from tools.protocol.runtime import ToolRuntime, ToolResult, set_tool_runtime, reset_tool_runtime

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm

            tool_call_resp = _make_llm_response("", tool_calls=[{
                "name": "coderunner.problem.get_detail",
                "args": {"problem_id": 1},
                "id": "tc1",
            }])
            final_resp = _make_llm_response("Based on the problem, check your loop.")
            mock_llm.invoke.side_effect = [tool_call_resp, final_resp]
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            mock_runtime = MagicMock(spec=ToolRuntime)
            mock_runtime.list_tools.return_value = []
            mock_runtime.call_sync.return_value = ToolResult(
                ok=True, tool="coderunner.problem.get_detail",
                data={"problem_id": 1, "title": "Two Sum", "test_cases": []},
            )
            set_tool_runtime(mock_runtime)
            try:
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
            finally:
                reset_tool_runtime()


class TestReviewerAgent:
    @patch("agents.base.AIConfig")
    def test_invoke_returns_review(self, mock_config, app):
        with app.app_context():
            from agents.reviewer.agent import ReviewerAgent

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
    @patch("agents.config.AIConfig.validate")
    @patch("agents.config.AIConfig.get_llm")
    def test_invoke_with_valid_json(self, mock_get_llm, mock_validate, app):
        with app.app_context():
            from agents.generator.agent import GeneratorAgent

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
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response(question_json)
            mock_get_llm.return_value = mock_llm

            with patch("agents.generator.agent._validate_solution") as mock_val:
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

            assert result["context"].get("generated_problem") is not None
            assert result["context"]["generated_problem"]["verified"] is True

    @patch("agents.config.AIConfig.validate")
    @patch("agents.config.AIConfig.get_llm")
    def test_invoke_retries_on_validation_failure(self, mock_get_llm, mock_validate, app):
        with app.app_context():
            from agents.generator.agent import GeneratorAgent

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
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.invoke.return_value = _make_llm_response(question_json)
            mock_get_llm.return_value = mock_llm

            call_count = 0

            def validation_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return [{"index": 0, "passed": False, "input": "", "expected": "1",
                             "actual": "2", "error": "", "status": "WA"}]
                return [{"index": 0, "passed": True, "input": "", "expected": "1",
                         "actual": "1", "error": "", "status": "AC"}]

            with patch("agents.generator.agent._validate_solution", side_effect=validation_side_effect):
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
            assert result["context"]["generated_problem"]["verified"] is True

    @patch("agents.config.AIConfig.validate")
    @patch("agents.generator.agent.AIConfig.get_llm")
    def test_stream_persists_trace(self, mock_get_llm, mock_validate, app, db_session, teacher_user):
        with app.app_context():
            from langchain_core.messages import HumanMessage
            from agents.generator.agent import GeneratorAgent
            from core.db.models.agent_trace import AgentTraceRun, AgentTraceSpan
            from core.db.session import db_session as core_db_session

            class Chunk:
                def __init__(self, content, usage_metadata=None):
                    self.content = content
                    self.usage_metadata = usage_metadata or {}

            question_json = '''```json
{
  "title": "Add Two Numbers",
  "description": "Given two integers, print their sum.",
  "programming_language": "python",
  "difficulty": "easy",
  "solution": "a, b = map(int, input().split())\\nprint(a + b)",
  "solution_explanation": "Read two ints and print sum",
  "test_cases": [
    {"input": "1 2", "expected_output": "3", "is_hidden": false, "weight": 1.0}
  ]
}
```'''

            mock_llm = MagicMock()
            mock_llm.stream.return_value = [
                Chunk(question_json, {"input_tokens": 10, "output_tokens": 20}),
            ]
            mock_get_llm.return_value = mock_llm

            with patch("agents.generator.agent._validate_solution") as mock_val:
                mock_val.return_value = [
                    {"index": 0, "passed": True, "input": "1 2", "expected": "3", "actual": "3", "error": "", "status": "AC"},
                ]

                state = {
                    "messages": [HumanMessage(content="Create a simple addition problem")],
                    "agent_type": "generator",
                    "user_id": teacher_user.id,
                    "user_role": "teacher",
                    "context": {"conversation_id": 123, "language": "python", "difficulty": "easy"},
                    "tool_results": [],
                    "final_response": "",
                }
                events = list(GeneratorAgent().stream(state))

            assert any(event["type"] == "token" for event in events)
            with core_db_session() as session:
                run = (
                    session.query(AgentTraceRun)
                    .filter_by(agent_type="generator")
                    .one()
                )
                assert run.conversation_id == 123
                assert run.status == "completed"
                assert run.tokens_input == 10
                assert run.tokens_output == 20
                span_count = (
                    session.query(AgentTraceSpan)
                    .filter_by(trace_id=run.trace_id)
                    .count()
                )
                assert span_count >= 2


class TestAnalyticsAgent:
    @patch("agents.base.AIConfig")
    def test_invoke_returns_report(self, mock_config, app):
        with app.app_context():
            from agents.analytics.agent import AnalyticsAgent

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
            from graph.runner import _route

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
            from graph.runner import _route

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
            from graph.runner import _route

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

    @patch("graph.runner.AIConfig")
    def test_auto_route_classifies_intent(self, mock_config, app):
        """Phase 2: Smart intent router classifies 'auto' agent_type."""
        with app.app_context():
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = _make_llm_response("reviewer")
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            from graph.runner import _route

            state = {
                "messages": [HumanMessage(content="Review my code please")],
                "agent_type": "auto",
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _route(state)
            assert result["agent_type"] == "reviewer"
            assert result.get("auto_routed") is True

    @patch("graph.runner.AIConfig")
    def test_auto_route_blocks_student_generator(self, mock_config, app):
        """Phase 2: Students cannot be routed to generator even if LLM says so."""
        with app.app_context():
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = _make_llm_response("generator")
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            from graph.runner import _route

            state = {
                "messages": [HumanMessage(content="Create a problem for me")],
                "agent_type": "auto",
                "user_id": 1,
                "user_role": "student",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _route(state)
            assert result["agent_type"] == "tutor"

    @patch("graph.runner.AIConfig")
    def test_auto_route_fallback_on_error(self, mock_config, app):
        """Phase 2: Falls back gracefully if intent classification fails."""
        with app.app_context():
            mock_config.get_llm.side_effect = RuntimeError("API down")

            from graph.runner import _route

            state = {
                "messages": [HumanMessage(content="Help me")],
                "agent_type": "auto",
                "user_id": 1,
                "user_role": "teacher",
                "context": {},
                "tool_results": [],
                "final_response": "",
            }
            result = _route(state)
            assert result["agent_type"] == "analytics"
            assert result.get("auto_routed") is True

    @patch("agents.base.AIConfig")
    def test_run_agent_catches_ai_error(self, mock_config, app):
        with app.app_context():
            from graph.runner import _run_agent
            from core.exceptions import LLMError

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

    @patch("agents.base.AIConfig")
    def test_run_agent_catches_unexpected_error(self, mock_config, app):
        with app.app_context():
            from graph.runner import _run_agent

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


# ── Phase 2 Tests ────────────────────────────────────────────


class TestTaskStateMachine:
    def test_valid_transitions(self):
        from core.task_state import TaskStatus, validate_transition

        assert validate_transition(TaskStatus.PENDING, TaskStatus.EXECUTING) is True
        assert validate_transition(TaskStatus.EXECUTING, TaskStatus.VALIDATING) is True
        assert validate_transition(TaskStatus.VALIDATING, TaskStatus.COMPLETED) is True
        assert validate_transition(TaskStatus.REVIEW, TaskStatus.REVISING) is True
        assert validate_transition(TaskStatus.FAILED, TaskStatus.PENDING) is True

    def test_invalid_transitions(self):
        from core.task_state import TaskStatus, validate_transition

        assert validate_transition(TaskStatus.COMPLETED, TaskStatus.EXECUTING) is False
        assert validate_transition(TaskStatus.CANCELLED, TaskStatus.PENDING) is False
        assert validate_transition(TaskStatus.PENDING, TaskStatus.COMPLETED) is False


class TestBatchRunner:
    def test_decompose_batch_params(self):
        from workers.batch import decompose_batch_params

        params = {"topic": "arrays", "language": "python", "difficulty": "easy", "count": 3}
        steps = decompose_batch_params(params)
        assert len(steps) == 3
        for i, step in enumerate(steps):
            assert step["topic"] == "arrays"
            assert step["language"] == "python"
            assert step["index"] == i
            assert "arrays" in step["prompt"]
            assert f"{i + 1} of 3" in step["prompt"]

    def test_decompose_single(self):
        from workers.batch import decompose_batch_params

        params = {"topic": "sorting", "language": "c", "count": 1}
        steps = decompose_batch_params(params)
        assert len(steps) == 1
        assert "1 of 1" not in steps[0]["prompt"]


class TestGeneratedQuestionDraft:
    def test_draft_to_dict(self, app):
        with app.app_context():
            from app.models.generated_question_draft import GeneratedQuestionDraft

            draft = GeneratedQuestionDraft(
                teacher_id=1,
                question_data={"title": "Test", "solution": "pass"},
                validation_status="passed",
                status="pending_review",
            )
            d = draft.to_dict()
            assert d["status"] == "pending_review"
            assert d["question_data"]["title"] == "Test"
            assert d["validation_status"] == "passed"


class TestCrashRecovery:
    def test_recovers_orphaned_tasks(self, db_session, app):
        with app.app_context():
            from app.models.agent_task import AgentTask
            from app.models.user import User, UserRole
            from graph.recovery import recover_orphaned_tasks

            user = User.query.filter_by(username="recovery_test_user").first()
            if not user:
                user = User(username="recovery_test_user", password="x", email="recov@test.com", role=UserRole.TEACHER)
                db_session.add(user)
                db_session.flush()

            task = AgentTask(
                user_id=user.id,
                task_type="generate_batch",
                agent_type="generator",
                status="executing",
                input_params={"topic": "test"},
                attempt=0,
                max_attempts=3,
            )
            db_session.add(task)
            db_session.commit()
            task_id = task.id

            recover_orphaned_tasks()

            recovered = AgentTask.query.get(task_id)
            assert recovered.status == "pending"
            assert recovered.attempt == 1

    def test_fails_exhausted_tasks(self, db_session, app):
        with app.app_context():
            from app.models.agent_task import AgentTask
            from app.models.user import User, UserRole
            from graph.recovery import recover_orphaned_tasks

            user = User.query.filter_by(username="recovery_test_user2").first()
            if not user:
                user = User(username="recovery_test_user2", password="x", email="recov2@test.com", role=UserRole.TEACHER)
                db_session.add(user)
                db_session.flush()

            task = AgentTask(
                user_id=user.id,
                task_type="generate_batch",
                agent_type="generator",
                status="executing",
                input_params={"topic": "test"},
                attempt=3,
                max_attempts=3,
            )
            db_session.add(task)
            db_session.commit()
            task_id = task.id

            recover_orphaned_tasks()

            recovered = AgentTask.query.get(task_id)
            assert recovered.status == "failed"
