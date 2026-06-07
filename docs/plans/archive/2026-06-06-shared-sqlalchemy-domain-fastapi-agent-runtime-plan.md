# 共享 SQLAlchemy 2.0 Domain 与 FastAPI Agent Runtime 迁移计划

> **Status: archived / completed (2026-06-08).** 归档依据是 Task 10 的最终验证证据
> 与文末“验收总表”；早期任务 checklist 保留执行计划原貌，不再作为当前 active
> 状态跟踪入口。

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留已经完成的 Phase 1 清理结果，把当前 Flask 业务模型和
runtime-neutral trace/eval 模型收敛为一套 SQLAlchemy 2.0 Domain 映射，并在该
Domain 之上重建独立的 FastAPI Agent Runtime；迁移期间每张表始终只有一个 ORM
class，Flask 主站持续可运行。

**Architecture:** 建立纯 SQLAlchemy 2.0 的 `domain/`，由
`DomainBase(DeclarativeBase)` 承载唯一 registry 和 metadata。Flask-SQLAlchemy
通过 `SQLAlchemy(model_class=DomainBase)` 使用同一 registry；Flask、MCP
Gateway、Eval CLI 和 FastAPI Agent Runtime 各自拥有进程内 engine/session，
但导入同一组 mapped classes。模型和 repository 按
User/Auth -> Chat -> Workflow -> Trace/Eval -> MCP 纵切迁移；Agent Runtime
只在 Chat 所需 Domain 边界完成后开始重建，不恢复已删除的旧 Agent Host。

**Tech Stack:** Python 3, SQLAlchemy 2.0 typed declarative mapping,
Flask-SQLAlchemy 3.1, Alembic/Flask-Migrate, FastAPI, Uvicorn, `asyncmy`,
Pydantic 2, Redis SSE buffer, pytest.

---

## 已锁定决策

1. **保留 Phase 1 清理。** commit `f1f0a9f` 删除的
   `workers/__main__.py`、`workers/task_runner.py`、
   `app/api/v1/agents/*`、`app/api/v1/ai_proxy.py`、
   `app/services/agent_client.py` 和旧 `workers` compose service 不恢复。
2. **废止 Flask-only Phase 2。** 不把 MCP Gateway、Eval、TraceStore 强制塞入
   Flask app context；不以删除 runtime-neutral session 能力作为目标。
3. **一表一映射。** 迁移某张表时移动原 class 或重新导出同一个 class，禁止同时
   保留 `app.models.X` 和 `domain.models.X` 两个 mapped class。
4. **多进程多 engine 是正常的。** 统一的是模型、metadata、事务接口和 schema
   契约，不是跨进程共享连接池。
5. **Alembic 是唯一 schema source of truth。** ORM 重组不得顺手创建 migration；
   每个纵切都必须证明 `flask db check` 无 schema diff。
6. **FastAPI 是新的运行边界，不是旧代码复活。** 新服务使用
   `agent_runtime/` 包、明确的 command API、异步 session 和结构化 SSE；Flask
   对外 API 在迁移期保持不变。
7. **切换顺序是 embedded -> shadow -> remote。** 默认继续使用 Phase 1 后的
   Flask-native worker；新 Runtime 完成契约验证后才接管任务执行。

## 当前基线

截至 2026-06-06：

- Flask 业务模型位于 `app/models/*`，继承 `db.Model`。
- 剩余 plain SQLAlchemy 模型位于
  `core/db/models/agent_trace.py`，继承 `core.db.session.Base`。
- `core/db/metadata.py` 仍把两个 metadata 复制进第三个 metadata。
- `tests/conftest.py` 仍需把两套 metadata 建到同一 SQLite engine。
- `mcp_gateway` 已经用普通 SQLAlchemy Session 查询 Flask mapped classes，
  证明“同一 class + 非 Flask Session”可行。
- Flask chat/workflow worker 位于 `workers/chat.py` 和
  `workers/workflow.py`，它们是新 Runtime 上线前的可回滚基线。
- requirements 中已经移除 FastAPI/Uvicorn；只在 Runtime shell 落地时重新加入。

## 目标目录与职责

```text
domain/
  base.py                    # 唯一 DeclarativeBase / metadata
  models/                    # 唯一 mapped classes，不 import Flask/FastAPI
  statements/                # sync/async 共用的 Select/Update builders
  repositories/              # sync/async repository implementations

core/db/
  session.py                 # sync engine/session factory
  async_session.py           # async engine/async_sessionmaker
  metadata.py                # 直接返回 DomainBase.metadata

app/
  models/                    # 迁移期兼容 re-export；最终不再定义已迁移 class
  core/extensions.py         # Flask adapter
  services/                  # Flask use-case adapters

agent_runtime/
  main.py                    # FastAPI app factory
  dependencies.py            # AsyncSession、Redis、internal auth
  api/health.py
  api/chat_tasks.py
  api/workflows.py
  services/chat_runner.py
  services/workflow_runner.py
  schemas.py
```

依赖方向：

```text
domain <- app
domain <- agent_runtime
domain <- mcp_gateway
domain <- evals

domain -X-> Flask
domain -X-> FastAPI
domain -X-> app.core.extensions
```

## Task 1: 固化 Phase 1 清理和“一表一映射”守卫

**Files:**
- Create: `tests/test_phase1_agent_host_removal.py`
- Create: `tests/test_single_domain_registry.py`

- [ ] **Step 1: 写 Phase 1 residue 守卫**

扫描 runtime code/config，拒绝重新出现：

```python
FORBIDDEN = (
    "app.api.v1.agents",
    "app.services.agent_client",
    "app.api.v1.ai_proxy",
    "USE_AGENT_HOST_PROXY",
    "workers.task_runner",
)
```

同时断言旧文件和旧 compose `workers` service 不存在。历史归档文档不计入。

- [ ] **Step 2: 写单 registry 目标测试**

初始测试先 `xfail(strict=True)`：

```python
from app.core.extensions import db
from domain.base import DomainBase

assert db.Model.registry is DomainBase.registry
assert db.Model.metadata is DomainBase.metadata
```

- [ ] **Step 3: 运行基线**

```powershell
python -m pytest tests/test_phase1_agent_host_removal.py -q
python -m pytest tests/test_single_domain_registry.py -q
```

Expected: removal guard PASS；registry target 以 strict xfail 记录未完成状态。

- [ ] **Step 4: Commit**

```powershell
git add tests/test_phase1_agent_host_removal.py tests/test_single_domain_registry.py
git commit -m "test(arch): pin phase 1 cleanup and single-registry target"
```

## Task 2: 建立唯一 Base、metadata 和双 session factory

**Files:**
- Create: `domain/__init__.py`
- Create: `domain/base.py`
- Create: `core/db/async_session.py`
- Modify: `app/core/extensions.py`
- Modify: `core/db/session.py`
- Modify: `core/db/metadata.py`
- Modify: `core/config.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_combined_metadata.py`
- Modify: `tests/test_migration_full_schema.py`
- Test: `tests/test_single_domain_registry.py`

- [ ] **Step 1: 创建纯 SQLAlchemy Base**

```python
# domain/base.py
from sqlalchemy.orm import DeclarativeBase


class DomainBase(DeclarativeBase):
    """The only mapped-class registry in the application."""
```

- [ ] **Step 2: 让 Flask-SQLAlchemy 使用同一 Base**

`app/core/extensions.py`：

```python
from domain.base import DomainBase

db = SQLAlchemy(model_class=DomainBase)
```

保留 Flask 的 scoped `db.session` 和 request teardown。

- [ ] **Step 3: 把旧 `Base` 变成临时 alias**

`core/db/session.py` 删除 `declarative_base()`：

```python
from domain.base import DomainBase

Base = DomainBase  # temporary import compatibility, not another registry
```

不要从 `create_app()` 修改 core session globals；独立进程各自初始化 engine。

- [ ] **Step 4: 增加 async session factory**

`core/config.py` 新增 `DATABASE_ASYNC_URL`。未配置时只允许把
`mysql+pymysql://` 显式转换为 `mysql+asyncmy://`，其他 dialect 要求显式 URL。

```python
def _build_async_database_url(sync_url: str) -> str:
    explicit = os.environ.get("DATABASE_ASYNC_URL", "").strip()
    if explicit:
        return explicit
    if sync_url.startswith("mysql+pymysql://"):
        return sync_url.replace("mysql+pymysql://", "mysql+asyncmy://", 1)
    raise RuntimeError(
        "DATABASE_ASYNC_URL is required for non-MySQL async database access"
    )


class Settings:
    DB_URL: str = _build_database_url()
    DB_ASYNC_URL: str = _build_async_database_url(DB_URL)
```

`core/db/async_session.py` 暴露：

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        _async_engine = create_async_engine(
            settings.DB_ASYNC_URL,
            pool_size=settings.DB_POOL_SIZE,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
            echo=settings.DEBUG,
        )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with get_async_session_factory()() as session:
        yield session
```

- [ ] **Step 5: 简化 metadata 与测试 DB**

`build_target_metadata()` 导入所有 model module 后直接返回
`DomainBase.metadata`。`tests/conftest.py` 只创建和清理一次 metadata。

- [ ] **Step 6: 验证**

```powershell
python -m pytest tests/test_single_domain_registry.py tests/test_combined_metadata.py tests/test_trace_schema_contract.py -q
python -m pytest tests/test_migration_full_schema.py -q
```

Expected: registry 测试改为 PASS；MySQL gate 在 Docker 可用时 PASS。

- [ ] **Step 7: Commit**

```powershell
git add domain app/core/extensions.py core/db core/config.py tests/conftest.py tests/test_single_domain_registry.py tests/test_combined_metadata.py tests/test_migration_full_schema.py
git commit -m "refactor(db): establish one SQLAlchemy 2.0 domain registry"
```

## Task 3: User/Auth 纵切

**Files:**
- Create: `domain/models/__init__.py`
- Create: `domain/models/user.py`
- Create: `domain/statements/users.py`
- Create: `domain/repositories/users.py`
- Create: `app/models/_query_compat.py`
- Replace: `app/models/user.py` with compatibility re-export
- Modify: `app/auth/utils.py`
- Modify: `app/auth/decorators.py`
- Modify: `app/services/auth_service.py`
- Modify: `mcp_gateway/middleware/auth.py`
- Test: `tests/test_domain_user_repository.py`

- [ ] **Step 1: 移动唯一 User mapping**

`domain/models/user.py` 使用 `Mapped[]`、`mapped_column()` 和
`relationship()` 定义现有 `User`/`UserRole`。字段、Enum、索引、关系和默认值
必须与当前 schema 一致。

`app/models/user.py` 只能 re-export：

```python
from domain.models.user import User, UserRole
from app.models._query_compat import enable_legacy_query

enable_legacy_query(User)
```

`enable_legacy_query()` 仅为未迁移的 Flask call sites 安装
`db.session.query_property()`；不得定义 mapped class。

- [ ] **Step 2: 建立共享 statements 与 repository**

`domain/statements/users.py` 返回 sync/async session 共用的 `select(User)`。
`domain/repositories/users.py` 提供 `SyncUserRepository` 和
`AsyncUserRepository`；repository 不自行 commit。

- [ ] **Step 3: 迁移认证边界**

先迁移 `app/auth/*`、`app/services/auth_service.py` 和 MCP API-key 验证。
其他业务页面允许暂时通过 re-export 的 `.query` 运行。

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/test_domain_user_repository.py tests/test_mcp_gateway_internal_auth.py tests/test_mcp_gateway_external_rbac.py -q
flask db check
```

- [ ] **Step 5: Commit**

```powershell
git add domain/models domain/statements domain/repositories app/models/user.py app/models/_query_compat.py app/auth app/services/auth_service.py mcp_gateway/middleware/auth.py tests/test_domain_user_repository.py
git commit -m "refactor(domain): migrate user and auth onto shared models"
```

## Task 4: Chat Domain 纵切

**Files:**
- Create: `domain/models/chat.py`
- Create: `domain/statements/chat.py`
- Create: `domain/repositories/chat.py`
- Replace: `app/models/ai_conversation.py` with re-export
- Replace: `app/models/chat_task.py` with re-export
- Modify: `app/api/v1/ai.py`
- Modify: `workers/chat.py`
- Modify: `memory/service.py`
- Test: `tests/test_domain_chat_repository.py`
- Test: `tests/test_api_ai.py`

- [ ] **Step 1: 移动 `AIConversation`、`AIMessage`、`ChatTask`**

三张表只在 `domain/models/chat.py` 定义。保留 FK、cascade、时间戳、task 状态和
relationship；旧模块只 re-export 同一个 class 并临时安装 `.query`。

- [ ] **Step 2: 实现 Chat repository**

覆盖 conversation 创建/读取、消息追加、有序 history、task 创建和
`pending -> processing -> completed|failed` 状态转换。状态更新必须带 expected
state 条件，避免 embedded 与 remote worker 双执行。

- [ ] **Step 3: 迁移 Flask API 与 embedded worker**

`app/api/v1/ai.py` 和 `workers/chat.py` 改用 repository。对外 route、JSON、
Redis key、SSE event shape 和 summary 条件保持不变。

- [ ] **Step 4: 验证并提交**

```powershell
python -m pytest tests/test_domain_chat_repository.py tests/test_api_ai.py tests/test_agents.py -q
flask db check
git add domain/models/chat.py domain/statements/chat.py domain/repositories/chat.py app/models/ai_conversation.py app/models/chat_task.py app/api/v1/ai.py workers/chat.py memory/service.py tests/test_domain_chat_repository.py
git commit -m "refactor(domain): migrate chat persistence as one vertical slice"
```

## Task 5: 重建 FastAPI Runtime shell 与 Chat command path

**Files:**
- Modify: `requirements.txt`
- Create: `agent_runtime/__init__.py`
- Create: `agent_runtime/main.py`
- Create: `agent_runtime/dependencies.py`
- Create: `agent_runtime/schemas.py`
- Create: `agent_runtime/api/health.py`
- Create: `agent_runtime/api/chat_tasks.py`
- Create: `agent_runtime/services/chat_runner.py`
- Create: `app/services/agent_runtime_dispatcher.py`
- Create: `core/auth/service_tokens.py`
- Modify: `core/config.py`
- Modify: `compose.yaml`
- Test: `tests/test_agent_runtime_app.py`
- Test: `tests/test_agent_runtime_chat.py`
- Test: `tests/test_agent_runtime_dispatcher.py`

- [x] **Step 1: 恢复依赖但不恢复旧包**

新增受控版本的 `fastapi`、`uvicorn`、`asyncmy`、`httpx`。不恢复
`app/api/v1/agents/*` 或 `workers/__main__.py`。

- [x] **Step 2: 建立 FastAPI app factory**

只注册：

```text
GET  /health/live
GET  /health/ready
POST /internal/v1/chat-tasks/{task_id}:start
GET  /internal/v1/chat-tasks/{task_id}
GET  /internal/v1/chat-tasks/{task_id}/events
```

内部 command 使用专门 audience 的短期签名 JWT；不复用用户 JWT，不信任
`X-User-Id`/`X-Role` 等自报 header。

- [x] **Step 3: 实现 async Chat runner**

使用 `AsyncChatRepository` 读取任务、conversation、user 和 history，再调用现有
Agent kernel。为 `agents/runtime.py` / `agents/llm_runner.py` 增加真正使用
`ainvoke`/`astream` 的异步路径；不得在 event loop 中直接运行阻塞 DB/LLM。
ToolRuntime/MCP 必须保留 signed capability token、scope、trace_id 和 envelope。

> **实际实现（偏离，2026-06-07）：** 未给 `agents/runtime.py` /
> `agents/llm_runner.py` 增加 `ainvoke`/`astream` 路径——这两个文件**未被修改**。
> `agent_runtime/services/chat_runner.py` 改用 `asyncio.to_thread` 把现有**同步**
> kernel（`get_agent_instance(type).stream(state)` + 意图分类 + handoff loop）移出
> event loop，runner 自身在 event loop 上只做 `AsyncChatRepository` 的 DB I/O 和
> Redis I/O。
>
> 偏离理由：同步 kernel 的 trace 生命周期、MCP 签名 capability token/scope/trace_id/
> envelope、`MAX_HANDOFFS` handoff loop 嵌套很深，另起 `ainvoke`/`astream` 分支会复制
> 该逻辑并与 embedded worker（`workers/chat.py`）漂移。`to_thread` 方案让 kernel 与其
> 签名 tool-path 安全语义保持与 embedded 路径逐字一致，且 event loop 不被阻塞 DB/LLM。
>
> **遗留技术债：** 仍是线程池里跑同步 LLM，不是端到端 streaming async。若日后要真正的
> `astream`，需回到本 Step 在 kernel 层补 async 路径（并保证与 embedded worker 行为
> 不漂移）。

- [x] **Step 4: 建立三态 dispatcher**

```text
embedded  # default: workers/chat.py
shadow    # embedded 执行；验证 remote readiness/contract，不重复调用 LLM
remote    # Flask 创建 task/message，FastAPI Runtime 领取执行
```

Flask 对外 SSE 继续读取相同 Redis buffer。command dispatch 失败时标记 task
failed，不静默双投递。

- [x] **Step 5: Compose 增加 `agent_runtime`**

独立 healthcheck、端口 `8100`、DB/Redis/MCP 配置。`web` 只获得内部 command
URL 和签名配置，不恢复 `USE_AGENT_HOST_PROXY`。

- [x] **Step 6: 验证并提交**（commit `8b09049`；full suite 640 passed / 1 skipped）

```powershell
python -m pytest tests/test_agent_runtime_app.py tests/test_agent_runtime_chat.py tests/test_agent_runtime_dispatcher.py tests/test_api_ai.py -q
docker compose config
git add requirements.txt agent_runtime app/services/agent_runtime_dispatcher.py core/auth/service_tokens.py core/config.py compose.yaml tests/test_agent_runtime_app.py tests/test_agent_runtime_chat.py tests/test_agent_runtime_dispatcher.py
git commit -m "feat(runtime): rebuild FastAPI agent runtime on the shared domain"
```

## Task 6: Workflow Domain 与 remote execution 纵切

**Files:**
- Create: `domain/models/workflow.py`
- Create: `domain/statements/workflows.py`
- Create: `domain/repositories/workflows.py`
- Replace: `app/models/workflow.py` with re-export
- Create: `agent_runtime/api/workflows.py`
- Create: `agent_runtime/services/workflow_runner.py`
- Modify: `graph/engine.py`
- Modify: `graph/supervisor.py`
- Modify: `workers/workflow.py`
- Modify: `app/api/v1/ai.py`
- Test: `tests/test_domain_workflow_repository.py`

- [x] **Step 1: 移动唯一 workflow mappings**

移动 `WorkflowRun`、`WorkflowStep`、`WorkflowApproval`，保留状态、approval
audit、`trace_id`、dependency 和 JSON 字段。

- [x] **Step 2: repository 拥有状态机写入**

run/step/approval 更新使用 expected-state compare-and-set。`WorkflowEngine`
接收 repository/unit-of-work，不再默认读取 Flask global `db.session`。

- [x] **Step 3: FastAPI 增加 workflow command/status/events**

复用 Chat 的 internal auth、AsyncSession 和 Redis SSE infrastructure，保持
`workflow:{run_id}:*` key 与 event shape。

- [x] **Step 4: 验证并提交**

```powershell
python -m pytest tests/test_domain_workflow_repository.py tests/test_graph_engine.py tests/test_workflow_routes.py tests/test_workflow_worker.py tests/test_workflow_resume.py tests/test_workflow_approval_audit.py -q
flask db check
git add domain/models/workflow.py domain/statements/workflows.py domain/repositories/workflows.py app/models/workflow.py agent_runtime/api/workflows.py agent_runtime/services/workflow_runner.py graph workers/workflow.py app/api/v1/ai.py tests/test_domain_workflow_repository.py
git commit -m "refactor(domain): migrate workflow persistence and remote execution"
```

## Task 7: Trace/Eval 纵切

**Files:**
- Create: `domain/models/observability.py`
- Create: `domain/repositories/traces.py`
- Create: `domain/repositories/evals.py`
- Replace: `core/db/models/agent_trace.py` with re-export
- Replace: `app/models/eval_run.py` with re-export
- Modify: `core/observability/trace_store.py`
- Modify: `core/observability/audit.py`
- Modify: `evals/`
- Modify: `app/services/trace_query_service.py`
- Modify: `app/api/v1/ai.py`
- Modify: `core/db/session.py`

- [x] **Step 1: 移动剩余 observability mappings**

`AgentTraceRun/Span/Event/Artifact/Link`、`EvalRun`、
`EvalCaseRun`、`EvalCaseGraderResult` 全部进入
`domain/models/observability.py`；旧模块只 re-export。

- [x] **Step 2: 注入 repository**

TraceStore、Eval harness/report、Flask trace pages 使用 sync repository；
FastAPI Runtime 使用 async repository。禁止 Domain/repository 读取 Flask context。

- [x] **Step 3: 删除 `Base` alias**

所有 imports 转到 `DomainBase` 后，从 `core/db/session.py` 删除临时 alias；
测试不再使用“core Base vs Flask metadata”术语。

- [x] **Step 4: 验证并提交**

```powershell
python -m pytest tests/test_trace_store_runtime_neutral.py tests/test_trace_schema_contract.py tests/test_trace_api_complete.py tests/test_agent_runtime_kernel.py tests/test_eval_harness_trace_binding.py tests/test_eval_report_generator.py tests/test_evals_ci.py -q
flask db check
git add domain/models/observability.py domain/repositories/traces.py domain/repositories/evals.py core/db/models/agent_trace.py app/models/eval_run.py core/observability evals app/services/trace_query_service.py app/api/v1/ai.py core/db/session.py tests
git commit -m "refactor(domain): unify trace and eval persistence"
```

## Task 8: MCP 纵切

**Files:**
- Create: `domain/models/mcp.py`
- Create: `domain/repositories/mcp.py`
- Replace: `core/db/models/mcp_api_key.py` with re-export
- Replace: `core/db/models/mcp_audit_log.py` with re-export
- Replace: `core/db/models/mcp_approval.py` with re-export
- Modify: `mcp_gateway/__main__.py`
- Modify: `mcp_gateway/bootstrap.py`
- Modify: `mcp_gateway/middleware/auth.py`
- Modify: `app/api/v1/mcp_keys.py`
- Modify: `app/api/v1/mcp_approvals.py`

- [x] **Step 1: 移动 MCP 唯一 mappings**

Domain model 不 import `app.core.extensions.db`。保留 API key hash/revocation、
approval 状态、audit payload 和索引。

- [x] **Step 2: Gateway 使用显式 repository**

删除 `mcp_gateway/__main__.py` 中导入全部 `app.models` 的特殊逻辑；直接导入
`domain.models` 并注入 `SyncMcpRepository`。Gateway 仍是独立进程。

- [x] **Step 3: 验证并提交**

```powershell
python -m pytest tests/test_mcp_gateway.py tests/test_mcp_gateway_human_gate.py tests/test_mcp_gateway_internal_auth.py tests/test_mcp_gateway_external_rbac.py tests/test_gateway_bootstrap_import.py -q
flask db check
git add domain/models/mcp.py domain/repositories/mcp.py core/db/models mcp_gateway app/api/v1/mcp_keys.py app/api/v1/mcp_approvals.py tests
git commit -m "refactor(domain): migrate MCP persistence off Flask model imports"
```

## Task 9: Remote cutover 与兼容层删除

**Files:**
- Modify: `core/config.py`
- Modify: `compose.yaml`
- Modify: `app/api/v1/ai.py`
- Delete: `workers/chat.py`
- Delete: `workers/workflow.py`
- Delete: completed-slice re-exports under `app/models/` and `core/db/models/`
- Delete: `app/models/_query_compat.py`
- Modify: all remaining migrated-model `.query` call sites

- [x] **Step 1: import/query residue audit**

```powershell
rg -n "from app\.models|from core\.db\.models|\.query\b" app core agents graph workers evals mcp_gateway agent_runtime --glob "*.py"
```

尚未迁移的非 Agent 业务模型可继续位于 `app/models`；User/Auth、Chat、
Workflow、Trace/Eval、MCP 必须直接使用 `domain.models` 且不再依赖 `.query`。

- [x] **Step 2: remote 成为默认**

先运行 shadow，再切 `remote`。完成 bake 后删除 embedded dispatcher 分支和
两个 Flask-native worker。失败写入 task/run 状态，不做隐藏 Flask fallback。

- [x] **Step 3: Docker smoke**

```powershell
docker compose up -d --build web agent_runtime redis db mcp_gateway
docker compose ps
curl.exe -f http://localhost:8100/health/ready
```

执行一次 chat 和 workflow，确认 MySQL 状态完成、SSE 可重连、trace_id 同时出现
在 trace/workflow/MCP audit，且 Web 进程不执行 Agent loop。

- [x] **Step 4: Commit**

```powershell
git add -u
git add core/config.py compose.yaml app agent_runtime domain tests
git commit -m "feat(runtime)!: cut agent execution over to FastAPI runtime"
```

## Task 10: Schema、回归和文档收口

**完成状态(2026-06-08):** 已完成并归档。收口时补充
`d9a1f2c3b4e5_drop_legacy_quiz_questions.py`，处理既有 MySQL 环境中遗留
`quiz_questions` 表导致的 `flask db check` diff，并用
`test_alembic_upgrade_head_removes_legacy_quiz_questions` 固化回归。

**最终验证证据(2026-06-08):**
- `docker exec educode_web flask db upgrade head` PASS。
- `docker exec educode_web flask db check` PASS: `No new upgrade operations detected.`
- `python -m pytest tests/test_migration_full_schema.py tests/test_remote_runtime_cutover.py tests/test_single_domain_registry.py tests/test_combined_metadata.py -q` PASS: 12 passed。
- `python -m pytest -q --tb=short` PASS: 661 passed。
- Docker `web + agent_runtime + mcp_gateway + db + redis` 均为 healthy。

**Files:**
- Modify: `docs/architecture/ai-agents.md`
- Modify: `docs/architecture/agent-runtime-core.md`
- Modify: `docs/architecture/data-state-memory.md`
- Modify: `docs/plans/README.md`
- Modify: `docs/issues/2026-06-04-dual-orm-database-issues.md`

- [x] **Step 1: Schema gates**

```powershell
flask db check
python -m pytest tests/test_migration_full_schema.py -q
```

Expected: 无 ORM-only migration diff；空 MySQL 可 `upgrade head`。

- [x] **Step 2: Full regression**

```powershell
python -m pytest -q
```

Expected: full PASS。Docker-only gate 被 skip 时必须单独记录。

- [x] **Step 3: Architecture residue gates**

```powershell
rg -n "declarative_base\(|class .*\(Base\)|class .*\(db\.Model\)" domain app core --glob "*.py"
rg -n "app\.api\.v1\.agents|ai_proxy|USE_AGENT_HOST_PROXY|workers\.task_runner" . --glob "!docs/plans/archive/**"
```

Expected: 只有 `DomainBase` 创建 registry；每张已迁移表只有一个 mapped class；
无旧 Host/proxy residue；`domain/` 不 import Flask/FastAPI。

- [x] **Step 4: 文档和 issue 状态**

关闭 dual-ORM issue，明确最终形态是“shared Domain + process-local sessions”，
不是“所有进程共享 Flask context”。全部 gate 通过后归档本计划。

- [x] **Step 5: Version control handoff**

```powershell
git add docs tests
git commit -m "docs(arch): record shared domain and FastAPI runtime completion"
```

本次按用户要求执行验收和归档，未创建 commit；改动保留在当前工作区。

## 验收总表

- [x] `db.Model.registry is DomainBase.registry`
- [x] `build_target_metadata() is DomainBase.metadata`
- [x] tests 不再创建两套 metadata
- [x] 每张迁移表只有一个 mapped class
- [x] sync/async repository 的 transaction ownership 明确
- [x] AsyncSession 路径无隐式 lazy-load `MissingGreenlet`
- [x] 新服务位于 `agent_runtime/`，没有恢复旧 Host/proxy
- [x] internal command 经过签名认证
- [x] Chat/Workflow SSE 与现有前端兼容
- [x] Web 只负责用户 API、任务创建和读取，不执行 Agent loop
- [x] `python -m pytest -q` PASS
- [x] `flask db check` 无 diff
- [x] empty MySQL `upgrade head` PASS
- [x] Docker `web + agent_runtime + mcp_gateway` health PASS

## 明确不做

- 不恢复旧 Agent Host 文件、旧 proxy 分支或 `USE_AGENT_HOST_PROXY`。
- 不复制第二个 ORM class 加速迁移。
- 不在 Domain model 中 import Flask、FastAPI、request context 或 Redis。
- 不要求 Flask、FastAPI、MCP Gateway 跨进程共享 engine/pool/session。
- 不在 ORM 重组阶段修改业务 schema。
- 不在 Chat Domain 未稳定前同时迁移全部 Flask `.query` call sites。
- 不牺牲当前 SSE、workflow approval、trace 或 MCP security 语义。

## 主要风险与控制

1. **共享 registry 一次性影响 mapper。** Task 2 先统一 Base，不搬业务 class；
   用 mapper、metadata 和 full suite 暴露关系问题。
2. **AsyncSession 隐式 lazy load。** Async repository 显式使用
   `selectinload/joinedload`，FastAPI serialization 只访问已加载字段。
3. **embedded/remote 双执行。** Chat/Workflow 状态更新使用 expected-state
   compare-and-set；dispatcher 不做失败后的隐藏 fallback。
4. **`.query` 兼容污染 Domain。** compatibility descriptor 只放在
   `app/models` re-export 层，并按 slice 删除。
5. **旧 FastAPI 代码回流。** residue test 固化 Phase 1 删除列表；新服务只通过
   Domain/repository 和现有 Agent kernel 重建。
6. **ORM 重构误生成 migration。** 每个 slice 都运行 `flask db check`；任意 diff
   先视为 mapping 漂移，不直接提交 migration。
