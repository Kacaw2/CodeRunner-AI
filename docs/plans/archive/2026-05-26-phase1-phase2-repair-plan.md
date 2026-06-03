# Phase 1/2 修复方案：让 Agent Host 和 Supervisor 真正接入主链路

> 日期：2026-05-26
> 状态：待审阅（v2 — 工程化版本）
> 前置文档：`docs/FASTAPI_AGENT_HOST_MCP_WORKFLOW_PLAN_ZH.md`
> 目标：修复 Phase 1/2 的 scaffold 级实现，使其成为可用的生产链路，为 Phase 3 MCP Server 做准备

## 一、问题诊断

### 1.1 Phase 1 现状：scaffold + Docker 存在 ≠ 正确接入

| 问题 | 证据 |
|------|------|
| **workflow DB relationship 已坏** | `agent_host/models/workflow.py:89` — `workflow_run_id = Column(String(36), nullable=False)` 缺少 `ForeignKey("workflow_runs.id")`，导致 `relationship()` 抛 `NoForeignKeysError`，`GET /api/workflows` 返回 500 |
| **FastAPI 只是 HTTP 转发层** | `agent_host/worker/task_runner.py:103` 调 `flask_client.create_chat_task()`，`:219` 调 `flask_client.create_workflow()` — 文件开头注释明确写 *"delegates actual agent execution to the Flask backend via HTTP adapter"* |
| **前端仍打 Flask** | `app/static/js/ai_chat.js:3` — `API_CHAT_ASYNC = "/api/v1/ai/chat/async"` 指向 Flask，不是 Agent Host `:8100` |

### 1.2 Phase 2 现状：内部原型可运行 ≠ 正确完成

| 问题 | 证据 |
|------|------|
| **核心组件存在** | `supervisor.py`、`planner.py`、`engine.py`、`critic.py`、`handlers.py`、`registry.py` 均有实质代码，Flask smoke test 证明能落库 |
| **chat_worker 没走 Supervisor** | `app/agents/chat_worker.py:158` import `_classify_intent`，`:200` 直接 `agent_cls = _AGENT_MAP.get(resolved_agent_type, TutorAgent)` — 完全跳过 SupervisorAgent |
| **出题入口仍用旧 pipeline** | `app/api/v1/ai.py:1107` — `from app.agents.generation_pipeline import run_generation_pipeline`，新的 `run_generation_workflow`（`generation_pipeline.py:320`）未被任何入口调用 |
| **生产 DB 无 workflow 数据** | `workflow_runs=0, workflow_steps=0, chat_tasks=6` — 所有流量走 chat task，不走 workflow |

## 二、架构决策审查

在给出修复方案前，先对每个关键决策点做工程化评审，排除临时方案。

### 2.1 Flask 耦合分析

经依赖扫描确认，各层对 Flask-SQLAlchemy 的耦合程度如下：

| 层级 | Flask-SQLAlchemy 耦合 | 具体依赖 |
|------|----------------------|---------|
| Agent (tutor/reviewer/generator/analytics) | **无** | 纯 LangChain，不 import `db` 或 `models` |
| AIConfig | **无** | 纯环境变量 + `ChatOpenAI` |
| Planner | **无** | 纯 LLM 调用 + 模板 |
| Critic | **无** | 纯 LLM 调用 |
| **WorkflowEngine** | **有 — 3 处** | `from app.core.extensions import db`; `WorkflowRun.query` |
| **Supervisor** | **有 — 1 处** | `WorkflowRun.query.get()` in `get_workflow_status()` |
| **Tools** (question_query, analytics_query 等) | **有 — 4 文件** | `Problem.query.get()`, `Submission.query.filter()` 等 |
| **Handlers** | **间接** | 通过 Agent + Tools 间接依赖 |

关键结论：**Agent 层本身不依赖 Flask。耦合点集中在 Engine、Supervisor、Tools 的 DB 访问行上**。

### 2.2 WP-2 Agent Host 执行方式：方案淘汰

| 方案 | 说明 | 工程化评价 | 结论 |
|------|------|-----------|------|
| A: Worker 线程内 `with flask_app.app_context():` | 最小改动 | 两框架生命周期、middleware、session 全耦合，任何升级都是地雷 | ❌ 淘汰 |
| C: FastAPI 进程加载 Flask app 对象 | 中等改动 | Frankenstein 进程，两个框架的 app 对象共存，context/session/middleware 互相干扰 | ❌ 淘汰 |
| **B: 抽 service 层，Agent Host 直接执行** | DB 访问改为接收 session 参数 | 干净解耦，Agent Host 和 Flask 各用自己的 session factory | ✅ **采用** |

**方案 B 的实际工作量远小于预期**：不需要重构所有 Agent 代码（Agent 不依赖 Flask），只需要改 Engine（3 处）、Supervisor（1 处）、Tools（4 文件）中的 `db.session` / `Model.query` → 接收 session 参数。

### 2.3 WP-3 前端接入方式

| 方案 | 说明 | 工程化评价 | 结论 |
|------|------|-----------|------|
| A: 前端直连 `:8100` | 改 `ai_chat.js` URL | 跨域处理、灰度困难、暴露内部拓扑 | ❌ 不推荐 |
| **B: Flask 反向代理到 Agent Host** | Flask 作为 API Gateway | 标准微服务模式，前端零改动，单一域名，认证/限流在一处 | ✅ **采用** |

Flask proxy 不是临时 hack，而是正确的 API Gateway 模式。即使未来 Agent Host 完全成熟，保留 Flask 作为统一入口仍有工程价值。

### 2.4 WP-4 Supervisor 接入位置

| 方案 | 说明 | 工程化评价 | 结论 |
|------|------|-----------|------|
| 改 Flask `chat_worker.py` 加 Supervisor 调用 | 在 Flask Worker 内部插入 Supervisor 判断 | 方向相反 — 如果目标是 Agent Host 成为主控，在 Flask 里加更多逻辑等于现在加、Phase 3 搬走 | ❌ 临时方案 |
| **改 Agent Host `task_runner.py` 接入 Supervisor** | Agent Host Worker 直接调 SupervisorAgent | 逻辑归属正确，与 WP-2B（service 层）配合后一步到位 | ✅ **采用** |

### 2.5 决策总结

```
WP-1  修 ForeignKey                        — 无争议
WP-2  方案 B：抽 service 层                — 一次到位，不走 Frankenstein
WP-3  Flask proxy 到 Agent Host            — 标准 API Gateway
WP-4  Supervisor 接入 Agent Host worker    — 逻辑归属正确
WP-5  /generate/pipeline 切 workflow       — Flask 内直接切函数（短期可接受）
WP-6  端到端验证                           — 无争议
```

## 三、修复总览

```
Phase 1 修复（Agent Host 从转发层变为真正的主控）
  ├── WP-1: 修 ForeignKey bug（5 分钟）
  ├── WP-2B: 抽 service 层，Agent Host 直接执行（2-3 小时）
  └── WP-3: Flask proxy 到 Agent Host（20 分钟）

Phase 2 修复（Supervisor 接入主链路）
  ├── WP-4: Agent Host task_runner 接入 SupervisorAgent（30 分钟）
  ├── WP-5: /generate/pipeline 切换到 run_generation_workflow（15 分钟）
  └── WP-6: 端到端验证（20 分钟）
```

## 四、WP-1：修 ForeignKey bug

**文件**: `agent_host/models/workflow.py`

**当前代码** (第 9、89 行):

```python
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
# ...
class WorkflowStep(Base):
    # ...
    workflow_run_id: Mapped[str] = Column(String(36), nullable=False)
```

**修复**:

```python
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
# ...
class WorkflowStep(Base):
    # ...
    workflow_run_id: Mapped[str] = Column(
        String(36), ForeignKey("workflow_runs.id"), nullable=False
    )
```

**影响范围**: 仅 `agent_host/models/workflow.py`，不影响 Flask 侧的 `app/models/workflow.py`（Flask 侧第 70 行已正确声明 `db.ForeignKey("workflow_runs.id")`）。

**验证**: 重启 Agent Host 容器后，带 JWT 访问 `GET /api/workflows` 返回 200。

## 五、WP-2B：抽 service 层，Agent Host 直接执行 Agent

### 5.1 目标

将 Workflow Engine、Supervisor、Tools 中的 Flask-SQLAlchemy 依赖改为接收 session 参数，使 Agent Host 和 Flask 都能调用同一套代码，各用自己的 session factory。

### 5.2 不需要改动的部分

以下代码**不动**（不依赖 Flask-SQLAlchemy）：

- `app/agents/agents/` — 四个 specialist agent（纯 LangChain）
- `app/agents/config.py` — `AIConfig`（纯环境变量）
- `app/agents/workflow/planner.py` — 纯 LLM 调用
- `app/agents/workflow/critic.py` — 纯 LLM 调用
- `app/agents/workflow/state.py` — 纯 TypedDict
- `app/agents/workflow/registry.py` — 纯注册表（handler 内部的 import 是 lazy 的）
- `app/agents/prompts/` — 纯字符串模板

### 5.3 需要改动的文件

#### 5.3.1 app/agents/workflow/engine.py（3 处 `db.session` → session 参数）

**当前**:

```python
class WorkflowEngine:
    def execute(self, plan, user_id, user_role, ...):
        from app.core.extensions import db           # ← Flask 耦合
        from app.models.workflow import WorkflowRun   # ← Flask-SQLAlchemy 模型
        # ...
        db.session.add(workflow_run)
        db.session.commit()
```

**改为**:

```python
class WorkflowEngine:
    def __init__(self, session=None):
        self._events: list[dict] = []
        self._session = session

    def _get_session(self):
        """获取 DB session：优先用注入的，否则回退到 Flask db.session。"""
        if self._session is not None:
            return self._session
        from app.core.extensions import db
        return db.session

    def execute(self, plan, user_id, user_role, ...):
        from app.models.workflow import WorkflowRun, WorkflowStep
        session = self._get_session()
        # ...
        session.add(workflow_run)
        session.commit()
```

同时 `resume_after_approval()` 和 `_execute_step()` 中的 `db.session` 也改为 `self._get_session()`。

`from app.models.workflow import WorkflowRun, WorkflowStep` 保留不变——这些是 SQLAlchemy 模型定义，Flask-SQLAlchemy 的 `db.Model` 底层就是 `declarative_base()`，与纯 SQLAlchemy session 兼容。Agent Host 侧需要确保表映射一致（已通过共享 DB 保证）。

> **备注**：如果 Agent Host 需要避免 import `app.models.workflow`（避免拉入整个 Flask app），可以让 Agent Host 使用自己的 `agent_host/models/workflow.py`（已存在且结构一致）。此时 engine.py 的 import 需要参数化，但这是更后期的解耦，当前阶段可先保留。

#### 5.3.2 app/agents/workflow/supervisor.py（1 处 `Model.query`）

**当前** (`get_workflow_status()`, 第 85-91 行):

```python
def get_workflow_status(self, workflow_run_id: str) -> dict:
    from app.models.workflow import WorkflowRun, WorkflowStep
    run = WorkflowRun.query.get(workflow_run_id)
    steps = WorkflowStep.query.filter_by(...).all()
```

**改为**:

```python
def __init__(self, session=None):
    self._session = session

def get_workflow_status(self, workflow_run_id: str) -> dict:
    from app.models.workflow import WorkflowRun, WorkflowStep
    if self._session:
        run = self._session.get(WorkflowRun, workflow_run_id)
        steps = (self._session.query(WorkflowStep)
                 .filter_by(workflow_run_id=workflow_run_id)
                 .order_by(WorkflowStep.step_index).all())
    else:
        run = WorkflowRun.query.get(workflow_run_id)
        steps = (WorkflowStep.query
                 .filter_by(workflow_run_id=workflow_run_id)
                 .order_by(WorkflowStep.step_index).all())
```

并且 `run_workflow()` 创建 `WorkflowEngine` 时传入 session：

```python
def run_workflow(self, ...):
    engine = WorkflowEngine(session=self._session)
    state = engine.execute(...)
```

#### 5.3.3 Tools 中的 DB 访问（4 文件）

工具函数中使用 `Model.query.get()` / `Model.query.filter_by()`。改造方式：给每个工具函数增加可选的 `session` 参数，有则用 `session.get()` / `session.query()`，无则走原来的 `Model.query`：

**app/agents/tools/question_query.py**:

```python
# 当前
def get_problem_detail(problem_id: int) -> dict:
    problem = Problem.query.get(problem_id)

# 改为（保持向后兼容）
def get_problem_detail(problem_id: int, *, session=None) -> dict:
    if session:
        problem = session.get(Problem, problem_id)
    else:
        problem = Problem.query.get(problem_id)
```

同理修改:
- `app/agents/tools/analytics_query.py` — `get_student_activity`, `get_class_statistics`, `get_problem_difficulty_stats`
- `app/agents/tools/submission_query.py` — 如有 `Model.query` 调用

**LangChain Tool 包装层**：现有 Tools 通过 `@tool` 装饰器注册，LangChain 调用时不传 session。解决方式：使用 `contextvars` 或在 Tool 的 run 方法中通过 context dict 获取 session：

```python
import contextvars

_current_session: contextvars.ContextVar = contextvars.ContextVar("db_session", default=None)

def get_current_session():
    return _current_session.get()

# 工具内部使用
def get_problem_detail(problem_id: int) -> dict:
    session = get_current_session()
    if session:
        problem = session.get(Problem, problem_id)
    else:
        problem = Problem.query.get(problem_id)

# Agent Host worker 执行前设置
_current_session.set(agent_host_session)
try:
    result = agent.invoke(state)
finally:
    _current_session.set(None)
```

### 5.4 Agent Host task_runner.py 重写

WP-2B 完成后，`task_runner.py` 不再需要 `flask_client` HTTP 转发，而是直接：

```python
from agent_host.core.db import db_session

def _run_chat_task(task_id: str, jwt_token: str, message: str):
    """直接执行 Agent，不再 HTTP 转发。"""
    with db_session() as session:
        # 1. 查 ChatTask → 标记 processing
        task = session.get(ChatTask, task_id)
        task.status = "processing"
        session.flush()

        # 2. 设置 session context var（供 Tools 使用）
        from app.agents.tools.db_context import _current_session
        _current_session.set(session)

        try:
            # 3. 意图分类 → Agent 执行（Agent 层不依赖 Flask）
            from app.agents.orchestrator import _classify_intent
            from app.agents.agents import TutorAgent, ...

            state = _classify_intent(state)
            agent = _AGENT_MAP[state["agent_type"]]()
            for event in agent.stream(state):
                redis_buffer.ct_push_event(task_id, event)

            # 4. 保存结果
            ...
        finally:
            _current_session.set(None)
```

### 5.5 清理

`agent_host/adapters/flask_client.py` 不再被主路径使用。保留文件但标记 deprecated，后续移除。

## 六、WP-3：Flask proxy 到 Agent Host

### 6.1 方案

Flask 作为 API Gateway，将 AI chat 请求转发到 Agent Host。这是标准微服务模式，不是临时方案。

### 6.2 代码修改

**新建**: `app/api/v1/ai_proxy.py` 或在现有 `ai.py` 中添加 proxy 函数：

```python
import os
import httpx

AGENT_HOST_URL = os.environ.get("AGENT_HOST_URL", "http://localhost:8100")

def _proxy_to_agent_host(path: str, flask_request):
    """标准反向代理：转发请求到 Agent Host，原样返回响应。"""
    url = f"{AGENT_HOST_URL}{path}"
    headers = {
        "Authorization": flask_request.headers.get("Authorization", ""),
        "Content-Type": "application/json",
    }
    resp = httpx.request(
        method=flask_request.method,
        url=url,
        headers=headers,
        content=flask_request.get_data(),
        timeout=120,
    )
    return (resp.content, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json")})
```

**修改** `app/api/v1/ai.py` 中的 `/chat/async` 端点：

```python
@bp.route("/chat/async", methods=["POST"])
@require_auth
def create_chat_async():
    """Proxy to Agent Host."""
    return _proxy_to_agent_host("/api/chat", request)
```

**SSE 流式 proxy**（`/chat/task/<id>/stream`）需要特殊处理——使用 `httpx.stream` + Flask `Response(stream_with_context(...))`：

```python
@bp.route("/chat/task/<task_id>/stream", methods=["GET"])
@require_auth
def stream_chat_task_proxy(task_id):
    """SSE proxy to Agent Host."""
    url = f"{AGENT_HOST_URL}/api/chat/task/{task_id}/stream"
    headers = {"Authorization": request.headers.get("Authorization", "")}

    def generate():
        with httpx.stream("GET", url, headers=headers, timeout=330) as resp:
            for line in resp.iter_lines():
                yield line + "\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")
```

### 6.3 前端改动

**无**。前端继续打 `/api/v1/ai/chat/async`，Flask 透明转发。

### 6.4 灰度策略

可通过环境变量控制是否启用 proxy：

```python
USE_AGENT_HOST_PROXY = os.environ.get("USE_AGENT_HOST_PROXY", "false").lower() == "true"

@bp.route("/chat/async", methods=["POST"])
@require_auth
def create_chat_async():
    if USE_AGENT_HOST_PROXY:
        return _proxy_to_agent_host("/api/chat", request)
    # 原有 Flask 内部处理逻辑（fallback）
    ...
```

## 七、WP-4：Agent Host task_runner 接入 SupervisorAgent

### 7.1 前置依赖

WP-2B 完成后，Agent Host worker 已能直接调用 Agent 代码。在此基础上接入 Supervisor。

### 7.2 执行路径

```
前端 → Flask /chat/async → proxy → Agent Host POST /api/chat
  → Agent Host worker _run_chat_task()
    → SupervisorAgent.invoke_from_chat()
      ├── _should_use_workflow() == True
      │   → Planner → Engine.execute(session=agent_host_session) → workflow 落库
      │   → 返回 workflow 结果
      └── _should_use_workflow() == False
          → _classify_intent → Agent.stream(state)
          → 返回单 Agent 结果
    → 事件写 Redis → SSE 返回
```

### 7.3 代码修改

**文件**: `agent_host/worker/task_runner.py`

在 `_run_chat_task()` 中，intent 分类完成后、agent 执行之前，插入 Supervisor 判断：

```python
def _run_chat_task(task_id: str, jwt_token: str, message: str):
    with db_session() as session:
        # ... 查 task, 加载历史, _classify_intent ...

        # ── Try Supervisor workflow first ──
        from app.agents.workflow import SupervisorAgent

        supervisor = SupervisorAgent(session=session)
        wf_result = supervisor.invoke_from_chat(
            user_id=task.user_id,
            user_role=user_role,
            message=message,
            conversation_id=task.conversation_id,
            chat_task_id=task_id,
            context=context,
        )

        if wf_result.get("use_workflow"):
            # Supervisor 接管，推送 workflow 事件
            for evt in wf_result.get("events", []):
                redis_buffer.ct_push_event(task_id, evt)
            full_response = _format_workflow_result(wf_result)
        else:
            # 单 Agent 路径
            agent_cls = _AGENT_MAP.get(resolved_agent_type, TutorAgent)
            agent = agent_cls()
            full_response = ""
            for event in agent.stream(state):
                if event["type"] == "token":
                    full_response += event["content"]
                redis_buffer.ct_push_event(task_id, event)
            # ... handoff 逻辑 ...

        # ... 保存 assistant message, 标记 completed ...
```

### 7.4 新增辅助函数

```python
def _format_workflow_result(wf_result: dict) -> str:
    """将 Supervisor workflow 结果格式化为用户可读的回复文本。"""
    status = wf_result.get("status", "unknown")
    result = wf_result.get("result")
    error = wf_result.get("error")

    if status == "waiting_approval":
        return "题目已生成并保存为草稿，等待您的审批。"
    if status == "failed":
        return f"工作流执行失败：{error or '未知错误'}"
    if status == "completed" and result:
        if isinstance(result, dict):
            for step_output in result.values():
                if isinstance(step_output, dict) and "problem_data" in step_output:
                    import json
                    return json.dumps(step_output["problem_data"],
                                      indent=2, ensure_ascii=False)
        return str(result)
    return "工作流已完成。"
```

### 7.5 SupervisorAgent.invoke_from_chat() 现状确认

`supervisor.py:100-134` 中 `invoke_from_chat()` 逻辑完整：
- 调用 `_should_use_workflow(message, user_role)` 做启发式判断
- 触发条件包括：教师出题关键词（生成/出题/创建题目）、多步关键词（然后/接着/批量）
- 不触发时返回 `{"use_workflow": False}`
- 触发时调 `run_workflow()` → `create_plan()` → `engine.execute()`

`_should_use_workflow()` 的触发词列表（`supervisor.py:148-160`）：
- 教师出题：`生成, 出题, 创建题目, generate, create problem, create a problem, 出一道, 新题`
- 多步操作：`然后, 接着, 之后, and then, followed by, 批量, batch, 多个, multiple`

学生日常 chat（"这道题怎么做"）不会触发 workflow，行为与当前一致。

## 八、WP-5：/generate/pipeline 切换到 workflow

**文件**: `app/api/v1/ai.py`

### 8.1 当前代码（第 1107-1117 行）

```python
from app.agents.generation_pipeline import run_generation_pipeline
try:
    result = run_generation_pipeline(
        teacher_id=user.id,
        prompt=prompt,
        language=data.get("language", "python"),
        difficulty=data.get("difficulty", "medium"),
        topic=data.get("topic", ""),
        test_case_count=int(data.get("test_case_count", 5)),
        teacher_context=teacher_ctx,
    )
```

### 8.2 目标代码

```python
from app.agents.generation_pipeline import run_generation_workflow
try:
    result = run_generation_workflow(
        teacher_id=user.id,
        prompt=prompt,
        language=data.get("language", "python"),
        difficulty=data.get("difficulty", "medium"),
        topic=data.get("topic", ""),
        test_case_count=int(data.get("test_case_count", 5)),
        conversation_id=data.get("conversation_id"),
    )
```

### 8.3 返回值兼容性

`run_generation_workflow`（`generation_pipeline.py:320`）返回 `WorkflowState`，结构与原 `run_generation_pipeline` 不同：

| 字段 | `run_generation_pipeline` | `run_generation_workflow` |
|------|--------------------------|--------------------------|
| `status` | `"running"` → `"completed"/"failed"` | `"completed"/"failed"/"waiting_approval"` |
| `final_draft` | `{"question_data": {...}}` | 在 `step_outputs` 内 |
| `error` | `result["error"]` | `state["error"]` |

**需要在 `run_generation_workflow` 中加适配层**：

```python
def run_generation_workflow(...) -> dict:
    from app.agents.workflow import SupervisorAgent

    supervisor = SupervisorAgent()
    state = supervisor.run_workflow(...)

    # ── 适配原 run_generation_pipeline 返回格式 ──
    adapted = {
        "status": state.get("status", "failed"),
        "error": state.get("error"),
        "final_draft": None,
        "workflow_run_id": state.get("workflow_run_id"),
    }

    step_outputs = state.get("step_outputs") or state.get("final_result") or {}
    if isinstance(step_outputs, dict):
        for step_output in step_outputs.values():
            if isinstance(step_output, dict) and "problem_data" in step_output:
                adapted["final_draft"] = {
                    "question_data": step_output["problem_data"]
                }
                break

    return adapted
```

### 8.4 注意事项

- `run_generation_pipeline` 接受 `teacher_context` 参数，`run_generation_workflow` 不接受 — 需要将 teacher_context 放入 workflow context 传递。
- 两者都是同步阻塞调用，兼容。
- 此端点仍在 Flask 内直接调用（不经过 Agent Host proxy），因为它是独立的 pipeline 入口，短期内可接受。后续可选择 proxy 到 Agent Host。

## 九、WP-6：端到端验证

### 9.1 验证矩阵

| # | 测试项 | 操作 | 预期结果 | 验证方法 |
|---|--------|------|---------|---------|
| 1 | Agent Host health | `GET :8100/api/health` | `{"status":"ok"}` | curl |
| 2 | Agent Host workflow list | `GET :8100/api/workflows` (带 JWT) | 200，返回列表（不再 500） | curl + JWT |
| 3 | 学生普通 chat | 前端发"帮我看看这道题怎么做" | 走 TutorAgent，不触发 workflow | 检查 `workflow_runs` 表无新增 |
| 4 | 教师出题 (chat) | 前端发"出一道 Python 中等难度数组题" | `_should_use_workflow` → True → SupervisorAgent | 检查 `workflow_runs` 有 1 条新记录，`workflow_steps` 有 5 条 |
| 5 | 教师出题 (pipeline) | `POST /api/v1/ai/generate/pipeline` | 走 `run_generation_workflow` | 同上 |
| 6 | Workflow 落库 | 查 DB | `workflow_runs > 0, workflow_steps > 0` | SQL 查询 |
| 7 | Handoff 不受影响 | 学生发"帮我分析下我的成绩" → TutorAgent handoff 到 AnalyticsAgent | handoff 机制正常 | 检查 SSE 事件有 `handoff_start` |
| 8 | 断线恢复 | 发出题请求，中途关页面，重开 | ChatTask 状态为 completed，消息已保存 | 检查 `chat_tasks` 和 `ai_messages` |
| 9 | Proxy 透明性 | 前端 chat 请求 URL 不变 | Flask 透明代理到 Agent Host | 检查 Agent Host 容器日志有请求记录 |
| 10 | Fallback 开关 | `USE_AGENT_HOST_PROXY=false` | 请求走 Flask 内部 chat_worker | 检查 Flask 日志 |

### 9.2 回归检查

- [ ] 学生 chat 延迟无明显增加（proxy 增加 < 5ms，`_should_use_workflow` < 1ms）
- [ ] Generator JSON 前端卡片渲染不受影响
- [ ] 对话历史加载不受影响
- [ ] Agent trace 记录正常（`AgentRun` + `AgentRunStep`）

## 十、执行顺序

```
第一步  WP-1  修 ForeignKey                           (5 min)
        │     agent_host/models/workflow.py 加 ForeignKey
        │     → 验证 GET /api/workflows 返回 200
        │
第二步  WP-2B 抽 service 层                           (2-3 hr)
        │     engine.py    — 3 处 db.session → self._get_session()
        │     supervisor.py — 1 处 Model.query → session.get()
        │     tools/*.py   — 4 文件 Model.query → contextvars session
        │     task_runner.py — 直接调用 Agent，不再 HTTP 转发
        │     → 验证 Agent Host worker 能独立执行 Agent
        │
第三步  WP-4  Agent Host task_runner 接入 Supervisor   (30 min)
        │     invoke_from_chat() 在 Agent Host worker 中调用
        │     → 验证教师出题走 workflow，学生 chat 走单 Agent
        │
第四步  WP-3  Flask proxy /chat/async → Agent Host     (20 min)
        │     ai_proxy.py 或 ai.py 中加 proxy 函数
        │     灰度开关 USE_AGENT_HOST_PROXY
        │     → 验证前端请求透明代理到 Agent Host
        │
第五步  WP-5  Flask /generate/pipeline 切 workflow     (15 min)
        │     ai.py 中切到 run_generation_workflow
        │     generation_pipeline.py 加返回值适配层
        │     → 验证 pipeline 入口走 workflow
        │
第六步  WP-6  端到端验证                              (20 min)
        │     全部 10 项测试 + 回归检查
        │
        ▼
   Phase 1/2 修复完成 → 可启动 Phase 3
```

## 十一、风险与注意事项

### 11.1 WP-2B 的 Model 兼容性

Flask-SQLAlchemy 的 `db.Model` 底层是 `declarative_base()`。Agent Host 使用独立的 `Base = declarative_base()`。两者映射同一张表时，需要确保列定义完全一致。

当前 `agent_host/models/workflow.py` 是 `app/models/workflow.py` 的镜像，列定义一致。但如果未来一侧加列另一侧没同步，会出问题。

**建议**：考虑将共享模型抽到独立包（`shared/models/`），两侧都 import。但这是后续优化，当前阶段维护两份镜像文件即可。

### 11.2 WP-2B 的 contextvars 与线程池

`contextvars` 在 `ThreadPoolExecutor` 中的行为：Python 3.12+ 默认会复制 context 到子线程。但 `executor.submit()` 的时机和 context 设置的时机需要匹配。

**安全做法**：在 worker 线程内部设置 `_current_session`，不要在主线程设置后期望子线程继承。当前 `task_runner.py` 的 `_run_chat_task` 已经在 worker 线程内执行，所以在函数开头设置 contextvars 即可。

### 11.3 WP-4 的 Supervisor 误触发风险

`_should_use_workflow` 使用关键词匹配，可能存在误触发。学生说"我不理解这道题目是怎么生成的"包含"生成"，但 `user_role == "student"` 时教师出题触发条件不生效（`supervisor.py:147` 有 `if user_role == "teacher":` 保护），风险可控。

多步触发词（"然后"/"接着"）对学生也生效，但即使误触发，Planner 会生成合理的计划（通常是 1-2 步的 agent_call），不会造成破坏性影响。

### 11.4 WP-5 的返回值兼容风险

如果适配层不完整，`ai.py` 后续的 draft 保存逻辑（第 1119-1139 行）可能取不到 `question_data`，导致 draft 保存失败。需要重点测试这条路径。

### 11.5 WP-3 的 SSE Proxy

Flask 的 WSGI 不原生支持长连接流式响应。当前 Flask 已通过 `Response(stream_with_context(...))` 实现 SSE，proxy 到 Agent Host 的 SSE 也用同样方式。但需要确保：

- 反向代理（如 Nginx）不缓冲 SSE 响应（需要 `X-Accel-Buffering: no`）
- `httpx.stream` 的 timeout 足够长（330 秒，与 Agent Host 侧一致）

## 十二、不动的部分

以下代码在此次修复中**不修改**：

- `app/agents/orchestrator.py` — LangGraph 图不变，单 Agent 路径继续使用
- `app/agents/agents/` — 四个 specialist agent 不变
- `app/agents/prompts/` — prompt 不变
- `app/static/js/ai_chat.js` — 前端不变，URL 不变
- `app/agents/chat_worker.py` — Flask 内部 worker 保留作为 fallback（`USE_AGENT_HOST_PROXY=false` 时使用）

## 十三、后续（Phase 3 启动条件）

Phase 1/2 修复完成后，Phase 3 MCP Server 的前置条件为：

1. ✅ Agent Host 能直接执行 Agent（不再转发 Flask）
2. ✅ Supervisor workflow 在生产链路中运行，`workflow_runs` 表有实际数据
3. ✅ Agent Host DB relationship 正常
4. ✅ Flask proxy 到 Agent Host 已就绪
5. ⬜ 补齐 `get_agent_trace` 和 `get_student_summary` 两个 MCP 工具
6. ⬜ 实现 MCP 协议层（推荐使用 `mcp` SDK）
7. ⬜ MCP Server 鉴权接入（复用 Agent Host JWT）
