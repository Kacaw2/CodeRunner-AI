# Known Issues / 当前已知问题

本目录是**当前已知、尚未解决问题**的入口。它和 `docs/status/` 的区别:

- `status/` 保存状态报告、审计快照、成熟度评估(某个时间点的全景)。
- `issues/` 只保留当前仍需要跟踪或后续决策的问题；已解决项应移出未解决表，或在详细报告中标为已关闭。

> 维护约定:每条问题给出严重度(P1/P2/P3)、来源文档和证据位置。详细问题报告单独成文,本页只做索引和状态汇总。

---

## 详细问题报告

| 报告 | 主题 | 当前状态 | 严重度 |
|---|---|---|---|
| [2026-06-04-dual-orm-database-issues.md](2026-06-04-dual-orm-database-issues.md) | 双层 ORM 数据模型 | 部分解决:迁移基线/create_all 已关闭,双引擎/重复映射仍是架构债 | P2 |
| [2026-06-08-agent-memory-context-improvements.md](2026-06-08-agent-memory-context-improvements.md) | Agent memory / context 治理 | Draft:已整理现状、边界、目标设计与阶段建议 | P2 |
| [2026-06-03-production-maturity-priority-assessment.md](2026-06-03-production-maturity-priority-assessment.md) | 生产成熟度优先级评估 | 已按 2026-06-05 代码事实更新 | P1-P3 |
| [2026-06-03-agents-module-review-report.md](2026-06-03-agents-module-review-report.md) | agents 模块审查报告 | 已按 2026-06-05 agent platform 完成状态更新 | P2-P3 |

---

## 未解决问题汇总(2026-06-05)

来源:本目录下三份详细报告、`docs/plans/archive/2026-06-04-*` 已完成执行方案、以及当前代码核验。已关闭项见下方“已关闭”。

### P1 — 上线前必须

| # | 问题 | 证据 | 来源 |
|---|---|---|---|
| 1 | Cypress E2E 未进 CI;`cypress.config.js` seed 指向缺失的 `docker/docker-compose.yml`;`npm test` 仍是占位失败 | `.github/workflows/tests.yml`、`cypress.config.js`、`package.json` | maturity #2 |
| 2 | 生产安全边界仍不完整:开放注册可直接选 `teacher`;缺少真正 CSRF token;AI Redis 限流失败时 fail-open | `app/services/auth_service.py`、`signup.html`、`app/core/config.py`、`app/api/v1/ai.py` | maturity #3 |

### P2 — 平台边界与可维护性

| # | 问题 | 证据 | 来源 |
|---|---|---|---|
| 3 | 双层 ORM 边界仍未最终收敛:Flask/core 双 engine、双事务、重复 mapped class 仍存在 | 见 [dual-orm 报告](2026-06-04-dual-orm-database-issues.md) | maturity #5 |
| 4 | `app/api/v1/ai.py` 仍是大型聚合文件(chat/generation/traces/evals/knowledge/workflows 混在一起) | `app/api/v1/ai.py` | maturity #4 |
| 5 | 运维闭环缺失:备份恢复、日志聚合、错误告警、部署回滚、容量指引、trace/eval 排障 runbook | `compose.yaml` 已有服务但无完整运维面 | maturity #6 |
| 6 | RAG 知识点检索仍缺通用来源追踪(`doc_id/source/url`) | `knowledge/`、`tools/knowledge_search/` | agents review #6 |
| 7 | 无用户反馈闭环:没有面向 agent 输出质量的 rating/feedback 端点 | `app/api/v1/ai.py` 中 `feedback` 主要是 human-gate 审批语义 | agents review #8 |
| 8 | Agent memory/context 仍缺结构化策略、注入预算、trace 审计和 replay snapshot | [memory/context 改进议题](2026-06-08-agent-memory-context-improvements.md)、`ai/memory/service.py`、`core/definitions.py` | agent platform follow-up |

### P3 — 质量与文档

| # | 问题 | 证据 | 来源 |
|---|---|---|---|
| 9 | EvalOps 仍需产品化:fast/full eval、prompt/model/tool/runtime 版本绑定、生产失败自动回灌、成本趋势 | `evals/`、`.github/workflows/evals.yml`;后续计划见 `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md` | maturity #8 |
| 10 | ToolRuntime 运维级 guardrails 尚未做:per-tool/per-user quota、circuit breaker、write-tool idempotency、live HTTP E2E | `tools/protocol/runtime.py`;后续计划见 active remaining-improvements | agent platform follow-up |
| 11 | ChromaDB 单机落盘无副本/无备份(RAG 单点) | `knowledge/store.py`、`compose.yaml` | audit F6 残余 |

---

## 已关闭(参考,不再作为当前问题跟踪)

| 关闭日期 | 问题 | 证据 |
|---|---|---|
| 2026-06-04 | 迁移链无基线、空库无法 `flask db upgrade` 重建、生产启动依赖 `db.create_all()` | `migrations/versions/e21895a59f7d_baseline_full_schema.py`;`migrations/env.py` 使用 `core/db/metadata.py`;`tests/test_migration_full_schema.py` 常态 PASS;`app/__init__.py` 只做 schema check |
| 2026-06-05 | WorkflowRun 孤儿不可恢复 | `graph/recovery.py:41` `recover_orphaned_workflows()`;`app/__init__.py` 启动调用;`tests/test_graph_engine.py` 覆盖 |
| 2026-06-05 | WorkflowEngine 无全局墙钟超时 | `graph/engine.py` 使用 `DEFAULT_TIMEOUT_SECONDS`;`tests/test_graph_engine.py::test_workflow_aborts_when_wall_clock_timeout_exceeded` |
| 2026-06-05 | Planner LLM 失败无模板兜底 | `graph/planner.py` `plan_general_fallback()`;`tests/test_graph_engine.py::TestPlannerFallback` |
| 2026-06-05 | Memory 摘要不回放 | `memory/service.py` 读取 `AIConversation.summary`;`tests/test_agents.py::test_get_memory_context_replays_recent_summaries` |
| 2026-06-05 | Agent Core 无生产侧跨 agent LLM 调用总量护栏 | `agents/runtime.py` 检查 `MAX_LLM_CALLS_PER_TRACE`;`tests/test_agents.py`/`tests/test_agent_runtime_kernel.py` 覆盖 |

2026-05-30 生产就绪审计的 F1-F9 已全部修复(S0-S9 完成),总体风险从 MEDIUM 降至 LOW。详见 [status/2026-05-30-production-readiness-audit.md](../status/2026-05-30-production-readiness-audit.md) 第五节。本目录不重复跟踪这些已关闭项。
