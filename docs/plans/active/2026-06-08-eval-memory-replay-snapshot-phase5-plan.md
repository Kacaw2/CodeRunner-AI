# Eval Memory Replay Snapshot Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 trace 和 eval case 持有版本化、可验证的 memory snapshot，并支持 `current`、`recorded`、`none` 三种回放模式以及 report 中的 memory drift 对比。

**Architecture:** `MemorySnapshot` 是 runtime-neutral dataclass，Phase 3 的 `MemorySelection` 可转换为 snapshot 并作为 `memory_context_snapshot` trace artifact 保存。DatasetStore 从 trace 导入时嵌入 snapshot；EvalHarness 通过 AgentHarness 顶层 replay 参数传递，不把 snapshot 混进用户业务 context。

**Tech Stack:** Python 3.11、dataclasses、JSON schema versioning、TraceStore artifact、EvalCase/DatasetStore、AgentHarness/EvalHarness、ReportGenerator、GitHub Actions eval workflow、pytest。

---

## 1. 前置条件

必须完成：

- Phase 3 memory audit，包含 stable `snapshot_hash`。
- Phase 4 governed active memory lifecycle。

本阶段不改变 memory 选择策略本身，只控制 eval run 使用哪一份输入。

## 2. Replay 模式

```python
class MemoryReplayMode(str, Enum):
    CURRENT = "current"
    RECORDED = "recorded"
    NONE = "none"
```

| Mode | 行为 |
|---|---|
| `current` | 按当前数据库 active memory + 当前 policy 重新选择 |
| `recorded` | 完全使用 case 内嵌 snapshot，不查询当前 memory |
| `none` | 不注入 memory，用于隔离 memory 对质量的影响 |

Dataset case 默认 `current`。从 production trace 导入的 case 默认 `recorded`。

## 3. Snapshot contract

```python
@dataclass(frozen=True)
class MemorySnapshot:
    schema_version: int
    agent_name: str
    user_id: int
    user_role: str
    policy_fingerprint: str
    snapshot_hash: str
    rendered: str
    context_payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MemorySnapshot":
        if data.get("schema_version") != 1:
            raise ValueError("unsupported memory snapshot schema_version")
        return cls(**data)
```

Snapshot 只包含经过 Phase 3 sensitivity filter 后实际注入的 item。禁止保存 filtered restricted value。

## 4. 文件地图

### 新增

- `ai/memory/snapshot.py`
- `ai/evals/memory_replay.py`
- `tests/test_memory_snapshot.py`
- `tests/test_eval_memory_replay.py`

### 修改

- `ai/memory/governance.py`
- `ai/memory/service.py`
- `ai/agents/base.py`
- `ai/agents/session.py`
- `ai/agents/runtime.py`
- `ai/evals/harness/agent_harness.py`
- `ai/evals/datasets/schema.py`
- `ai/evals/datasets/store.py`
- `ai/evals/harness/eval_harness.py`
- `ai/evals/reports/generator.py`
- `ai/evals/ci.py`
- `domain/repositories/traces.py`
- `app/api/v1/ai.py`
- `.github/workflows/evals.yml`
- `docs/architecture/data-state-memory.md`
- `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- `docs/plans/README.md`

---

### Task 1: 定义版本化 MemorySnapshot

**Files:**
- Create: `ai/memory/snapshot.py`
- Modify: `ai/memory/governance.py`
- Create: `tests/test_memory_snapshot.py`

- [ ] **Step 1: 写 snapshot round-trip tests**

```python
def test_memory_snapshot_round_trips_and_validates_hash():
    from ai.memory.snapshot import MemorySnapshot

    snapshot = MemorySnapshot.create(
        agent_name="tutor",
        user_id=7,
        user_role="student",
        policy_payload={"max_memory_chars": 4000},
        rendered="Student Background: needs recursion practice",
        context_payload={
            "student_profile": [
                {
                    "key": "learning_summary",
                    "value": "needs recursion practice",
                    "source": "memory_item:abc",
                }
            ],
            "teacher_preference": [],
            "recent_sessions": [],
        },
    )

    restored = MemorySnapshot.from_dict(snapshot.to_dict())

    assert restored.snapshot_hash == snapshot.snapshot_hash
    restored.validate()
```

```python
def test_snapshot_rejects_tampered_payload():
    from dataclasses import replace
    import pytest
    from ai.memory.snapshot import MemorySnapshot

    snapshot = MemorySnapshot.create(
        agent_name="tutor",
        user_id=7,
        user_role="student",
        policy_payload={},
        rendered="safe",
        context_payload={"student_profile": [], "teacher_preference": [], "recent_sessions": []},
    )
    tampered = replace(snapshot, rendered="changed")

    with pytest.raises(ValueError, match="hash"):
        tampered.validate()
```

- [ ] **Step 2: 实现 snapshot**

`create()`：

- canonical hash 覆盖 schema_version、agent/user identity、policy fingerprint、rendered、context payload。
- `policy_fingerprint` 是 policy canonical JSON 的 SHA-256。
- `created_at` 使用 UTC ISO-8601。
- `validate()` 重新计算 hash。

- [ ] **Step 3: 给 MemorySelection 增加 payload serializer**

在 governance module 增加：

```python
def selection_context_payload(selection: MemorySelection) -> dict:
    return {
        "student_profile": [
            serialize_memory_item(item)
            for item in selection.context.student_profile
        ],
        "teacher_preference": [
            serialize_memory_item(item)
            for item in selection.context.teacher_preference
        ],
        "recent_sessions": [
            serialize_recent_session(item)
            for item in selection.context.recent_sessions
        ],
    }
```

序列化只处理 included context。

- [ ] **Step 4: 运行 tests**

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_memory_snapshot.py tests/test_memory_governance.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai/memory/snapshot.py ai/memory/governance.py tests/test_memory_snapshot.py tests/test_memory_governance.py
git commit -m "feat(memory): add versioned replay snapshot"
```

---

### Task 2: 将完整 snapshot 写入 trace artifact

**Files:**
- Modify: `ai/agents/base.py`
- Modify: `ai/agents/session.py`
- Modify: `ai/agents/runtime.py`
- Modify: `tests/test_memory_trace_audit.py`
- Modify: `tests/test_memory_snapshot.py`

- [ ] **Step 1: 写 artifact 失败测试**

```python
def test_runtime_persists_memory_context_snapshot_artifact(
    app, db_session, student_user, fake_agent_runtime
):
    from domain.models.observability import AgentTraceArtifact

    trace_id = fake_agent_runtime.run_tutor(user_id=student_user.id).trace_id

    artifact = (
        db_session.query(AgentTraceArtifact)
        .filter_by(
            trace_id=trace_id,
            artifact_type="memory_context_snapshot",
        )
        .one()
    )
    assert artifact.payload_json["schema_version"] == 1
    assert artifact.payload_json["snapshot_hash"]
    assert artifact.payload_json["rendered"]
```

在 `tests/conftest.py` 抽取 `fake_agent_runtime` fixture，复用 `tests/test_agent_runtime_kernel.py` 已有 fake LLM、tool registry 和 trace repository 配置；fixture 返回带 `run_tutor(user_id)` 方法的测试驱动，不新增真实 provider 调用。

- [ ] **Step 2: 在 BaseAgent 创建 snapshot**

`_prepare_memory_for_state()` 在 selection 后调用：

```python
snapshot = MemorySnapshot.create(
    agent_name=self.name,
    user_id=state.get("user_id", 0),
    user_role=state.get("user_role", "student"),
    policy_payload=selection.policy_payload,
    rendered=selection.rendered,
    context_payload=selection_context_payload(selection),
)
state["_memory_snapshot"] = snapshot
```

Phase 3 `MemorySelection` 必须增加 `policy_payload`，其 hash 与 policy fingerprint 一致。

- [ ] **Step 3: AgentSession 携带 snapshot**

增加：

```python
memory_snapshot: Any = None
```

读取 `_memory_snapshot`，不在 `to_state()` 输出。

- [ ] **Step 4: Runtime 写 artifact**

在 memory audit event 后：

```python
if session.memory_snapshot is not None:
    trace.add_artifact(
        artifact_type="memory_context_snapshot",
        name="Memory context snapshot",
        payload_json=session.memory_snapshot.to_dict(),
        mime_type="application/json",
    )
```

- [ ] **Step 5: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_snapshot.py tests/test_memory_trace_audit.py tests/test_agent_runtime_kernel.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/agents/base.py ai/agents/session.py ai/agents/runtime.py tests/test_memory_trace_audit.py tests/test_memory_snapshot.py
git commit -m "feat(trace): persist replayable memory snapshot"
```

---

### Task 3: 增加 trace artifact lookup

**Files:**
- Modify: `domain/repositories/traces.py`
- Modify: `tests/test_domain_observability_repository.py`

- [ ] **Step 1: 写 repository test**

```python
def test_trace_repository_gets_latest_artifact_by_type(db_session):
    from domain.models.observability import AgentTraceArtifact
    from domain.repositories.traces import SyncTraceRepository
    from app.core.timezone import now_china

    db_session.add_all([
        AgentTraceArtifact(
            trace_id="trace-snapshot",
            artifact_type="memory_context_snapshot",
            name="old",
            payload_json={"snapshot_hash": "old"},
            created_at=now_china(),
        ),
        AgentTraceArtifact(
            trace_id="trace-snapshot",
            artifact_type="memory_context_snapshot",
            name="new",
            payload_json={"snapshot_hash": "new"},
            created_at=now_china(),
        ),
    ])
    db_session.flush()

    artifact = SyncTraceRepository(db_session).get_latest_artifact(
        "trace-snapshot",
        "memory_context_snapshot",
    )

    assert artifact.name == "new"
```

- [ ] **Step 2: 实现 lookup**

```python
def get_latest_artifact(self, trace_id: str, artifact_type: str):
    return self.session.execute(
        select(AgentTraceArtifact)
        .where(
            AgentTraceArtifact.trace_id == trace_id,
            AgentTraceArtifact.artifact_type == artifact_type,
        )
        .order_by(
            AgentTraceArtifact.created_at.desc(),
            AgentTraceArtifact.id.desc(),
        )
    ).scalars().first()
```

- [ ] **Step 3: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain_observability_repository.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add domain/repositories/traces.py tests/test_domain_observability_repository.py
git commit -m "feat(trace): query memory snapshot artifacts"
```

---

### Task 4: 扩展 eval dataset schema

**Files:**
- Modify: `ai/evals/datasets/schema.py`
- Modify: `ai/evals/datasets/store.py`
- Modify: `tests/test_eval_dataset_store.py`

- [ ] **Step 1: 写 schema tests**

```python
def test_eval_case_defaults_to_current_memory():
    from ai.evals.datasets.schema import EvalCase

    case = EvalCase.from_dict(
        {
            "id": "case-1",
            "agent_type": "tutor",
            "input": {"message": "help"},
        },
        case_type="golden",
        suite="tutor",
    )

    assert case.memory.mode.value == "current"
    assert case.memory.snapshot is None
```

```python
def test_recorded_memory_case_requires_snapshot():
    import pytest
    from ai.evals.datasets.schema import EvalCase

    with pytest.raises(ValueError, match="snapshot"):
        EvalCase.from_dict(
            {
                "id": "case-recorded",
                "agent_type": "tutor",
                "input": {"message": "help"},
                "memory": {"mode": "recorded"},
            },
            case_type="regression",
            suite="tutor",
        )
```

- [ ] **Step 2: 定义 MemoryReplaySpec**

```python
@dataclass
class MemoryReplaySpec:
    mode: MemoryReplayMode = MemoryReplayMode.CURRENT
    snapshot: MemorySnapshot | None = None
    source_trace_id: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> "MemoryReplaySpec":
        payload = data or {}
        mode = MemoryReplayMode(payload.get("mode", "current"))
        snapshot_data = payload.get("snapshot")
        snapshot = (
            MemorySnapshot.from_dict(snapshot_data)
            if snapshot_data is not None
            else None
        )
        if mode is MemoryReplayMode.RECORDED and snapshot is None:
            raise ValueError("recorded memory mode requires snapshot")
        return cls(
            mode=mode,
            snapshot=snapshot,
            source_trace_id=payload.get("source_trace_id", ""),
        )
```

`EvalCase` 增加 `memory: MemoryReplaySpec`，并在 `to_dict()` 输出。

- [ ] **Step 3: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_dataset_store.py tests/test_memory_snapshot.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add ai/evals/datasets/schema.py ai/evals/datasets/store.py tests/test_eval_dataset_store.py
git commit -m "feat(evals): add memory replay spec to cases"
```

---

### Task 5: 从 production trace 导入 recorded snapshot

**Files:**
- Modify: `ai/evals/datasets/store.py`
- Modify: `tests/test_eval_dataset_store.py`
- Modify: `tests/test_eval_pages.py`

- [ ] **Step 1: 写 import test**

```python
def test_create_from_trace_embeds_recorded_memory_snapshot(
    tmp_path, app, db_session
):
    from ai.memory.snapshot import MemorySnapshot
    from domain.models.observability import AgentTraceRun, AgentTraceArtifact
    from app.core.timezone import now_china

    snapshot = MemorySnapshot.create(
        agent_name="tutor",
        user_id=7,
        user_role="student",
        policy_payload={"max_memory_chars": 4000},
        rendered="Student Background: recorded",
        context_payload={
            "student_profile": [],
            "teacher_preference": [],
            "recent_sessions": [],
        },
    )
    db_session.add(AgentTraceRun(
        trace_id="trace-memory-import",
        source="agent",
        agent_type="tutor",
        status="failed",
        started_at=now_china(),
    ))
    db_session.add(AgentTraceArtifact(
        trace_id="trace-memory-import",
        artifact_type="memory_context_snapshot",
        name="Memory context snapshot",
        payload_json=snapshot.to_dict(),
        created_at=now_china(),
    ))
    db_session.commit()
    from ai.evals.datasets.store import DatasetStore

    case = DatasetStore(root=tmp_path).create_from_trace(
        "trace-memory-import",
        reason="memory regression",
    )

    assert case.memory.mode.value == "recorded"
    assert case.memory.source_trace_id == "trace-memory-import"
    assert case.memory.snapshot.snapshot_hash == snapshot.snapshot_hash
```

该测试直接使用当前 `AgentTraceRun` / `AgentTraceArtifact` shared-domain model 建立真实持久化数据，不得绕过 repository/store 读取路径。

- [ ] **Step 2: 修改 create_from_trace**

查询 `get_latest_artifact(trace_id, "memory_context_snapshot")`：

- 找到 -> `MemoryReplaySpec(mode=MemoryReplayMode.RECORDED, snapshot=snapshot, source_trace_id=trace_id)`。
- 未找到 -> raise `ValueError("trace has no memory_context_snapshot artifact")`。

不允许 production failure 默默退化到 current memory，否则无法复现失败。

- [ ] **Step 3: 更新 promote API test**

`POST /api/v1/ai/evals/promote-regression` 对无 snapshot trace 返回 400，错误 code `memory_snapshot_missing`；有 snapshot 返回 case memory block。

- [ ] **Step 4: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_dataset_store.py tests/test_eval_pages.py tests/test_api_ai.py -k "promote or snapshot or create_from_trace" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai/evals/datasets/store.py app/api/v1/ai.py tests/test_eval_dataset_store.py tests/test_eval_pages.py tests/test_api_ai.py
git commit -m "feat(evals): import recorded memory from traces"
```

---

### Task 6: 在 agent execution 支持 replay override

**Files:**
- Create: `ai/evals/memory_replay.py`
- Modify: `ai/evals/harness/agent_harness.py`
- Modify: `ai/agents/base.py`
- Modify: `ai/agents/session.py`
- Create: `tests/test_eval_memory_replay.py`

- [ ] **Step 1: 写 mode behavior tests**

```python
def test_recorded_mode_uses_snapshot_without_querying_memory(app):
    from unittest.mock import patch
    from ai.agents.tutor.agent import TutorAgent
    from ai.evals.memory_replay import MemoryReplayEnvelope
    from ai.memory.snapshot import MemorySnapshot
    from ai.evals.datasets.schema import MemoryReplayMode

    snapshot = MemorySnapshot.create(
        agent_name="tutor",
        user_id=7,
        user_role="student",
        policy_payload={},
        rendered="Student Background: recorded value",
        context_payload={
            "student_profile": [],
            "teacher_preference": [],
            "recent_sessions": [],
        },
    )
    state = {
        "user_id": 7,
        "user_role": "student",
        "context": {},
        "_memory_replay": MemoryReplayEnvelope(
            mode=MemoryReplayMode.RECORDED,
            snapshot=snapshot,
        ),
    }
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.prepare_memory_context"
    ) as prepare:
        rendered = TutorAgent()._prepare_memory_for_state(state)

    assert rendered == "Student Background: recorded value"
    prepare.assert_not_called()
```

```python
def test_none_mode_disables_memory(app):
    from unittest.mock import patch
    from ai.agents.tutor.agent import TutorAgent
    from ai.evals.memory_replay import MemoryReplayEnvelope
    from ai.evals.datasets.schema import MemoryReplayMode

    state = {
        "user_id": 7,
        "user_role": "student",
        "context": {},
        "_memory_replay": MemoryReplayEnvelope(
            mode=MemoryReplayMode.NONE,
        ),
    }
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.prepare_memory_context"
    ) as prepare:
        rendered = TutorAgent()._prepare_memory_for_state(state)

    assert rendered == ""
    prepare.assert_not_called()
```

```python
def test_current_mode_uses_live_memory_service(app):
    from unittest.mock import patch
    from ai.agents.tutor.agent import TutorAgent
    from ai.evals.memory_replay import MemoryReplayEnvelope
    from ai.evals.datasets.schema import MemoryReplayMode

    state = {
        "user_id": 7,
        "user_role": "student",
        "context": {},
        "_memory_replay": MemoryReplayEnvelope(
            mode=MemoryReplayMode.CURRENT,
        ),
    }
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.prepare_memory_context"
    ) as prepare:
        prepare.return_value.rendered = "live"
        rendered = TutorAgent()._prepare_memory_for_state(state)

    assert rendered == "live"
    prepare.assert_called_once()
```

- [ ] **Step 2: 定义 replay envelope**

`ai/evals/memory_replay.py`：

```python
@dataclass(frozen=True)
class MemoryReplayEnvelope:
    mode: MemoryReplayMode
    snapshot: MemorySnapshot | None = None

    @classmethod
    def from_spec(cls, spec: MemoryReplaySpec) -> "MemoryReplayEnvelope":
        return cls(mode=spec.mode, snapshot=spec.snapshot)
```

- [ ] **Step 3: AgentHarness 接收顶层参数**

`stream()` / `run()` 增加：

```python
memory_replay: MemoryReplayEnvelope | None = None
```

state 增加：

```python
"_memory_replay": memory_replay,
```

`AgentSession.from_state()` 读取并排除该 private key；`to_state()` 不输出。

- [ ] **Step 4: BaseAgent 实现 mode**

`_prepare_memory_for_state()`：

```python
replay = state.get("_memory_replay")
if replay is not None:
    if replay.mode is MemoryReplayMode.NONE:
        state["_memory_snapshot"] = None
        state["_memory_selection"] = None
        return ""
    if replay.mode is MemoryReplayMode.RECORDED:
        replay.snapshot.validate()
        state["_memory_snapshot"] = replay.snapshot
        state["_memory_selection"] = None
        return replay.snapshot.rendered
```

CURRENT 继续走 live service。

- [ ] **Step 5: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_memory_replay.py tests/test_agent_session.py tests/test_agent_harness_trace_binding.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/evals/memory_replay.py ai/evals/harness/agent_harness.py ai/agents/base.py ai/agents/session.py tests/test_eval_memory_replay.py tests/test_agent_session.py
git commit -m "feat(evals): execute agents with memory replay modes"
```

---

### Task 7: EvalHarness 持久化 mode/hash 并支持 override

**Files:**
- Modify: `ai/evals/harness/eval_harness.py`
- Modify: `tests/test_eval_harness_trace_binding.py`
- Modify: `tests/test_eval_memory_replay.py`

- [ ] **Step 1: 写 harness test**

```python
def test_eval_harness_passes_case_memory_replay_and_persists_metadata(
    app, db_session, capturing_agent_harness
):
    report = EvalHarness(agent_harness=capturing_agent_harness).run(
        selector="regression:tutor",
        memory_mode_override="recorded",
    )

    assert capturing_agent_harness.memory_replays
    assert all(
        replay.mode.value == "recorded"
        for replay in capturing_agent_harness.memory_replays
    )

    with core_db_session() as session:
        rows = session.query(EvalCaseRun).filter_by(
            eval_run_id=report.eval_run_id
        ).all()
        assert all(r.metadata_json["memory_mode"] == "recorded" for r in rows)
        assert all(r.metadata_json["memory_snapshot_hash"] for r in rows)
```

在 `tests/test_eval_memory_replay.py` 定义 `capturing_agent_harness` fixture：实现与真实 `AgentHarness.run()` 相同的关键字参数签名，把收到的 `memory_replay` 追加到 `memory_replays`，并返回 EvalHarness 当前期望的最小成功 result。不得 patch `EvalHarness` 内部 replay resolver。

- [ ] **Step 2: 扩展 run signature**

```python
def run(
    self,
    *,
    selector: str = "all",
    model_name: str | None = None,
    max_cases: int | None = None,
    memory_mode_override: str = "",
) -> EvalRunReport:
```

override 为空时使用 case mode；非空时：

- `current` 和 `none` 可覆盖任意 case。
- `recorded` 只允许 case 有 snapshot，否则 case status=`error`，failure_type=`memory_snapshot_missing`。

- [ ] **Step 3: 传入 AgentHarness**

```python
memory_replay = resolve_memory_replay(
    case.memory,
    override=memory_mode_override,
)
result = self.agent_harness.run(
    agent_type=case.agent_type,
    message=case.input.message,
    user_id=case.input.user_id,
    user_role=case.input.user_role,
    source="eval",
    context=context,
    budget=case.budget,
    memory_replay=memory_replay,
)
```

- [ ] **Step 4: persist metadata_json**

```python
metadata_json={
    "memory_mode": memory_replay.mode.value,
    "memory_snapshot_hash": (
        memory_replay.snapshot.snapshot_hash
        if memory_replay.snapshot is not None
        else None
    ),
    "memory_source_trace_id": case.memory.source_trace_id or None,
}
```

- [ ] **Step 5: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_memory_replay.py tests/test_eval_harness_trace_binding.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/evals/harness/eval_harness.py tests/test_eval_harness_trace_binding.py tests/test_eval_memory_replay.py
git commit -m "feat(evals): persist memory replay metadata"
```

---

### Task 8: Report 显示 memory drift

**Files:**
- Modify: `ai/evals/reports/generator.py`
- Modify: `tests/test_eval_report_generator.py`

- [ ] **Step 1: 写 report test**

```python
def test_report_marks_memory_drift_between_runs(
    db_session, eval_run_factory
):
    baseline_run = eval_run_factory(
        case_id="tutor::memory",
        metadata_json={
            "memory_mode": "recorded",
            "memory_snapshot_hash": "recorded-hash",
        },
    )
    current_run = eval_run_factory(
        case_id="tutor::memory",
        metadata_json={
            "memory_mode": "current",
            "memory_snapshot_hash": "current-hash",
        },
    )

    report = ReportGenerator().build(
        eval_run_id=current_run,
        compare_to_eval_run_id=baseline_run,
    )

    assert report.summary["memory_drift_cases"] == [{
        "case_id": "tutor::memory",
        "baseline_hash": "recorded-hash",
        "current_hash": "current-hash",
        "baseline_mode": "recorded",
        "current_mode": "current",
    }]
```

`eval_run_factory` 复用 `tests/test_eval_report_generator.py` 现有 EvalRun/EvalCaseRun seed 逻辑；若当前文件没有 fixture，先把重复 seed 代码抽成该 fixture，并让既有 report tests 一并使用。

- [ ] **Step 2: 暴露 case metadata**

`_case_to_dict()` 增加：

```python
"memory_mode": (c.metadata_json or {}).get("memory_mode"),
"memory_snapshot_hash": (
    c.metadata_json or {}
).get("memory_snapshot_hash"),
```

- [ ] **Step 3: 计算 drift**

按 `case_id` 对齐 baseline/current，hash 不同且两边都有 hash 时加入 `memory_drift_cases`。Markdown report 增加 `## Memory drift`。

- [ ] **Step 4: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_report_generator.py tests/test_eval_memory_replay.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai/evals/reports/generator.py tests/test_eval_report_generator.py
git commit -m "feat(evals): report memory snapshot drift"
```

---

### Task 9: CLI、CI 与 API replay controls

**Files:**
- Modify: `ai/evals/ci.py`
- Modify: `.github/workflows/evals.yml`
- Modify: `app/api/v1/ai.py`
- Modify: `tests/test_evals_ci.py`
- Modify: `tests/test_eval_pages.py`
- Modify: `tests/test_phase8_ci_docs_contract.py`

- [ ] **Step 1: CLI 参数**

新增：

```python
parser.add_argument(
    "--memory-mode",
    choices=("case", "current", "recorded", "none"),
    default="case",
)
```

传给 harness：

```python
memory_mode_override = (
    "" if args.memory_mode == "case" else args.memory_mode
)
```

- [ ] **Step 2: API 参数**

`POST /api/v1/ai/evals/run` 接受：

```json
{
  "selector": "regression:tutor",
  "memory_mode": "recorded"
}
```

非法值返回 400。response case 中返回 `memory_mode` 和 `memory_snapshot_hash`。

- [ ] **Step 3: CI 默认**

`.github/workflows/evals.yml` 默认使用：

```bash
--memory-mode case
```

manual dispatch 增加 choice input：`case/current/recorded/none`。Nightly 仍使用 case-defined mode。

- [ ] **Step 4: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evals_ci.py tests/test_eval_pages.py tests/test_phase8_ci_docs_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai/evals/ci.py .github/workflows/evals.yml app/api/v1/ai.py tests/test_evals_ci.py tests/test_eval_pages.py tests/test_phase8_ci_docs_contract.py
git commit -m "feat(evals): expose memory replay controls"
```

---

### Task 10: 文档、完整验证与归档

**Files:**
- Modify: `docs/architecture/data-state-memory.md`
- Modify: `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- Modify: `docs/plans/README.md`
- Modify: `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md`

- [ ] **Step 1: 更新文档**

必须说明：

- snapshot 只含已注入、已过滤的 prompt-safe memory。
- recorded mode 不查当前数据库 memory。
- current mode 反映今天的 active memory。
- none mode 用于归因。
- hash mismatch 是 drift signal，不自动等于质量回归。

- [ ] **Step 2: Focused verification**

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_memory_snapshot.py tests/test_eval_memory_replay.py tests/test_eval_dataset_store.py tests/test_eval_harness_trace_binding.py tests/test_eval_report_generator.py tests/test_eval_pages.py tests/test_evals_ci.py tests/test_memory_trace_audit.py -q
```

Expected: PASS.

- [ ] **Step 3: CLI smoke**

```powershell
.\.venv\Scripts\python.exe -m ai.evals.ci --help
```

Expected: output contains `--memory-mode`.

使用 fake/local test data 的 recorded/current 对比由 pytest 覆盖；没有 provider key 时不运行真实付费 eval。

- [ ] **Step 4: Full verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
docker compose up -d --build web agent_runtime
docker exec educode_web flask db check
docker compose ps
git diff --check
```

Expected: PASS / healthy / no schema diff。

- [ ] **Step 5: 归档**

```powershell
git mv docs/plans/active/2026-06-08-eval-memory-replay-snapshot-phase5-plan.md docs/plans/archive/2026-06-08-eval-memory-replay-snapshot-phase5-plan.md
```

Issue 状态更新为：

```markdown
Phase 1-5 Completed
```

若仍有产品 UI、批量 forget 或更高级 extractor 工作，单独创建新 issue，不保留在本 issue 的已完成范围中。

- [ ] **Step 6: Commit**

```powershell
git add ai/memory ai/evals ai/agents domain/repositories/traces.py app/api/v1/ai.py .github/workflows/evals.yml tests docs
git commit -m "feat(evals): complete memory snapshot replay"
```

## 5. 完成定义

Phase 5 完成必须同时满足：

1. 每个 memory-enabled trace 有版本化 snapshot artifact。
2. snapshot hash 可验证篡改。
3. production failure import 无 snapshot 时明确失败。
4. current/recorded/none 三种模式都有执行测试。
5. recorded mode 不查询 live memory。
6. EvalCaseRun 保存 mode/hash/source trace。
7. report 能区分 memory drift 与普通 regression。
8. CLI/API/CI 均可选择 replay mode。
9. full pytest、Docker health、`flask db check` 通过。
