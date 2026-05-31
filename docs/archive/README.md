# CodeRunner 文档归档

这里保存已经完成、被主文档替代或仅用于历史追溯的文档。当前文档入口保留在 [docs/README.md](../README.md)。

## 归档分区

| 目录 | 内容 |
|---|---|
| `completed/` | 已完成的实现指南和阶段性增强方案 |
| `plans/` | 已落地或不再执行的架构方案、审查计划 |
| `status/` | 历史状态总览、知识图谱和一次性审查产物 |
| `superpowers/plans/` | 代理执行计划、迁移计划和历史审计记录 |

## 主要归档文件

### completed/

- [AGENT_ENHANCEMENT_GUIDE.md](completed/AGENT_ENHANCEMENT_GUIDE.md)
- [AGENT_ENHANCEMENT_GUIDE_ZH.md](completed/AGENT_ENHANCEMENT_GUIDE_ZH.md)

### plans/

- [AGENT_ARCHITECTURE_MATURITY_PLAN.md](plans/AGENT_ARCHITECTURE_MATURITY_PLAN.md) — Agent 架构成熟化原始草案；多数条目已被后续 Phase E/E2/6 落地或重排，留作历史参考
- [FASTAPI_AGENT_HOST_MCP_WORKFLOW_PLAN_ZH.md](plans/FASTAPI_AGENT_HOST_MCP_WORKFLOW_PLAN_ZH.md) — FastAPI Agent Host 原始设计
- [RAG_REVIEW_AND_FIX_PLAN.md](plans/RAG_REVIEW_AND_FIX_PLAN.md) — RAG 子系统早期审查
- [2026-05-26-phase1-phase2-repair-plan.md](plans/2026-05-26-phase1-phase2-repair-plan.md) — Phase 1/2 修复方案（已完成）
- [2026-05-26-phase3-mcp-server-plan.md](plans/2026-05-26-phase3-mcp-server-plan.md) — Phase 3 MCP Server 接入（已完成）
- [2026-05-26-phase4-human-gate-plan.md](plans/2026-05-26-phase4-human-gate-plan.md) — Phase 4 Human Gate 审批流（已完成）
- [2026-05-27-phase5-mcp-centric-architecture-plan.md](plans/2026-05-27-phase5-mcp-centric-architecture-plan.md) — Phase E：MCP 唯一工具边界（已完成）
- [2026-05-28-architecture-refactor-plan.md](plans/2026-05-28-architecture-refactor-plan.md) — Phase 6：顶层目录重组（已完成）
- [2026-05-29-0329-phase-0-security-hardening-plan.md](plans/2026-05-29-0329-phase-0-security-hardening-plan.md) — Phase 0 安全加固：trace 脱敏 + SECRET_KEY 门禁 + 隔离 executor（已完成，commit 9acb2cb）
- [2026-05-29-phase-1-architecture-unification-detailed.md](plans/2026-05-29-phase-1-architecture-unification-detailed.md) — Phase 1 架构合一详细落地（已完成，后续由 2026-05-29-mcp-architecture-repair-plan 接续完善）
- [2026-05-29-mcp-architecture-repair-plan.md](plans/2026-05-29-mcp-architecture-repair-plan.md) — MCP 原生架构修复（已完成，含 Docker 运行时 smoke；修复 gateway ORM 注册缺失，commit bd60e75）
- [2026-05-29-phase-1-4-architecture-hardening-plan.md](plans/2026-05-29-phase-1-4-architecture-hardening-plan.md) — Phase 1–4 加固路线图（Phase 0/1 已完成并各自归档，Phase 3/4 并入生产就绪审计，Phase 2 现已落地，整体被审计报告取代）
- [2026-05-29-phase-2-rag-orchestration-detailed.md](plans/2026-05-29-phase-2-rag-orchestration-detailed.md) — Phase 2 RAG + 编排详细方案（chunk/rerank/owner 隔离、critic 接入 engine 均已在代码实现）

### status/

- [AI_AGENTS_STATUS.md](status/AI_AGENTS_STATUS.md) — Agent 模块能力状态历史快照
- [AI_AGENT_KNOWLEDGE_GRAPH.html](status/AI_AGENT_KNOWLEDGE_GRAPH.html)
- [2026-05-30-production-readiness-audit.md](status/2026-05-30-production-readiness-audit.md) — 12 层 Agent 架构生产就绪审计（S0–S9 全部完成，总体降至 LOW RISK）
- [2026-05-30-agents-module-review-report.md](status/2026-05-30-agents-module-review-report.md) — Agents 模块能力交叉验证报告

### superpowers/plans/

- [2026-05-22-problem-variant-migration.md](superpowers/plans/2026-05-22-problem-variant-migration.md)
- [2026-05-22-problem-variant-migration-zh.md](superpowers/plans/2026-05-22-problem-variant-migration-zh.md)
- [2026-05-23-agent-module-integration.md](superpowers/plans/2026-05-23-agent-module-integration.md)
- [ai-agents-module-audit.md](superpowers/plans/ai-agents-module-audit.md)

> 当前生效的设计文档位于 [../](..) 顶层（`ARCHITECTURE.md` / `AI_AGENTS.md` / `AI_API.md` 等）。归档文件中提到的路径多为历史布局（`app/agents/`、`agent_host/`、`mcp/`、`mcp_server/`），不再反映当前代码结构。
