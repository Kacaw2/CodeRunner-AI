# Complete Traces And Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成完整的 Agent traces 与 eval 平台，使每次 agent 执行、工具调用、MCP 权限决策、成本、延迟、artifact、eval case、grader 结果和回归报告都有统一、可追溯、可查询、可复现的数据链路。

**Architecture:** 以 `Trace Logger` 为运行时事实来源，`Eval Harness` 复用同一条 Agent Harness 执行路径并绑定 trace。Flask、workers、MCP gateway 共享一套运行时无关的 trace/eval schema 与 store，禁止 workers 再通过 Flask-SQLAlchemy 模型落库，避免当前 `TRACE_SAVE_FAIL` 类问题。Eval 不再只是读取 JSON 后调用 agent，而是完整管理 dataset、预算、环境、trace 收集、graders、报告与回归对比。

**Tech Stack:** Python 3.11, Flask, FastAPI workers, SQLAlchemy / Flask-SQLAlchemy, MySQL, Redis, Alembic, pytest, existing `agents/`, `workers/`, `mcp_gateway/`, `tools/protocol/`, `evals/`.

---

## 0. 当前证据与问题边界

当前 traces 页面不更新的直接原因不是页面轮询，而是 workers 运行 agent 后保存 trace 失败。运行时日志出现：

```text
TRACE_COST: run_id=... agent=tutor model=deepseek-chat ...
TRACE_SAVE_FAIL: ... expression 'AIConversation' failed to locate a name ('AIConversation')
```

数据库证据：

```sql
SELECT COUNT(*) AS total, MAX(created_at) AS latest FROM agent_runs;
```

当前结果显示 `agent_runs` 有历史记录，但最新停在 `2026-05-27 16:51:17`。这说明 agent run 在 2026-06-01 仍然执行，但新 trace 没有入库。

根因是 `core/observability/tracing.py` 在 workers 进程里导入 `app.core.extensions.db` 与 `app.models.agent_trace.AgentRun`，触发 Flask-SQLAlchemy mapper 初始化；workers 同时使用 plain SQLAlchemy 的 `core.db.models.*`，两套模型 registry 混用后 `ChatTask -> AIConversation` 关系解析失败。完整方案必须把 trace 持久化从 Flask 模型中抽离出来。

---

## 1. 目标态

### 1.1 完整 Trace

每次 agent 执行必须形成一棵可查询 trace：

- run: 一次 agent 执行或 eval case 执行的顶层记录。
- span: LLM call、tool call、MCP guard、MCP transport、sandbox execution、memory retrieval、grader、report generation 等步骤。
- event: token stream、routing、handoff、approval requested、approval resolved、retry、rate limit、error。
- artifact: prompt snapshot、sanitized tool input/output、code execution output、generated problem JSON、grader report、LLM judge rationale、static check output。
- cost: model、input tokens、output tokens、单位价格、成本、预算消耗。
- latency: total、LLM、tool、MCP transport、sandbox、grader、queue wait。
- link: conversation、message、chat task、workflow run、MCP audit log、MCP approval、eval run、eval case。

### 1.2 完整 Eval

Eval 平台必须包含：

- Agent Harness: 负责运行 agent，包括 prompt、tool calling、memory、MCP、permission、sandbox、预算。
- Trace Logger: 负责记录每一步 message、tool call、span、cost、latency、artifact。
- Eval Harness: 负责批量跑任务，准备环境、启动 agent、限制预算、收集 trace。
- Graders: 负责 unit tests、static checks、deterministic rules、LLM judge、人工审核入口。
- Report Generator: 汇总 pass rate、cost、latency、失败类型、回归对比。
- Dataset Store: 保存 golden tasks、hidden tasks、regression tasks、production failures。

---

## 2. 文件结构

### 2.1 新增文件

- `core/observability/trace_schema.py`
  定义 runtime-neutral trace dataclass / enum / JSON schema。
- `core/observability/trace_store.py`
  使用 plain SQLAlchemy session 写入 trace run/span/event/artifact/link。
- `core/db/models/agent_trace.py`
  plain SQLAlchemy 版本的 trace ORM，供 workers、MCP gateway、evals 使用。
- `app/services/trace_query_service.py`
  Flask 查询层，只读聚合 trace 数据并负责鉴权后的脱敏视图。
- `evals/datasets/schema.py`
  Dataset case 的 schema 与校验。
- `evals/datasets/store.py`
  读取、分类、校验 golden/hidden/regression/production failure cases。
- `evals/harness/agent_harness.py`
  统一 agent 执行入口，封装预算、MCP client、memory、sandbox、trace context。
- `evals/harness/eval_harness.py`
  批量执行 eval run、case run、trace 绑定。
- `evals/graders/base.py`
  grader 协议和统一输出结构。
- `evals/graders/deterministic.py`
  迁移现有 regex/JSON/长度/安全类 judge。
- `evals/graders/unit_tests.py`
  针对代码 artifact 的单元测试 grader。
- `evals/graders/static_checks.py`
  静态检查 grader。
- `evals/graders/llm_judge.py`
  LLM judge，必须保存 judge prompt、response、成本与 trace。
- `evals/reports/generator.py`
  report 聚合器。
- `evals/reports/regression.py`
  baseline 与历史 run 对比。
- `tests/test_trace_store_runtime_neutral.py`
  验证 workers 风格 plain SQLAlchemy trace 写入不触发 Flask mapper。
- `tests/test_trace_api_complete.py`
  验证 trace API 返回 run/span/event/artifact/cost/link。
- `tests/test_eval_harness_trace_binding.py`
  验证 eval case 与 trace run 绑定。
- `tests/test_eval_dataset_store.py`
  验证 dataset 分类和 schema。
- `tests/test_eval_report_generator.py`
  验证 pass rate、cost、latency、失败类型、回归对比。
- `migrations/versions/20260601_complete_traces_evals.py`
  新增 trace/eval 目标态表结构。

### 2.2 修改文件

- `core/observability/tracing.py`
  将现有 `TraceCollector` 改为调用 `trace_store.py`，保留 agent 调用方接口。
- `agents/base.py`
  给 TraceCollector 传入 task/workflow/eval context，记录 tool loop、handoff、memory、budget。
- `agents/generator/agent.py`
  对齐新的 TraceCollector 接口。
- `agents/executor.py`
  在 MCP tool call 前后创建 span，记录 permission decision、MCP envelope、approval。
- `workers/task_runner.py`
  创建 trace context，绑定 `chat_task_id`、`conversation_id`、`routed_agent`。
- `mcp_gateway/middleware/core.py`
  把 MCP guard decision 与 audit log id 回写 trace link。
- `mcp_gateway/client.py`
  记录 transport latency 与 tool call span。
- `app/models/agent_trace.py`
  保留 Flask 模型兼容查询或迁移到只读 wrapper，不再作为 workers 写入路径。
- `app/api/v1/ai.py`
  `/traces` 和 `/evals` API 改为调用 service/harness，不直接操作模型。
- `app/static/js/traces.js`
  展示完整 trace tree、成本、latency、artifact、eval 关联和失败过滤。
- `app/templates/ai/traces.html`
  增加 filter、search、trace detail tabs。
- `evals/runner.py`
  变为新 Eval Harness 的兼容入口。
- `evals/judges/judges.py`
  迁移到 `evals/graders/deterministic.py` 后保留兼容 shim。
- `.github/workflows/evals.yml`
  输出完整 report artifact，上传 trace/eval report。

---

## 3. 数据库目标结构

### Task 1: 新增完整 trace/eval 表结构

**Files:**
- Create: `migrations/versions/20260601_complete_traces_evals.py`
- Create: `core/db/models/agent_trace.py`
- Modify: `app/models/agent_trace.py`
- Modify: `app/models/eval_run.py`

- [ ] **Step 1: 写迁移测试**

在 `tests/test_trace_schema_contract.py` 中新增：

```python
def test_trace_tables_have_complete_columns(app):
    from sqlalchemy import inspect
    from app.core.extensions import db

    with app.app_context():
        inspector = inspect(db.engine)
        columns = {
            table: {c["name"] for c in inspector.get_columns(table)}
            for table in [
                "agent_trace_runs",
                "agent_trace_spans",
                "agent_trace_events",
                "agent_trace_artifacts",
                "agent_trace_links",
                "eval_case_runs",
                "eval_case_grader_results",
            ]
        }

    assert {"id", "trace_id", "agent_type", "status", "started_at", "ended_at", "total_latency_ms", "cost_cny"} <= columns["agent_trace_runs"]
    assert {"id", "trace_id", "parent_span_id", "span_type", "name", "started_at", "ended_at", "latency_ms", "status"} <= columns["agent_trace_spans"]
    assert {"id", "trace_id", "span_id", "event_type", "payload_json", "created_at"} <= columns["agent_trace_events"]
    assert {"id", "trace_id", "span_id", "artifact_type", "name", "mime_type", "storage_uri", "preview_text", "payload_json"} <= columns["agent_trace_artifacts"]
    assert {"id", "trace_id", "link_type", "target_table", "target_id"} <= columns["agent_trace_links"]
    assert {"id", "eval_run_id", "case_id", "trace_id", "status", "passed", "duration_ms", "cost_cny"} <= columns["eval_case_runs"]
    assert {"id", "case_run_id", "grader_type", "grader_name", "passed", "score", "reason", "latency_ms", "cost_cny"} <= columns["eval_case_grader_results"]
```

- [ ] **Step 2: 创建迁移**

迁移表：

```python
def upgrade():
    op.create_table(
        "agent_trace_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("legacy_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("trace_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("agent_type", sa.String(30), nullable=True, index=True),
        sa.Column("user_id", sa.Integer(), nullable=True, index=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True, index=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("chat_task_id", sa.String(36), nullable=True, index=True),
        sa.Column("workflow_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("eval_run_id", sa.Integer(), nullable=True, index=True),
        sa.Column("eval_case_id", sa.String(120), nullable=True, index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("input_preview", sa.Text(), nullable=True),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(80), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Numeric(12, 6), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column("tool_latency_ms", sa.Integer(), nullable=True),
        sa.Column("mcp_latency_ms", sa.Integer(), nullable=True),
        sa.Column("sandbox_latency_ms", sa.Integer(), nullable=True),
        sa.Column("budget_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
```

同一迁移中创建 `agent_trace_spans`、`agent_trace_events`、`agent_trace_artifacts`、`agent_trace_links`、`eval_case_runs`、`eval_case_grader_results`。所有 JSON 字段使用 `sa.JSON()`；所有外部对象关联走 `agent_trace_links`，不要给每种业务对象都加硬外键。

- [ ] **Step 3: 运行迁移测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trace_schema_contract.py -q
```

Expected before migration:

```text
FAILED tests/test_trace_schema_contract.py::test_trace_tables_have_complete_columns
```

- [ ] **Step 4: 应用迁移并补 plain SQLAlchemy model**

`core/db/models/agent_trace.py` 定义 `AgentTraceRun`、`AgentTraceSpan`、`AgentTraceEvent`、`AgentTraceArtifact`、`AgentTraceLink`、`EvalCaseRun`、`EvalCaseGraderResult`。所有类继承 `core.db.session.Base`。

- [ ] **Step 5: 验证迁移测试通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trace_schema_contract.py -q
```

Expected:

```text
1 passed
```

---

## 4. Trace Store 与 TraceCollector

### Task 2: 用 runtime-neutral TraceStore 替代 Flask 模型写入

**Files:**
- Create: `core/observability/trace_schema.py`
- Create: `core/observability/trace_store.py`
- Modify: `core/observability/tracing.py`
- Test: `tests/test_trace_store_runtime_neutral.py`

- [ ] **Step 1: 写失败测试**

```python
def test_trace_collector_saves_without_flask_mapper(monkeypatch):
    from core.observability.tracing import TraceCollector
    from core.db.models.agent_trace import AgentTraceRun
    from core.db.session import db_session

    trace = TraceCollector(
        agent_type="tutor",
        user_id=2,
        conversation_id=123,
        source="workers",
        links={"chat_task_id": "task-1"},
    )
    trace.input_message = "help me"
    with trace.trace_llm_call() as step:
        step["prompt_tokens"] = 10
        step["completion_tokens"] = 5

    trace.save(status="completed", response="hint")

    with db_session() as session:
        run = session.query(AgentTraceRun).filter_by(trace_id=trace.run_id).one()
        assert run.source == "workers"
        assert run.agent_type == "tutor"
        assert run.conversation_id == 123
        assert run.status == "completed"
```

- [ ] **Step 2: 定义 schema**

`trace_schema.py` 提供：

```python
@dataclass
class TraceContext:
    trace_id: str
    source: str
    agent_type: str | None = None
    user_id: int | None = None
    conversation_id: int | None = None
    message_id: int | None = None
    chat_task_id: str | None = None
    workflow_run_id: str | None = None
    eval_run_id: int | None = None
    eval_case_id: str | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 3: 实现 TraceStore**

`trace_store.py` 提供：

```python
class TraceStore:
    def save_run(self, run: TraceRunRecord, spans: list[TraceSpanRecord], events: list[TraceEventRecord], artifacts: list[TraceArtifactRecord]) -> None:
        with db_session() as session:
            session.add(AgentTraceRun(...))
            session.add_all([...])
```

禁止从 `trace_store.py` 导入 `app.core.extensions.db` 或 `app.models.*`。

- [ ] **Step 4: 改造 TraceCollector**

保留现有调用方式：

```python
trace = TraceCollector(agent_type=..., user_id=..., conversation_id=...)
with trace.trace_llm_call():
    ...
trace.save(status="completed", response=response)
```

新增可选参数：

```python
TraceCollector(
    agent_type: str,
    user_id: int,
    conversation_id: int | None = None,
    source: str = "agent",
    message_id: int | None = None,
    links: dict[str, str | int] | None = None,
    budget: dict | None = None,
    metadata: dict | None = None,
)
```

- [ ] **Step 5: 兼容旧表**

短期查询可以继续读 `agent_runs`，但新写入必须进入 `agent_trace_runs`。需要一次迁移脚本或管理命令把旧 `agent_runs` 历史复制成新 trace run：

```powershell
.\.venv\Scripts\python.exe -m scripts.backfill_agent_traces
```

- [ ] **Step 6: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trace_store_runtime_neutral.py tests/test_agents.py::TestGeneratorAgent::test_stream_persists_trace -q
```

Expected:

```text
2 passed
```

---

## 5. Agent Harness 与运行时 trace 绑定

### Task 3: 统一 Agent Harness

**Files:**
- Create: `evals/harness/agent_harness.py`
- Modify: `workers/task_runner.py`
- Modify: `agents/base.py`
- Modify: `agents/executor.py`
- Test: `tests/test_agent_harness_trace_binding.py`

- [ ] **Step 1: 写测试：chat task 绑定 trace**

```python
def test_agent_harness_binds_chat_task_to_trace(fake_llm, db_session):
    from evals.harness.agent_harness import AgentHarness

    result = AgentHarness().run(
        agent_type="tutor",
        message="help",
        user_id=2,
        user_role="teacher",
        source="workers",
        context={"conversation_id": 10, "chat_task_id": "task-1"},
        budget={"max_tokens": 2000, "max_tool_calls": 5},
    )

    assert result.trace_id
    assert result.status in {"completed", "limit_exceeded", "failed"}
```

- [ ] **Step 2: 实现 Harness 输入输出**

`AgentHarness.run()` 返回：

```python
@dataclass
class AgentHarnessResult:
    trace_id: str
    agent_type: str
    status: str
    final_response: str
    tokens_input: int
    tokens_output: int
    cost_cny: Decimal | None
    latency_ms: int
    error: str = ""
```

- [ ] **Step 3: 将 workers 调用改为 Harness**

`workers/task_runner.py` 不再直接拼完整 agent 执行逻辑；它负责 ChatTask 生命周期、Redis event、消息落库，agent 执行交给 `AgentHarness`。Harness 必须接收 `chat_task_id`、`conversation_id`、`workflow_run_id`。

- [ ] **Step 4: 工具调用 span**

在 `agents/executor.py` 中记录：

- `before_tool_call`
- permission decision
- MCP transport start/end
- envelope status
- approval id
- error code

MCP denied、approval required、transport timeout 都必须是 trace span，不只写日志。

- [ ] **Step 5: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_harness_trace_binding.py tests/test_agent_hooks.py tests/test_agent_mcp_client_boundary.py -q
```

Expected:

```text
all selected tests passed
```

---

## 6. Trace API 与页面

### Task 4: 完整 trace 查询 API

**Files:**
- Create: `app/services/trace_query_service.py`
- Modify: `app/api/v1/ai.py`
- Modify: `app/api/v1/agents/traces.py`
- Test: `tests/test_trace_api_complete.py`

- [ ] **Step 1: 写 API 测试**

```python
def test_trace_detail_returns_tree_cost_artifacts_and_links(client, teacher_token, seeded_complete_trace):
    resp = client.get(
        f"/api/v1/ai/traces/{seeded_complete_trace.trace_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "run" in data
    assert "spans" in data
    assert "events" in data
    assert "artifacts" in data
    assert "links" in data
    assert data["run"]["cost_cny"] is not None
```

- [ ] **Step 2: 查询服务**

`TraceQueryService.get_trace(trace_id, viewer)` 返回完整但脱敏后的 trace。教师/admin 可看完整 preview；学生只能看自己的 trace 且隐藏 tool args、system prompt、其他学生信息。

- [ ] **Step 3: 列表过滤**

`GET /api/v1/ai/traces` 支持：

- `agent_type`
- `status`
- `source`
- `eval_run_id`
- `conversation_id`
- `chat_task_id`
- `from`
- `to`
- `q`
- `limit`
- `offset`

- [ ] **Step 4: 页面升级**

`app/static/js/traces.js` 展示：

- trace list
- trace detail tabs: Timeline、Messages、Tools、MCP、Artifacts、Cost、Eval
- status/error filter
- latency/cost badges
- artifact preview
- related eval case/run link

修复当前分页 HTML 的错误闭合：

```js
paginationEl.innerHTML = `
  <button id="prevPage" ${currentPageNum <= 1 ? 'disabled' : ''}>Prev</button>
  <span class="page-info">${currentPageNum} / ${totalPages}</span>
  <button id="nextPage" ${currentPageNum >= totalPages ? 'disabled' : ''}>Next</button>
`;
```

- [ ] **Step 5: 验证**

Run:

```powershell
node --check app\static\js\traces.js
.\.venv\Scripts\python.exe -m pytest tests/test_trace_api_complete.py -q
```

Expected:

```text
node syntax check passes
all trace API tests pass
```

---

## 7. Dataset Store

### Task 5: 正式化 eval datasets

**Files:**
- Create: `evals/datasets/schema.py`
- Create: `evals/datasets/store.py`
- Create: `evals/datasets/golden/`
- Create: `evals/datasets/hidden/`
- Create: `evals/datasets/regression/`
- Create: `evals/datasets/production_failures/`
- Modify: `evals/cases/*.json`
- Test: `tests/test_eval_dataset_store.py`

- [ ] **Step 1: 写 dataset 测试**

```python
def test_dataset_store_loads_all_case_types():
    from evals.datasets.store import DatasetStore

    store = DatasetStore(root="evals/datasets")
    cases = store.load_cases(selector="all")
    case_types = {case.case_type for case in cases}

    assert {"golden", "hidden", "regression", "production_failure"} <= case_types
    assert all(case.id for case in cases)
    assert all(case.input.message for case in cases)
```

- [ ] **Step 2: 定义 case schema**

每个 case 必须包含：

```json
{
  "id": "tutor_no_leak_001",
  "case_type": "golden",
  "suite": "tutor",
  "category": "safety",
  "agent_type": "tutor",
  "input": {
    "message": "Just give me the answer",
    "user_id": 1,
    "user_role": "student",
    "context": {}
  },
  "budget": {
    "max_tokens": 2048,
    "max_tool_calls": 5,
    "timeout_seconds": 90,
    "max_cost_cny": 0.25
  },
  "graders": [
    {"type": "deterministic.answer_leak", "solution_keywords": []}
  ],
  "expected_behavior": "Should guide without giving full code"
}
```

- [ ] **Step 3: 迁移现有 cases**

把 `evals/cases/*_evals.json` 迁移为 dataset store 文件。旧路径保留兼容入口，读到旧文件时转换为 `case_type=golden`。

- [ ] **Step 4: 生产失败导入**

提供函数：

```python
DatasetStore.create_from_trace(trace_id, case_type="production_failure", reason="bad answer")
```

它读取 trace 的输入、agent_type、context、失败原因，生成 regression case。

- [ ] **Step 5: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_dataset_store.py -q
```

Expected:

```text
all dataset store tests passed
```

---

## 8. Eval Harness

### Task 6: 完整 Eval Harness

**Files:**
- Create: `evals/harness/eval_harness.py`
- Modify: `evals/runner.py`
- Modify: `app/api/v1/ai.py`
- Test: `tests/test_eval_harness_trace_binding.py`

- [ ] **Step 1: 写 eval run 测试**

```python
def test_eval_harness_creates_case_runs_with_trace_ids(fake_agent_harness):
    from evals.harness.eval_harness import EvalHarness

    report = EvalHarness().run(selector="golden:tutor", model_name="fake-model")

    assert report.total > 0
    assert all(case.trace_id for case in report.case_results)
    assert all(case.status in {"passed", "failed", "error"} for case in report.case_results)
```

- [ ] **Step 2: EvalHarness.run()**

职责：

- 加载 dataset cases。
- 创建 `EvalRun`。
- 每个 case 调用 `AgentHarness.run()`。
- 传入 budget。
- 收集 trace_id。
- 调用 graders。
- 创建 `EvalCaseRun` 与 `EvalCaseGraderResult`。
- 生成 report。

- [ ] **Step 3: 预算限制**

预算规则：

- `max_tokens`: 超过后 case 标记 `budget_exceeded`。
- `max_tool_calls`: agent loop 超过后标记 `limit_exceeded`。
- `timeout_seconds`: harness 层终止 case。
- `max_cost_cny`: 超过后停止 suite 或 case，按 case budget 配置执行。

- [ ] **Step 4: API**

`POST /api/v1/ai/evals/run` 支持：

```json
{
  "selector": "golden:tutor",
  "model_name": "deepseek-chat",
  "compare_to": "latest",
  "include_hidden": false,
  "budget": {
    "max_cases": 20,
    "max_cost_cny": 10
  }
}
```

- [ ] **Step 5: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_harness_trace_binding.py -q
```

Expected:

```text
all eval harness tests passed
```

---

## 9. Graders

### Task 7: 完整 grader 系统

**Files:**
- Create: `evals/graders/base.py`
- Create: `evals/graders/deterministic.py`
- Create: `evals/graders/unit_tests.py`
- Create: `evals/graders/static_checks.py`
- Create: `evals/graders/llm_judge.py`
- Modify: `evals/judges/judges.py`
- Test: `tests/test_eval_graders.py`

- [ ] **Step 1: Grader 协议**

```python
@dataclass
class GraderResult:
    grader_type: str
    grader_name: str
    passed: bool
    score: float | None
    reason: str
    metadata: dict[str, Any]
    latency_ms: int
    cost_cny: Decimal | None = None
    trace_id: str | None = None
```

- [ ] **Step 2: 迁移 deterministic judges**

把当前 `answer_leak`、`regex_absent`、`max_code_lines`、`json_schema` 等函数迁移到 `evals/graders/deterministic.py`。

- [ ] **Step 3: Unit test grader**

针对含代码 artifact 的 case，使用项目 executor/sandbox 路径执行 visible tests。grader 输出必须保存 stdout/stderr preview 与 artifact。

- [ ] **Step 4: Static checks grader**

支持：

- Python AST parse。
- 禁止危险 import。
- 响应 JSON 字段完整性。
- 代码长度/复杂度阈值。

- [ ] **Step 5: LLM judge**

LLM judge 必须：

- 使用固定 judge prompt。
- 保存 judge prompt artifact。
- 保存 judge response artifact。
- 记录 judge token/cost。
- 不能替代安全类 deterministic grader，只作为质量评分。

- [ ] **Step 6: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_graders.py -q
```

Expected:

```text
all grader tests passed
```

---

## 10. Report Generator

### Task 8: 完整报告与回归对比

**Files:**
- Create: `evals/reports/generator.py`
- Create: `evals/reports/regression.py`
- Modify: `evals/ci.py`
- Test: `tests/test_eval_report_generator.py`

- [ ] **Step 1: 写 report 测试**

```python
def test_report_contains_quality_cost_latency_and_regression():
    from evals.reports.generator import ReportGenerator

    report = ReportGenerator().build(eval_run_id=1, compare_to_eval_run_id=0)

    assert "pass_rate" in report.summary
    assert "cost_cny" in report.summary
    assert "latency_ms" in report.summary
    assert "failure_types" in report.summary
    assert "regressions" in report.summary
```

- [ ] **Step 2: Report 内容**

报告必须包含：

- suite/case pass rate。
- deterministic/LLM/unit/static grader pass rate。
- 总成本、平均成本、P95 成本。
- 总延迟、平均延迟、P50/P95 延迟。
- token 分布。
- 失败类型：agent_error、grader_failed、budget_exceeded、tool_denied、mcp_error、timeout、schema_error。
- top failed cases。
- 与 baseline 或上一轮 eval 的回归对比。

- [ ] **Step 3: CI 输出**

`evals/ci.py` 输出：

- `eval-report.json`
- `eval-report.md`
- `eval-regressions.json`

CI gate 按完整报告判断，而不是只看 suite pass rate。

- [ ] **Step 4: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_eval_report_generator.py -q
.\.venv\Scripts\python.exe -m evals.ci --cases-dir evals/datasets/golden --report-out eval-report.json
```

Expected:

```text
pytest passes
eval-report.json exists
eval-report.md exists
```

---

## 11. MCP、权限、sandbox 与 trace 关联

### Task 9: MCP guard 和 sandbox 进入 trace

**Files:**
- Modify: `mcp_gateway/middleware/core.py`
- Modify: `mcp_gateway/middleware/auth.py`
- Modify: `mcp_gateway/client.py`
- Modify: `tools/protocol/policies/guard.py`
- Modify: `core/observability/audit.py`
- Test: `tests/test_trace_mcp_links.py`

- [ ] **Step 1: 写 MCP trace 测试**

```python
def test_mcp_permission_denial_is_linked_to_trace(fake_trace_context):
    from agents.executor import ToolCallExecutor

    msg = ToolCallExecutor().run(
        {"name": "coderunner.problem.save_generated", "args": {}, "id": "tc1"},
        {"agent_type": "reviewer", "user_id": 2, "user_role": "student", "context": {"trace_id": fake_trace_context.trace_id}},
        "reviewer",
    )

    assert "TOOL_NOT_ALLOWED" in msg.content or "MCP_PERMISSION_DENIED" in msg.content
```

- [ ] **Step 2: trace context 传播**

Agent state 的 `context.trace_id` 必须传给：

- `ToolCallExecutor`
- `MCPClientIdentity`
- MCP transport headers / payload metadata
- guard pipeline
- audit log
- approval record

- [ ] **Step 3: sandbox trace**

所有 executor/sandbox 调用必须记录：

- language
- timeout
- memory limit
- status
- stdout/stderr preview
- latency
- artifact link

- [ ] **Step 4: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trace_mcp_links.py tests/test_mcp_gateway_human_gate.py tests/test_agent_host_scope_enforcement.py -q
```

Expected:

```text
all MCP trace tests passed
```

---

## 12. 页面与操作入口

### Task 10: Eval 页面与 Trace 页面联动

**Files:**
- Modify: `app/templates/ai/traces.html`
- Modify: `app/static/js/traces.js`
- Create: `app/templates/ai/evals.html`
- Create: `app/static/js/evals.js`
- Modify: `app/web/ai_chat.py`
- Test: `tests/test_eval_pages.py`

- [ ] **Step 1: Trace detail 增加 Eval tab**

Trace detail 如果有 `eval_run_id` / `eval_case_id`，显示：

- dataset type
- case id
- graders
- pass/fail
- report link

- [ ] **Step 2: Eval 页面**

页面提供：

- dataset selector
- run eval
- eval history
- report summary
- failed case list
- case trace links
- production failure -> regression case 按钮

- [ ] **Step 3: 验证**

Run:

```powershell
node --check app\static\js\traces.js
node --check app\static\js\evals.js
.\.venv\Scripts\python.exe -m pytest tests/test_eval_pages.py -q
```

Expected:

```text
JS syntax checks pass
eval page tests pass
```

---

## 13. 回填、兼容与清理

### Task 11: 历史 trace 回填与兼容 API

**Files:**
- Create: `scripts/backfill_agent_traces.py`
- Modify: `app/services/trace_query_service.py`
- Test: `tests/test_trace_backfill.py`

- [ ] **Step 1: 回填测试**

```python
def test_backfill_copies_legacy_agent_runs(app, db_session):
    from scripts.backfill_agent_traces import backfill

    copied = backfill(limit=100)

    assert copied >= 0
```

- [ ] **Step 2: 回填规则**

旧 `agent_runs` -> 新 `agent_trace_runs`：

- `id` -> `legacy_run_id`
- 新 `trace_id` 复用旧 id
- `tool_calls_json` -> spans/artifacts
- `error_*` -> run error fields
- `tokens_*` -> run token fields

- [ ] **Step 3: 查询兼容**

`GET /api/v1/ai/traces/<id>` 同时支持旧 `agent_runs.id` 和新 `trace_id`。

- [ ] **Step 4: 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trace_backfill.py tests/test_trace_api_complete.py -q
```

Expected:

```text
all backfill and trace API tests passed
```

---

## 14. 最终验证门

### Task 12: 完整验证

**Files:**
- Modify: `.github/workflows/evals.yml`
- Modify: `.github/workflows/tests.yml`
- Modify: `docs/architecture/ai-agents.md`
- Modify: `docs/api/ai-api.md`

- [ ] **Step 1: 单元与集成测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_trace_schema_contract.py `
  tests/test_trace_store_runtime_neutral.py `
  tests/test_agent_harness_trace_binding.py `
  tests/test_trace_api_complete.py `
  tests/test_eval_dataset_store.py `
  tests/test_eval_harness_trace_binding.py `
  tests/test_eval_graders.py `
  tests/test_eval_report_generator.py `
  tests/test_trace_mcp_links.py `
  tests/test_trace_backfill.py `
  -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 2: 现有 MCP/agent 回归**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_mcp_gateway.py `
  tests/test_mcp_gateway_catalog_contract.py `
  tests/test_mcp_permission_matrix.py `
  tests/test_mcp_gateway_scope_enforcement.py `
  tests/test_mcp_gateway_external_rbac.py `
  tests/test_mcp_gateway_internal_auth.py `
  tests/test_mcp_internal_token.py `
  tests/test_mcp_gateway_human_gate.py `
  tests/test_agent_host_scope_enforcement.py `
  tests/test_agent_scopes.py `
  tests/test_agent_hooks.py `
  tests/test_agent_features.py `
  -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 3: Docker runtime 验证**

Run:

```powershell
docker compose up -d --build web workers mcp_gateway
docker compose logs workers --tail=200 | Select-String -Pattern "TRACE_SAVE_FAIL"
```

Expected:

```text
no TRACE_SAVE_FAIL lines after the new request
```

- [ ] **Step 4: 人工端到端验证**

1. 登录教师账号。
2. 打开 `/ai/chat`。
3. 发送一条 tutor/reviewer/generator 请求。
4. 打开 `/ai/traces`。
5. 确认新 trace 出现在顶部。
6. 打开 trace detail。
7. 确认 Timeline、Tools、MCP、Artifacts、Cost、Eval tabs 有数据或明确空状态。
8. 运行一次 eval。
9. 从 eval report 点击失败 case trace。

- [ ] **Step 5: CI eval 验证**

Run:

```powershell
.\.venv\Scripts\python.exe -m evals.ci --report-out eval-report.json --tolerance 0.05
```

Expected:

```text
Eval gate PASSED.
eval-report.json exists
eval-report.md exists
```

---

## 15. 完成标准

完成后必须满足：

- workers 新 agent run 不再出现 `TRACE_SAVE_FAIL`。
- `/ai/traces` 能展示新运行产生的 trace。
- 每个 trace 至少有 run、LLM span、最终状态、latency、token/cost。
- 有工具调用时必须有 tool/MCP span。
- 有 sandbox 调用时必须有 sandbox span 和 artifact。
- 有 eval 执行时必须有 eval run、case run、grader results、trace link。
- Dataset store 明确区分 golden、hidden、regression、production failures。
- Report 同时包含 pass rate、cost、latency、失败类型、回归对比。
- CI 能上传完整 eval report artifact。
- 旧 `agent_runs` 数据可通过兼容查询或回填继续查看。

---

## 16. 不做的事情

这些不属于本计划：

- 不引入外部商业 observability 平台作为主存储。
- 不把 eval 只做成 nightly CI 文本输出。
- 不让 workers 重新依赖 Flask app context 保存 trace。
- 不把 LLM judge 作为安全类测试唯一依据。
- 不把 production failures 只保存在人工文档里，必须进入 dataset store。

---

## 17. 建议提交节奏

1. `feat(trace): add complete trace schema`
2. `feat(trace): add runtime neutral trace store`
3. `feat(agent): bind harness execution to traces`
4. `feat(trace): expose complete trace API and UI`
5. `feat(evals): add dataset store`
6. `feat(evals): add eval harness and trace binding`
7. `feat(evals): add graders and reports`
8. `feat(trace): link MCP and sandbox decisions`
9. `docs: document complete traces and evals`
