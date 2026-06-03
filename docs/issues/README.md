# Known Issues / 当前已知问题

本目录是**当前已知、尚未解决问题**的唯一入口。它和 `docs/status/` 的区别:

- `status/` 保存状态报告、审计快照、成熟度评估(某个时间点的全景)。
- `issues/`(本目录)只保留**当前仍未解决**的问题清单,用于跟踪与排期;问题一旦解决就从下表移除或标记关闭。

> 维护约定:每条问题给出严重度(P1/P2/P3)、来源文档和证据位置。详细问题报告单独成文,本页只做索引和状态汇总。

---

## 详细问题报告

| 报告 | 主题 | 严重度 |
|---|---|---|
| [2026-06-04-dual-orm-database-issues.md](2026-06-04-dual-orm-database-issues.md) | 双层 ORM 数据模型(双引擎/双 URL/迁移盲区/重复表/无基线) | P1 |
| [2026-06-03-production-maturity-priority-assessment.md](2026-06-03-production-maturity-priority-assessment.md) | 生产成熟度优先级评估(下方 P1–P3 清单的原始来源) | P1–P3 |
| [2026-06-03-agents-module-review-report.md](2026-06-03-agents-module-review-report.md) | agents 模块审查报告(结构、问题清单、改进方向) | — |

---

## 未解决问题汇总(从 status 报告承接)

来源:[2026-06-03-production-maturity-priority-assessment.md](2026-06-03-production-maturity-priority-assessment.md)(已随本目录迁入)与 [status/2026-05-30-production-readiness-audit.md](../status/2026-05-30-production-readiness-audit.md)。下列为**截至 2026-06-04 仍未解决**的项。表中 `maturity #N` 指 assessment 的条目编号。

### P1 — 上线前必须

| # | 问题 | 证据 | 来源 |
|---|---|---|---|
| 1 | 迁移链无基线,`db.create_all()` 才是真正 schema 源头;空库无法 `flask db upgrade` 重建 | `app/__init__.py:70`、`tests/test_migration_full_schema.py`(xfail) | maturity #1 |
| 2 | 双层 ORM 边界未收敛(双引擎/双事务/迁移只见 Flask 一半表/7 张表重复定义) | 见 [dual-orm 报告](2026-06-04-dual-orm-database-issues.md) | maturity #5 |
| 3 | Cypress E2E 未进 CI;`cypress.config.js` seed 指向缺失的 `docker/docker-compose.yml`;`npm test` 仍是占位失败 | `.github/workflows/tests.yml`、`cypress.config.js:~10`、`package.json:~10` | maturity #2 |

### P2 — 生产边界与可维护性

| # | 问题 | 证据 | 来源 |
|---|---|---|---|
| 4 | 开放注册可直接选 `teacher`,非生产级;应改邀请码/管理员审批 | `app/services/auth_service.py:~40`、`signup.html:~52` | maturity #3 |
| 5 | 无真正 CSRF token(Cookie 有 HttpOnly/SameSite,但无 CSRF) | `app/core/config.py:~58` | maturity #3 |
| 6 | Redis 限流失败时 fail-open(失败即放行) | `app/api/v1/ai.py:~47` | maturity #3 |
| 7 | `app/api/v1/ai.py` 约 2252 行单文件累积(chat/generation/traces/evals/knowledge/workflows 混在一起) | `app/api/v1/ai.py` | maturity #4 |
| 8 | 运维闭环缺失:备份恢复、日志聚合、错误告警、部署回滚、容量指引、trace/eval 排障 runbook | compose.yaml 已有服务但无运维面 | maturity #6 |

### P3 — 质量与文档

| # | 问题 | 证据 | 来源 |
|---|---|---|---|
| 9 | Eval 仍是基础通过率,未产品化(数据集小、未记录 prompt/model 版本、未自动回灌生产失败、无成本趋势) | `.github/workflows/evals.yml:~70` | maturity #8 |
| 10 | Human Gate 仅作为草稿审批流,未与 AgentTask 状态机完整打通 | `docs/architecture/ai-agents.md:~30` | maturity #9 |
| 11 | 文档漂移:`docs/architecture/executor.md:~33` 仍描述远程失败回退本地,实际代码已 fail-closed | `app/services/executor_service.py:~72` | maturity #7 |
| 12 | ChromaDB 单机落盘无副本/无备份(RAG 单点) | `knowledge/store.py` | audit F6 残余 |

---

## 已关闭(参考,不再跟踪)

2026-05-30 生产就绪审计的 F1–F9 已全部修复(S0–S9 完成),总体风险从 MEDIUM 降至 LOW。详见 [status/2026-05-30-production-readiness-audit.md](../status/2026-05-30-production-readiness-audit.md) 第五节。本目录不重复跟踪这些已关闭项。
