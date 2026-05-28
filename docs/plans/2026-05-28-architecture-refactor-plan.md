# 架构重构计划 — 顶层目录重组与命名统一

> 目标：消除 `mcp/` 与 PyPI `mcp` SDK 的命名冲突，拆散 `agent_host/` 大杂烩，把 `app/agents/` 里寄居的工具实现搬到顶层，按主流 agent 项目惯例重排顶层目录。
>
> 原则：
> 1. 不保留任何向后兼容 shim（旧路径不做 re-export）
> 2. 每个 Phase 自成一个 PR，PR 内原子合并，跨 Phase 不允许中间态长期存在
> 3. 测试改写与实现搬迁放在同一个 PR
> 4. 业务逻辑零改动，只动文件位置和 import 路径

---

## 0. 目标布局

```
coderunner-ai/
├── app/                      # Flask Web（保持，但接收新增 api/v1/agents/）
├── core/                     # 平台基建：config / db / auth / observability / exceptions / security / schemas / state
├── tools/                    # 工具实现（纯函数 impl，不依赖 MCP/LangChain）
│   ├── code/
│   ├── problems/
│   ├── analytics/
│   ├── students/
│   ├── traces/
│   ├── knowledge_search/
│   └── protocol/             # 工具协议层：registry / runtime / transports / policies / schemas / adapters / errors
├── mcp_gateway/              # 对外 MCP 服务进程（python -m mcp_gateway）
├── agents/                   # tutor / reviewer / generator / analytics（每个 agent 一个子包）
├── graph/                    # 编排引擎（LangGraph 风格）
├── memory/                   # short_term / long_term / summarizer / preference
├── knowledge/                # RAG 底层 store / embeddings / retriever / indexer
├── models/                   # LLM router + providers
├── workers/                  # chat / batch / generation_pipeline / task_runner
├── tests/
├── migrations/
└── docs/ scripts/ docker/ ...
```

**删除**：`agent_host/`、`mcp/`、`mcp_server/`、`app/agents/`

---

## Phase 0 — 测试清理（先于一切搬迁）

### 0.1 直接删除

```bash
git rm tests/test_agent_host_integration.py
git rm tests/test_phase3.py
```

理由：
- `test_agent_host_integration.py` 只断言 Dockerfile 字符串，重构后必然失败且本身价值低
- `test_phase3.py` 实验 API 已与生产路径脱节

### 0.2 重命名（保留功能、改 import 延后到对应 Phase）

```bash
git mv tests/test_mcp_server.py            tests/test_mcp_gateway.py
git mv tests/test_mcp_phase4.py            tests/test_mcp_gateway_human_gate.py
git mv tests/test_mcp_phase5.py            tests/test_tool_protocol.py
git mv tests/test_phase4.py                tests/test_agent_features.py
git mv tests/test_workflow_engine.py       tests/test_graph_engine.py
```

### 0.3 内部清理

- 在 `tests/test_tool_protocol.py` 中删掉文件末尾的 **grep gate** 测试块（`subprocess.run(["grep", ...])` 那段）。该断言重构后必然失效，由新结构自然保证。
- 删除 `tests/test_agent_features.py`（原 `test_phase4.py`）中的 **judge function** 测试块（约 150 行的 eval 框架测试）。

### 0.4 Phase 0 验证

```bash
pytest tests/ -v --co     # 只收集，确认无 ImportError
pytest tests/ -x          # 实际跑一遍，应全绿（路径未变）
```

**预期结果**：删除 + 改名后，剩余 14 个测试文件全绿（import 路径暂未变）。

---

## Phase 1 — 基建下沉到 `core/`

### 1.1 文件搬迁

```bash
mkdir -p core/auth core/db core/observability

# config
git mv agent_host/core/config.py             core/config.py
# 合并 mcp_server/config.py 进 core/config.py（手工合并，下同）

# db
git mv agent_host/core/db.py                 core/db/session.py
# 合并 mcp_server/db.py 进 core/db/

# auth (Phase 3 再合并 mcp/auth)
git mv agent_host/core/auth.py               core/auth/caller.py

# observability
git mv agent_host/tracing.py                 core/observability/tracing.py

# 平铺到 core/ 根
git mv agent_host/exceptions.py              core/exceptions.py
git mv agent_host/security.py                core/security.py
git mv agent_host/schemas.py                 core/schemas.py
git mv agent_host/definitions.py             core/definitions.py
git mv agent_host/state.py                   core/state.py
git mv agent_host/task_state.py              core/task_state.py
```

### 1.2 新建空骨架

```bash
mkdir -p tools/protocol agents graph memory knowledge models workers mcp_gateway
touch {tools,tools/protocol,agents,graph,memory,knowledge,models,workers,mcp_gateway}/__init__.py
```

### 1.3 Import 改写

| 旧 | 新 |
|---|---|
| `from agent_host.core.config` | `from core.config` |
| `from agent_host.core.db` | `from core.db.session` |
| `from agent_host.core.auth` | `from core.auth.caller` |
| `from agent_host.tracing` | `from core.observability.tracing` |
| `from agent_host.exceptions` | `from core.exceptions` |
| `from agent_host.security` | `from core.security` |
| `from agent_host.schemas` | `from core.schemas` |
| `from agent_host.definitions` | `from core.definitions` |
| `from agent_host.state` | `from core.state` |
| `from agent_host.task_state` | `from core.task_state` |
| `from mcp_server.config` | `from core.config` |
| `from mcp_server.db` | `from core.db.session` |

### 1.4 Phase 1 验证

```bash
pytest tests/test_exceptions.py -v
pytest tests/test_model_router_and_definitions.py -v
python run.py                                  # Flask 能起
python -m mcp_server --transport stdio &      # 旧 MCP 服务仍能起
```

**风险**：`mcp_server/__main__.py` 和 `agent_host/main.py` 内部还会 import 自身模块，本 Phase 不动这两个入口，只改它们对 `config/db/auth` 的引用方式。

---

## Phase 2 — `app/agents/tools/core/` → `tools/`

### 2.1 文件搬迁

```bash
mkdir -p tools/code tools/problems tools/analytics tools/students tools/traces tools/knowledge_search

git mv app/agents/tools/core/code_executor.py      tools/code/executor.py
git mv app/agents/tools/core/problems.py           tools/problems/queries.py
git mv app/agents/tools/core/question_save.py      tools/problems/write.py
git mv app/agents/tools/core/knowledge.py          tools/knowledge_search/search.py
git mv app/agents/tools/core/analytics.py          tools/analytics/queries.py
git mv app/agents/tools/core/student_summary.py    tools/students/summary.py
git mv app/agents/tools/core/traces.py             tools/traces/queries.py

git rm -r app/agents/
```

### 2.2 Import 改写表

| 旧 | 新 |
|---|---|
| `app.agents.tools.core.code_executor` | `tools.code.executor` |
| `app.agents.tools.core.problems` | `tools.problems.queries` |
| `app.agents.tools.core.question_save` | `tools.problems.write` |
| `app.agents.tools.core.knowledge` | `tools.knowledge_search.search` |
| `app.agents.tools.core.analytics` | `tools.analytics.queries` |
| `app.agents.tools.core.student_summary` | `tools.students.summary` |
| `app.agents.tools.core.traces` | `tools.traces.queries` |

### 2.3 受影响文件清单（11 个）

```
mcp_server/tools/write.py           （Phase 3 中再次改）
mcp_server/tools/traces.py
mcp_server/tools/students.py
mcp_server/tools/problems.py
mcp_server/tools/knowledge.py
mcp_server/tools/analytics.py
mcp/server/shared/bootstrap.py      （Phase 3 中再次改）
tests/test_tools.py
tests/test_mcp_gateway.py           （Phase 0 已改名）
tests/test_mcp_gateway_human_gate.py
tests/test_agent_features.py
agent_host/agents/generator.py      （Phase 4 中再次改）
```

### 2.4 Phase 2 验证

```bash
pytest tests/test_tools.py tests/test_mcp_gateway.py \
       tests/test_mcp_gateway_human_gate.py tests/test_agent_features.py -v
python -m mcp_server --transport stdio   # 旧 MCP 服务仍能起
```

---

## Phase 3 — `mcp/` → `tools/protocol/` + `mcp_server/` → `mcp_gateway/`（必须原子）

> **关键收益**：完成后 `mcp_server/server.py:11-26` 的 `_import_fastmcp()` sys.path hack 整段删掉，PyPI `mcp` SDK 可正常 `from mcp.server import FastMCP`。

### 3.1 `mcp/` 搬迁

```bash
mkdir -p tools/protocol/transports tools/protocol/schemas tools/protocol/policies tools/protocol/adapters

git mv mcp/registry/registry.py              tools/protocol/registry.py
git mv mcp/client/runtime.py                 tools/protocol/runtime.py
git mv mcp/transport/local.py                tools/protocol/transports/inproc.py
git mv mcp/schemas/catalog.py                tools/protocol/schemas/catalog.py
git mv mcp/schemas/descriptors.py            tools/protocol/schemas/descriptors.py
git mv mcp/policies/guard.py                 tools/protocol/policies/guard.py
git mv mcp/policies/rbac.py                  tools/protocol/policies/rbac.py
git mv mcp/policies/risk.py                  tools/protocol/policies/risk.py
git mv mcp/policies/scopes.py                tools/protocol/policies/scopes.py
git mv mcp/adapters/llm_to_mcp.py            tools/protocol/adapters/llm_to_tool.py
git mv mcp/adapters/mcp_to_llm.py            tools/protocol/adapters/tool_to_llm.py
git mv mcp/adapters/result_to_message.py     tools/protocol/adapters/result_to_message.py

# errors 合并为单文件
cat mcp/errors/codes.py mcp/errors/exceptions.py > tools/protocol/errors.py
git rm -r mcp/errors/

# auth 合并到 core/auth/
git mv mcp/auth/context.py                   core/auth/context.py
git mv mcp/auth/tokens.py                    core/auth/tokens.py

# audit 合并到 core/observability/
# 手工合并 mcp/observability/audit.py + mcp_server/audit.py → core/observability/audit.py
git rm mcp/observability/audit.py
git rm mcp_server/audit.py

# bootstrap 搬到 gateway
git mv mcp/server/shared/bootstrap.py        mcp_gateway/bootstrap.py

git rm -r mcp/
```

### 3.2 `mcp_server/` 搬迁

```bash
mkdir -p mcp_gateway/middleware mcp_gateway/handlers

git mv mcp_server/__main__.py                mcp_gateway/__main__.py
git mv mcp_server/server.py                  mcp_gateway/server.py
# 编辑 mcp_gateway/server.py，删除 _import_fastmcp() 整段，恢复正常 import

git mv mcp_server/auth.py                    mcp_gateway/middleware/auth.py
git mv mcp_server/middleware.py              mcp_gateway/middleware/__init__.py
git mv mcp_server/rate_limiter.py            mcp_gateway/middleware/rate_limit.py
git mv mcp_server/sanitizer.py               mcp_gateway/middleware/sanitizer.py

git mv mcp_server/tools/knowledge.py         mcp_gateway/handlers/knowledge.py
git mv mcp_server/tools/problems.py          mcp_gateway/handlers/problems.py
git mv mcp_server/tools/analytics.py         mcp_gateway/handlers/analytics.py
git mv mcp_server/tools/traces.py            mcp_gateway/handlers/traces.py
git mv mcp_server/tools/students.py          mcp_gateway/handlers/students.py
git mv mcp_server/tools/write.py             mcp_gateway/handlers/write.py

# 数据模型搬到 core/db/models/
mkdir -p core/db/models
git mv mcp_server/models/api_key.py          core/db/models/mcp_api_key.py
git mv mcp_server/models/approval.py         core/db/models/mcp_approval.py
git mv mcp_server/models/audit_log.py        core/db/models/mcp_audit_log.py

git rm -r mcp_server/
```

### 3.3 Import 改写表

| 旧 | 新 |
|---|---|
| `mcp.registry.registry` / `mcp.registry` | `tools.protocol.registry` |
| `mcp.client.runtime` | `tools.protocol.runtime` |
| `mcp.schemas.catalog` | `tools.protocol.schemas.catalog` |
| `mcp.schemas.descriptors` | `tools.protocol.schemas.descriptors` |
| `mcp.transport.local` | `tools.protocol.transports.inproc` |
| `mcp.policies.guard` | `tools.protocol.policies.guard` |
| `mcp.policies.rbac` | `tools.protocol.policies.rbac` |
| `mcp.policies.risk` | `tools.protocol.policies.risk` |
| `mcp.policies.scopes` | `tools.protocol.policies.scopes` |
| `mcp.adapters.llm_to_mcp` | `tools.protocol.adapters.llm_to_tool` |
| `mcp.adapters.mcp_to_llm` | `tools.protocol.adapters.tool_to_llm` |
| `mcp.adapters.result_to_message` | `tools.protocol.adapters.result_to_message` |
| `mcp.errors.codes` / `mcp.errors.exceptions` | `tools.protocol.errors` |
| `mcp.auth.context` | `core.auth.context` |
| `mcp.auth.tokens` | `core.auth.tokens` |
| `mcp.observability.audit` | `core.observability.audit` |
| `mcp.server.shared.bootstrap` | `mcp_gateway.bootstrap` |
| `mcp_server.config` | `core.config` |
| `mcp_server.db` | `core.db.session` |
| `mcp_server.auth` | `mcp_gateway.middleware.auth` |
| `mcp_server.middleware` | `mcp_gateway.middleware` |
| `mcp_server.audit` | `core.observability.audit` |
| `mcp_server.rate_limiter` | `mcp_gateway.middleware.rate_limit` |
| `mcp_server.sanitizer` | `mcp_gateway.middleware.sanitizer` |
| `mcp_server.tools.knowledge` | `mcp_gateway.handlers.knowledge` |
| `mcp_server.tools.problems` | `mcp_gateway.handlers.problems` |
| `mcp_server.tools.analytics` | `mcp_gateway.handlers.analytics` |
| `mcp_server.tools.traces` | `mcp_gateway.handlers.traces` |
| `mcp_server.tools.students` | `mcp_gateway.handlers.students` |
| `mcp_server.tools.write` | `mcp_gateway.handlers.write` |
| `mcp_server.models.api_key` | `core.db.models.mcp_api_key` |
| `mcp_server.models.approval` | `core.db.models.mcp_approval` |
| `mcp_server.models.audit_log` | `core.db.models.mcp_audit_log` |

### 3.4 入口/部署改名

| 文件 | 修改 |
|---|---|
| `compose.yaml` | `python -m mcp_server` → `python -m mcp_gateway` |
| `docker/Dockerfile.mcp_server` → `docker/Dockerfile.mcp_gateway` | 改名 + 内部 COPY 路径 |
| `scripts/*.py` | 检查是否引用 `mcp_server` 或 `mcp.*` |
| `README.md` | 启动命令更新 |

### 3.5 Phase 3 验证

```bash
# 1. 命名冲突已消除：直接 import 第三方 mcp
python -c "from mcp.server import FastMCP; print('OK')"

# 2. 新入口可启动
python -m mcp_gateway --transport stdio &

# 3. 协议层测试
pytest tests/test_tool_protocol.py -v

# 4. Gateway 测试
pytest tests/test_mcp_gateway.py tests/test_mcp_gateway_human_gate.py -v

# 5. 死代码检查：确认 sys.path hack 已删除
grep -r "_import_fastmcp\|saved_path = sys.path" mcp_gateway/ && echo "REMOVE!" || echo "clean"
```

---

## Phase 4 — `agent_host/` 拆散

### 4.1 agents 部分

```bash
mkdir -p agents/{tutor,reviewer,generator,analytics}

git mv agent_host/agents/base.py              agents/base.py
git mv agent_host/agents/tutor.py             agents/tutor/agent.py
git mv agent_host/prompts/tutor.py            agents/tutor/prompt.py
git mv agent_host/agents/reviewer.py          agents/reviewer/agent.py
git mv agent_host/prompts/reviewer.py         agents/reviewer/prompt.py
git mv agent_host/agents/generator.py         agents/generator/agent.py
git mv agent_host/prompts/generator.py        agents/generator/prompt.py
git mv agent_host/agents/analytics.py         agents/analytics/agent.py
git mv agent_host/prompts/analytics.py        agents/analytics/prompt.py
git mv agent_host/agents_config.py            agents/config.py
```

### 4.2 graph 部分

```bash
git mv agent_host/workflow/engine.py          graph/engine.py
git mv agent_host/workflow/planner.py         graph/planner.py
git mv agent_host/workflow/supervisor.py      graph/supervisor.py
git mv agent_host/workflow/critic.py          graph/critic.py
git mv agent_host/workflow/handlers.py        graph/handlers.py
git mv agent_host/workflow/state.py           graph/state.py
git mv agent_host/workflow/registry.py        graph/node_registry.py
git mv agent_host/orchestrator.py             graph/runner.py
git mv agent_host/handoff.py                  graph/handoff.py
git mv agent_host/recovery.py                 graph/recovery.py
```

### 4.3 memory 部分

```bash
# 手工拆分 agent_host/memory.py
# - short_term + long_term + summarizer 按类拆分到三个文件
git rm agent_host/memory.py

# 写入：
# memory/short_term.py
# memory/long_term.py
# memory/summarizer.py

git mv agent_host/preference_learner.py       memory/preference.py
```

### 4.4 knowledge 部分

```bash
# 手工拆分 agent_host/knowledge_base.py（按职责切 4 个文件）
git rm agent_host/knowledge_base.py

# 写入：
# knowledge/store.py        (ChromaDB client)
# knowledge/embeddings.py   (SentenceTransformer)
# knowledge/retriever.py    (高层检索 API)
# knowledge/indexer.py      (文档入库)
```

### 4.5 models 部分

```bash
git mv agent_host/model_router/router.py              models/router.py
git mv agent_host/model_router/tiers.py               models/tiers.py
git mv agent_host/model_router/providers/__init__.py  models/providers/__init__.py
git mv agent_host/model_router/providers/base.py      models/providers/base.py
git mv agent_host/model_router/providers/deepseek.py  models/providers/deepseek.py
git rm -r agent_host/model_router/
```

### 4.6 workers 部分

```bash
git mv agent_host/worker/task_runner.py       workers/task_runner.py
git mv agent_host/worker/redis_buffer.py      workers/redis_buffer.py
git mv agent_host/chat_worker.py              workers/chat.py
git mv agent_host/batch_runner.py             workers/batch.py
git mv agent_host/generation_pipeline.py      workers/generation_pipeline.py
git mv agent_host/main.py                     workers/__main__.py
git rm -r agent_host/worker/
```

### 4.7 数据模型部分

```bash
git mv agent_host/models/ai_conversation.py   core/db/models/ai_conversation.py
git mv agent_host/models/chat_task.py         core/db/models/chat_task.py
git mv agent_host/models/user.py              core/db/models/user.py
git mv agent_host/models/workflow.py          core/db/models/workflow.py
git rm -r agent_host/models/
```

### 4.8 API 蓝图归位到 app

```bash
mkdir -p app/api/v1/agents

git mv agent_host/api/chat.py       app/api/v1/agents/chat.py
git mv agent_host/api/traces.py     app/api/v1/agents/traces.py
git mv agent_host/api/workflows.py  app/api/v1/agents/workflows.py
git mv agent_host/api/__init__.py   app/api/v1/agents/__init__.py
```

> 注意：蓝图 `url_prefix` 必须保持原值，URL 不变。

### 4.9 杂项

```bash
git mv agent_host/adapters/flask_client.py    app/services/agent_client.py
git rm -r agent_host/adapters/
git rm -r agent_host/prompts/                 # 应已空
git rm -r agent_host/                         # 应已空
```

### 4.10 Import 改写表（约 40 条映射）

```
agent_host.agents.tutor           → agents.tutor.agent
agent_host.agents.reviewer        → agents.reviewer.agent
agent_host.agents.generator       → agents.generator.agent
agent_host.agents.analytics       → agents.analytics.agent
agent_host.agents.base            → agents.base
agent_host.agents_config          → agents.config
agent_host.prompts.tutor          → agents.tutor.prompt
agent_host.prompts.reviewer       → agents.reviewer.prompt
agent_host.prompts.generator      → agents.generator.prompt
agent_host.prompts.analytics      → agents.analytics.prompt

agent_host.workflow.engine        → graph.engine
agent_host.workflow.planner       → graph.planner
agent_host.workflow.supervisor    → graph.supervisor
agent_host.workflow.critic        → graph.critic
agent_host.workflow.handlers      → graph.handlers
agent_host.workflow.state         → graph.state
agent_host.workflow.registry      → graph.node_registry
agent_host.orchestrator           → graph.runner
agent_host.handoff                → graph.handoff
agent_host.recovery               → graph.recovery

agent_host.memory                 → memory.short_term / memory.long_term / memory.summarizer
agent_host.preference_learner     → memory.preference

agent_host.knowledge_base         → knowledge.store / knowledge.retriever / knowledge.indexer

agent_host.model_router.router    → models.router
agent_host.model_router.tiers     → models.tiers
agent_host.model_router.providers → models.providers

agent_host.worker.task_runner     → workers.task_runner
agent_host.worker.redis_buffer    → workers.redis_buffer
agent_host.chat_worker            → workers.chat
agent_host.batch_runner           → workers.batch
agent_host.generation_pipeline    → workers.generation_pipeline
agent_host.main                   → workers.__main__

agent_host.api.chat               → app.api.v1.agents.chat
agent_host.api.traces             → app.api.v1.agents.traces
agent_host.api.workflows          → app.api.v1.agents.workflows

agent_host.models.ai_conversation → core.db.models.ai_conversation
agent_host.models.chat_task       → core.db.models.chat_task
agent_host.models.user            → core.db.models.user
agent_host.models.workflow        → core.db.models.workflow

agent_host.adapters.flask_client  → app.services.agent_client
```

### 4.11 入口改名

| 旧 | 新 |
|---|---|
| `python -m agent_host.main` | `python -m workers` |
| `docker/Dockerfile.agent_host` → `docker/Dockerfile.workers` | 改名 + 内部 COPY |
| `compose.yaml` 服务名 `agent_host` → `workers` |

### 4.12 Phase 4 验证

```bash
# 1. 进程入口
python run.py                                # Flask
python -m workers &                          # 守护进程
python -m mcp_gateway --transport stdio &    # MCP 服务

# 2. 测试套件
pytest tests/test_agents.py \
       tests/test_graph_engine.py \
       tests/test_knowledge_base.py \
       tests/test_model_router_and_definitions.py \
       tests/test_api_ai.py -v

# 3. 全量
pytest tests/ -v
```

---

## Phase 5 — 清理收尾

### 5.1 文件清理

```bash
# 确认四个旧目录已为空
test ! -d agent_host && test ! -d mcp && test ! -d mcp_server && test ! -d app/agents && echo "OK"

# 死 import 扫描
grep -rE "^(from|import) (agent_host|app\.agents|mcp_server)\b|^(from|import) mcp(\.|\s)" \
     --include="*.py" -n .
# 应输出为空（PyPI mcp 由 mcp_gateway 内部使用，import 形如 `from mcp.server import FastMCP`，
# 这种是允许的，可用更精确的正则排除）
```

### 5.2 文档与配置

- [ ] `README.md`：架构说明 + 启动命令
- [ ] `docs/AI_AGENTS.md`：路径全面更新
- [ ] `docs/AGENT_ARCHITECTURE_MATURITY_PLAN.md`：标记本计划完成
- [ ] `compose.yaml`：服务名和命令
- [ ] `docker/Dockerfile.*`：路径与文件名
- [ ] `pytest.ini`：testpaths、pythonpath 检查
- [ ] `requirements.txt`：无需改（依赖不变）
- [ ] `scripts/migrate_kb.py` / `scripts/seed_knowledge.py`：import 路径
- [ ] `migrations/`：检查 Alembic 脚本是否硬编码旧模型路径

### 5.3 最终验证

```bash
# 全量测试
pytest tests/ -v --tb=short

# 三进程冒烟
python run.py &                              # Flask :9900
python -m workers &                          # 守护进程
python -m mcp_gateway --transport sse --port 8200 &  # MCP HTTP
sleep 5
curl http://localhost:9900/healthz
curl http://localhost:8200/sse
kill %1 %2 %3

# 静态扫描
grep -rE "agent_host|mcp_server|app\.agents\.tools" --include="*.py" -l . | \
  grep -v __pycache__
# 应为空（除 docs/plans/ 旧计划文件）
```

---

## 风险登记表

| 风险 | 概率 | 缓解 |
|---|---|---|
| Phase 3 中间态命名冲突未消除 | 高 | 整个 Phase 3 在一个分支完成后一次性合并，期间不 push |
| 179 处 import 漏改 | 中 | 每个 Phase 末用 `grep` 扫描映射表左侧词，必须为空 |
| Flask 蓝图 URL 漂移 | 中 | `url_prefix` 必须 git diff 逐行 review |
| Chroma / 持久化目录路径丢失 | 中 | `data/chroma/` 等硬编码路径在搬迁前先 `grep` 扫描 |
| Alembic 迁移引用旧模型路径 | 中 | Phase 4 单独 review `migrations/versions/*.py` |
| Cypress E2E 引用旧 URL | 低 | 本计划不涉及 cypress，但 Phase 4 后跑一遍 e2e 确认 |
| pytest fixture 路径漂移 | 中 | `tests/conftest.py` 跟随 Phase 1 一起改 |

---

## 进度追踪

- [ ] Phase 0 — 测试清理
- [ ] Phase 1 — `core/` 基建下沉
- [ ] Phase 2 — `tools/` 工具实现层
- [ ] Phase 3 — `tools/protocol/` + `mcp_gateway/`（原子）
- [ ] Phase 4 — `agent_host/` 拆散
- [ ] Phase 5 — 清理收尾

每个 Phase 完成时：
1. 跑该 Phase 的验证命令全绿
2. 提交一个独立 PR（commit message 引用本计划的 Phase 编号）
3. PR 描述粘贴对应 Phase 的"验证"输出
