# Agents 项目 12 模块审查结果报告（2026-06-03 更新版）

**审查日期:** 2026-06-03
**基线:** `2026-05-30-agents-module-review-report.md`（含 2026-05-31 交叉验证）
**本次范围:** 在 Phase 8（Trace + Eval + CI 交付，提交 `e46175b → b10a81f`）落地后，逐条核验到 file:line 的当前状态
**范围模块:** Agent Core、Planner、Tool/Action Layer、Memory/Context、Knowledge/RAG、Executor、Workflow Orchestrator、Safety/Governance、Observability、Evaluation Harness、API/UI、Deployment/Ops

> 本报告是对 2026-05-31 交叉验证的增量更新。结论以**当前代码核验**为准，不再复述未变更模块的历史细节。

---

## 🟢 自 2026-05-31 以来的最大变化：Phase 8 落地

提交 `e46175b → b10a81f` 交付了一整套 **Trace + Eval + CI** 基础设施，实质性升级了报告里两个中等模块（Observability、Evaluation）：

- **完整 trace 体系**：`core/observability/trace_schema.py` + `trace_store.py`（runtime-neutral）、`app/api/v1/agents/traces.py` 完整 trace API/UI、`scripts/backfill_agent_traces.py` 历史回填。
- **EvalHarness**：`evals/harness/eval_harness.py` 把数据集用例绑定到单条 trace；4 类 grader（`deterministic` / `llm_judge` / `static_checks` / `unit_tests`）、`evals/datasets/store.py`、`evals/judges/`、`evals/reports/`（含 regression 生成器）。
- **CI 门禁**：`evals.yml`（DB-backed harness gate，低于基线即 fail）+ `tests.yml`（每 PR 跑 pytest）。
- **测试规模**：从基线时的 ~30 个测试文件增至 **54 个**，新增大量 trace/eval 契约测试。

> 重要边界：EvalHarness 引入了 token/cost/timeout 的 **soft budget**（`eval_harness.py` 文档串明示「never interrupting the agent loop」），但它**只在 eval 离线跑时事后检查**，既不中断 agent 循环，也不作用于生产运行时。它不构成下方缺陷 #2/#5 的护栏。

---

## 更新后总览评分

| 模块 | 2026-05-31 | 2026-06-03 | 关键变化 / 残留风险 |
|---|---|---|---|
| Agent Core | 🔴 基本不变 | 🔴 不变 | 生产运行时仍无跨 agent LLM 调用总量护栏（仅 per-loop 上限） |
| Planner | 🔴 不变 | 🔴 不变 | `create_plan` 为「模板→LLM」单向；general 类 LLM 失败返回 `None` 无模板兜底 |
| Tool/Action Layer | ✅ 增强 | ✅ 不变 | 维持护城河，本轮无回归 |
| Memory/Context | 🟡 微改 | 🟡 不变 | `get_memory_context` 仍只读静态画像，不回读 `AIConversation.summary` |
| Knowledge/RAG | 🟡 部分修复 | 🟡 微改 | `search_similar_problems` 带 `problem_id/title`，但 `search_knowledge` 等仍无通用 `doc_id/source` |
| Executor | 🟡 部分修复 | 🟡 不变 | `pids_limit` + 内网隔离已挡 fork bomb/外联；seccomp 仍缺 |
| Workflow Orchestrator | 🔴 仍存在 | 🔴 不变 | `recovery.py` 仍不恢复 `WorkflowRun`；无 per-workflow 全局超时 |
| Safety/Governance | ✅ 增强 | ✅ 不变 | 维持，本轮无回归 |
| Observability | ✅ 已修复 | 🟢 **再升级** | 在 `/metrics` + 成本换算之上，新增完整 trace schema/store/API/UI + 回填 |
| Evaluation Harness | ✅ 已修复 | 🟢 **再升级** | 在 CI 门禁之上，新增 trace 绑定的 EvalHarness + 4 类 grader + 回归报告 |
| API/UI | 🟡 部分修复 | 🟡 不变 | 后台线程池 + SSE 超时已就位；用户反馈/评分闭环仍缺 |
| Deployment/Ops | 🟡 部分修复 | 🟡 不变 | CI/`/metrics`/healthcheck 已就位；备份/告警/自动回滚仍缺 |

---

## 报告 8 条硬缺陷的当前状态（已核验到 file:line）

| # | 缺陷 | 级别 | 当前状态 |
|---|---|---|---|
| 1 | WorkflowRun 孤儿不可恢复 | 🔴 P0 | **仍在**。`graph/recovery.py:13` `recover_orphaned_tasks()` 仍只查 `AgentTask.status in [executing, validating, planning]`，完全不碰 `WorkflowRun` |
| 2 | 无 per-workflow 全局墙钟超时 | 🔴 P0 | **仍在**。`DEFAULT_TIMEOUT_SECONDS=300` 仍只在 `graph/engine.py:22` 声明一处、零处比较；`engine.py:137` 的 `start_time` 只用于事后算 `total_latency_ms`，主循环仅限 `MAX_WORKFLOW_STEPS=10` |
| 3 | Planner 无降级 | 🔴 P1 | **仍在**。`graph/planner.py:171` `plan_with_llm()` 失败返回 `None`，general 类无模板兜底，`supervisor` 见 `None` 即终止 |
| 4 | Memory 摘要不回放 | 🟡 P1 | **仍在**。`memory/service.py:74` `get_memory_context()` 仍只拼 `StudentProfile` 静态字段，从不读回会话摘要 |
| 5 | Agent Core 无调用总量护栏 | 🔴 P1 | **仍在**。生产运行时无跨 agent 聚合计数器（eval 的 soft budget 不作用于线上） |
| 6 | RAG 无来源追踪 | 🟡 P2 | **部分**。问题检索已带 `problem_id/title`；知识点检索仍无通用 `doc_id/source/url` 出处字段 |
| 7 | 运维欠账 | 🟡 P2 | **仍在**。CI + `/metrics` 已就位；备份/恢复、应用内告警规则、自动回滚仍缺 |
| 8 | 无用户反馈闭环 | 🟡 P2 | **仍在**。`app/api` 里的 `feedback` 全是 human-gate 审批语义，无 agent 产出的 rating/feedback 端点 |

---

## 一句话结论

Phase 8 把**「可观测 → 可评测」**这条线彻底补齐：完整 trace、trace 绑定的 EvalHarness、4 类 grader、CI 回归门禁、历史回填都已就位，评测/观测从「能调试」推进到「能持续回归」。

但**编排健壮性的两个 P0（WorkflowRun 崩溃不可恢复、无全局墙钟超时）、Planner 无降级、Memory 仍只写不回放、Agent Core 生产侧无调用总量护栏——这 5 项一条都没动**，正是 Phase 8（聚焦评测面）未覆盖的部分，仍是 agentic 主干的可靠性短板。

## 下一轮优先级建议（按性价比）

| 优先级 | 动作 | 解决模块 | 备注 |
|---|---|---|---|
| P0 | `recovery.py` 增加 `WorkflowRun` 孤儿恢复 | Orchestrator | 改动小、闭环风险高 |
| P0 | engine 主循环把已有 `start_time` 接到 `DEFAULT_TIMEOUT_SECONDS` 做中止 | Orchestrator | 常量已声明，只差引用 |
| P1 | Planner 加 LLM→模板兜底 | Planner | `plan_with_llm` 返回 `None` 时回退 general 模板 |
| P1 | Memory 打通摘要回放（`get_memory_context` 读回 `AIConversation.summary`）+ 补测试 | Memory | |
| P1 | Agent Core 加生产侧跨 agent 调用总量护栏 | Agent Core | 可复用 eval soft budget 的计数思路 |
| P2 | RAG 知识点检索补 `source/doc_id`；监控告警 + 备份 + 反馈端点 | RAG, Ops, API | |
