# Agents 项目模块审查结果报告

**原始审查日期:** 2026-06-03
**更新日期:** 2026-06-05
**范围模块:** Agent Core、Planner、Tool/Action Layer、Memory/Context、Knowledge/RAG、Executor、Workflow Orchestrator、Safety/Governance、Observability、Evaluation Harness、API/UI、Deployment/Ops

> 本报告已按 2026-06-05 的 agent platform 完成状态刷新。原 2026-06-03 版本中多项“仍在”的问题已经由 Phase 1-4 / Phase 3.5 的实现关闭；当前未解决项只保留真实残余。

---

## 自 2026-06-03 以来的关键变化

- **Agent Core 收束**: `agents/session.py`、`agents/runtime.py`、`agents/llm_runner.py` 已落地,`BaseAgent` 通过 `AgentRuntime` 执行,工具 identity/trace 从 `AgentSession` 传递。
- **声明式 registry 完整化**: `core/definitions.py` 已承载 `max_tool_iterations`、`rate_limit`、`handoff_targets`、`prompt_ref`;`agents/registry.py` 是 name -> class 的单一入口。
- **Tool/MCP boundary 收口**: 内部 agent path 与外部 MCP path 共享 `ToolRuntime`;`coderunner.agent.delegate` 取代 regex handoff。
- **Workflow execution 增强**: `WorkflowEngine` 已支持 step trace 绑定、approval audit、全局墙钟超时、显式断点续跑、step context 裁剪;启动时会安全处理 orphaned workflows。
- **Planner fallback 已补**: `graph/planner.py` 在 LLM 规划失败时回退 general template。
- **Memory summary replay 已补**: `memory/service.py` 会读取 `AIConversation.summary`,并有回归测试。
- **Eval/trace 基础继续保留**: trace-bound eval、grader、report、production failure promotion 基础存在;后续重点转向 EvalOps 产品化。

---

## 当前总览评分

| 模块 | 当前状态 | 关键变化 / 残留风险 |
|---|---|---|
| Agent Core | 🟢 已显著收束 | `AgentSession`/`AgentRuntime`/`LLMRunner`;`MAX_LLM_CALLS_PER_TRACE` 生产侧护栏已接入 |
| Planner | 🟢 已补关键兜底 | LLM planner 失败时回退 general template |
| Tool/Action Layer | 🟢 强 | ToolRuntime policy core、retry_policy、output schema enforce toggle、delegate tool |
| Memory/Context | 🟡 部分完成 | 会回放会话摘要;完整 context/memory 分层仍是后续提升 |
| Knowledge/RAG | 🟡 部分修复 | 问题检索已有基础出处;知识点检索仍缺通用 `doc_id/source/url` |
| Executor | 🟡 部分修复 | 容器隔离已有基础;seccomp/更完整运行时安全仍可加强 |
| Workflow Orchestrator | 🟢 已显著增强 | orphan recovery、timeout、trace binding、approval audit、resume、context crop 已有;任意 step replay 仍后续 |
| Safety/Governance | 🟢 强 | platform-enforced tool permission + human gate + audit |
| Observability | 🟢 强 | trace schema/store/API/UI 与 workflow trace 绑定 |
| Evaluation Harness | 🟡 基础强,产品化未完成 | trace-bound eval 已有;fast/full eval、版本绑定、生产失败回灌仍后续 |
| API/UI | 🟡 可用但需拆分 | `app/api/v1/ai.py` 仍过大;用户质量反馈闭环仍缺 |
| Deployment/Ops | 🟡 部分修复 | CI/health/metrics 基础存在;备份/告警/回滚/runbook 仍缺 |

---

## 原 8 条硬缺陷的当前状态

| # | 缺陷 | 原级别 | 当前状态 |
|---|---|---|---|
| 1 | WorkflowRun 孤儿不可恢复 | P0 | ✅ 已关闭。`graph/recovery.py:41` `recover_orphaned_workflows()` 会将崩溃中断的 workflow 安全标 failed,`app/__init__.py` 启动调用;`tests/test_graph_engine.py` 覆盖 |
| 2 | 无 per-workflow 全局墙钟超时 | P0 | ✅ 已关闭。`graph/engine.py` 使用 `DEFAULT_TIMEOUT_SECONDS` 检查 elapsed;`tests/test_graph_engine.py::test_workflow_aborts_when_wall_clock_timeout_exceeded` 覆盖 |
| 3 | Planner 无降级 | P1 | ✅ 已关闭。`graph/planner.py` 新增 `plan_general_fallback()`;`create_plan()` 在 LLM 失败时回退 |
| 4 | Memory 摘要不回放 | P1 | ✅ 已关闭。`memory/service.py` 读取 `AIConversation.summary`;`tests/test_agents.py::test_get_memory_context_replays_recent_summaries` 覆盖 |
| 5 | Agent Core 无调用总量护栏 | P1 | ✅ 已关闭。`agents/runtime.py` 检查 `MAX_LLM_CALLS_PER_TRACE`;超限进入 `limit_exceeded` |
| 6 | RAG 无来源追踪 | P2 | 🟡 部分。问题检索已有 `problem_id/title`;知识点检索仍缺通用 `doc_id/source/url` |
| 7 | 运维欠账 | P2 | 🔴 仍在。备份/恢复、日志聚合、告警、自动回滚、容量指引、trace/eval 排障 runbook 仍缺 |
| 8 | 无用户反馈闭环 | P2 | 🔴 仍在。`feedback` 主要是 human-gate 审批语义,仍缺面向 agent 输出质量的 rating/feedback 端点 |

---

## 当前一句话结论

Agentic 主干已经从“功能堆叠”推进到较完整的平台内核:runtime kernel、declarative registry、ToolRuntime boundary、tool-based delegation、workflow trace/approval/resume、planner fallback、memory summary replay 都已落地。

当前剩余短板不再是原来的 P0 编排基础缺口,而是产品化和运维成熟度:EvalOps/replay 质量门禁、context/memory 治理、RAG 来源追踪、用户反馈闭环、`app/api/v1/ai.py` 拆分、备份告警回滚 runbook。

## 下一轮优先级建议

| 优先级 | 动作 | 解决模块 | 备注 |
|---|---|---|---|
| P1 | RAG 知识点检索补 `source/doc_id/url` | RAG | 让 AI 回答可追溯 |
| P1 | 增加 agent 输出质量 feedback/rating 端点 | API/UI, Eval | 为生产失败回灌和质量趋势提供入口 |
| P2 | Context and Memory Architecture 专项 | Memory/Context | 见 active remaining-improvements plan |
| P2 | EvalOps/replay 产品化 | Evaluation | fast/full eval、版本绑定、生产失败回灌 |
| P2 | Ops runbook + backup/alert/rollback | Deployment/Ops | 上线成熟度 |
| P2 | 拆分 `app/api/v1/ai.py` | API | 降低维护风险 |
