"""Phase 4 / Task 3: AgentHarness binds a single logical trace.

Progressive B: one chat task / handoff chain == one trace. The harness owns the
TraceCollector; agents write spans into the ambient trace. Both run() and
stream() share the same trace-binding path.
"""
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage  # noqa: F401  (import parity)


class _Chunk:
    """Minimal LangChain-style stream chunk: content only, no tool calls."""

    def __init__(self, content, usage_metadata=None):
        self.content = content
        self.usage_metadata = usage_metadata or {}
        self.tool_call_chunks = []


def _mock_tutor_llm(text="Here is a hint to get you started."):
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.stream.return_value = [
        _Chunk(text, {"input_tokens": 12, "output_tokens": 7}),
    ]
    return mock_llm


@patch("agents.base.AIConfig")
def test_agent_harness_binds_chat_task_to_trace(mock_config, app, db_session, teacher_user):
    with app.app_context():
        from evals.harness.agent_harness import AgentHarness
        from core.db.models.agent_trace import AgentTraceRun
        from core.db.session import db_session as core_db_session
        from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

        mock_config.get_llm.return_value = _mock_tutor_llm()
        mock_config.validate.return_value = None

        mock_runtime = MagicMock(spec=ToolRuntime)
        mock_runtime.list_tools.return_value = []
        set_tool_runtime(mock_runtime)
        try:
            result = AgentHarness().run(
                agent_type="tutor",
                message="help",
                user_id=teacher_user.id,
                user_role="teacher",
                source="workers",
                context={"conversation_id": 10, "chat_task_id": "task-1"},
                budget={"max_tokens": 2000, "max_tool_calls": 5},
            )
        finally:
            reset_tool_runtime()

        assert result.trace_id
        assert result.status in {"completed", "limit_exceeded", "failed"}
        assert result.agent_type == "tutor"

        with core_db_session() as session:
            runs = session.query(AgentTraceRun).filter_by(trace_id=result.trace_id).all()
            assert len(runs) == 1, "one chat task must produce exactly one trace run"
            run = runs[0]
            assert run.source == "workers"
            assert run.conversation_id == 10
            assert run.chat_task_id == "task-1"


@patch("agents.base.AIConfig")
def test_agent_harness_stream_yields_events_and_binds_trace(mock_config, app, db_session, teacher_user):
    """stream() must yield token/done events and share one trace with run()."""
    with app.app_context():
        from evals.harness.agent_harness import AgentHarness
        from core.db.models.agent_trace import AgentTraceRun
        from core.db.session import db_session as core_db_session
        from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

        mock_config.get_llm.return_value = _mock_tutor_llm()
        mock_config.validate.return_value = None

        mock_runtime = MagicMock(spec=ToolRuntime)
        mock_runtime.list_tools.return_value = []
        set_tool_runtime(mock_runtime)
        try:
            events = list(
                AgentHarness().stream(
                    agent_type="tutor",
                    message="help",
                    user_id=teacher_user.id,
                    user_role="teacher",
                    source="workers",
                    context={"conversation_id": 10, "chat_task_id": "task-1"},
                )
            )
        finally:
            reset_tool_runtime()

        types = {e["type"] for e in events}
        assert "token" in types
        assert "done" in types

        done = next(e for e in events if e["type"] == "done")
        trace_id = done.get("trace_id")
        assert trace_id

        with core_db_session() as session:
            runs = session.query(AgentTraceRun).filter_by(trace_id=trace_id).all()
            assert len(runs) == 1
            assert runs[0].chat_task_id == "task-1"
