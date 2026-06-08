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
    def test_legacy_tool_name_xml_tag_parses_to_canonical_tool(self):
        from ai.agents.base import _parse_legacy_function_text

        call = _parse_legacy_function_text(
            "Let me inspect it.\n\n<get_problem_detail>\n</get_problem_detail>",
            ["coderunner.problem.get_detail"],
        )

        assert call == {
            "name": "coderunner.problem.get_detail",
            "args": {},
            "id": "legacy_coderunner_problem_get_detail",
        }

    def test_sanitize_args_strips_identity(self):
        from ai.tools.protocol.runtime import ToolRuntime
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
        from ai.tools.protocol.runtime import ToolRuntime
        from core.auth.context import CallerContext

        caller = CallerContext(actor_type="user", user_id=42, role="student")
        args = {"student_id": 999}
        result = ToolRuntime._sanitize_args(args, caller)
        assert result["student_id"] == 42

    def test_sanitize_args_preserves_teacher_query(self):
        from ai.tools.protocol.runtime import ToolRuntime
        from core.auth.context import CallerContext

        caller = CallerContext(actor_type="user", user_id=10, role="teacher")
        args = {"some_param": "value"}
        result = ToolRuntime._sanitize_args(args, caller)
        assert result["teacher_id"] == 10

    def test_run_mcp_tool_handles_unknown_tool(self):
        from ai.agents.base import BaseAgent
        from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

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
    @patch("ai.agents.runtime.AIConfig")
    def test_sync_exhaustion_is_explicit(self, mock_config, mock_save, app):
        with app.app_context():
            from ai.agents.tutor.agent import TutorAgent
            from ai.tools.protocol.runtime import (
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
    @patch("ai.agents.runtime.AIConfig")
    def test_stream_exhaustion_yields_error(self, mock_config, mock_save, app):
        with app.app_context():
            from ai.agents.tutor.agent import TutorAgent
            from ai.tools.protocol.runtime import (
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

    @patch("ai.agents.runtime.AIConfig")
    def test_invoke_strips_system_message(self, mock_config, app):
        with app.app_context():
            from ai.agents.tutor.agent import TutorAgent

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

    @patch("ai.agents.config.AIConfig.validate")
    @patch("ai.agents.config.AIConfig.get_llm")
    def test_generator_retry_does_not_accumulate_system_messages(
        self, mock_get_llm, mock_validate, app,
    ):
        with app.app_context():
            from ai.agents.generator.agent import GeneratorAgent

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

            with patch("ai.agents.generator.agent._validate_solution", side_effect=validation_side_effect):
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
    def test_tutor_build_context_requests_tutor_policy(self, app):
        with app.app_context(), patch(
            "ai.memory.service.MemoryService.get_memory_context",
            return_value="Student Background: prior context",
        ) as get_memory:
            from ai.agents.tutor.agent import TutorAgent

            state = {
                "user_id": 7,
                "user_role": "student",
                "messages": [],
                "context": {"conversation_id": 9},
            }

            rendered = TutorAgent()._build_system_context(state)

            get_memory.assert_called_once_with(
                7,
                "student",
                conversation_id=9,
                agent_name="tutor",
            )
            assert "## Student Profile (from previous sessions)" in rendered
            assert "Student Background: prior context" in rendered

    @patch("ai.agents.runtime.AIConfig")
    def test_invoke_returns_response(self, mock_config, app):
        with app.app_context():
            from ai.agents.tutor.agent import TutorAgent

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

    @patch("ai.agents.runtime.AIConfig")
    def test_invoke_with_tool_calls(self, mock_config, app):
        with app.app_context():
            from ai.agents.tutor.agent import TutorAgent
            from ai.tools.protocol.runtime import ToolRuntime, ToolResult, set_tool_runtime, reset_tool_runtime

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
    @patch("ai.agents.runtime.AIConfig")
    def test_invoke_returns_review(self, mock_config, app):
        with app.app_context():
            from ai.agents.reviewer.agent import ReviewerAgent

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
    def test_generator_build_context_requests_generator_policy(self, app):
        with app.app_context(), patch(
            "ai.memory.service.MemoryService.get_memory_context",
            return_value="Teacher Preferences: concise",
        ) as get_memory, patch(
            "ai.agents.generator.agent.GeneratorAgent._get_similar_problems",
            return_value="",
        ):
            from ai.agents.generator.agent import GeneratorAgent

            state = {
                "user_id": 8,
                "user_role": "teacher",
                "messages": [],
                "context": {"conversation_id": 10},
            }

            rendered = GeneratorAgent()._build_system_context(state)

            get_memory.assert_called_once_with(
                8,
                "teacher",
                conversation_id=10,
                agent_name="generator",
            )
            assert "## Teacher Preferences (from profile)" in rendered
            assert "Teacher Preferences: concise" in rendered

    @patch("ai.agents.config.AIConfig.validate")
    @patch("ai.agents.config.AIConfig.get_llm")
    def test_invoke_with_valid_json(self, mock_get_llm, mock_validate, app):
        with app.app_context():
            from ai.agents.generator.agent import GeneratorAgent

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

            with patch("ai.agents.generator.agent._validate_solution") as mock_val:
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

    @patch("ai.agents.config.AIConfig.validate")
    @patch("ai.agents.config.AIConfig.get_llm")
    def test_invoke_retries_on_validation_failure(self, mock_get_llm, mock_validate, app):
        with app.app_context():
            from ai.agents.generator.agent import GeneratorAgent

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

            with patch("ai.agents.generator.agent._validate_solution", side_effect=validation_side_effect):
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

    @patch("ai.agents.config.AIConfig.validate")
    @patch("ai.agents.generator.agent.AIConfig.get_llm")
    def test_stream_persists_trace(self, mock_get_llm, mock_validate, app, db_session, teacher_user):
        with app.app_context():
            from langchain_core.messages import HumanMessage
            from ai.agents.generator.agent import GeneratorAgent
            from core.observability.tracing import TraceCollector
            from domain.models.observability import AgentTraceRun, AgentTraceSpan
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

            with patch("ai.agents.generator.agent._validate_solution") as mock_val:
                mock_val.return_value = [
                    {"index": 0, "passed": True, "input": "1 2", "expected": "3", "actual": "3", "error": "", "status": "AC"},
                ]

                unrelated_trace = TraceCollector(
                    agent_type="generator",
                    user_id=teacher_user.id,
                    conversation_id=999,
                )
                unrelated_trace.save(status="completed", response="older trace")

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
                    .filter_by(
                        agent_type="generator",
                        user_id=teacher_user.id,
                        conversation_id=123,
                    )
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
    @patch("ai.agents.runtime.AIConfig")
    def test_invoke_returns_report(self, mock_config, app):
        with app.app_context():
            from ai.agents.analytics.agent import AnalyticsAgent

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

    @patch("core.observability.tracing.TraceCollector.save")
    @patch("ai.agents.runtime.AIConfig")
    def test_stream_executes_legacy_function_text_without_leaking_it(self, mock_config, mock_save, app):
        with app.app_context():
            from ai.agents.analytics.agent import AnalyticsAgent
            from ai.tools.protocol.runtime import (
                ToolRuntime, ToolResult, set_tool_runtime, reset_tool_runtime,
            )

            class FunctionTextChunk:
                content = '<function>\nget_class_statistics({"teacher_id": 10})\n</function>'
                usage_metadata = {}
                tool_call_chunks = []

            class FinalChunk:
                content = '{"summary": "Class activity is steady", "progress": {"trend": "stable"}}'
                usage_metadata = {}
                tool_call_chunks = []

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.stream.side_effect = [[FunctionTextChunk()], [FinalChunk()]]
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            mock_runtime = MagicMock(spec=ToolRuntime)
            mock_runtime.list_tools.return_value = []
            mock_runtime.call_sync.return_value = ToolResult(
                ok=True,
                tool="coderunner.analytics.class_statistics",
                data={"classrooms": [], "total_students": 0},
            )
            set_tool_runtime(mock_runtime)
            try:
                agent = AnalyticsAgent()
                state = {
                    "messages": [HumanMessage(content="Analyze my class")],
                    "agent_type": "analytics",
                    "user_id": 10,
                    "user_role": "teacher",
                    "context": {"period": "30d"},
                    "tool_results": [],
                    "final_response": "",
                }
                events = list(agent.stream(state))
            finally:
                reset_tool_runtime()

            token_text = "".join(e.get("content", "") for e in events if e["type"] == "token")
            assert "<function>" not in token_text
            assert any(e["type"] == "tool_call" and e["tool"] == "coderunner.analytics.class_statistics"
                       for e in events)
            mock_runtime.call_sync.assert_called()
            assert state["final_response"].startswith('{"summary"')


class TestOrchestrator:
    def test_routes_to_correct_agent(self, app):
        with app.app_context():
            from ai.graph.runner import _route

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
            from ai.graph.runner import _route

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
            from ai.graph.runner import _route

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

    @patch("ai.graph.runner.AIConfig")
    def test_auto_route_classifies_intent(self, mock_config, app):
        """Phase 2: Smart intent router classifies 'auto' agent_type."""
        with app.app_context():
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = _make_llm_response("reviewer")
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            from ai.graph.runner import _route

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

    @patch("ai.graph.runner.AIConfig")
    def test_auto_route_blocks_student_generator(self, mock_config, app):
        """Phase 2: Students cannot be routed to generator even if LLM says so."""
        with app.app_context():
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = _make_llm_response("generator")
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            from ai.graph.runner import _route

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

    @patch("ai.graph.runner.AIConfig")
    def test_auto_route_fallback_on_error(self, mock_config, app):
        """Phase 2: Falls back gracefully if intent classification fails."""
        with app.app_context():
            mock_config.get_llm.side_effect = RuntimeError("API down")

            from ai.graph.runner import _route

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

    @patch("ai.agents.runtime.AIConfig")
    def test_run_agent_catches_ai_error(self, mock_config, app):
        with app.app_context():
            from ai.graph.runner import _run_agent
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

    @patch("ai.agents.runtime.AIConfig")
    def test_run_agent_catches_unexpected_error(self, mock_config, app):
        with app.app_context():
            from ai.graph.runner import _run_agent

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
        from ai.workers.batch import decompose_batch_params

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
        from ai.workers.batch import decompose_batch_params

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
            from domain.models.user import User, UserRole
            from domain.repositories.users import SyncUserRepository
            from ai.graph.recovery import recover_orphaned_tasks

            user = SyncUserRepository(db_session).get_by_username(
                "recovery_test_user"
            )
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
            from domain.models.user import User, UserRole
            from domain.repositories.users import SyncUserRepository
            from ai.graph.recovery import recover_orphaned_tasks

            user = SyncUserRepository(db_session).get_by_username(
                "recovery_test_user2"
            )
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


class TestMemoryContextCompatibility:
    def test_legacy_student_context_keeps_existing_labels(self, db_session, app):
        with app.app_context():
            from domain.models.user import User, UserRole
            from app.models.student_profile import StudentProfile
            from ai.memory.service import MemoryService

            user = User(
                username="memory_student",
                password="x",
                email="memory-student@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add(StudentProfile(
                student_id=user.id,
                learning_summary="Needs visual examples.",
                error_patterns={"WA": 3},
                knowledge_map={"recursion": 0.4, "arrays": 0.9},
                current_hint_level={"recursion": 2},
            ))
            db_session.commit()

            rendered = MemoryService.get_memory_context(user.id, "student")

            assert "Student Background: Needs visual examples." in rendered
            assert "Error History: {'WA': 3}" in rendered
            assert "Weak Areas: recursion" in rendered
            assert "Previous Hints Given: {'recursion': 2}" in rendered

    def test_legacy_teacher_context_keeps_existing_labels(self, db_session, app):
        with app.app_context():
            from domain.models.user import User, UserRole
            from app.models.student_profile import TeacherPreference
            from ai.memory.service import MemoryService

            user = User(
                username="memory_teacher",
                password="x",
                email="memory-teacher@test.com",
                role=UserRole.TEACHER,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add(TeacherPreference(
                teacher_id=user.id,
                style_notes="Prefer concise prompts.",
                preferred_language="java",
                preferred_difficulty="hard",
                class_weak_areas=["loops", "recursion"],
            ))
            db_session.commit()

            rendered = MemoryService.get_memory_context(user.id, "teacher")

            assert "Teacher Preferences: Prefer concise prompts." in rendered
            assert "Class Weak Areas: loops, recursion" in rendered

    def test_legacy_context_returns_empty_when_profile_query_fails(self, app):
        with app.app_context(), patch(
            "app.models.student_profile.StudentProfile.query"
        ) as query:
            from ai.memory.service import MemoryService

            query.filter_by.side_effect = RuntimeError("table unavailable")
            assert MemoryService.get_memory_context(1, "student") == ""


class TestStructuredMemoryContext:
    def test_memory_context_exposes_structured_sections(self):
        from ai.memory.context import (
            MemoryContext,
            MemoryItem,
            MemoryMetadata,
            RecentSessionMemory,
        )

        profile_item = MemoryItem(
            key="learning_summary",
            value="Needs visual examples.",
            metadata=MemoryMetadata(
                source="student_profile:7",
                reason_included="tutor profile policy",
            ),
        )
        session = RecentSessionMemory(
            conversation_id=11,
            agent_type="tutor",
            summary="Worked on recursion.",
            created_at=None,
            metadata=MemoryMetadata(
                source="ai_conversation:11",
                reason_included="recent tutor summary policy",
            ),
        )

        context = MemoryContext(
            student_profile=(profile_item,),
            recent_sessions=(session,),
        )

        assert context.student_profile[0].key == "learning_summary"
        assert context.recent_sessions[0].conversation_id == 11
        assert context.is_empty is False
        assert MemoryContext().is_empty is True


class TestMemoryContextBuilder:
    def test_build_student_context_returns_source_metadata(
        self, db_session, app
    ):
        with app.app_context():
            from domain.models.user import User, UserRole
            from app.models.student_profile import StudentProfile
            from ai.memory.service import MemoryService

            user = User(
                username="structured_student",
                password="x",
                email="structured-student@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add(StudentProfile(
                student_id=user.id,
                learning_summary="Needs visual examples.",
                knowledge_map={"recursion": 0.4},
            ))
            db_session.commit()

            context = MemoryService.build_memory_context(
                user.id,
                "student",
            )

            items = {item.key: item for item in context.student_profile}
            assert items["learning_summary"].value == "Needs visual examples."
            assert items["learning_summary"].metadata.source == (
                f"student_profile:{user.id}"
            )
            assert items["weak_areas"].value == ("recursion",)

    def test_build_context_keeps_recent_session_identity(
        self, db_session, app
    ):
        with app.app_context():
            from domain.models.chat import AIConversation
            from domain.models.user import User, UserRole
            from ai.memory.service import MemoryService

            user = User(
                username="structured_session",
                password="x",
                email="structured-session@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            previous = AIConversation(
                user_id=user.id,
                agent_type="tutor",
                summary="Worked on recursion.",
            )
            db_session.add(previous)
            db_session.commit()

            context = MemoryService.build_memory_context(user.id, "student")

            assert context.recent_sessions[0].conversation_id == previous.id
            assert context.recent_sessions[0].agent_type == "tutor"
            assert context.recent_sessions[0].summary == "Worked on recursion."
            assert context.recent_sessions[0].metadata.source == (
                f"ai_conversation:{previous.id}"
            )


class TestAgentMemoryPolicy:
    def test_tutor_only_reads_tutor_summaries(self, db_session, app):
        with app.app_context():
            from domain.models.chat import AIConversation
            from domain.models.user import User, UserRole
            from ai.memory.service import MemoryService

            user = User(
                username="policy_student",
                password="x",
                email="policy-student@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add_all([
                AIConversation(
                    user_id=user.id,
                    agent_type="tutor",
                    summary="Tutor-only summary.",
                ),
                AIConversation(
                    user_id=user.id,
                    agent_type="generator",
                    summary="Generator-only summary.",
                ),
            ])
            db_session.commit()

            rendered = MemoryService.get_memory_context(
                user.id,
                "student",
                agent_name="tutor",
            )

            assert "Tutor-only summary." in rendered
            assert "Generator-only summary." not in rendered

    def test_reviewer_policy_renders_no_memory(self, db_session, app):
        with app.app_context():
            from ai.memory.service import MemoryService

            assert MemoryService.get_memory_context(
                1,
                "student",
                agent_name="reviewer",
            ) == ""


class TestMemorySummaryReplay:
    def test_get_memory_context_replays_recent_summaries(self, db_session, app):
        with app.app_context():
            from domain.models.chat import AIConversation
            from domain.models.user import User, UserRole
            from ai.memory.service import MemoryService

            user = User(username="mem_replay_user", password="x",
                        email="memreplay@test.com", role=UserRole.STUDENT)
            db_session.add(user)
            db_session.flush()

            past = AIConversation(
                user_id=user.id, agent_type="tutor",
                summary="Student struggled with recursion base cases.")
            current = AIConversation(
                user_id=user.id, agent_type="tutor",
                summary="Currently working on linked lists.")
            db_session.add_all([past, current])
            db_session.commit()

            ctx = MemoryService.get_memory_context(
                user.id, "student", conversation_id=current.id)

            assert "recursion base cases" in ctx
            # The in-progress conversation must be excluded from its own context.
            assert "linked lists" not in ctx


class TestCrossAgentCallGuardrail:
    def test_trace_llm_call_increments_counter(self):
        from core.observability.tracing import TraceCollector

        trace = TraceCollector(agent_type="tutor", user_id=1)
        assert trace.llm_call_count == 0
        with trace.trace_llm_call():
            pass
        with trace.trace_llm_call():
            pass
        assert trace.llm_call_count == 2

    @patch("ai.agents.runtime.AIConfig")
    def test_guardrail_aborts_when_shared_budget_exhausted(self, mock_config, app):
        with app.app_context():
            from ai.agents.config import MAX_LLM_CALLS_PER_TRACE
            from ai.agents.tutor.agent import TutorAgent
            from core.observability.tracing import TraceCollector, use_current_trace
            from ai.tools.protocol.runtime import (
                ToolRuntime, set_tool_runtime, reset_tool_runtime,
            )

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_config.get_llm.return_value = mock_llm
            mock_config.validate.return_value = None

            mock_runtime = MagicMock(spec=ToolRuntime)
            mock_runtime.list_tools.return_value = []
            set_tool_runtime(mock_runtime)

            # Simulate a handoff chain where earlier agents already spent the
            # whole cross-agent LLM budget on this shared trace.
            trace = TraceCollector(agent_type="supervisor", user_id=1)
            trace.llm_call_count = MAX_LLM_CALLS_PER_TRACE
            try:
                with use_current_trace(trace):
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

            # Guardrail must trip before any further LLM call is made.
            mock_llm.invoke.assert_not_called()
            assert result["final_response"]
            assert trace.pending_status == "limit_exceeded"
