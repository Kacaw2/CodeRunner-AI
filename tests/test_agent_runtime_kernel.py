"""Phase 1 runtime-kernel regressions: trace join, prompt isolation, limits."""

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

# Register the full shared metadata before early runtime-only tests touch the
# User mapper; later tests in this file also use Flask fixtures.
import app.models  # noqa: F401


def test_executor_uses_session_trace_id_for_identity():
    """The tool identity must carry the run's real trace_id, not context's None."""
    from ai.agents.executor import ToolCallExecutor
    from ai.agents.session import AgentSession
    from ai.mcp_gateway import client as client_mod

    captured = {}

    class _FakeClient:
        def call_tool(self, name, args, identity, tool_call_id=""):
            captured["trace_id"] = identity.trace_id
            captured["agent_type"] = identity.agent_type
            return {"ok": True, "data": {"title": "Two Sum"}}

    client_mod.set_mcp_tool_client(_FakeClient())
    try:
        state = {
            "messages": [HumanMessage(content="x")],
            "agent_type": "tutor",
            "user_id": 7,
            "user_role": "student",
            "context": {"conversation_id": 10},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        session.trace_id = "trace-xyz"

        tool_call = {"name": "coderunner.problem.get_detail", "args": {"problem_id": 1}, "id": "tc1"}
        msg = ToolCallExecutor().run(tool_call, state, "tutor", session=session)

        assert captured["trace_id"] == "trace-xyz"
        assert captured["agent_type"] == "tutor"
        assert "Two Sum" in msg.content
    finally:
        client_mod.set_mcp_tool_client(None)


def _mock_llm_no_tools(text="Here is a hint."):
    class _Resp:
        content = text
        tool_calls = []
        usage_metadata = {"input_tokens": 5, "output_tokens": 3}
        response_metadata = {}
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = _Resp()
    return llm


def test_runtime_run_sets_trace_id_and_strips_system_prompt(monkeypatch):
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    from langchain_core.messages import SystemMessage
    import ai.agents.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm",
                        staticmethod(lambda tier=None: _mock_llm_no_tools()))

    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    try:
        state = {
            "messages": [HumanMessage(content="help")],
            "agent_type": "tutor",
            "user_id": 7,
            "user_role": "student",
            "context": {},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        result = AgentRuntime().run(session, tool_names=[], system_ctx="SYS")

        assert result["trace_id"]
        assert result["final_response"] == "Here is a hint."
        assert all(not isinstance(m, SystemMessage) for m in result["messages"])
    finally:
        reset_tool_runtime()


def test_runtime_limit_exceeded_stops_after_max_iterations(monkeypatch):
    """A model that always wants another tool call ends in limit_exceeded."""
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    import ai.agents.runtime as runtime_mod
    from ai.agents.config import MAX_TOOL_ITERATIONS

    class _ToolResp:
        content = ""
        tool_calls = [{"name": "coderunner.problem.get_detail", "args": {}, "id": "tc"}]
        usage_metadata = {}
        response_metadata = {}

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = _ToolResp()
    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm",
                        staticmethod(lambda tier=None: llm))

    from ai.mcp_gateway import client as client_mod
    client_mod.set_mcp_tool_client(
        type("C", (), {"call_tool": lambda self, *a, **k: {"ok": True, "data": {}}})()
    )
    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    try:
        state = {
            "messages": [HumanMessage(content="loop")],
            "agent_type": "tutor", "user_id": 7, "user_role": "student",
            "context": {}, "tool_results": [], "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        result = AgentRuntime().run(
            session, tool_names=["coderunner.problem.get_detail"], system_ctx="SYS")
        assert result["final_response"]  # the limit-exceeded user message
        assert llm.invoke.call_count == MAX_TOOL_ITERATIONS
    finally:
        reset_tool_runtime()
        client_mod.set_mcp_tool_client(None)


def test_runtime_uses_per_agent_iteration_budget(monkeypatch):
    """The loop ceiling comes from the agent definition, not the global const."""
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    import ai.agents.runtime as runtime_mod

    class _ToolResp:
        content = ""
        tool_calls = [{"name": "coderunner.problem.get_detail", "args": {}, "id": "tc"}]
        usage_metadata = {}
        response_metadata = {}

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = _ToolResp()
    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm",
                        staticmethod(lambda tier=None: llm))

    from ai.mcp_gateway import client as client_mod
    client_mod.set_mcp_tool_client(
        type("C", (), {"call_tool": lambda self, *a, **k: {"ok": True, "data": {}}})()
    )
    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    try:
        state = {
            "messages": [HumanMessage(content="loop")],
            "agent_type": "tutor", "user_id": 7, "user_role": "student",
            "context": {}, "tool_results": [], "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        # Override the definition's budget to a small number for the test.
        import dataclasses
        session.definition = dataclasses.replace(session.definition, max_tool_iterations=2)
        AgentRuntime().run(
            session, tool_names=["coderunner.problem.get_detail"], system_ctx="SYS")
        assert llm.invoke.call_count == 2
    finally:
        reset_tool_runtime()
        client_mod.set_mcp_tool_client(None)


def test_runtime_blocks_undeclared_tool():
    """A tool outside the agent allowlist is denied before crossing the client."""
    from ai.agents.executor import ToolCallExecutor
    from ai.agents.session import AgentSession

    state = {
        "messages": [HumanMessage(content="x")],
        "agent_type": "tutor", "user_id": 7, "user_role": "student",
        "context": {}, "tool_results": [], "final_response": "",
    }
    session = AgentSession.from_state(state, agent_name="tutor")
    session.trace_id = "t1"
    # tutor's allowlist does NOT include the generator-only save tool
    tc = {"name": "coderunner.problem.save_generated", "args": {}, "id": "tc"}
    msg = ToolCallExecutor().run(tc, state, "tutor", session=session)
    assert "TOOL_NOT_ALLOWED" in msg.content


def test_runtime_stream_executes_tool_name_xml_and_persists_tool_output(
    monkeypatch, app, db_session, teacher_user,
):
    """Provider-emitted <get_problem_detail> tags are tool calls, not final text."""
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    import ai.agents.runtime as runtime_mod

    class _Chunk:
        def __init__(self, content="", tool_call_chunks=None, usage_metadata=None):
            self.content = content
            self.tool_call_chunks = tool_call_chunks or []
            self.usage_metadata = usage_metadata or {}

    class _XmlThenDoneLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, _schemas):
            return self

        def stream(self, _messages):
            self.calls += 1
            if self.calls == 1:
                return [_Chunk(
                    "Let me inspect it.\n\n<get_problem_detail>\n</get_problem_detail>"
                )]
            return [_Chunk("Check the boundary case.", usage_metadata={
                "input_tokens": 2,
                "output_tokens": 3,
            })]

    monkeypatch.setattr(
        runtime_mod.AIConfig,
        "get_llm",
        staticmethod(lambda tier=None: _XmlThenDoneLLM()),
    )

    from ai.mcp_gateway import client as client_mod
    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

    captured = {}

    class _FakeClient:
        def call_tool(self, name, args, identity, tool_call_id=""):
            captured["name"] = name
            captured["args"] = args
            captured["trace_id"] = identity.trace_id
            return {"ok": True, "data": {"problem_id": 42, "title": "Two Sum"}}

    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    client_mod.set_mcp_tool_client(_FakeClient())
    try:
        state = {
            "messages": [HumanMessage(content="Why WA?")],
            "agent_type": "tutor",
            "user_id": teacher_user.id,
            "user_role": "teacher",
            "context": {"conversation_id": 5678, "question_id": 42},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        events = list(AgentRuntime().stream(
            session,
            tool_names=["coderunner.problem.get_detail"],
            system_ctx="SYS",
        ))
    finally:
        reset_tool_runtime()
        client_mod.set_mcp_tool_client(None)

    token_text = "".join(e.get("content", "") for e in events if e["type"] == "token")
    assert "<get_problem_detail>" not in token_text
    assert any(e["type"] == "tool_call" for e in events)
    assert captured["name"] == "coderunner.problem.get_detail"
    assert captured["args"] == {"problem_id": 42}
    assert captured["trace_id"]
    assert session.final_response == "Check the boundary case."

    from domain.models.observability import AgentTraceRun, AgentTraceSpan
    from core.db.session import db_session as core_db_session

    with core_db_session() as session_db:
        run = (
            session_db.query(AgentTraceRun)
            .filter_by(
                agent_type="tutor",
                user_id=teacher_user.id,
                conversation_id=5678,
            )
            .one()
        )
        tool_span = (
            session_db.query(AgentTraceSpan)
            .filter_by(trace_id=run.trace_id, span_type="tool")
            .one()
        )
        assert "Two Sum" in tool_span.output_preview


def test_runtime_persists_memory_audit_event_and_artifact(
    monkeypatch, app, db_session, teacher_user,
):
    """A run carrying a memory selection writes both a memory_context_selected
    event and a memory_injection_audit artifact to the trace."""
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    import ai.agents.runtime as runtime_mod
    from ai.memory.context import MemoryContext, MemoryItem, MemoryMetadata
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm",
                        staticmethod(lambda tier=None: _mock_llm_no_tools()))

    context = MemoryContext(student_profile=(
        MemoryItem(
            key="learning_summary",
            value="Needs recursion practice.",
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=80,
            ),
        ),
    ))
    selection = select_memory_context(
        context,
        MemoryPolicy(
            profile_kind=MemoryProfileKind.STUDENT,
            max_memory_chars=4000,
            max_memory_tokens=1000,
        ),
    )

    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    try:
        state = {
            "messages": [HumanMessage(content="help")],
            "agent_type": "tutor",
            "user_id": teacher_user.id,
            "user_role": "student",
            "context": {"conversation_id": 7777},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        session.memory_selection = selection
        result = AgentRuntime().run(session, tool_names=[], system_ctx="SYS")
    finally:
        reset_tool_runtime()

    from domain.models.observability import AgentTraceEvent, AgentTraceArtifact
    from core.db.session import db_session as core_db_session

    with core_db_session() as session_db:
        events = (
            session_db.query(AgentTraceEvent)
            .filter_by(
                trace_id=result["trace_id"],
                event_type="memory_context_selected",
            )
            .all()
        )
        artifacts = (
            session_db.query(AgentTraceArtifact)
            .filter_by(
                trace_id=result["trace_id"],
                artifact_type="memory_injection_audit",
            )
            .all()
        )
        assert len(events) == 1
        assert len(artifacts) == 1
        assert events[0].payload_json["included_count"] == 1


def test_runtime_context_restores_question_id_from_conversation():
    from ai.agent_runtime.services.chat_runner import (
        _chat_context_from_conversation,
    )

    conv = type("Conversation", (), {
        "id": 10,
        "context_type": "question",
        "context_id": 42,
    })()

    context = _chat_context_from_conversation(conv)

    assert context == {"conversation_id": 10, "question_id": 42}


def test_split_holds_tool_tag_streamed_token_by_token():
    """A tool tag arriving across chunks must never leak as visible text, while
    unrelated angle brackets (code) stream through untouched."""
    from ai.agents.base import _split_safe_stream_content, _legacy_tag_names

    tags = _legacy_tag_names(["coderunner.problem.get_detail"])

    buf, visible = "", ""
    for tok in ["Let me look.\n", "<get", "_problem", "_detail>", "</get_problem_detail>"]:
        buf += tok
        safe, buf = _split_safe_stream_content(buf, tags)
        visible += safe
    # The opening/closing tag must stay held (consumed later by the parser),
    # never emitted as a visible token mid-stream.
    assert "<get_problem_detail>" not in visible
    assert "</get_problem_detail>" not in visible
    assert visible == "Let me look.\n"

    # Code with angle brackets is not a tool tag → streams normally.
    buf, visible = "", ""
    for tok in ["Use ", "vector", "<int>", " when ", "a < b"]:
        buf += tok
        safe, buf = _split_safe_stream_content(buf, tags)
        visible += safe
    visible += buf
    assert visible == "Use vector<int> when a < b"


def test_runtime_stream_records_artifact_for_generated_problem(
    monkeypatch, app, db_session, teacher_user,
):
    """save_generated tool output is persisted as a trace artifact."""
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    import ai.agents.runtime as runtime_mod

    class _Chunk:
        def __init__(self, content="", tool_call_chunks=None, usage_metadata=None):
            self.content = content
            self.tool_call_chunks = tool_call_chunks or []
            self.usage_metadata = usage_metadata or {}

    class _XmlThenDoneLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, _schemas):
            return self

        def stream(self, _messages):
            self.calls += 1
            if self.calls == 1:
                return [_Chunk("Saving it.\n<save_generated_problem></save_generated_problem>")]
            return [_Chunk("Done.")]

    monkeypatch.setattr(
        runtime_mod.AIConfig,
        "get_llm",
        staticmethod(lambda tier=None: _XmlThenDoneLLM()),
    )

    from ai.mcp_gateway import client as client_mod
    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

    class _FakeClient:
        def call_tool(self, name, args, identity, tool_call_id=""):
            return {"ok": True, "data": {"title": "Two Sum", "verified": True}}

    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    client_mod.set_mcp_tool_client(_FakeClient())
    try:
        state = {
            "messages": [HumanMessage(content="Make a problem")],
            "agent_type": "generator",
            "user_id": teacher_user.id,
            "user_role": "teacher",
            "context": {"conversation_id": 9090},
            "tool_results": [],
            "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="generator")
        list(AgentRuntime().stream(
            session,
            tool_names=["coderunner.problem.save_generated"],
            system_ctx="SYS",
        ))
    finally:
        reset_tool_runtime()
        client_mod.set_mcp_tool_client(None)

    from domain.models.observability import AgentTraceRun, AgentTraceArtifact
    from core.db.session import db_session as core_db_session

    with core_db_session() as session_db:
        run = (
            session_db.query(AgentTraceRun)
            .filter_by(agent_type="generator", conversation_id=9090)
            .one()
        )
        artifact = (
            session_db.query(AgentTraceArtifact)
            .filter_by(trace_id=run.trace_id, artifact_type="generated_problem")
            .one()
        )
        assert "Two Sum" in artifact.preview_text
        assert artifact.payload_json["verified"] is True


def test_compaction_span_recorded_when_over_budget(monkeypatch):
    from core.observability.tracing import TraceCollector
    from ai.memory.compaction import CompactionResult

    trace = TraceCollector(agent_type="tutor", user_id=1)
    result = CompactionResult(
        messages=[], compacted=True, dropped_messages=5, kept_messages=3,
        summarized=True, fallback_used=False, tokens_before=900, tokens_after=300,
    )
    trace.trace_compaction(result)

    spans = [s for s in trace.steps if s.get("step_type") == "compaction"]
    assert len(spans) == 1
    assert spans[0]["tool_input"]["dropped_messages"] == 5
    assert spans[0]["tool_input"]["tokens_after"] == 300


def test_trace_compaction_noop_not_recorded():
    from core.observability.tracing import TraceCollector
    from ai.memory.compaction import CompactionResult

    trace = TraceCollector(agent_type="tutor", user_id=1)
    result = CompactionResult(
        messages=[], compacted=False, dropped_messages=0, kept_messages=3,
        summarized=False, fallback_used=False, tokens_before=10, tokens_after=10,
    )
    trace.trace_compaction(result)
    assert not [s for s in trace.steps if s.get("step_type") == "compaction"]


def test_inloop_compaction_records_span_and_run_completes(monkeypatch):
    """Two-iteration run with large tool output triggers in-loop compaction span."""
    from ai.agents.runtime import AgentRuntime
    from ai.agents.session import AgentSession
    import ai.agents.runtime as runtime_mod

    # Iteration 1: return a tool call; iteration 2: return final text
    call_count = {"n": 0}

    class _Resp:
        def __init__(self, tool_calls, content="", usage=None):
            self.tool_calls = tool_calls
            self.content = content
            self.usage_metadata = usage or {}
            self.response_metadata = {}

    def _invoke(_llm_with_tools, _messages):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _Resp(
                tool_calls=[{"name": "coderunner.problem.get_detail", "args": {}, "id": "tc1"}],
                usage={"input_tokens": 10, "output_tokens": 5},
            )
        return _Resp(tool_calls=[], content="All done.", usage={"input_tokens": 5, "output_tokens": 3})

    monkeypatch.setattr(runtime_mod.LLMRunner, "invoke", staticmethod(_invoke))
    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm", staticmethod(lambda tier=None: MagicMock()))

    from ai.mcp_gateway import client as client_mod
    from ai.tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime

    class _FakeClient:
        def call_tool(self, name, args, identity, tool_call_id=""):
            # Large output to exceed DEFAULT_CONTEXT_TOKEN_BUDGET (12000 tokens ~ 48000 chars)
            return {"ok": True, "data": {"output": "x" * 60000}}

    mock_rt = MagicMock(spec=ToolRuntime)
    mock_rt.list_tools.return_value = []
    set_tool_runtime(mock_rt)
    client_mod.set_mcp_tool_client(_FakeClient())
    try:
        state = {
            "messages": [HumanMessage(content="explain")],
            "agent_type": "tutor", "user_id": 7, "user_role": "student",
            "context": {}, "tool_results": [], "final_response": "",
        }
        session = AgentSession.from_state(state, agent_name="tutor")
        result = AgentRuntime().run(
            session, tool_names=["coderunner.problem.get_detail"], system_ctx="SYS"
        )
    finally:
        reset_tool_runtime()
        client_mod.set_mcp_tool_client(None)

    assert result["final_response"] == "All done."
    compaction_spans = [s for s in session.trace.steps if s.get("step_type") == "compaction"]
    assert len(compaction_spans) >= 1
