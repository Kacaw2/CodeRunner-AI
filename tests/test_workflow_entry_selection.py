"""T4 (Phase 4): one boundary for multi-step workflow vs single conversational turn.

Two invariants:
  * ``should_use_workflow`` is the single decision that escalates a chat message
    to ``WorkflowEngine`` (multi-step / generation) vs keeping it on the
    orchestrator/harness single-turn path (including bounded intra-turn handoff).
  * ``stream_with_handoffs`` is the single streaming-orchestration loop shared by
    the chat worker and the SSE endpoint (no more copy-pasted handoff loops).
"""

from langchain_core.messages import HumanMessage

from ai.graph.handoff import MAX_HANDOFFS, stream_with_handoffs
from ai.graph.supervisor import SupervisorAgent, should_use_workflow


# ── Entry-selection boundary ───────────────────────────────────

def test_teacher_generation_request_escalates_to_workflow():
    assert should_use_workflow("帮我生成一道排序题", "teacher") is True
    assert should_use_workflow("Create a problem about recursion", "teacher") is True


def test_student_generation_request_stays_single_turn():
    # Generation triggers only escalate for teachers; a student asking about
    # "生成" is a normal tutoring turn.
    assert should_use_workflow("生成器是怎么工作的", "student") is False


def test_explicit_multi_step_phrasing_escalates_for_any_role():
    assert should_use_workflow("先解释再举例 然后 总结", "student") is True
    assert should_use_workflow("Analyze this and then refactor it", "teacher") is True
    assert should_use_workflow("批量导入这些题目", "teacher") is True


def test_plain_single_turn_message_does_not_escalate():
    assert should_use_workflow("这段代码为什么报错？", "student") is False
    assert should_use_workflow("Explain big-O notation", "student") is False


def test_classification_is_case_insensitive():
    assert should_use_workflow("GENERATE a problem", "teacher") is True
    assert should_use_workflow("do X AND THEN Y", "student") is True


def test_static_shim_delegates_to_module_function():
    # Back-compat: existing callers use the static method.
    assert SupervisorAgent._should_use_workflow("生成题目", "teacher") is True
    assert SupervisorAgent._should_use_workflow("hello", "student") is False


# ── Shared streaming-handoff loop ──────────────────────────────

def _base_state():
    return {
        "agent_type": "tutor",
        "messages": [HumanMessage(content="help me")],
        "handoff_to": None,
        "handoff_reason": "",
        "handoff_summary": "",
    }


def test_stream_with_handoffs_runs_single_agent_when_no_delegation():
    calls = []

    def fake_stream(agent_type, run_state):
        calls.append(agent_type)
        yield {"type": "token", "content": agent_type}

    state = _base_state()
    events = list(stream_with_handoffs(state, stream_fn=fake_stream))

    assert calls == ["tutor"]
    assert not any(e.get("type") == "handoff_start" for e in events)
    assert state["agent_type"] == "tutor"


def test_stream_with_handoffs_follows_one_delegation():
    calls = []

    def fake_stream(agent_type, run_state):
        calls.append(agent_type)
        yield {"type": "token", "content": agent_type}
        if agent_type == "tutor":
            run_state["handoff_to"] = "reviewer"
            run_state["handoff_reason"] = "needs review"
            run_state["handoff_summary"] = "tutor conclusion"

    state = _base_state()
    events = list(stream_with_handoffs(state, stream_fn=fake_stream))

    assert calls == ["tutor", "reviewer"]
    starts = [e for e in events if e.get("type") == "handoff_start"]
    assert len(starts) == 1
    assert starts[0]["target"] == "reviewer"
    assert starts[0]["reason"] == "needs review"
    # apply_handoff switched the live agent and cleared the transient fields.
    assert state["agent_type"] == "reviewer"
    assert state["handoff_to"] is None


def test_stream_with_handoffs_blocks_revisiting_an_agent():
    calls = []

    def fake_stream(agent_type, run_state):
        calls.append(agent_type)
        yield {"type": "token", "content": agent_type}
        # tutor -> reviewer -> tutor: the loop back to tutor must be blocked.
        if agent_type == "tutor" and calls.count("tutor") == 1:
            run_state["handoff_to"] = "reviewer"
            run_state["handoff_summary"] = "s"
        elif agent_type == "reviewer":
            run_state["handoff_to"] = "tutor"
            run_state["handoff_summary"] = "s"

    state = _base_state()
    list(stream_with_handoffs(state, stream_fn=fake_stream))

    assert calls == ["tutor", "reviewer"]


def test_stream_with_handoffs_respects_max_handoffs():
    chain = ["reviewer", "generator", "analytics"]
    calls = []

    def fake_stream(agent_type, run_state):
        calls.append(agent_type)
        yield {"type": "token", "content": agent_type}
        idx = len(calls) - 1
        if idx < len(chain):
            run_state["handoff_to"] = chain[idx]
            run_state["handoff_summary"] = "s"

    state = _base_state()
    list(stream_with_handoffs(state, stream_fn=fake_stream, max_handoffs=1))

    # One switch only: tutor -> reviewer, then stop despite a pending delegation.
    assert calls == ["tutor", "reviewer"]
    assert MAX_HANDOFFS == 2
