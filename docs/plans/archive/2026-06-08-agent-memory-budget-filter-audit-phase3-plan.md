# Agent Memory Budget, Filtering, and Audit Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为结构化 `MemoryContext` 增加确定性的敏感级别、TTL、字符/token 预算过滤，并将每次 memory 注入的 included/filtered 决策写入现有 trace event/artifact。

**Architecture:** `ai/memory/governance.py` 负责纯函数式选择与预算裁剪，`MemoryService.prepare_memory_context()` 返回渲染文本和审计结果。Agent 在创建 `AgentSession` 前完成选择，`AgentSession.memory_selection` 将结果传到 `AgentRuntime`，后者在获取 trace 后记录审计，不新建第二套 observability 存储。

**Tech Stack:** Python 3.11、dataclasses、hashlib/json、现有 `MemoryContext` / `MemoryPolicy`、AgentSession/AgentRuntime、TraceCollector、SQLAlchemy trace store、pytest。

---

## 1. 前置条件

执行本计划前必须完成并归档：

- `docs/plans/active/2026-06-08-agent-memory-context-governance-phase1-2-plan.md`
- `ai/memory/context.py`
- `MemoryService.build_memory_context()` / `render_memory_context()`
- `AgentDefinition.memory_policy`

若 Phase 1-2 的最终符号名与计划不同，先按已归档实现更新本文件中的符号引用，不得重新实现平行类型。

## 2. 范围

本阶段实现：

- `MemoryMetadata.priority` 与稳定 item identity。
- TTL、sensitivity、空值、角色/subject 边界后的统一过滤。
- 每 agent `max_memory_chars` / `max_memory_tokens`。
- deterministic token estimate，禁止为了预算再调用 LLM。
- included/filtered/dropped 决策与原因。
- canonical snapshot hash。
- trace `memory_context_selected` event。
- trace `memory_injection_audit` artifact。
- trace detail API 自动暴露现有 event/artifact。

本阶段不实现：

- memory item 数据库表。
- extractor / candidate lifecycle。
- forget / suppress / superseded。
- eval recorded snapshot 回放。
- 将完整 rendered memory 长期保存到 trace；Phase 3 只保存审计描述和 hash。

## 3. 目标契约

### 3.1 Policy 扩展

```python
@dataclass(frozen=True)
class MemoryPolicy:
    profile_kind: MemoryProfileKind = MemoryProfileKind.NONE
    include_recent_summaries: bool = False
    recent_summary_agent_types: frozenset[str] = frozenset()
    max_recent_summaries: int = 3
    allow_target_student: bool = False
    allowed_sensitivities: frozenset[MemorySensitivity] = frozenset({
        MemorySensitivity.INTERNAL,
    })
    max_memory_chars: int = 0
    max_memory_tokens: int = 0
```

`0` 表示禁止 memory，不表示 unlimited。四个默认值：

| Agent | chars | estimated tokens |
|---|---:|---:|
| tutor | 4000 | 1000 |
| generator | 3000 | 750 |
| analytics | 3000 | 750 |
| reviewer | 0 | 0 |

### 3.2 Selection contract

```python
class MemoryFilterReason(str, Enum):
    INCLUDED = "included"
    EMPTY = "empty"
    EXPIRED = "expired"
    SENSITIVITY = "sensitivity"
    CHAR_BUDGET = "char_budget"
    TOKEN_BUDGET = "token_budget"


@dataclass(frozen=True)
class MemoryDecision:
    source: str
    key: str
    included: bool
    reason: MemoryFilterReason
    rendered_chars: int
    estimated_tokens: int
    priority: int


@dataclass(frozen=True)
class MemorySelection:
    context: MemoryContext
    rendered: str
    decisions: tuple[MemoryDecision, ...]
    rendered_chars: int
    estimated_tokens: int
    snapshot_hash: str
```

### 3.3 排序规则

候选 item 按以下顺序稳定排序：

1. `metadata.priority` 降序。
2. section 顺序：student profile、teacher preference、recent sessions。
3. `metadata.source`。
4. `key`。

默认优先级：

| Item | Priority |
|---|---:|
| target student profile | 100 |
| actor profile/preferences | 80 |
| current hint level / weak areas | 90 |
| recent session summary | 50 |

预算裁剪不得依赖数据库返回顺序。

## 4. 文件地图

### 新增

- `ai/memory/governance.py`: 纯函数选择、估算、canonical hash。
- `tests/test_memory_governance.py`: 预算、TTL、敏感过滤、稳定 hash。
- `tests/test_memory_trace_audit.py`: session/runtime/trace 审计集成。

### 修改

- `ai/memory/context.py`
- `ai/memory/service.py`
- `core/definitions.py`
- `ai/agents/base.py`
- `ai/agents/session.py`
- `ai/agents/tutor/agent.py`
- `ai/agents/generator/agent.py`
- `ai/agents/analytics/agent.py`
- `ai/agents/runtime.py`
- `core/observability/tracing.py`
- `docs/architecture/data-state-memory.md`
- `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- `docs/plans/README.md`

---

### Task 1: 扩展 metadata 与 policy 契约

**Files:**
- Modify: `ai/memory/context.py`
- Modify: `core/definitions.py`
- Modify: `tests/test_definitions_consistency.py`
- Create: `tests/test_memory_governance.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime, timedelta


def test_memory_metadata_carries_priority_and_expiry():
    from ai.memory.context import MemoryMetadata

    expiry = datetime(2030, 1, 1)
    metadata = MemoryMetadata(
        source="student_profile:7",
        reason_included="tutor profile policy",
        priority=90,
        expires_at=expiry,
    )

    assert metadata.priority == 90
    assert metadata.expires_at == expiry


def test_every_agent_memory_policy_has_enforced_budget():
    from core.definitions import AGENT_DEFINITIONS

    expected = {
        "tutor": (4000, 1000),
        "generator": (3000, 750),
        "analytics": (3000, 750),
        "reviewer": (0, 0),
    }
    for name, definition in AGENT_DEFINITIONS.items():
        policy = definition.memory_policy
        assert (
            policy.max_memory_chars,
            policy.max_memory_tokens,
        ) == expected[name]
```

- [ ] **Step 2: 运行测试**

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py tests/test_definitions_consistency.py -q
```

Expected: FAIL because priority and budget fields do not exist.

- [ ] **Step 3: 扩展数据类型**

在 `MemoryMetadata` 增加：

```python
priority: int = 50
```

在 `MemoryPolicy` 增加第 3.1 节字段。所有 agent definition 显式设置预算；reviewer 保持 `0/0`。

- [ ] **Step 4: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py tests/test_definitions_consistency.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai/memory/context.py core/definitions.py tests/test_memory_governance.py tests/test_definitions_consistency.py
git commit -m "feat(memory): define governance budgets and priority"
```

---

### Task 2: 实现 deterministic governance selector

**Files:**
- Create: `ai/memory/governance.py`
- Modify: `tests/test_memory_governance.py`

- [ ] **Step 1: 写 TTL 与 sensitivity 失败测试**

```python
def test_selector_filters_expired_and_restricted_items():
    from datetime import datetime, timedelta
    from ai.memory.context import (
        MemoryContext,
        MemoryItem,
        MemoryMetadata,
        MemorySensitivity,
    )
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    now = datetime(2026, 6, 8, 12, 0, 0)
    context = MemoryContext(student_profile=(
        MemoryItem(
            key="learning_summary",
            value="keep me",
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=80,
            ),
        ),
        MemoryItem(
            key="old_state",
            value="expired",
            metadata=MemoryMetadata(
                source="memory:old",
                reason_included="test",
                priority=100,
                expires_at=now - timedelta(seconds=1),
            ),
        ),
        MemoryItem(
            key="private_identity",
            value="restricted",
            metadata=MemoryMetadata(
                source="memory:restricted",
                reason_included="test",
                priority=100,
                sensitivity=MemorySensitivity.RESTRICTED,
            ),
        ),
    ))
    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=1000,
        max_memory_tokens=250,
    )

    result = select_memory_context(context, policy, now=now)

    assert result.rendered == "Student Background: keep me"
    reasons = {d.key: d.reason.value for d in result.decisions}
    assert reasons["old_state"] == "expired"
    assert reasons["private_identity"] == "sensitivity"
```

- [ ] **Step 2: 写预算优先级与稳定 hash 测试**

```python
def test_selector_keeps_high_priority_items_under_budget():
    from ai.memory.context import MemoryContext, MemoryItem, MemoryMetadata
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    context = MemoryContext(student_profile=(
        MemoryItem(
            key="learning_summary",
            value="A" * 30,
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=100,
            ),
        ),
        MemoryItem(
            key="error_patterns",
            value={"WA": 4},
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=40,
            ),
        ),
    ))
    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=60,
        max_memory_tokens=100,
    )

    first = select_memory_context(context, policy)
    second = select_memory_context(context, policy)

    assert "Student Background" in first.rendered
    assert "Error History" not in first.rendered
    assert first.snapshot_hash == second.snapshot_hash
    assert len(first.snapshot_hash) == 64
```

- [ ] **Step 3: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py -q
```

Expected: FAIL with missing `ai.memory.governance`.

- [ ] **Step 4: 实现 governance module**

模块必须提供：

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai.memory.context import MemoryContext, MemoryItem, RecentSessionMemory


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def canonical_snapshot_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

实现第 3.2 节 dataclass，并将每个 item 单独通过 `MemoryService.render_memory_context()` 渲染后计费。选择流程：

```python
def select_memory_context(
    context: MemoryContext,
    policy,
    *,
    now: datetime | None = None,
) -> MemorySelection:
    effective_now = now or datetime.now()
    candidates = _flatten_context(context)
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.metadata.priority,
            item.section_order,
            item.metadata.source,
            item.key,
        ),
    )
    included = []
    decisions = []
    used_chars = 0
    used_tokens = 0

    for candidate in ordered:
        rendered = candidate.rendered
        chars = len(rendered)
        tokens = estimate_tokens(rendered)
        reason = _filter_reason(candidate, policy, effective_now)
        if reason is MemoryFilterReason.INCLUDED:
            if used_chars + chars > policy.max_memory_chars:
                reason = MemoryFilterReason.CHAR_BUDGET
            elif used_tokens + tokens > policy.max_memory_tokens:
                reason = MemoryFilterReason.TOKEN_BUDGET
        if reason is MemoryFilterReason.INCLUDED:
            included.append(candidate)
            used_chars += chars
            used_tokens += tokens
        decisions.append(candidate.to_decision(reason, chars, tokens))

    selected_context = _rebuild_context(included)
    rendered = _render_selected(selected_context)
    payload = _snapshot_payload(selected_context)
    return MemorySelection(
        context=selected_context,
        rendered=rendered,
        decisions=tuple(decisions),
        rendered_chars=len(rendered),
        estimated_tokens=estimate_tokens(rendered),
        snapshot_hash=canonical_snapshot_hash(payload),
    )
```

`_flatten_context` 可使用私有 dataclass 统一 `MemoryItem` 和 `RecentSessionMemory`，但不得修改 public context 类型。

- [ ] **Step 5: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/memory/governance.py tests/test_memory_governance.py
git commit -m "feat(memory): enforce deterministic filtering and budget"
```

---

### Task 3: 在 MemoryService 建立 prepare API

**Files:**
- Modify: `ai/memory/service.py`
- Modify: `tests/test_memory_governance.py`

- [ ] **Step 1: 写失败测试**

```python
def test_prepare_memory_context_returns_render_and_audit(app, db_session):
    with app.app_context():
        from domain.models.user import User, UserRole
        from app.models.student_profile import StudentProfile
        from ai.memory.service import MemoryService

        user = User(
            username="memory_prepare",
            password="x",
            email="memory-prepare@test.com",
            role=UserRole.STUDENT,
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(StudentProfile(
            student_id=user.id,
            learning_summary="Needs recursion practice.",
        ))
        db_session.commit()

        selection = MemoryService.prepare_memory_context(
            user.id,
            "student",
            agent_name="tutor",
        )

        assert "Needs recursion practice." in selection.rendered
        assert selection.rendered_chars > 0
        assert selection.snapshot_hash
        assert any(d.included for d in selection.decisions)
```

- [ ] **Step 2: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py -q
```

Expected: FAIL with missing `prepare_memory_context`.

- [ ] **Step 3: 实现 prepare API**

```python
@staticmethod
def prepare_memory_context(
    user_id: int,
    user_role: str,
    conversation_id: int | None = None,
    *,
    agent_name: str | None = None,
    target_student_id: int | None = None,
) -> MemorySelection:
    from ai.memory.governance import select_memory_context
    from core.definitions import get_definition

    definition = get_definition(agent_name) if agent_name else None
    policy = (
        definition.memory_policy
        if definition is not None
        else MemoryService.legacy_memory_policy(user_role)
    )
    context = MemoryService.build_memory_context(
        user_id,
        user_role,
        conversation_id,
        profile_kind=policy.profile_kind.value,
        include_recent_summaries=policy.include_recent_summaries,
        recent_summary_agent_types=tuple(
            sorted(policy.recent_summary_agent_types)
        ),
        max_recent_summaries=policy.max_recent_summaries,
        target_student_id=target_student_id,
        allow_target_student=policy.allow_target_student,
    )
    return select_memory_context(context, policy)
```

`get_memory_context()` 改为返回 `prepare_memory_context(...).rendered`。Legacy policy 必须设置明确预算，例如 4000 chars / 1000 estimated tokens，避免兼容入口绕过治理。

- [ ] **Step 4: 运行 memory suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py tests/test_agents.py -k "Memory" -q
```

Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add ai/memory/service.py tests/test_memory_governance.py tests/test_agents.py
git commit -m "feat(memory): add governed preparation entrypoint"
```

---

### Task 4: 通过 AgentSession 携带 selection

**Files:**
- Modify: `ai/agents/base.py`
- Modify: `ai/agents/session.py`
- Modify: `ai/agents/tutor/agent.py`
- Modify: `ai/agents/generator/agent.py`
- Modify: `ai/agents/analytics/agent.py`
- Modify: `tests/test_agent_session.py`
- Create: `tests/test_memory_trace_audit.py`

- [ ] **Step 1: 写 session round-trip 失败测试**

```python
def test_session_carries_memory_selection_without_public_state_leak():
    from unittest.mock import MagicMock
    from ai.agents.session import AgentSession

    selection = MagicMock()
    state = {
        "messages": [],
        "agent_type": "tutor",
        "user_id": 1,
        "user_role": "student",
        "context": {},
        "tool_results": [],
        "final_response": "",
        "_memory_selection": selection,
    }

    session = AgentSession.from_state(state)

    assert session.memory_selection is selection
    assert "_memory_selection" not in session.to_state()
```

- [ ] **Step 2: 写 BaseAgent helper test**

```python
def test_base_agent_memory_helper_stashes_selection(app):
    from unittest.mock import patch
    from ai.agents.tutor.agent import TutorAgent

    state = {
        "messages": [],
        "agent_type": "tutor",
        "user_id": 1,
        "user_role": "student",
        "context": {},
        "tool_results": [],
        "final_response": "",
    }
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.prepare_memory_context"
    ) as prepare:
        prepare.return_value.rendered = "Student Background: test"

        rendered = TutorAgent()._prepare_memory_for_state(state)

    assert rendered == "Student Background: test"
    assert state["_memory_selection"] is prepare.return_value
```

- [ ] **Step 3: 实现 session field**

在 `AgentSession` 增加：

```python
memory_selection: Any = None
```

`from_state()` 读取 `_memory_selection`，`extra_state` 排除该 key；`to_state()` 不输出该 key。

- [ ] **Step 4: 实现 BaseAgent helper**

```python
def _prepare_memory_for_state(
    self,
    state: dict,
    *,
    target_student_id: int | None = None,
) -> str:
    from ai.memory.service import MemoryService

    context = state.get("context") or {}
    selection = MemoryService.prepare_memory_context(
        state.get("user_id", 0),
        state.get("user_role", "student"),
        conversation_id=context.get("conversation_id"),
        agent_name=self.name,
        target_student_id=target_student_id,
    )
    state["_memory_selection"] = selection
    return selection.rendered
```

- [ ] **Step 5: 修改三个 agent**

Tutor/Generator 使用：

```python
memory_ctx = self._prepare_memory_for_state(state)
```

Analytics 使用：

```python
memory_ctx = self._prepare_memory_for_state(
    state,
    target_student_id=context.get("target_student_id"),
)
```

Reviewer 不调用 helper。

- [ ] **Step 6: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_session.py tests/test_memory_trace_audit.py tests/test_agents.py -k "memory or Memory" -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add ai/agents/base.py ai/agents/session.py ai/agents/tutor/agent.py ai/agents/generator/agent.py ai/agents/analytics/agent.py tests/test_agent_session.py tests/test_memory_trace_audit.py tests/test_agents.py
git commit -m "refactor(memory): carry selection through agent session"
```

---

### Task 5: 给 TraceCollector 增加 event collection

**Files:**
- Modify: `core/observability/tracing.py`
- Modify: `tests/test_trace_store_runtime_neutral.py`
- Modify: `tests/test_memory_trace_audit.py`

- [ ] **Step 1: 写失败测试**

```python
def test_trace_collector_persists_memory_event(app, db_session):
    from core.observability.tracing import TraceCollector
    from domain.models.observability import AgentTraceEvent

    trace = TraceCollector(agent_type="tutor", user_id=1)
    trace.add_event(
        event_type="memory_context_selected",
        payload_json={"included_count": 2, "filtered_count": 1},
    )
    trace.save(status="completed", response="ok")

    row = (
        db_session.query(AgentTraceEvent)
        .filter_by(trace_id=trace.run_id)
        .one()
    )
    assert row.event_type == "memory_context_selected"
    assert row.payload_json["filtered_count"] == 1
```

- [ ] **Step 2: 实现 event buffer**

`TraceCollector.__init__`：

```python
self.events = []
```

新增：

```python
def add_event(
    self,
    *,
    event_type: str,
    payload_json: dict | None = None,
    span_id: str | None = None,
) -> None:
    self.events.append({
        "event_type": event_type,
        "payload_json": payload_json,
        "span_id": span_id,
    })
```

新增 `_build_events(ts)`，生成 `TraceEventRecord`；`save()` 将 `events=events` 传给 `TraceStore.save_run()`。

- [ ] **Step 3: 运行 trace tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trace_store_runtime_neutral.py tests/test_memory_trace_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add core/observability/tracing.py tests/test_trace_store_runtime_neutral.py tests/test_memory_trace_audit.py
git commit -m "feat(trace): persist runtime events"
```

---

### Task 6: 在 AgentRuntime 记录 memory 审计

**Files:**
- Modify: `ai/agents/runtime.py`
- Modify: `tests/test_memory_trace_audit.py`
- Modify: `tests/test_agent_runtime_kernel.py`

- [ ] **Step 1: 写 audit payload 失败测试**

```python
def test_runtime_records_memory_selection_on_trace():
    from unittest.mock import MagicMock
    from ai.agents.runtime import _record_memory_selection

    trace = MagicMock()
    decision = MagicMock(
        source="profile:1",
        key="learning_summary",
        included=True,
        reason=MagicMock(value="included"),
        rendered_chars=32,
        estimated_tokens=8,
        priority=80,
    )
    selection = MagicMock(
        decisions=(decision,),
        rendered_chars=32,
        estimated_tokens=8,
        snapshot_hash="a" * 64,
    )

    _record_memory_selection(trace, selection)

    trace.add_event.assert_called_once()
    trace.add_artifact.assert_called_once()
    payload = trace.add_event.call_args.kwargs["payload_json"]
    assert payload["included_count"] == 1
    assert payload["snapshot_hash"] == "a" * 64
```

- [ ] **Step 2: 实现 helper**

```python
def _record_memory_selection(trace, selection) -> None:
    if selection is None:
        return
    decisions = [
        {
            "source": d.source,
            "key": d.key,
            "included": d.included,
            "reason": d.reason.value,
            "rendered_chars": d.rendered_chars,
            "estimated_tokens": d.estimated_tokens,
            "priority": d.priority,
        }
        for d in selection.decisions
    ]
    included_count = sum(1 for d in selection.decisions if d.included)
    payload = {
        "included_count": included_count,
        "filtered_count": len(decisions) - included_count,
        "rendered_chars": selection.rendered_chars,
        "estimated_tokens": selection.estimated_tokens,
        "snapshot_hash": selection.snapshot_hash,
        "decisions": decisions,
    }
    trace.add_event(
        event_type="memory_context_selected",
        payload_json=payload,
    )
    trace.add_artifact(
        artifact_type="memory_injection_audit",
        name="Memory injection audit",
        payload_json=payload,
        mime_type="application/json",
    )
```

不得写入 `selection.rendered` 或完整 value。

- [ ] **Step 3: 在 `_acquire()` 接线**

在 trace 取得后、LLM 调用前：

```python
_record_memory_selection(trace, session.memory_selection)
```

- [ ] **Step 4: 写持久化集成断言**

扩展 runtime kernel test，执行一次 tutor run 后查询：

```python
events = db_session.query(AgentTraceEvent).filter_by(
    trace_id=run.trace_id,
    event_type="memory_context_selected",
).all()
artifacts = db_session.query(AgentTraceArtifact).filter_by(
    trace_id=run.trace_id,
    artifact_type="memory_injection_audit",
).all()
assert len(events) == 1
assert len(artifacts) == 1
```

- [ ] **Step 5: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_trace_audit.py tests/test_agent_runtime_kernel.py tests/test_trace_api_complete.py -q
```

Expected: PASS。现有 trace detail API 应自动返回新增 event/artifact，无需新增 endpoint。

- [ ] **Step 6: Commit**

```powershell
git add ai/agents/runtime.py tests/test_memory_trace_audit.py tests/test_agent_runtime_kernel.py
git commit -m "feat(memory): audit context selection in traces"
```

---

### Task 7: 加固敏感值和预算边界

**Files:**
- Modify: `ai/memory/governance.py`
- Modify: `core/observability/tracing.py`
- Modify: `tests/test_memory_governance.py`
- Modify: `tests/test_memory_trace_audit.py`

- [ ] **Step 1: 写边界测试**

在 `tests/test_memory_governance.py` 增加以下四个完整场景；每个场景直接构造 `MemoryContext`、`MemoryItem`、`MemoryMetadata` 和 `MemoryPolicy`，不 patch selector 内部：

- `test_zero_budget_includes_nothing`: policy 为 `0/0`，断言 rendered 为空、included count 为 0，并且所有非空候选的 reason 是 `char_budget` 或 `token_budget`。
- `test_exact_budget_boundary_is_included`: 先渲染单个候选得到精确 chars/tokens，再以该值作为 policy 上限，断言候选被包含且 reason 为 `included`。
- `test_snapshot_hash_changes_when_included_value_changes`: 仅修改同 source/key item 的 value，断言两个 selection 的 `snapshot_hash` 不同。
- `test_audit_payload_does_not_include_memory_value`: 使用值 `"SECRET_MEMORY_VALUE"` 创建 selection，调用 `_record_memory_selection()`，将 event/artifact kwargs 序列化后断言不包含该字符串。

- [ ] **Step 2: 实现要求**

- 预算比较使用 `>`，等于预算允许。
- `max_memory_chars <= 0` 或 `max_memory_tokens <= 0` 时全部标记相应 budget reason。
- hash payload 包含 source/key/value/sensitivity/expires_at，不包含 `reason_included`。
- trace audit decisions 不包含 value。
- trace `_redact_secrets()` 继续作为最终 persistence gate。

- [ ] **Step 3: 运行测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py tests/test_memory_trace_audit.py tests/test_trace_store_runtime_neutral.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add ai/memory/governance.py core/observability/tracing.py tests/test_memory_governance.py tests/test_memory_trace_audit.py
git commit -m "test(memory): harden audit and budget boundaries"
```

---

### Task 8: 文档、回归与归档

**Files:**
- Modify: `docs/architecture/data-state-memory.md`
- Modify: `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- Modify: `docs/plans/README.md`
- Modify: `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md`

- [ ] **Step 1: 更新文档**

文档必须说明：

- token 是 deterministic estimate，不是 provider tokenizer 精确计数。
- memory audit 使用现有 trace event/artifact。
- trace 不保存完整 rendered memory。
- Phase 4 lifecycle 与 Phase 5 replay 仍未完成。

- [ ] **Step 2: 运行 focused suites**

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py tests/test_memory_trace_audit.py tests/test_agents.py tests/test_agent_session.py tests/test_agent_runtime_kernel.py tests/test_trace_store_runtime_neutral.py tests/test_trace_api_complete.py tests/test_definitions_consistency.py -q
```

Expected: PASS.

- [ ] **Step 3: 运行完整验证**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
docker compose up -d --build web agent_runtime
docker exec educode_web flask db check
docker compose ps
git diff --check
```

Expected:

- pytest 无新增失败。
- `flask db check` 无 schema diff。
- web / agent_runtime healthy。
- diff 不包含 migration。

- [ ] **Step 4: 归档**

```powershell
git mv docs/plans/active/2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md docs/plans/archive/2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md
```

更新所有链接，并在 issue 标记：

```markdown
Phase 3 Completed: budget/filter/audit 已完成；Phase 4-5 仍 active。
```

- [ ] **Step 5: Commit**

```powershell
git add ai/memory ai/agents core/observability tests docs
git commit -m "feat(memory): complete budget filtering and trace audit"
```

## 5. 完成定义

Phase 3 完成必须同时满足：

1. 所有 policy budget 字段被 production selector 消费。
2. TTL/sensitivity/budget 各有正向和负向测试。
3. 选择顺序和 hash 在相同输入下稳定。
4. Reviewer 的 `0/0` policy 不注入 memory。
5. trace 同时存在 event 和 audit artifact。
6. audit 不包含完整 memory value。
7. 无 schema migration。
8. full pytest、Docker health、`flask db check` 通过。
