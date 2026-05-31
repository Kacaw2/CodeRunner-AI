# Phase 1–4 — 架构与能力加固落地路线图 (Implementation Roadmap)

> 本文是 Phase 0 安全加固之后的**剩余全部改动**落地方案，由四个规划代理在**真实阅读源码**后产出并整合。
>
> ## 进度状态（2026-05-30 复核）
>
> | 阶段 | 状态 | 说明 |
> |---|---|---|
> | Phase 0（安全三项） | ✅ 已完成 | commit `9acb2cb`，方案已归档至 `archive/plans/2026-05-29-0329-phase-0-security-hardening-plan.md` |
> | Phase 1（架构合一） | ✅ 已完成 | 详细方案已归档至 `archive/plans/2026-05-29-phase-1-architecture-unification-detailed.md`；并由 `2026-05-29-mcp-architecture-repair-plan.md` 接续完善（仅剩 Docker 运行时 smoke） |
> | **Phase 2（RAG + 编排）** | ⏳ **未开始 · 仍有效** | 唯一仍活跃的剩余项，详见 `2026-05-29-phase-2-rag-orchestration-detailed.md` |
> | Phase 3（工具契约 + 可观测） | ➡️ **已并入** `2026-05-30-production-readiness-audit.md`（F2/F8/F9），以审计修复计划为准 |
> | Phase 4（评测 + Agent 契约） | ➡️ **部分并入** 审计 F3（eval CI）；4.2 Agent 契约仍为低优先未排期 |
>
> **执行顺序以最新的 `2026-05-30-production-readiness-audit.md` 为主干**（写于 Phase 1 落地之后，反映当前真实状态）。本文 Phase 0/1 仅留作历史，Phase 2 为本文唯一仍需执行的内容。

---

## 重要事实纠正（阅读真实代码后）

动手前必须知道这几点与早期审计报告的偏差：

1. **执行器根本没用 Docker**：`app/core/executor.py` 的 `run_code_in_docker`（executor.py:520）名不副实，实际全程 `subprocess.run` 裸跑（`_run_python_native:412`、`_run_binary_native:286`），`USE_DOCKER` 开关读了从不用。→ “移除 fallback”实为“移除整条裸执行通路并真正引入隔离沙箱”。（已在 Phase 0.3 以独立 executor 微服务方案落地。）
2. **网关进程没有 bootstrap ToolRuntime**：`bootstrap_tool_runtime()` 只在 `workers/task_runner.py` 调用，`mcp_gateway` 启动不调。→ 合一前必须先在网关启动时 bootstrap。
3. **`tracing.py` 只有 ~128 行**，token 解析在 `agents/base.py:158-171`，不在 tracing。
4. **scope 模型不兼容**：网关 scope 存的是“工具名集合”，runtime 期望 `problem:read` 类权限串——这是合一的最大回归点。
5. **`jsonschema` 和 `pydantic` 已在 requirements**，output_schema 校验 / Pydantic 契约不引新依赖。
6. **三份 RBAC 真相源目前内容恰好一致**（命名都是 `coderunner.*`），所以派生改造是低风险。

---

## 阶段 1 — P1 架构合一（牵一发动全身）

> **详细落地（含逐文件 before/after、删除清单、scope/校验/审批三个硬骨头、提交顺序）见**：`docs/2026-05-29-phase-1-architecture-unification-detailed.md`。下方为概要。

### 1.1 RBAC 单一真相源（先做，风险低）
- `agents/base.py`：`mcp_tool_names` 改为 property，从 `core.definitions.allowed_tools_for(self.name)` 读。
- 删四个 agent 的 `*_MCP_TOOLS` 常量，invoke/stream 改用 `self.mcp_tool_names`（generator 的单工具常量 `coderunner.code.execute` 保留）。
- `tools/protocol/policies/rbac.py`：`_AGENT_TOOL_ALLOW` 改为从 `AGENT_DEFINITIONS` 派生（`@lru_cache`）。
- bootstrap 加启动一致性自检 + 单测。

### 1.2 MCP Gateway 合一走 ToolRuntime
- `mcp_gateway/__main__.py`：启动时 `bootstrap_tool_runtime(get_session)`。
- 新增 `call_via_runtime(mcp_tool, args)`：gateway 只做 auth + 连接级限流，其余（RBAC/scope/risk/audit）交 `runtime.call_sync()`。
- 6 个 handler 退化为单行 `call_via_runtime("coderunner.xxx.yyy", {...})` + 工具正名。
- 删 `_LEGACY_TO_MCP`、`TOOL_RISK_LEVELS`、`run_mcp_guard`。
- 错误改为基于 `errors.py` 的标准 envelope。
- **三个硬骨头**（建议拆子任务）：① scope 模型统一（过渡期 external_client 暂放行）；② input_schema 在 runtime 校验（删 handler 预校验后无人兜底）；③ 高风险审批落库下沉到 `runtime.call`（带 args）。

---

## 阶段 2 — P2 RAG + 编排

> **详细落地（含逐文件 before/after、RAG 重建注意、critic/handoff 回归点、提交顺序）见**：`docs/2026-05-29-phase-2-rag-orchestration-detailed.md`。下方为概要。

### 2.1 RAG 修复 `knowledge/store.py` + `core/config.py`
- **修过滤 bug**：写入加 `lang_{x}: True` 布尔位，查询用 `where={f"lang_{language}": True}`；删静默 except 兜底。
- **chunking**：`_split_text()`（langchain splitter + 纯 Python fallback），多 chunk upsert 带 `parent_id`，检索后按 parent 聚合取最高分。
- **rerank**：`_rerank()`（CrossEncoder，已装 sentence-transformers；不可用则按向量 score 退化）。top_k=20→取 5。
- **scope 隔离**：`search_similar_problems` 加 `owner_id` 过滤（用 `Problem.created_by`），对齐 `search_knowledge`。
- 阈值/模型/chunk 参数外置到 config。换 embedder 需清库重建。

### 2.2 编排修复 `graph/`
- **Critic 接入** `engine.py`：step 成功后调 `WorkflowCritic.validate_step`，不过则消耗 retry + 注入 `critic_feedback`（先修 `critic.py:21` 字段兼容 `response||problem_data`）。
- **修 REVIEW_TEMPLATE** `planner.py`：缺 `tool_name` 的 `tool_call` step 改为 `agent_call`，step2 补 `validates_step`。
- **handoff 传 context** `handoff.py` + `runner.py` + `state.py`：handoff 时生成 `handoff_summary`，切 agent 时把 messages 重建为 [原始用户问题 + 上一 agent 结论摘要]，丢弃工具残骸（注意验证 LangGraph `add_messages` 不重复叠加）。

---

## 阶段 3 — P2 工具契约 + 可观测

### 3.1 Tools 契约 `tools/protocol/`
- output_schema 补全 + `runtime.call` 后 `jsonschema.validate`（失败 `MCPSchemaInvalid`；schema 先松后紧）。
- RetryPolicy：runtime 加 retry loop，仅对**只读工具**开启（写工具会重复副作用）。
- execute_code 死锁：**拆 `coderunner.code.execute_internal`(MEDIUM)** 供 agent 自校验，保留 `execute`(HIGH) 给外部。
- 死工具 `get_agent_trace`：接入 analytics 的 allowed_tools。

### 3.2 可观测性 `core/observability/`
- **统一 trace_id**：TraceCollector 复用 `CallerContext.trace_id`，透传到 `McpAuditLog`（加字段 + alembic migration），`_emit` 同时 `log_tool_call` 落库。
- **成本**：`models/tiers.py` 加价格表，save 时算 `cost_usd` 写 AgentRun（加字段 + migration）。
- **结构化日志 + 滚动**：`logging_config.py` dictConfig + RotatingFileHandler（新依赖 `python-json-logger`）。
- **metrics**：`prometheus_client`（新依赖），runtime `_emit` 打点，streamable-http 暴露 `/metrics`；写库 / 打点失败不得阻塞工具调用。

---

## 阶段 4 — P3 评测 + Agent 契约

### 4.1 评测体系 `evals/`
- `judge_llm_rubric`（FAST tier 按 1-5 分评 helpfulness/factuality/safety）。
- `rag_evals.json`(recall@k) + `planner_evals.json`(tool_sequence)——需改 `runner.py` 把 `tool_results` 传给 judge。
- baseline 对比 + `.github/workflows/eval.yml`（PR 跑 fast suite，回归非零退出）——需给 runner 加 CLI 入口。
- 红队扩 8 条：Base64 / Unicode / RAG 投毒 / args fuzz / 角色混淆 / 越权。

### 4.2 Agent 契约 `agents/`
- `agents/contracts.py`：四个 Pydantic Input model，invoke 入口校验。
- BaseAgent 拆 `LLMRunner` + `ToolCallExecutor` + `TraceMixin`（先抽 ToolCallExecutor，公共签名不变，四 agent 无需改）。

---

## 统一执行顺序与依赖

```
阶段0 (并行: 0.1→0.2→0.3)   ← 安全，立即（已完成）
   │
阶段1: 1.1 (低风险先行) → 1.2 (依赖 1.1 的统一命名)
   │                          ├─ 子任务: scope统一 / schema校验 / 审批下沉
阶段2: 2.1 (独立) ‖ 2.2 (独立)   ← 可与阶段1并行
   │
阶段3: 3.1 → 3.2 (3.2 的 trace_id 统一会被 4.2 复用)
   │
阶段4: 4.2 (依赖 3.2 trace_id) ; 4.1 (依赖前面改动作回归基线)
```

**关键依赖**：
- 3.2 的 trace_id 统一 → 4.2 的 ToolCallExecutor 承接；
- 1.1 命名统一 → 1.2 合一；
- 2.1 换 embedder → 必须清库重建。

**最高 ROI**：1.2（合一）单点消除维度 1/2/3/8 的大量重复；但回归面最大，建议先稳住 1.1（RBAC 派生）再啃 1.2。

**建议分阶段提交**，而非一次性铺开。
