# Phase 1: Agent Runtime Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge the existing `BaseAgent` + `ToolCallExecutor` + hooks + trace + harness into a single runtime kernel built around an explicit `AgentSession`, `AgentRuntime`, and `LLMRunner`, fixing the tool-call `trace_id` mismatch along the way — with zero external behavior change for the four specialist agents.

**Architecture:** Today the per-run runtime context (trace, identity, budget, source) is read ad-hoc from a raw `AgentState` dict in three different places, and they disagree: `ToolCallExecutor` builds `MCPClientIdentity` from `state["context"]["trace_id"]`, but `BaseAgent` only writes the real `trace_id` back to `state["trace_id"]` *after* the tool loop finishes — so during tool calls the identity's `trace_id` is `None` and tool audit cannot be joined to the agent trace. We introduce `AgentSession` as the single in-memory carrier of that context (with lossless `from_state` / `to_state`), extract pure model concerns into `LLMRunner`, add a thin `AgentRuntime` facade that owns the invoke/stream orchestration, make `ToolCallExecutor` prefer the session for identity/trace, and reduce `BaseAgent`'s two big methods to session-construction shells. The progressive single-trace ownership model (`acquire_trace` / `owns_trace` / `finalize_trace`) and the `AgentState` dict at every public boundary are preserved.

**Tech Stack:** Python 3, LangChain core messages, pytest (existing `tests/` suite with `app` / `db_session` / `teacher_user` fixtures in `tests/conftest.py`), DeepSeek via `AIConfig.get_llm`.

---

## Background: the central bug this phase fixes

In [agents/executor.py:43-50](../../agents/executor.py) the tool identity is built as:

```python
identity = MCPClientIdentity(
    user_id=state.get("user_id", 0),
    role=state.get("user_role", "student"),
    agent_type=state.get("agent_type", default_agent),
    task_id=state.get("context", {}).get("task_id"),
    conversation_id=state.get("context", {}).get("conversation_id"),
    trace_id=state.get("context", {}).get("trace_id"),  # ← almost always None
)
```

But the real trace is created inside [agents/base.py:214](../../agents/base.py) (`acquire_trace`) and only written to `state["trace_id"]` at [base.py:305](../../agents/base.py) — *after* the tool loop. So every tool call audit records `trace_id=None`. Phase 1 acceptance requires "工具调用 audit 使用同一个 trace_id"; Task 3 makes that test pass.

## File Structure

| File | Responsibility | Created/Modified |
|---|---|---|
| `agents/session.py` | `AgentSession` dataclass: single carrier of runtime context; `from_state` / `to_state` / `mcp_identity` | Create |
| `agents/llm_runner.py` | Pure model concerns: retrying `_llm_invoke`/`_llm_stream`, token-usage extraction, message compaction | Create |
| `agents/runtime.py` | `AgentRuntime` facade: `run(session, ...)` / `stream(session, ...)` orchestration (trace acquire → loop → finalize) | Create |
| `agents/executor.py` | `ToolCallExecutor.run` prefers session identity/trace_id; keeps state fallback | Modify |
| `agents/base.py` | `_invoke_with_mcp_tools` / `_stream_with_mcp_tools` become session-building shells delegating to `AgentRuntime` | Modify |
| `evals/harness/agent_harness.py` | Build the initial run state via the session helper; assert single-trace path unchanged | Modify |
| `tests/test_agent_session.py` | Unit tests for `AgentSession` round-trip and identity | Create |
| `tests/test_llm_runner.py` | Unit tests for `LLMRunner` usage extraction + compaction | Create |
| `tests/test_agent_runtime_kernel.py` | Regression: trace_id join, system-prompt isolation, limit_exceeded, hooks, handoff | Create |

## Constraints (do not violate)

- The four specialist agents' `invoke(state)` / `stream(state)` signatures and outputs MUST be byte-identical in behavior. Existing tests (`tests/test_agents.py`, `tests/test_agent_features.py`, `tests/test_agent_harness_trace_binding.py`, `tests/test_agent_hooks.py`, `tests/test_agent_mcp_client_boundary.py`, `tests/test_eval_harness_trace_binding.py`) MUST stay green.
- The injected `SystemMessage` MUST NOT be persisted back into `state["messages"]` ([base.py:304](../../agents/base.py), [base.py:462](../../agents/base.py)).
- The `acquire_trace` / `owns_trace` / `finalize_trace` ownership contract MUST NOT change — who calls `trace.save()` stays the same.
- The stream fault paths (`GeneratorExit` → `interrupted`, `trace_saved` flag) MUST be preserved exactly ([base.py:486-494](../../agents/base.py)).
- `AgentState` dict stays the public boundary type. `AgentSession` is an internal aggregation view only.

---

## Task 1: AgentSession carrier

**Files:**
- Create: `agents/session.py`
- Test: `tests/test_agent_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_session.py
"""Unit tests for AgentSession: lossless state<->session and identity build."""

from langchain_core.messages import HumanMessage


def _state():
    return {
        "messages": [HumanMessage(content="help me")],
        "agent_type": "tutor",
        "user_id": 7,
        "user_role": "student",
        "context": {"conversation_id": 10, "task_id": "t-1", "question_id": 3},
        "tool_results": [],
        "final_response": "",
    }


def test_from_state_pulls_core_fields():
    from agents.session import AgentSession

    s = AgentSession.from_state(_state(), agent_name="tutor")
    assert s.agent_name == "tutor"
    assert s.user_id == 7
    assert s.user_role == "student"
    assert s.context["conversation_id"] == 10
    assert s.definition is not None and s.definition.name == "tutor"


def test_to_state_roundtrip_preserves_messages_and_context():
    from agents.session import AgentSession

    original = _state()
    s = AgentSession.from_state(original, agent_name="tutor")
    rebuilt = s.to_state()
    assert rebuilt["agent_type"] == "tutor"
    assert rebuilt["user_id"] == 7
    assert rebuilt["context"]["question_id"] == 3
    assert rebuilt["messages"] == original["messages"]


def test_mcp_identity_uses_session_trace_id_not_context():
    from agents.session import AgentSession

    s = AgentSession.from_state(_state(), agent_name="tutor")
    s.trace_id = "trace-abc"  # set once the trace is acquired
    identity = s.mcp_identity()
    assert identity.trace_id == "trace-abc"
    assert identity.user_id == 7
    assert identity.role == "student"
    assert identity.agent_type == "tutor"
    assert identity.task_id == "t-1"
    assert identity.conversation_id == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.session'`

- [ ] **Step 3: Write minimal implementation**

```python
# agents/session.py
"""AgentSession — the single in-memory carrier of per-run runtime context.

Replaces ad-hoc reads of trace/identity/budget from a raw AgentState dict.
``from_state`` / ``to_state`` keep the dict as the public boundary type so the
specialist agents, hooks, executor, and harness signatures stay unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSession:
    agent_name: str
    user_id: int
    user_role: str
    messages: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    tool_results: list = field(default_factory=list)
    final_response: str = ""
    definition: Any = None
    trace: Any = None
    trace_id: str | None = None
    budget: dict = field(default_factory=dict)
    source: str = "agent"
    tool_client: Any = None
    # Carry through any extra AgentState keys untouched for a lossless round-trip.
    extra_state: dict = field(default_factory=dict)

    _CORE_KEYS = (
        "messages", "agent_type", "user_id", "user_role",
        "context", "tool_results", "final_response",
    )

    @classmethod
    def from_state(cls, state: dict, agent_name: str | None = None) -> "AgentSession":
        from core.definitions import get_definition

        name = state.get("agent_type") or agent_name or ""
        extra = {k: v for k, v in state.items() if k not in cls._CORE_KEYS}
        return cls(
            agent_name=name,
            user_id=state.get("user_id", 0),
            user_role=state.get("user_role", "student"),
            messages=list(state.get("messages", [])),
            context=dict(state.get("context", {})),
            tool_results=list(state.get("tool_results", [])),
            final_response=state.get("final_response", ""),
            definition=get_definition(name),
            trace_id=extra.get("trace_id"),
            extra_state={k: v for k, v in extra.items() if k != "trace_id"},
        )

    def to_state(self) -> dict:
        state = dict(self.extra_state)
        state.update({
            "messages": self.messages,
            "agent_type": self.agent_name,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "context": self.context,
            "tool_results": self.tool_results,
            "final_response": self.final_response,
        })
        if self.trace_id is not None:
            state["trace_id"] = self.trace_id
        return state

    def mcp_identity(self):
        from mcp_gateway.client import MCPClientIdentity

        return MCPClientIdentity(
            user_id=self.user_id,
            role=self.user_role,
            agent_type=self.agent_name,
            task_id=self.context.get("task_id"),
            conversation_id=self.context.get("conversation_id"),
            trace_id=self.trace_id or self.context.get("trace_id"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_session.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/session.py tests/test_agent_session.py
git commit -m "feat(agents): add AgentSession runtime-context carrier"
```

---

## Task 2: LLMRunner — extract pure model concerns

**Files:**
- Create: `agents/llm_runner.py`
- Test: `tests/test_llm_runner.py`

This extracts the duplicated token-usage extraction (currently at [base.py:262-280](../../agents/base.py) and [base.py:406-413](../../agents/base.py)), the retrying invoke/stream ([base.py:135-142](../../agents/base.py)), and the compaction call ([base.py:238-241](../../agents/base.py)). No behavior change — `BaseAgent` keeps using these until Task 5.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_runner.py
"""Unit tests for LLMRunner pure helpers."""


def test_extract_usage_prefers_usage_metadata():
    from agents.llm_runner import LLMRunner

    class _Resp:
        usage_metadata = {"input_tokens": 11, "output_tokens": 5}
        response_metadata = {}

    assert LLMRunner.extract_usage(_Resp()) == (11, 5)


def test_extract_usage_falls_back_to_response_metadata():
    from agents.llm_runner import LLMRunner

    class _Resp:
        usage_metadata = None
        response_metadata = {"token_usage": {"prompt_tokens": 9, "completion_tokens": 3}}

    assert LLMRunner.extract_usage(_Resp()) == (9, 3)


def test_extract_usage_handles_missing_metadata():
    from agents.llm_runner import LLMRunner

    class _Resp:
        usage_metadata = None
        response_metadata = None

    assert LLMRunner.extract_usage(_Resp()) == (0, 0)


def test_compact_never_raises_and_returns_list():
    from agents.llm_runner import LLMRunner
    from langchain_core.messages import HumanMessage

    msgs = [HumanMessage(content=f"m{i}") for i in range(30)]
    out = LLMRunner.compact(msgs, max_messages=20)
    assert isinstance(out, list)
    assert len(out) <= 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.llm_runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# agents/llm_runner.py
"""LLMRunner — pure model concerns extracted from BaseAgent.

Holds the retrying LLM invoke/stream, token-usage extraction (single source for
both sync and stream paths), and message compaction. No tracing or tool logic.
"""

import logging

from core.exceptions import retry_on_llm_error

logger = logging.getLogger(__name__)


def _usage_number(metadata, key: str) -> int:
    if not isinstance(metadata, dict):
        return 0
    value = metadata.get(key, 0)
    return value if isinstance(value, int) else 0


class LLMRunner:
    """Stateless helpers for the model-call portion of an agent loop."""

    @staticmethod
    @retry_on_llm_error(max_retries=2, base_delay=1.0)
    def invoke(llm, messages):
        return llm.invoke(messages)

    @staticmethod
    @retry_on_llm_error(max_retries=2, base_delay=1.0)
    def stream(llm, messages):
        return llm.stream(messages)

    @staticmethod
    def extract_usage(response) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) from a response or chunk."""
        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, dict) and usage_metadata:
            return (
                _usage_number(usage_metadata, "input_tokens"),
                _usage_number(usage_metadata, "output_tokens"),
            )
        response_metadata = getattr(response, "response_metadata", None)
        usage = (
            response_metadata.get("token_usage", {})
            if isinstance(response_metadata, dict) else {}
        )
        return (
            _usage_number(usage, "prompt_tokens"),
            _usage_number(usage, "completion_tokens"),
        )

    @staticmethod
    def compact(messages, max_messages: int = 20):
        """Compact message history; never raise (mirrors BaseAgent behavior)."""
        try:
            from memory.service import MemoryService
            return MemoryService.compact_messages(messages, max_messages=max_messages)
        except Exception as e:
            logger.warning("Message compaction failed: %s", e)
            return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_runner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/llm_runner.py tests/test_llm_runner.py
git commit -m "feat(agents): extract LLMRunner pure model helpers"
```

---

## Task 3: ToolCallExecutor prefers session identity/trace (bug fix)

**Files:**
- Modify: `agents/executor.py`
- Test: `tests/test_agent_runtime_kernel.py` (new file; first test here)

`run()` gains an optional `session` parameter. When provided, identity comes from `session.mcp_identity()` (which carries the real `trace_id`); the agent name comes from the session. The existing `(tool_call, state, default_agent)` path is preserved as a fallback so nothing that still calls the old signature breaks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_runtime_kernel.py
"""Phase 1 runtime-kernel regressions: trace join, prompt isolation, limits."""

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage


def test_executor_uses_session_trace_id_for_identity():
    """The tool identity must carry the run's real trace_id, not context's None."""
    from agents.executor import ToolCallExecutor
    from agents.session import AgentSession
    from mcp_gateway import client as client_mod

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_runtime_kernel.py::test_executor_uses_session_trace_id_for_identity -v`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'session'`

- [ ] **Step 3: Write minimal implementation**

Modify `ToolCallExecutor.run` in [agents/executor.py](../../agents/executor.py) — change the signature and the identity/agent-name resolution:

```python
    def run(self, tool_call: dict, state: dict, default_agent: str, *, session=None) -> ToolMessage:
        from mcp_gateway.client import MCPClientIdentity, get_mcp_tool_client
        from agents.hooks import HookContext, HookEvent, get_hook_manager

        name = tool_call["name"]
        args = tool_call.get("args", {})
        tc_id = tool_call.get("id", "")

        agent_name = session.agent_name if session is not None else state.get("agent_type", default_agent)
        hooks = get_hook_manager()

        before = hooks.fire(HookContext(
            event=HookEvent.BEFORE_TOOL_CALL,
            agent_name=agent_name,
            state=state,
            tool_call=tool_call,
        ))
        if not before.allowed:
            content = json.dumps({
                "error": "TOOL_NOT_ALLOWED",
                "message": before.error or f"Tool '{name}' is not allowed",
            }, ensure_ascii=False)
            return ToolMessage(content=content, tool_call_id=tc_id)

        if session is not None:
            identity = session.mcp_identity()
        else:
            identity = MCPClientIdentity(
                user_id=state.get("user_id", 0),
                role=state.get("user_role", "student"),
                agent_type=state.get("agent_type", default_agent),
                task_id=state.get("context", {}).get("task_id"),
                conversation_id=state.get("context", {}).get("conversation_id"),
                trace_id=state.get("trace_id") or state.get("context", {}).get("trace_id"),
            )

        envelope = get_mcp_tool_client().call_tool(name, args, identity, tool_call_id=tc_id)
```

The rest of the method (the `AfterToolCall` hook fire and envelope→content mapping at [executor.py:54-79](../../agents/executor.py)) is unchanged.

Note the fallback also now reads `state.get("trace_id")` first — a defensive partial fix for any legacy caller.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_runtime_kernel.py::test_executor_uses_session_trace_id_for_identity -v`
Expected: PASS

- [ ] **Step 5: Run the boundary suite to confirm no regression**

Run: `pytest tests/test_agent_mcp_client_boundary.py -v`
Expected: PASS (all existing tests)

- [ ] **Step 6: Commit**

```bash
git add agents/executor.py tests/test_agent_runtime_kernel.py
git commit -m "fix(agents): tool identity carries real trace_id via AgentSession"
```

---

## Task 4: AgentRuntime facade

**Files:**
- Create: `agents/runtime.py`
- Test: `tests/test_agent_runtime_kernel.py` (add run smoke test)

`AgentRuntime` owns the invoke/stream orchestration that currently lives in `BaseAgent._invoke_with_mcp_tools` / `_stream_with_mcp_tools`. It takes a built `AgentSession` plus `tool_names` and `system_ctx`, acquires the trace, sets `session.trace_id = trace.run_id` **before** the loop (so tool calls get the right id), runs the loop via `LLMRunner` + `ToolCallExecutor`, and finalizes. It returns the updated `AgentState` dict (invoke) or yields events (stream), so `BaseAgent` callers are unchanged.

Move the loop logic verbatim from `base.py`, with three substitutions: (a) `self._llm_invoke`→`LLMRunner.invoke`, token extraction→`LLMRunner.extract_usage`, compaction→`LLMRunner.compact`; (b) the legacy-function parsing and stream-split helpers stay importable from `agents.base` (do not duplicate — import them); (c) tool execution calls `self._executor.run(tc, state, session.agent_name, session=session)`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_agent_runtime_kernel.py

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
    from agents.runtime import AgentRuntime
    from agents.session import AgentSession
    from langchain_core.messages import SystemMessage
    import agents.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod.AIConfig, "get_llm",
                        staticmethod(lambda tier=None: _mock_llm_no_tools()))

    from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_runtime_kernel.py::test_runtime_run_sets_trace_id_and_strips_system_prompt -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.runtime'`

- [ ] **Step 3: Write the implementation**

```python
# agents/runtime.py
"""AgentRuntime — thin facade that owns the invoke/stream orchestration.

The loop body is the same logic previously inlined in BaseAgent, now driven by
an AgentSession so trace/identity/budget come from one carrier. Trace ownership
(acquire/owns/finalize) is unchanged.
"""

import json
import logging

from langchain_core.messages import AIMessage, SystemMessage

from agents.config import AIConfig, MAX_LLM_CALLS_PER_TRACE, MAX_TOOL_ITERATIONS
from agents.executor import ToolCallExecutor
from agents.llm_runner import LLMRunner
from agents.base import (
    _parse_legacy_function_text,
    _split_safe_stream_content,
    _trace_links_from_state,
)
from core.exceptions import AgentExecutionLimitError, LLMError
from models.tiers import ModelTier

logger = logging.getLogger(__name__)

_HANDOFF_KEYS = (
    "handoff_to", "handoff_reason", "handoff_summary",
    "handoff_source", "previous_agents",
)


class AgentRuntime:
    """Run one agent session as invoke() or stream()."""

    _executor = ToolCallExecutor()

    def _acquire(self, session, system_ctx, tool_names):
        from core.observability.tracing import acquire_trace
        from tools.protocol import get_tool_runtime
        from tools.protocol.adapters import descriptors_to_llm_tools

        state = session.to_state()
        trace, owns_trace = acquire_trace(
            agent_type=session.agent_name,
            user_id=session.user_id,
            conversation_id=session.context.get("conversation_id"),
            links=_trace_links_from_state(state),
            input_message=(
                getattr(session.messages[-1], "content", "") if session.messages else ""
            ),
            input_context=session.context,
        )
        session.trace = trace
        session.trace_id = trace.run_id  # available to tool calls BEFORE the loop

        runtime = get_tool_runtime()
        descriptors = runtime.list_tools(names=tool_names)
        tool_schemas = descriptors_to_llm_tools(descriptors)

        tier = session.definition.default_model_tier if session.definition else ModelTier.BALANCED
        llm = AIConfig.get_llm(tier=tier)
        llm_with_tools = llm.bind_tools(tool_schemas)

        messages = [SystemMessage(content=system_ctx)] + list(session.messages)
        messages = LLMRunner.compact(messages, max_messages=20)
        return trace, owns_trace, llm_with_tools, messages

    def _apply_after_run(self, session, out_state):
        """Fire AFTER_AGENT_RUN, run handoff detection, and reflect handoff keys
        back onto the session so the caller's state (e.g. AgentHarness) sees them."""
        from agents.hooks import HookContext, HookEvent, get_hook_manager
        from graph.handoff import detect_handoff

        get_hook_manager().fire(HookContext(
            event=HookEvent.AFTER_AGENT_RUN,
            agent_name=session.agent_name,
            state=out_state,
            final_response=session.final_response,
        ))
        out_state = detect_handoff(out_state)
        for k in _HANDOFF_KEYS:
            if out_state.get(k) is not None:
                session.extra_state[k] = out_state[k]
        return out_state

    def run(self, session, *, tool_names, system_ctx):
        from core.observability.tracing import finalize_trace

        trace, owns_trace, llm_with_tools, messages = self._acquire(
            session, system_ctx, tool_names)
        state = session.to_state()  # boundary dict for executor/hooks

        response = None
        limit_exceeded = False
        try:
            for iteration in range(MAX_TOOL_ITERATIONS):
                if trace.llm_call_count >= MAX_LLM_CALLS_PER_TRACE:
                    logger.warning("Trace %s hit LLM budget; aborting %s loop",
                                   trace.run_id, session.agent_name)
                    limit_exceeded = True
                    break
                with trace.trace_llm_call() as llm_step:
                    try:
                        response = LLMRunner.invoke(llm_with_tools, messages)
                    except LLMError:
                        if iteration == 0:
                            raise
                        break
                    in_tok, out_tok = LLMRunner.extract_usage(response)
                    if in_tok or out_tok:
                        trace.total_input_tokens += in_tok
                        trace.total_output_tokens += out_tok
                        llm_step["prompt_tokens"] = in_tok
                        llm_step["completion_tokens"] = out_tok

                messages.append(response)
                legacy = _parse_legacy_function_text(getattr(response, "content", ""), tool_names)
                if legacy and not response.tool_calls:
                    response = AIMessage(content="", tool_calls=[legacy])
                    messages[-1] = response

                if not response.tool_calls:
                    break

                for tc in response.tool_calls:
                    with trace.trace_tool_call(tc["name"], tc["args"]):
                        tool_msg = self._executor.run(tc, state, session.agent_name, session=session)
                        messages.append(tool_msg)
            else:
                limit_exceeded = bool(response and response.tool_calls)

            session.messages = [m for m in messages if not isinstance(m, SystemMessage)]

            if limit_exceeded:
                error = AgentExecutionLimitError(session.agent_name, MAX_TOOL_ITERATIONS)
                session.final_response = error.user_message
                finalize_trace(trace, owns_trace, status="limit_exceeded",
                               response=error.user_message, error=error)
                return session.to_state()

            session.final_response = (response.content if response and response.content else "")
            out_state = self._apply_after_run(session, session.to_state())
            finalize_trace(trace, owns_trace, status="completed",
                           response=session.final_response)
            return out_state
        except Exception as e:
            finalize_trace(trace, owns_trace, status="failed", error=e)
            raise

    def stream(self, session, *, tool_names, system_ctx):
        from core.observability.tracing import finalize_trace

        trace, owns_trace, llm_with_tools, messages = self._acquire(
            session, system_ctx, tool_names)
        state = session.to_state()

        trace_saved = False
        limit_exceeded = False
        try:
            for iteration in range(MAX_TOOL_ITERATIONS):
                if trace.llm_call_count >= MAX_LLM_CALLS_PER_TRACE:
                    limit_exceeded = True
                    break

                collected_content = ""
                pending_content = ""
                tool_calls = []
                try:
                    with trace.trace_llm_call() as llm_step:
                        for chunk in LLMRunner.stream(llm_with_tools, messages):
                            if chunk.content:
                                collected_content += chunk.content
                                pending_content += chunk.content
                                safe, pending_content = _split_safe_stream_content(pending_content)
                                if safe:
                                    yield {"type": "token", "content": safe}
                            if chunk.tool_call_chunks:
                                for tcc in chunk.tool_call_chunks:
                                    if tcc.get("index") is not None:
                                        idx = tcc["index"]
                                        while len(tool_calls) <= idx:
                                            tool_calls.append({"name": "", "args": "", "id": ""})
                                        if tcc.get("name"):
                                            tool_calls[idx]["name"] = tcc["name"]
                                        if tcc.get("args"):
                                            tool_calls[idx]["args"] += tcc["args"]
                                        if tcc.get("id"):
                                            tool_calls[idx]["id"] = tcc["id"]
                            in_tok, out_tok = LLMRunner.extract_usage(chunk)
                            if in_tok or out_tok:
                                trace.total_input_tokens += in_tok
                                trace.total_output_tokens += out_tok
                                llm_step["prompt_tokens"] = llm_step.get("prompt_tokens", 0) + in_tok
                                llm_step["completion_tokens"] = llm_step.get("completion_tokens", 0) + out_tok
                except LLMError as e:
                    if iteration == 0:
                        yield {"type": "error", "message": e.user_message}
                        finalize_trace(trace, owns_trace, status="failed", error=e)
                        trace_saved = True
                        return
                    break

                legacy = _parse_legacy_function_text(collected_content, tool_names)
                if legacy and not tool_calls:
                    tool_calls = [legacy]
                    collected_content = ""

                if not tool_calls:
                    if pending_content:
                        yield {"type": "token", "content": pending_content}
                    session.final_response = collected_content
                    messages.append(AIMessage(content=collected_content))
                    break

                parsed_calls = []
                for tc in tool_calls:
                    if not tc["name"]:
                        continue
                    args = tc["args"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parsed_calls.append({"name": tc["name"], "args": args, "id": tc["id"]})

                messages.append(AIMessage(content=collected_content, tool_calls=parsed_calls))
                for tc in parsed_calls:
                    yield {"type": "tool_call", "tool": tc["name"], "input": str(tc["args"])}
                    with trace.trace_tool_call(tc["name"], tc["args"]):
                        tool_msg = self._executor.run(tc, state, session.agent_name, session=session)
                        messages.append(tool_msg)
                    yield {"type": "tool_result", "tool": tc["name"],
                           "summary": f"Fetched {tc['name']} result"}
            else:
                limit_exceeded = True

            session.messages = [m for m in messages if not isinstance(m, SystemMessage)]

            if limit_exceeded:
                error = AgentExecutionLimitError(session.agent_name, MAX_TOOL_ITERATIONS)
                session.final_response = error.user_message
                yield {"type": "error", "message": error.user_message}
                finalize_trace(trace, owns_trace, status="limit_exceeded",
                               response=error.user_message, error=error)
                trace_saved = True
                return

            out_state = self._apply_after_run(session, session.to_state())
            if out_state.get("handoff_to"):
                yield {"type": "handoff", "target": out_state["handoff_to"],
                       "reason": out_state.get("handoff_reason", "")}

            finalize_trace(trace, owns_trace, status="completed",
                           response=session.final_response)
            trace_saved = True
        except GeneratorExit:
            if not trace_saved:
                finalize_trace(trace, owns_trace, status="interrupted")
                trace_saved = True
        except Exception as e:
            if not trace_saved:
                finalize_trace(trace, owns_trace, status="failed", error=e)
                trace_saved = True
            raise
```

Note: `_apply_after_run` reproduces `BaseAgent._fire_after_agent_run` (which reads `agent_name=state.get("agent_type", self.name)` — equivalent to `session.agent_name`). The `BEFORE_AGENT_RUN` hook and the security-alert injection still happen in `BaseAgent` *before* it builds the session (Task 5), so the `system_ctx` passed in is already alerted.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_runtime_kernel.py::test_runtime_run_sets_trace_id_and_strips_system_prompt -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/runtime.py tests/test_agent_runtime_kernel.py
git commit -m "feat(agents): add AgentRuntime invoke/stream orchestration facade"
```

---

## Task 5: BaseAgent delegates to AgentRuntime

**Files:**
- Modify: `agents/base.py:206-329` (`_invoke_with_mcp_tools`), `agents/base.py:331-494` (`_stream_with_mcp_tools`)
- Test: existing `tests/test_agents.py`, `tests/test_agent_features.py`, `tests/test_handoff_context.py`

`BaseAgent` keeps `_fire_before_agent_run`, `_maybe_inject_security_alert`, `_run_mcp_tool`, `_tool_executor`, and the module-level helpers (`_parse_legacy_function_text`, `_split_safe_stream_content`, `_trace_links_from_state`, `_usage_number`) — `agents/runtime.py` imports the helpers. The two big methods shrink to: fire before-hook → inject alert → build session → delegate → copy result back into the caller's `state`.

- [ ] **Step 1: Replace `_invoke_with_mcp_tools` body**

Replace the entire method body ([base.py:206-329](../../agents/base.py)) with:

```python
    def _invoke_with_mcp_tools(self, state: AgentState, tool_names: list[str], system_ctx: str) -> AgentState:
        """Build a session and delegate the invoke loop to AgentRuntime."""
        from agents.runtime import AgentRuntime
        from agents.session import AgentSession

        self._fire_before_agent_run(state)
        system_ctx = self._maybe_inject_security_alert(system_ctx, state)

        session = AgentSession.from_state(state, agent_name=self.name)
        result = AgentRuntime().run(session, tool_names=tool_names, system_ctx=system_ctx)
        # Preserve the historical in-place mutation contract: callers and the
        # harness read the updated state dict they passed in.
        state.update(result)
        return state
```

- [ ] **Step 2: Replace `_stream_with_mcp_tools` body**

Replace the entire method body ([base.py:331-494](../../agents/base.py)) with:

```python
    def _stream_with_mcp_tools(self, state: AgentState, tool_names: list[str], system_ctx: str):
        """Build a session and delegate the stream loop to AgentRuntime."""
        from agents.runtime import AgentRuntime
        from agents.session import AgentSession

        self._fire_before_agent_run(state)
        system_ctx = self._maybe_inject_security_alert(system_ctx, state)

        session = AgentSession.from_state(state, agent_name=self.name)
        yield from AgentRuntime().stream(session, tool_names=tool_names, system_ctx=system_ctx)
        # After the generator finishes, mirror final messages/final_response and
        # handoff keys back onto the caller's state (AgentHarness reads handoff_to).
        state.update(session.to_state())
```

Note: `AgentRuntime._apply_after_run` writes handoff keys into `session.extra_state`, so `session.to_state()` carries them; this preserves the `AgentHarness` loop at [agent_harness.py:99](../../evals/harness/agent_harness.py).

- [ ] **Step 3: Verify the leftover helpers are still present**

Confirm these remain defined in `agents/base.py` (used by the runtime import and by direct callers/tests): `_parse_legacy_function_text`, `_split_safe_stream_content`, `_trace_links_from_state`, `_usage_number`, `BaseAgent._run_mcp_tool`, `BaseAgent._tool_executor`, `BaseAgent._fire_before_agent_run`, `BaseAgent._fire_after_agent_run`, `BaseAgent._maybe_inject_security_alert`. Do not delete them.

- [ ] **Step 4: Run the agent + handoff suites**

Run: `pytest tests/test_agents.py tests/test_agent_features.py tests/test_handoff_context.py -v`
Expected: PASS. If a handoff test fails, verify Step 2's `state.update(session.to_state())` and that `_apply_after_run` populated `extra_state` with the handoff keys.

- [ ] **Step 5: Run the runtime-kernel + boundary + hooks suites**

Run: `pytest tests/test_agent_runtime_kernel.py tests/test_agent_mcp_client_boundary.py tests/test_agent_hooks.py -v`
Expected: PASS. `test_base_agent_delegates_tool_execution_to_executor` asserts `_run_mcp_tool` references `_tool_executor` — keep both defined.

- [ ] **Step 6: Commit**

```bash
git add agents/base.py
git commit -m "refactor(agents): BaseAgent delegates invoke/stream to AgentRuntime"
```

---

## Task 6: AgentHarness single-trace path holds through the kernel

**Files:**
- Modify: `evals/harness/agent_harness.py` (comment only; no functional change)
- Test: existing `tests/test_agent_harness_trace_binding.py`, `tests/test_eval_harness_trace_binding.py`

The harness already owns the trace and binds it ambiently, so `acquire_trace` inside the runtime correctly reuses it (`owns_trace=False`) and the single-trace guarantee holds. `budget`/`source` flow to the runtime via the ambient `TraceCollector`, not via state. The change here is a regression test proving the harness path now produces a tool-call `trace_id` equal to the run `trace_id` (harness-level proof of the Task 3 fix), plus a clarifying comment.

- [ ] **Step 1: Add a regression test for trace_id join via the harness**

```python
# add to tests/test_agent_harness_trace_binding.py

class _ToolThenDoneLLM:
    """First stream() yields a tool call; second yields a plain finish."""

    def __init__(self):
        self._calls = 0

    def bind_tools(self, _schemas):
        return self

    def stream(self, _messages):
        self._calls += 1
        if self._calls == 1:
            chunk = _Chunk("")
            chunk.tool_call_chunks = [
                {"index": 0, "name": "coderunner.problem.get_detail",
                 "args": "{}", "id": "tc1"}
            ]
            return [chunk]
        return [_Chunk("done", {"input_tokens": 1, "output_tokens": 1})]


@patch("agents.runtime.AIConfig")
def test_harness_tool_calls_share_run_trace_id(mock_config, app, db_session, teacher_user):
    with app.app_context():
        from evals.harness.agent_harness import AgentHarness
        from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
        from mcp_gateway import client as client_mod

        captured = {}

        class _FakeClient:
            def call_tool(self, name, args, identity, tool_call_id=""):
                captured["trace_id"] = identity.trace_id
                return {"ok": True, "data": {"ok": 1}}

        mock_config.get_llm.return_value = _ToolThenDoneLLM()
        mock_config.validate.return_value = None

        mock_rt = MagicMock(spec=ToolRuntime)
        mock_rt.list_tools.return_value = []
        set_tool_runtime(mock_rt)
        client_mod.set_mcp_tool_client(_FakeClient())
        try:
            result = AgentHarness().run(
                agent_type="tutor", message="help",
                user_id=teacher_user.id, user_role="teacher",
                source="workers", context={"conversation_id": 10},
            )
        finally:
            reset_tool_runtime()
            client_mod.set_mcp_tool_client(None)

        assert captured["trace_id"] == result.trace_id
```

- [ ] **Step 2: Run test to verify it passes with the kernel in place**

Run: `pytest tests/test_agent_harness_trace_binding.py::test_harness_tool_calls_share_run_trace_id -v`
Expected: PASS. If it fails with `trace_id is None`, the ambient trace's `run_id` is not reaching `session.trace_id` — confirm `AgentRuntime._acquire` sets `session.trace_id = trace.run_id` and that `@patch` targets `agents.runtime.AIConfig` (the runtime is where `get_llm` is now called).

- [ ] **Step 3: Add a clarifying comment in the harness**

In [agent_harness.py:62-70](../../evals/harness/agent_harness.py), above the `state = {...}` block, add:

```python
        # budget/source reach the agent runtime via the ambient TraceCollector
        # below (use_current_trace), not through this state dict.
```

Do NOT change the trace-creation block at [agent_harness.py:78-90](../../evals/harness/agent_harness.py) — it is load-bearing for the single-trace guarantee.

- [ ] **Step 4: Run both harness suites**

Run: `pytest tests/test_agent_harness_trace_binding.py tests/test_eval_harness_trace_binding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evals/harness/agent_harness.py tests/test_agent_harness_trace_binding.py
git commit -m "test(harness): assert harness tool calls share the run trace_id"
```

---

## Task 7: Consolidated regression guard

**Files:**
- Test: `tests/test_agent_runtime_kernel.py` (add the remaining acceptance assertions)

Cover the Phase 1 acceptance criteria that aren't yet pinned by a focused test.

- [ ] **Step 1: Read the limit-exceeded message before asserting on it**

Run: `grep -n "class AgentExecutionLimitError" -A 15 core/exceptions.py`
Note the exact `user_message` string so the next test asserts on real text.

- [ ] **Step 2: Add limit_exceeded regression test**

```python
# add to tests/test_agent_runtime_kernel.py

def test_runtime_limit_exceeded_stops_after_max_iterations(monkeypatch):
    """A model that always wants another tool call ends in limit_exceeded."""
    from agents.runtime import AgentRuntime
    from agents.session import AgentSession
    import agents.runtime as runtime_mod
    from agents.config import MAX_TOOL_ITERATIONS

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

    from mcp_gateway import client as client_mod
    client_mod.set_mcp_tool_client(
        type("C", (), {"call_tool": lambda self, *a, **k: {"ok": True, "data": {}}})()
    )
    from tools.protocol.runtime import ToolRuntime, set_tool_runtime, reset_tool_runtime
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
```

- [ ] **Step 3: Add tool-allowlist-deny still-blocks test**

```python
def test_runtime_blocks_undeclared_tool():
    """A tool outside the agent allowlist is denied before crossing the client."""
    from agents.executor import ToolCallExecutor
    from agents.session import AgentSession

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
```

- [ ] **Step 4: Run the full new file**

Run: `pytest tests/test_agent_runtime_kernel.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full Phase 1 regression set**

Run: `pytest tests/test_agents.py tests/test_agent_features.py tests/test_agent_hooks.py tests/test_agent_contracts.py tests/test_agent_mcp_client_boundary.py tests/test_agent_harness_trace_binding.py tests/test_eval_harness_trace_binding.py tests/test_handoff_context.py tests/test_agent_session.py tests/test_llm_runner.py tests/test_agent_runtime_kernel.py -v`
Expected: PASS (the whole Phase 1 surface, green)

- [ ] **Step 6: Commit**

```bash
git add tests/test_agent_runtime_kernel.py
git commit -m "test(agents): pin Phase 1 runtime-kernel acceptance criteria"
```

---

## Acceptance Criteria (from the upgrade plan)

- [ ] Every agent run maps to one session and one trace — `AgentSession` constructed per run; `acquire_trace` owns/borrows exactly as before.
- [ ] Tool-call audit uses the same `trace_id` as the agent trace — `test_executor_uses_session_trace_id_for_identity` + `test_harness_tool_calls_share_run_trace_id`.
- [ ] The system prompt is never written back into conversation history — `test_runtime_run_sets_trace_id_and_strips_system_prompt`.
- [ ] `limit_exceeded`, hooks, handoff, output validation do not regress — Task 5/7 suites.
- [ ] Sync invoke, stream, and worker harness tests still pass — Task 7 Step 5.

## Out of scope (per the upgrade plan)

- No dashboard / trace viewer UI.
- No MCP Gateway rewrite.
- No eval dataset expansion.
- No specialist agent prompt rewrites.
- No new external LLM provider.

## Risks & Mitigations

- **Dual-carrier divergence (state vs session):** `from_state`/`to_state` must round-trip losslessly, including unknown keys via `extra_state`. Task 1's round-trip test guards this; Task 5 adds the caller-dict write-back so `AgentHarness` still reads `handoff_to`.
- **Trace ownership change:** Only `_acquire` calls `acquire_trace`; `finalize_trace(trace, owns_trace, ...)` is called with the original `owns_trace` flag — never hard-code `save()`.
- **Stream fault paths:** `GeneratorExit`→`interrupted` and the `trace_saved` flag are copied verbatim into `AgentRuntime.stream`; do not "simplify" them.
- **Circular import:** `agents.runtime` imports module-level helpers from `agents.base`; `agents.base` imports `agents.runtime` only inside methods (function-local), as written in Task 5. Keep it that way.
- **`@patch` target moved:** model calls now happen in `agents.runtime`. Tests that previously patched `agents.base.AIConfig` for tool-loop behavior must patch `agents.runtime.AIConfig`. The existing `tests/test_agent_harness_trace_binding.py` patches `agents.base.AIConfig` — verify whether it still needs to (it patches before the harness runs; if it goes green unchanged, leave it; if not, repoint to `agents.runtime.AIConfig`).
```