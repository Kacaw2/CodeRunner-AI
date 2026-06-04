# Phase 2: Declarative Agent Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `core/definitions.py` the single source of truth for agent configuration, so every runtime path (API, worker, orchestrator, eval harness, hooks) reads capabilities — tools, roles, model tier, output schema, per-agent budget, handoff targets, rate limit — from one registry, and adding a new agent stops requiring edits in many places.

**Architecture:** The registry already drives *capability lookups* — tool allowlist ([hooks.py:151](../../agents/hooks.py), [base.py:120](../../agents/base.py)), role routing ([handoff.py:63](../../graph/handoff.py)), model tier ([runtime.py:60](../../agents/runtime.py)), output schema ([hooks.py:175](../../agents/hooks.py)), input contract ([contracts.py](../../agents/contracts.py)). Phase 2 closes the remaining gaps: (1) the **name→class instantiation** is hand-duplicated in five files with no central factory — this is the real "edit many places" pain; (2) per-agent execution budget and rate limit are global constants instead of per-agent declarations; (3) the handoff target set is hardcoded in `graph/handoff.py` rather than declared per agent; (4) `name`/`description`/`default_model_tier` are declared twice (on the agent class *and* in the definition). We extend `AgentDefinition` with a small set of concrete fields, add an `agents/registry.py` factory keyed by the same names, repoint the five call sites and the budget/handoff/rate-limit consumers at the registry, strip the duplicated class attributes, and add consistency tests that fail on drift.

**Tech Stack:** Python 3, frozen dataclasses (`core/definitions.py` stays pure data — no import of agent classes), LangChain core messages, pytest (`tests/` suite with `app` / `db_session` / `teacher_user` fixtures in `tests/conftest.py`), DeepSeek via `AIConfig.get_llm`.

---

## Scope decisions (read before starting)

These narrow the upgrade-plan's Phase 2 "具体方向" to what is concrete and non-overlapping:

- **`budget_policy` is dropped.** Two concrete integers (`max_tool_iterations`, and the existing trace-level cap) cover the real need; a policy wrapper is design for a requirement that does not exist.
- **`context_policy` is deferred to Phase 5.** It is the core of Phase 5 (context/memory architecture). Adding the field now with no consumer creates a dead field. The only context knob touched here is the existing `compact(max_messages=20)`, left as-is.
- **`max_llm_calls` stays trace-level, not per-agent.** `MAX_LLM_CALLS_PER_TRACE` ([config.py:18-23](../../agents/config.py)) caps aggregate LLM usage across an entire handoff chain / workflow / chat task — a different axis from a single agent's loop. It remains a chain guardrail and is **not** moved into a per-agent definition.
- **The name→class factory is added explicitly.** Without it, the acceptance criterion "新增 agent 不需要修改多处运行时分支" cannot be met, because `AgentDefinition` is pure data and cannot carry a class reference.
- **`prompt_ref` references the static base prompt only.** The live system context is assembled dynamically per agent in `_build_system_context()` (memory, KB, runtime context injection). `prompt_ref` records which base prompt constant an agent uses; it does not replace `_build_system_context()`.

## File Structure

| File | Responsibility | Created/Modified |
|---|---|---|
| `core/definitions.py` | Extend `AgentDefinition` with `max_tool_iterations`, `rate_limit`, `handoff_targets`, `prompt_ref`; populate the four definitions; add accessor helpers | Modify |
| `agents/registry.py` | `AGENT_CLASSES` map + `get_agent_class(name)` / `get_agent_instance(name)` factory keyed by definition names | Create |
| `agents/runtime.py` | `_acquire`/loops read `session.definition.max_tool_iterations` (fallback to module default) | Modify |
| `agents/config.py` | `MAX_TOOL_ITERATIONS` becomes the fallback default; `AGENT_RATE_LIMITS` deprecated in favor of registry (kept as fallback) | Modify |
| `graph/handoff.py` | `VALID_HANDOFF_TARGETS` + per-target validation derived from registry `handoff_targets` | Modify |
| `app/api/v1/ai.py` | Rate limit + agent instantiation read from registry/factory | Modify |
| `workers/chat.py` | `_AGENT_MAP` replaced by the factory | Modify |
| `graph/runner.py` | `_AGENTS` built from the factory | Modify |
| `evals/runner.py` | `agent_map` replaced by the factory | Modify |
| `evals/harness/agent_harness.py` | `_AGENT_MAP` replaced by the factory | Modify |
| `agents/tutor/agent.py`, `reviewer/agent.py`, `generator/agent.py`, `analytics/agent.py` | Drop duplicated `description`/`default_model_tier`; keep `name` | Modify |
| `tests/test_agent_registry.py` | Factory resolves every definition; round-trip; consistency assertions | Create |
| `tests/test_definitions_consistency.py` | `handoff_targets ⊆ registry`, `allowed_tools ⊆ tool catalog`, `output_schema_name` resolves, budgets sane | Create |

## Constraints (do not violate)

- `core/definitions.py` MUST stay pure data — it MUST NOT import agent classes (would create a circular import; the class map lives in `agents/registry.py`).
- The four specialist agents' `invoke(state)` / `stream(state)` signatures and external behavior MUST be unchanged. Existing suites (`tests/test_agents.py`, `tests/test_agent_features.py`, `tests/test_agent_hooks.py`, `tests/test_agent_contracts.py`, `tests/test_model_router_and_definitions.py`, `tests/test_handoff_context.py`) MUST stay green.
- Default behavior MUST NOT change for the current four agents: their new `max_tool_iterations` defaults MUST equal the current global `5`, and `rate_limit` MUST equal the current `AGENT_RATE_LIMITS` values, so no live limit shifts.
- The trace-level `MAX_LLM_CALLS_PER_TRACE` guardrail MUST remain in force exactly as today.
- `frozen=True` on `AgentDefinition` MUST be preserved; new collection fields use immutable types (`tuple`, `frozenset`) so the dataclass stays hashable/frozen.

---

## Task 1: Extend AgentDefinition with concrete fields

**Files:**
- Modify: `core/definitions.py`
- Test: `tests/test_definitions_consistency.py` (new file; first tests here)

Add four fields to the frozen dataclass with defaults that preserve current behavior, then populate them on the four definitions. `handoff_targets` declares the legal downstream agents for each agent (mirrors today's universal "any of the four except self/role-blocked" but now per-agent and data-driven). `prompt_ref` is a dotted reference string to the base prompt constant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_definitions_consistency.py
"""Registry consistency: every definition is internally coherent and its
references resolve. These fail loudly on drift so a new agent cannot ship
half-wired."""

import importlib

from core.definitions import AGENT_DEFINITIONS


def test_every_definition_declares_budget_and_rate_limit():
    for name, defn in AGENT_DEFINITIONS.items():
        assert defn.max_tool_iterations >= 1, name
        assert defn.rate_limit >= 1, name


def test_current_agents_keep_their_legacy_defaults():
    # No live behavior shift: tutor/reviewer/generator/analytics keep iterations=5
    # and the previous AGENT_RATE_LIMITS values.
    expected_rate = {"tutor": 20, "reviewer": 10, "generator": 5, "analytics": 10}
    for name, defn in AGENT_DEFINITIONS.items():
        assert defn.max_tool_iterations == 5, name
        assert defn.rate_limit == expected_rate[name], name


def test_handoff_targets_are_known_agents_and_exclude_self():
    names = set(AGENT_DEFINITIONS)
    for name, defn in AGENT_DEFINITIONS.items():
        assert name not in defn.handoff_targets, f"{name} hands off to itself"
        assert set(defn.handoff_targets) <= names, name


def test_prompt_ref_resolves_to_an_importable_constant():
    for name, defn in AGENT_DEFINITIONS.items():
        if not defn.prompt_ref:
            continue
        module_path, attr = defn.prompt_ref.rsplit(".", 1)
        module = importlib.import_module(module_path)
        assert hasattr(module, attr), defn.prompt_ref
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_definitions_consistency.py -v`
Expected: FAIL with `AttributeError: 'AgentDefinition' object has no attribute 'max_tool_iterations'`

- [ ] **Step 3: Extend the dataclass and populate the definitions**

In [core/definitions.py](../../core/definitions.py), add to `AgentDefinition` (after `output_schema_name`):

```python
    max_tool_iterations: int = 5          # per-agent tool-loop ceiling
    rate_limit: int = 20                  # requests/minute (was AGENT_RATE_LIMITS)
    handoff_targets: frozenset[str] = frozenset()
    prompt_ref: str | None = None         # dotted path to the base system prompt
```

Then add the fields to each definition. Values that preserve today's behavior:

| agent | max_tool_iterations | rate_limit | handoff_targets | prompt_ref |
|---|---|---|---|---|
| tutor | 5 | 20 | `{"reviewer","analytics"}` | `agents.tutor.prompt.TUTOR_SYSTEM_PROMPT` |
| reviewer | 5 | 10 | `{"tutor","analytics"}` | `agents.reviewer.prompt.REVIEWER_SYSTEM_PROMPT` |
| generator | 5 | 5 | `{"analytics"}` | `agents.generator.prompt.GENERATOR_SYSTEM_PROMPT` |
| analytics | 5 | 10 | `{"tutor","reviewer"}` | `agents.analytics.prompt.ANALYTICS_SYSTEM_PROMPT` |

> Note on `handoff_targets`: today every agent could hand off to any other (role permitting). The table above codifies the *intended* graph (e.g. a student-facing handoff never targets the teacher-only `generator`). Before committing, confirm each prompt's actual handoff examples match — if a current prompt suggests a handoff not in this set, either widen the set or fix the prompt in a follow-up, and record the decision here. Do NOT silently narrow live behavior.

Verify the exact prompt constant names first:

Run: `grep -rn "_SYSTEM_PROMPT" agents/*/prompt.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_definitions_consistency.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the existing definitions suite for no regression**

Run: `pytest tests/test_model_router_and_definitions.py tests/test_agent_contracts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/definitions.py tests/test_definitions_consistency.py
git commit -m "feat(definitions): add per-agent budget, rate_limit, handoff_targets, prompt_ref"
```

---

## Task 2: Agent factory (the missing single instantiation point)

**Files:**
- Create: `agents/registry.py`
- Test: `tests/test_agent_registry.py`

This is the keystone of Phase 2. `core/definitions.py` is pure data; the class map must live in the `agents/` layer, keyed by the same names. Every runtime path will resolve `name → instance` through this factory instead of its own local dict.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_registry.py
"""The factory is the single name->class resolution point. Every declared
definition must resolve to a concrete BaseAgent subclass, and vice versa."""

import pytest

from core.definitions import AGENT_DEFINITIONS


def test_every_definition_has_a_registered_class():
    from agents.registry import AGENT_CLASSES
    from agents.base import BaseAgent

    assert set(AGENT_CLASSES) == set(AGENT_DEFINITIONS)
    for name, cls in AGENT_CLASSES.items():
        assert issubclass(cls, BaseAgent), name
        assert cls.name == name, f"{cls.__name__}.name != registry key {name}"


def test_get_agent_instance_returns_correct_type():
    from agents.registry import get_agent_instance
    from agents.tutor.agent import TutorAgent

    inst = get_agent_instance("tutor")
    assert isinstance(inst, TutorAgent)


def test_unknown_agent_raises():
    from agents.registry import get_agent_class

    with pytest.raises(KeyError):
        get_agent_class("nonexistent")


def test_get_agent_instance_default_for_router_fallback():
    # The routing call sites fall back to tutor on an unknown type; the factory
    # exposes that as an explicit default rather than each site hardcoding it.
    from agents.registry import get_agent_instance
    from agents.tutor.agent import TutorAgent

    inst = get_agent_instance("garbage", default="tutor")
    assert isinstance(inst, TutorAgent)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.registry'`

- [ ] **Step 3: Write the factory**

```python
# agents/registry.py
"""Single name->class resolution point for the four specialist agents.

`core.definitions` is pure data and cannot reference the agent classes; this
module is the `agents/`-layer companion that maps the same definition names to
their concrete `BaseAgent` subclasses. Every runtime path (API, worker,
orchestrator, eval harness) resolves agents here instead of keeping its own
local dict, so adding an agent means editing this map plus its definition — not
five call sites.
"""

from __future__ import annotations

from agents.base import BaseAgent
from agents.tutor.agent import TutorAgent
from agents.reviewer.agent import ReviewerAgent
from agents.generator.agent import GeneratorAgent
from agents.analytics.agent import AnalyticsAgent

AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "tutor": TutorAgent,
    "reviewer": ReviewerAgent,
    "generator": GeneratorAgent,
    "analytics": AnalyticsAgent,
}


def get_agent_class(name: str, default: str | None = None) -> type[BaseAgent]:
    """Return the agent class for *name*.

    With *default* set, an unknown name resolves to the default class instead of
    raising — mirrors the routing call sites' historical fallback to tutor.
    """
    if name in AGENT_CLASSES:
        return AGENT_CLASSES[name]
    if default is not None:
        return AGENT_CLASSES[default]
    raise KeyError(f"No agent registered for '{name}'")


def get_agent_instance(name: str, default: str | None = None) -> BaseAgent:
    return get_agent_class(name, default=default)()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_registry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/registry.py tests/test_agent_registry.py
git commit -m "feat(agents): add name->class factory as single agent resolution point"
```

---

## Task 3: Repoint the five call sites at the factory

**Files:**
- Modify: `workers/chat.py`, `app/api/v1/ai.py`, `graph/runner.py`, `evals/runner.py`, `evals/harness/agent_harness.py`
- Test: existing `tests/test_agents.py`, `tests/test_agent_harness_trace_binding.py`, `tests/test_eval_harness_trace_binding.py`, plus a guard test

Each site currently builds its own `name → class` dict and falls back to `TutorAgent`. Replace each with the factory. Keep behavior identical: the fallback default stays `"tutor"`.

- [ ] **Step 1: Add a guard test that no runtime module keeps a private agent map**

```python
# add to tests/test_agent_registry.py
import re
from pathlib import Path


def test_no_runtime_module_redeclares_an_agent_class_map():
    """Guard against a sixth hand-rolled name->class dict creeping back in.

    Allowed to import the classes (e.g. for isinstance), but not to build a
    `{"tutor": TutorAgent, ...}` dispatch dict outside agents/registry.py.
    """
    root = Path(__file__).resolve().parents[1]
    suspects = [
        root / "workers" / "chat.py",
        root / "app" / "api" / "v1" / "ai.py",
        root / "graph" / "runner.py",
        root / "evals" / "runner.py",
        root / "evals" / "harness" / "agent_harness.py",
    ]
    pattern = re.compile(r'["\']tutor["\']\s*:\s*TutorAgent')
    for path in suspects:
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path} still hand-rolls an agent map"
```

- [ ] **Step 2: Run it to confirm it currently fails**

Run: `pytest tests/test_agent_registry.py::test_no_runtime_module_redeclares_an_agent_class_map -v`
Expected: FAIL (the five maps still exist)

- [ ] **Step 3: Replace `evals/harness/agent_harness.py`**

Remove the import block and `_AGENT_MAP` ([agent_harness.py:12-21](../../evals/harness/agent_harness.py)). Replace `_AGENT_MAP.get(resolved, TutorAgent)()` ([agent_harness.py:93](../../evals/harness/agent_harness.py)) and the handoff lookups ([agent_harness.py:104](../../evals/harness/agent_harness.py), [agent_harness.py:116](../../evals/harness/agent_harness.py)) with the factory:

```python
from agents.registry import get_agent_instance, AGENT_CLASSES
# ...
agent = get_agent_instance(resolved, default="tutor")
# handoff guard:  state["handoff_to"] in AGENT_CLASSES
target_agent = get_agent_instance(target_type, default="tutor")
```

- [ ] **Step 4: Replace `workers/chat.py`**

Same transformation at [workers/chat.py:156-164](../../workers/chat.py), [chat.py:204](../../workers/chat.py), [chat.py:219](../../workers/chat.py), [chat.py:237](../../workers/chat.py). Use `AGENT_CLASSES` for the `in` membership check and `get_agent_instance(..., default="tutor")` for construction.

- [ ] **Step 5: Replace `app/api/v1/ai.py`**

Same transformation at [ai.py:438-445](../../app/api/v1/ai.py), [ai.py:467](../../app/api/v1/ai.py), [ai.py:487](../../app/api/v1/ai.py), [ai.py:499](../../app/api/v1/ai.py). The single-agent imports later in the file (e.g. [ai.py:870](../../app/api/v1/ai.py) `ReviewerAgent`, [ai.py:946](../../app/api/v1/ai.py) `GeneratorAgent`) may stay as direct imports — they are explicit one-agent endpoints, not dispatch dicts — but prefer `get_agent_instance("reviewer")` for consistency where trivial.

- [ ] **Step 6: Replace `graph/runner.py`**

`_AGENTS` ([runner.py:14-18](../../graph/runner.py)) becomes `{name: get_agent_instance(name) for name in AGENT_CLASSES}`. `VALID_AGENT_TYPES` and the loops at [runner.py:225-238](../../graph/runner.py) keep working since they iterate `_AGENTS`.

- [ ] **Step 7: Replace `evals/runner.py`**

Same at [runner.py:139-147](../../evals/runner.py).

- [ ] **Step 8: Run the guard + the affected suites**

Run: `pytest tests/test_agent_registry.py tests/test_agents.py tests/test_agent_harness_trace_binding.py tests/test_eval_harness_trace_binding.py -v`
Expected: PASS (guard now green; no behavior regression)

- [ ] **Step 9: Commit**

```bash
git add workers/chat.py app/api/v1/ai.py graph/runner.py evals/runner.py evals/harness/agent_harness.py tests/test_agent_registry.py
git commit -m "refactor(agents): resolve agents through the factory, drop five local maps"
```

---

## Task 4: Per-agent tool-iteration budget from the registry

**Files:**
- Modify: `agents/runtime.py`, `agents/config.py`
- Test: `tests/test_agent_runtime_kernel.py` (add a per-agent budget test)

`MAX_TOOL_ITERATIONS` becomes the fallback default; the live ceiling comes from `session.definition.max_tool_iterations`. The trace-level `MAX_LLM_CALLS_PER_TRACE` check is untouched.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_agent_runtime_kernel.py

def test_runtime_uses_per_agent_iteration_budget(monkeypatch):
    """The loop ceiling comes from the agent definition, not the global const."""
    from agents.runtime import AgentRuntime
    from agents.session import AgentSession
    import agents.runtime as runtime_mod

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
        # Override the definition's budget to a small number for the test.
        import dataclasses
        session.definition = dataclasses.replace(session.definition, max_tool_iterations=2)
        AgentRuntime().run(
            session, tool_names=["coderunner.problem.get_detail"], system_ctx="SYS")
        assert llm.invoke.call_count == 2
    finally:
        reset_tool_runtime()
        client_mod.set_mcp_tool_client(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_runtime_kernel.py::test_runtime_uses_per_agent_iteration_budget -v`
Expected: FAIL (`call_count == 5`, the global default)

- [ ] **Step 3: Read the per-agent ceiling in the runtime**

In [agents/runtime.py](../../agents/runtime.py), add a helper and use it in both `run` and `stream`:

```python
    @staticmethod
    def _max_iterations(session) -> int:
        defn = session.definition
        if defn is not None and getattr(defn, "max_tool_iterations", None):
            return defn.max_tool_iterations
        return MAX_TOOL_ITERATIONS  # fallback for unregistered agents
```

Replace `for iteration in range(MAX_TOOL_ITERATIONS):` at [runtime.py:96](../../agents/runtime.py) and [runtime.py:160](../../agents/runtime.py) with `for iteration in range(self._max_iterations(session)):`, and the two `AgentExecutionLimitError(session.agent_name, MAX_TOOL_ITERATIONS)` at [runtime.py:135](../../agents/runtime.py) / [runtime.py:241](../../agents/runtime.py) with `self._max_iterations(session)`.

Update [config.py:16](../../agents/config.py) comment to mark `MAX_TOOL_ITERATIONS` as the fallback default.

- [ ] **Step 4: Run the new test + the existing limit_exceeded test**

Run: `pytest tests/test_agent_runtime_kernel.py -k "iteration or limit" -v`
Expected: PASS (the existing `test_runtime_limit_exceeded_stops_after_max_iterations` still passes because tutor's definition default is 5)

- [ ] **Step 5: Commit**

```bash
git add agents/runtime.py agents/config.py tests/test_agent_runtime_kernel.py
git commit -m "feat(agents): tool-iteration budget comes from the agent definition"
```

---

## Task 5: Handoff targets and rate limit from the registry

**Files:**
- Modify: `graph/handoff.py`, `app/api/v1/ai.py`, `agents/config.py`
- Test: existing `tests/test_handoff_context.py`; add assertions

`VALID_HANDOFF_TARGETS` ([handoff.py:15](../../graph/handoff.py)) becomes the union of every definition's `handoff_targets`, and `detect_handoff` validates the specific source→target edge against the *source* agent's declared targets. The rate-limit lookup ([ai.py:27](../../app/api/v1/ai.py)) reads `get_definition(agent_type).rate_limit`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_handoff_context.py (or a new test in the same module)

def test_detect_handoff_respects_per_agent_targets():
    """A handoff to an agent not in the source's declared targets is dropped."""
    from graph.handoff import detect_handoff

    # generator's handoff_targets is {"analytics"} only — a generator->tutor
    # marker must NOT produce a handoff.
    state = {
        "agent_type": "generator",
        "user_role": "teacher",
        "final_response": "Done. [HANDOFF: tutor | help the student]",
    }
    out = detect_handoff(state)
    assert out.get("handoff_to") is None


def test_detect_handoff_allows_declared_target():
    from graph.handoff import detect_handoff

    state = {
        "agent_type": "generator",
        "user_role": "teacher",
        "final_response": "Done. [HANDOFF: analytics | show difficulty stats]",
    }
    out = detect_handoff(state)
    assert out.get("handoff_to") == "analytics"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_handoff_context.py -k "per_agent_targets or declared_target" -v`
Expected: FAIL (today any of the four is accepted regardless of source)

- [ ] **Step 3: Derive handoff validation from the registry**

In [graph/handoff.py](../../graph/handoff.py):

```python
from core.definitions import AGENT_DEFINITIONS

VALID_HANDOFF_TARGETS = frozenset().union(
    *(d.handoff_targets for d in AGENT_DEFINITIONS.values())
)
```

In `detect_handoff`, after resolving `current = state.get("agent_type", "")` and `target`, add the per-source check (keep the existing `can_route_to` role check):

```python
    source_defn = AGENT_DEFINITIONS.get(current)
    if source_defn is not None and target not in source_defn.handoff_targets:
        logger.info("Blocked handoff %s -> %s: not a declared target", current, target)
        return state
```

> Keep `HANDOFF_PROMPT_ADDENDUM` listing the agent names for now (the prompt still teaches the marker format). A later phase can render the per-agent target list into each prompt; that is out of scope here.

- [ ] **Step 4: Move the rate-limit lookup to the registry**

In [app/api/v1/ai.py:27](../../app/api/v1/ai.py), replace `AGENT_RATE_LIMITS.get(agent_type, 20)` with:

```python
from core.definitions import get_definition
defn = get_definition(agent_type)
limit = defn.rate_limit if defn is not None else 20
```

Mark `AGENT_RATE_LIMITS` in [config.py:9](../../agents/config.py) as deprecated (keep it for any other reader; remove only if grep shows none).

Run: `grep -rn "AGENT_RATE_LIMITS" --include=*.py .`

- [ ] **Step 5: Run handoff + a smoke of the API rate path**

Run: `pytest tests/test_handoff_context.py -v`
Expected: PASS. If a previously-passing handoff test now fails, the `handoff_targets` table in Task 1 is narrower than a tested edge — reconcile the table with the test's intended graph (and confirm it matches the prompt).

- [ ] **Step 6: Commit**

```bash
git add graph/handoff.py app/api/v1/ai.py agents/config.py tests/test_handoff_context.py
git commit -m "feat(agents): handoff targets and rate limit sourced from the registry"
```

---

## Task 6: Strip duplicated class attributes

**Files:**
- Modify: `agents/tutor/agent.py`, `agents/reviewer/agent.py`, `agents/generator/agent.py`, `agents/analytics/agent.py`
- Test: existing `tests/test_agents.py`; add a no-duplication assertion

`name` stays on the class (the factory and routing key off it). `description` and `default_model_tier` are removed from the classes and read from the definition via `BaseAgent` properties, eliminating the second source of truth.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_agent_registry.py

def test_class_attrs_match_definition_and_are_not_redeclared():
    """description/tier come from the definition; classes only fix `name`."""
    from agents.registry import AGENT_CLASSES
    from core.definitions import get_definition

    for name, cls in AGENT_CLASSES.items():
        defn = get_definition(name)
        inst = cls()
        assert inst.description == defn.description, name
        assert inst.default_model_tier == defn.default_model_tier, name
        # description/default_model_tier must not be in the class __dict__
        assert "description" not in cls.__dict__, f"{name} redeclares description"
        assert "default_model_tier" not in cls.__dict__, f"{name} redeclares tier"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_agent_registry.py::test_class_attrs_match_definition_and_are_not_redeclared -v`
Expected: FAIL (classes redeclare `description`/`default_model_tier`)

- [ ] **Step 3: Make BaseAgent derive description/tier from the definition**

In [agents/base.py](../../agents/base.py), replace the class attributes `description` / `default_model_tier` ([base.py:114-115](../../agents/base.py)) with properties that read the definition, keeping `name` as a plain class attribute:

```python
    name: str = ""

    @property
    def description(self) -> str:
        from core.definitions import get_definition
        defn = get_definition(self.name)
        return defn.description if defn else ""

    @property
    def default_model_tier(self) -> ModelTier:
        from core.definitions import get_definition
        defn = get_definition(self.name)
        return defn.default_model_tier if defn else ModelTier.BALANCED
```

> Check no code *sets* `self.default_model_tier` (a property would break assignment). Run: `grep -rn "default_model_tier" agents/ graph/ workers/ app/ evals/`. The runtime reads tier from `session.definition.default_model_tier` already ([runtime.py:60](../../agents/runtime.py)), so the property is read-only and safe.

- [ ] **Step 4: Remove the duplicated attrs from the four agent classes**

Delete the `description = ...` and `default_model_tier = ...` lines from each agent (e.g. [tutor/agent.py:11-12](../../agents/tutor/agent.py)). Keep `name = "..."`.

- [ ] **Step 5: Run the agent suite**

Run: `pytest tests/test_agents.py tests/test_agent_features.py tests/test_agent_registry.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agents/base.py agents/tutor/agent.py agents/reviewer/agent.py agents/generator/agent.py agents/analytics/agent.py tests/test_agent_registry.py
git commit -m "refactor(agents): description/tier derive from the definition, not the class"
```

---

## Task 7: Consolidated consistency guard

**Files:**
- Test: `tests/test_definitions_consistency.py` (add the cross-system assertions)

Pin the Phase 2 acceptance criteria that aren't yet guarded: every declared tool exists in the live tool catalog, and every `output_schema_name` resolves to a real schema.

- [ ] **Step 1: Add tool-catalog and schema resolution tests**

```python
# add to tests/test_definitions_consistency.py

def test_allowed_tools_exist_in_the_tool_catalog(app):
    """Every tool an agent can call must be a registered ToolRuntime descriptor."""
    with app.app_context():
        from tools.protocol import get_tool_runtime
        catalog = {d.name for d in get_tool_runtime().list_tools()}
        for name, defn in AGENT_DEFINITIONS.items():
            missing = set(defn.allowed_tools) - catalog
            assert not missing, f"{name} references unknown tools: {missing}"


def test_output_schema_names_resolve():
    from core import schemas as schema_mod

    for name, defn in AGENT_DEFINITIONS.items():
        if defn.output_format != "json_schema":
            continue
        assert defn.output_schema_name, f"{name} is json_schema but names no schema"
        assert hasattr(schema_mod, defn.output_schema_name), defn.output_schema_name
```

> Verify the schema lookup mechanism first — `core/schemas.py` may expose schemas by attribute or via a dict/`validate_agent_output`. Run: `grep -n "REVIEW_SCHEMA\|QUESTION_SCHEMA\|ANALYTICS_SCHEMA\|def validate_agent_output" core/schemas.py` and adjust the assertion to match how schemas are actually registered.

- [ ] **Step 2: Run the full consistency file**

Run: `pytest tests/test_definitions_consistency.py -v`
Expected: PASS (adjust the schema assertion if Step 1's grep shows a dict-based registry)

- [ ] **Step 3: Run the full Phase 2 surface**

Run: `pytest tests/test_definitions_consistency.py tests/test_agent_registry.py tests/test_agent_runtime_kernel.py tests/test_agents.py tests/test_agent_features.py tests/test_agent_hooks.py tests/test_agent_contracts.py tests/test_handoff_context.py tests/test_model_router_and_definitions.py tests/test_agent_harness_trace_binding.py tests/test_eval_harness_trace_binding.py -v`
Expected: PASS (whole Phase 2 surface green)

- [ ] **Step 4: Commit**

```bash
git add tests/test_definitions_consistency.py
git commit -m "test(definitions): pin tool-catalog and output-schema consistency"
```

---

## Acceptance Criteria (from the upgrade plan)

- [ ] An agent's tool allowlist, role permissions, output schema, and budget are all queryable from one registry — Tasks 1, 7 + existing capability readers.
- [ ] Adding a new agent does not require editing multiple runtime branches — Task 2 factory + Task 3 repoint; the guard test forbids new local maps.
- [ ] `auto` route, worker, eval, and MCP scope read the same definition — Task 3 (factory) + capability readers already on the registry.

## Out of scope (per the upgrade plan + scope decisions)

- No `budget_policy` wrapper (dropped — two integers suffice).
- No `context_policy` field (deferred to Phase 5 context/memory architecture).
- No per-agent `max_llm_calls` (the trace-level cap is a different, chain-wide axis and stays as-is).
- No rendering of per-agent handoff target lists into prompts (later phase).
- No MCP Gateway rewrite, no eval dataset expansion, no specialist prompt rewrites, no new LLM provider.

## Risks & Mitigations

- **Behavior drift on budget/rate limit:** new per-agent defaults are pinned to today's values by `test_current_agents_keep_their_legacy_defaults`. Do not change the four agents' numbers in this phase.
- **Narrowing handoff behavior:** the `handoff_targets` table can be stricter than today's "any of four". Task 5 Step 5 reconciles the table against existing handoff tests and the prompt examples — widen the set rather than break a tested edge, and record the decision.
- **Circular imports:** `core/definitions.py` MUST NOT import agent classes; the class map lives in `agents/registry.py`, which imports the classes at module top-level (safe — agents import `core.definitions` lazily inside methods, not at import time). Verify `import agents.registry` works standalone.
- **Property vs assignment:** turning `description`/`default_model_tier` into read-only properties (Task 6) breaks any `self.default_model_tier = ...` assignment. The grep in Task 6 Step 3 confirms there is none before the change.
- **A sixth local map regressing later:** the guard test in Task 3 Step 1 fails if any of the five runtime modules reintroduces a `{"tutor": TutorAgent, ...}` dispatch dict.
```
