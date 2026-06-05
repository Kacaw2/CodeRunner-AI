# Plans

本目录是计划文档的唯一入口。`active/` 只放仍需要决策或执行的计划；已完成、被新计划替代或仅供追溯的执行方案放入 `archive/`。

## 目录约定

| 目录 | 用途 |
|---|---|
| `active/` | 当前仍在执行，或仍作为后续目标状态依据的计划 |
| `archive/` | 已完成、被替代、暂停或仅供历史追溯的计划 |
| `archive/superpowers/` | 历史 agent 执行计划、迁移计划和审计计划 |

不再使用 `docs/archive/plans/`。所有计划都应该放在本目录下，避免 archive 与 plans 双重归档。

## Active

### Agent Platform 后续提升

- [2026-06-05-agent-platform-remaining-improvements-plan.md](active/2026-06-05-agent-platform-remaining-improvements-plan.md) — 从 Claude Code-inspired 架构升级路线中抽取的未实现真实提升项：Context/Memory、EvalOps/Replay、streaming workflow、replay/idempotency、ToolRuntime 运维级 guardrails。

## Archive

### 已完成：Agent Platform 架构路线和执行方案

- [2026-06-04-claude-code-inspired-architecture-upgrade-plan.md](archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md) — 已完成主体路线，剩余提升项转入 active 的 remaining improvements 文档。
- [2026-06-04-phase1-agent-runtime-kernel-plan.md](archive/2026-06-04-phase1-agent-runtime-kernel-plan.md)
- [2026-06-04-phase2-declarative-agent-registry-plan.md](archive/2026-06-04-phase2-declarative-agent-registry-plan.md)
- [2026-06-04-phase3-unified-tool-mcp-boundary-closeout-plan.md](archive/2026-06-04-phase3-unified-tool-mcp-boundary-closeout-plan.md)
- [2026-06-04-phase3.5-toolruntime-hardening-plan.md](archive/2026-06-04-phase3.5-toolruntime-hardening-plan.md)
- [2026-06-04-phase4-planning-task-execution-plan.md](archive/2026-06-04-phase4-planning-task-execution-plan.md)

### 已完成：数据库 / Schema 基础设施

- [2026-06-04-dual-orm-single-schema-source-plan.md](archive/2026-06-04-dual-orm-single-schema-source-plan.md)

### 历史计划

- [2026-05-26-phase1-phase2-repair-plan.md](archive/2026-05-26-phase1-phase2-repair-plan.md)
- [2026-05-26-phase3-mcp-server-plan.md](archive/2026-05-26-phase3-mcp-server-plan.md)
- [2026-05-26-phase4-human-gate-plan.md](archive/2026-05-26-phase4-human-gate-plan.md)
- [2026-05-27-phase5-mcp-centric-architecture-plan.md](archive/2026-05-27-phase5-mcp-centric-architecture-plan.md)
- [2026-05-28-architecture-refactor-plan.md](archive/2026-05-28-architecture-refactor-plan.md)
- [2026-05-29-0329-phase-0-security-hardening-plan.md](archive/2026-05-29-0329-phase-0-security-hardening-plan.md)
- [2026-05-29-mcp-architecture-repair-plan.md](archive/2026-05-29-mcp-architecture-repair-plan.md)
- [2026-05-29-phase-1-4-architecture-hardening-plan.md](archive/2026-05-29-phase-1-4-architecture-hardening-plan.md)
- [2026-05-29-phase-1-architecture-unification-detailed.md](archive/2026-05-29-phase-1-architecture-unification-detailed.md)
- [2026-05-29-phase-2-rag-orchestration-detailed.md](archive/2026-05-29-phase-2-rag-orchestration-detailed.md)
- [2026-05-31-agent-improvement-plan.md](archive/2026-05-31-agent-improvement-plan.md)
- [2026-06-01-complete-traces-evals-plan.md](archive/2026-06-01-complete-traces-evals-plan.md)
- [2026-06-02-chroma-1x-upgrade-plan.md](archive/2026-06-02-chroma-1x-upgrade-plan.md)
- [AGENT_ARCHITECTURE_MATURITY_PLAN.md](archive/AGENT_ARCHITECTURE_MATURITY_PLAN.md)
- [FASTAPI_AGENT_HOST_MCP_WORKFLOW_PLAN_ZH.md](archive/FASTAPI_AGENT_HOST_MCP_WORKFLOW_PLAN_ZH.md)
- [RAG_REVIEW_AND_FIX_PLAN.md](archive/RAG_REVIEW_AND_FIX_PLAN.md)

## Archive / Superpowers

- [2026-05-22-problem-variant-migration.md](archive/superpowers/2026-05-22-problem-variant-migration.md)
- [2026-05-22-problem-variant-migration-zh.md](archive/superpowers/2026-05-22-problem-variant-migration-zh.md)
- [2026-05-23-agent-module-integration.md](archive/superpowers/2026-05-23-agent-module-integration.md)
- [ai-agents-module-audit.md](archive/superpowers/ai-agents-module-audit.md)
