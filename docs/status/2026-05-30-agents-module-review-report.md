# Agents 项目 12 模块审查结果报告

**审查日期:** 2026-05-30
**交叉验证更新:** 2026-05-31（逐条核验到 file:line，反映 S0–S9 修复后的当前状态）
**范围:** Agent Core、Planner、Tool/Action Layer、Memory/Context、Knowledge/RAG、Executor、Workflow Orchestrator、Safety/Governance、Observability、Evaluation Harness、API/UI、Deployment/Ops

> 关键修正：`.env` 并未提交到 git（已在 `.gitignore`，历史中也从未出现），所以“密钥泄漏到版本库”这个风险不成立。密钥只在本地磁盘明文存放。子 agent 在排查时把它们打印出来了，建议轮换一次作为卫生习惯，但严重性远低于“进了 git”。

---

## 🟢 交叉验证更新（2026-05-31）

> 本节由 4 个并行探查代理逐条核验、再人工复核关键项后得出，是**当前状态的权威结论**；下方原始 2026-05-30 报告正文作为基线保留，但其中已被修复的断言以本节为准。
>
> 自审查日起 `2026-05-30-production-readiness-audit.md` 的 S0–S9 已全部落地，多条原始发现已被覆盖。状态标记：**✅ 已修复 / 🟡 部分修复 / 🔴 仍存在**。

### 更新后总览评分

| 模块 | 原评分 | 当前状态 | 关键变化 / 残留风险 |
|---|---:|---|---|
| Agent Core | 85% | 🔴 基本不变 | 仍无跨 agent 的 LLM 调用总量护栏（仅 per-loop：`MAX_VALIDATION_ROUNDS=3`、`MAX_TOOL_ITERATIONS=5`）。Phase4.2 抽出 `ToolCallExecutor`，结构更清晰 |
| Planner | 70% | 🔴 不变 | LLM 规划失败仍返回 `None` → `supervisor` 直接中止，无回退到模板 |
| Tool/Action Layer | 85% | ✅ 增强 | F8 审批改 descriptor 动态分发、F9 补值域校验后更稳健 |
| Memory/Context | 45% | 🟡 微改 | 摘要现已落库（`AIConversation.summary`），但 `get_memory_context` 仍只读静态画像、**不回读摘要**；零测试仍未补 |
| Knowledge/RAG | 70% | 🟡 部分修复 | 模型已镜像预置 + 强制离线 + `kb_health()` 启动探针（S8）；**来源追踪仍缺**，ChromaDB 单机无副本不变 |
| Executor | 70% | 🟡 部分修复 | 容器 `pids_limit=128` + `internal` 网络隔离已挡住 fork bomb 与外联；**仍无 seccomp**，`RLIMIT_NPROC` 仍被刻意移除 |
| Workflow Orchestrator | 75% | 🔴 仍存在 | `recovery.py` 仍只恢复 `AgentTask`，`WorkflowRun` 崩溃后永久卡 `executing`；`DEFAULT_TIMEOUT_SECONDS=300` **声明了却从未引用**，无全局超时 |
| Safety/Governance | 80% | ✅ 增强 | 审计改为同步 `session.commit()`，不再 fire-and-forget；审批 TOCTOU 窗口仍在但很窄 |
| Observability | 65% | ✅ 已修复 | `/metrics`(Prometheus) + `/health`+`/live` + `compute_cost_cny()` 成本换算（S2）；token 采集与落库解耦、错误路径不再丢。看板/告警仍属外部基础设施 |
| Evaluation Harness | 75% | ✅ 已修复 | `evals.yml` 夜间门禁 + `baseline.json` 基线 + `evals/ci.py` 低于基线即 fail；`tests.yml` 每 PR 跑 pytest（S1） |
| API/UI | 75% | 🟡 部分修复 | `/chat` 已派发到 `ThreadPoolExecutor` 后台执行，不再阻塞请求线程；SSE 已加 ~300s idle 超时；**用户反馈/评分闭环仍缺** |
| Deployment/Ops | 65% | 🟡 部分修复 | CI/CD（tests/evals）+ `/metrics` + healthcheck + `restart` 策略已就位；**备份策略、告警规则、自动回滚仍缺** |

### 仍然成立的硬缺陷（必须优先处理）

1. **WorkflowRun 孤儿不可恢复（🔴 P0）** — `graph/recovery.py:13` 的 `recover_orphaned_tasks()` 只查 `AgentTask.status in [executing, validating, planning]`，完全不碰 `WorkflowRun`。服务器在 `workflow_run.status="executing"` 时崩溃，该行将永久卡死，无任何恢复或告警路径。
2. **无 per-workflow 全局墙钟超时（🔴 P0）** — `graph/engine.py:22` 定义了 `DEFAULT_TIMEOUT_SECONDS=300`，但全仓库**只有这一处声明、零处引用**；主循环（`engine.py:137-180`）只用 `MAX_WORKFLOW_STEPS=10` 限步数，不限时间。10 步每步慢调用可跑 20+ 分钟。
3. **Planner 无降级（🔴 P1）** — `graph/planner.py:plan_with_llm()` 失败返回 `None`，`graph/supervisor.py` 见 `None` 即返回 `"Failed to generate execution plan"` 终止，不回退到模板计划。
4. **Memory 摘要仍不回放（🟡 P1）** — `generate_conversation_summary()` 的输出已写入 `AIConversation.summary`，但 `memory/service.py:get_memory_context()` 仅拼装 `StudentProfile` 静态字段（`learning_summary/error_patterns/...`），从不读回会话摘要；跨会话长期记忆仍未打通，且 `memory/` 零测试。
5. **Agent Core 无调用总量护栏（🔴 P1）** — 仅有 per-loop 上限，多 agent workflow（supervisor→generator→reviewer）可叠加放大调用次数，无聚合计数器。
6. **RAG 无来源追踪（🟡 P2）** — `knowledge/store.py` 各 `search_*` 返回结果均无 `source/url/doc_id` 等出处字段，无法回溯证据来源。
7. **运维欠账（🟡 P2）** — 无备份/恢复方案（compose 定义了卷但无快照/自动备份）、无应用内告警规则、无自动回滚（需 K8s/Swarm 编排器）。
8. **无用户反馈闭环（🟡 P2）** — `/api/v1` 下无任何 rating/feedback 端点，agent 产出质量无法从真实用户侧收敛。

### 已被 S0–S9 覆盖、不再成立的原始断言

- ❌「Observability 无成本换算、token 依赖回调会丢」→ 已加 `compute_cost_cny()` 与解耦的 metrics 发射。
- ❌「Evaluation 未进 CI、无回归基线」→ `evals.yml` + `baseline.json` + `evals/ci.py` 已就位。
- ❌「API 同步执行阻塞 worker、SSE 无超时」→ 已改后台线程池派发 + SSE idle 超时。
- ❌「Deployment 无 CI/CD、无 Prometheus」→ CI 与 `/metrics` 已就位（但备份/告警/回滚仍缺，见上）。
- ❌「Executor fork bomb 仅靠 2s 墙钟」→ 容器 `pids_limit` + 内网隔离已实质降低风险（seccomp 仍缺）。
- ❌「Safety 审计 fire-and-forget 可能丢」→ 已改同步 `commit()`。

---

## 总览评分（原始 2026-05-30 基线）

| 模块 | 实际完成度 | 接入状态 | 稳健性 | 最大风险 |
|---|---:|---|---|---|
| Agent Core | 85% | ✅ 已接入 | 🟡 中 | Generator 嵌套校验循环最多 18 次 LLM 调用无总量护栏 |
| Planner | 70% | 🟡 部分 | 🔴 弱 | LLM 失败即返回 `None`，无重规划，整个 workflow 直接中止 |
| Tool/Action Layer | 85% | ✅ 已接入 | 🟢 强 | codegen 身份注入映射若错位可越权 |
| Memory/Context | 45% | 🟡 部分 | 🔴 弱 | 会话摘要“只写不读”，下轮不回放；零测试覆盖 |
| Knowledge/RAG | 70% | ✅ 已接入 | 🟡 中 | embedding 模型运行时下载，初始化脆弱；无来源追踪 |
| Executor | 70% | 🟡 部分 | 🟡 中 | fork bomb 仅靠 2s 墙钟拦截；无 seccomp/网络隔离 |
| Workflow Orchestrator | 75% | 🟡 部分 | 🔴 弱 | 崩溃后 `WorkflowRun` 永久卡 `executing`；无全局超时 |
| Safety/Governance | 80% | ✅ 已接入 | 🟢 强 | 审批竞态 + 审计异步 fire-and-forget |
| Observability | 65% | ✅ 已接入 | 🟡 中 | token 统计依赖回调触发，错误路径会丢；无成本换算 |
| Evaluation Harness | 75% | 🟡 部分 | 🟡 中 | 仅测 happy-path；无回归基线；未进 CI |
| API/UI | 75% | 🟡 部分 | 🟡 中 | 同步执行 agent 阻塞 worker；SSE 无超时；无反馈闭环 |
| Deployment/Ops | 65% | 🟡 部分 | 🔴 弱 | 无 CI/CD、无监控告警、无自动回滚 |

## 三档判断

### 做得扎实（强）

**Tool/Action + Safety/Governance** 是这个项目的亮点。

15 个工具走统一 `catalog → codegen → guard` 管线，具备 `jsonschema` 校验、三层权限（RBAC/scope/risk）、EdDSA 签名能力令牌（120s TTL）、HIGH 风险工具的人工审批门、出口脱敏，并且有 `test_mcp_permission_matrix.py` 等矩阵测试守护。这是少见地按生产标准在做的部分。

### 能跑但有结构性缺口（中/弱）

**Planner / Orchestrator** 是最薄弱的一环。规划主要靠硬编码模板，LLM 规划极少触发且无重规划。任一步骤失败时，`engine.py` 直接终止整个 workflow（无降级、无重试到更简单计划）。`recovery.py` 只恢复 `ChatTask`/`AgentTask`，不恢复 `WorkflowRun`，服务器崩溃后这些 run 永久卡死。且无 per-workflow 全局超时。

**Memory** 名不副实：当前只有“每请求加载静态画像”+ 单会话内压缩。`generate_conversation_summary()` 生成的摘要去向不明，下一轮不会被读回，本质是只写不读，谈不上长期记忆。且 `memory/` 零测试。

**API/UI** 同步执行：`/chat` 直接在请求线程上 `AgentOrchestrator.run()` 阻塞，gunicorn 4 worker 只能扛 4 个并发，第 5 个排队；SSE 生成器无超时，agent 挂起则连接永不关闭。有审计但没有任何用户反馈/评分闭环。

### 基础设施欠账（弱）

**Deployment/Ops**：容器化本身做得不错（4 服务、只读 FS、非 root、健康检查全覆盖、Alembic 11 个迁移）。但完全没有 CI/CD、没有 Prometheus/Sentry/告警、没有自动回滚、没有备份策略。审计日志和 trace 写进 DB 了但没有任何看板消费。

## 跨模块共性问题

- **测试广而浅：** 30 个测试文件、约 318 个用例，但大量用 mock 验证契约而非端到端行为；没有一条贯穿 Planner → Engine → Agent 的集成测试，并发/竞态/崩溃恢复均无测试，且未进 CI（提交不触发测试）。
- **超时缺位：** agent 工具循环有 `MAX_TOOL_ITERATIONS=5`、handoff 有 `MAX_HANDOFFS=2`、workflow 步数有上限，但没有任何按墙钟时间的全局超时，任一 LLM 慢调用可无限期占住请求。
- **可观测但不可运营：** trace/audit/token 都在采集，但 token 统计依赖回调、错误路径会丢，且没有成本换算、没有看板、没有告警。“能调试，不能运营”。

## 建议优先级（原始 · 已用 2026-05-31 状态标注）

| 优先级 | 动作 | 解决模块 | 当前状态 |
|---|---|---|---|
| P0 | 把 agent 执行移出请求线程 + 给 SSE 和 workflow 加全局超时 | API/UI, Orchestrator | 🟡 线程池派发 + SSE 超时已做；**workflow 全局超时仍未做** |
| P0 | `recovery.py` 增加 `WorkflowRun` 孤儿恢复 | Orchestrator | 🔴 仍未做 |
| P1 | 搭最小 CI（pytest + 迁移校验），把 eval harness 挂进去做回归基线 | Deployment, Eval | ✅ 已完成（tests/evals workflow + baseline） |
| P1 | Memory 打通“摘要回放”：把会话摘要写回并在下轮 `_build_system_context` 读取；补测试 | Memory | 🟡 已写回库，**仍未在下轮读回**；测试仍缺 |
| P1 | Executor 恢复 `RLIMIT_NPROC` 或上 seccomp/容器网络隔离，挡 fork bomb | Executor | 🟡 内网隔离 + `pids_limit` 已挡住；seccomp 仍缺 |
| P1（新增）| Agent Core 加跨 agent 的 LLM 调用总量护栏 | Agent Core | 🔴 仍未做 |
| P2 | Docker 预缓存 embedding 模型 + KB 启动健康检查；给 RAG 加来源追踪字段 | Knowledge/RAG | 🟡 预缓存 + 健康检查已做；**来源追踪仍缺** |
| P2 | 接入监控告警（Prometheus/Grafana 或 Sentry），消费已有 audit/trace | Observability, Deployment | 🟡 `/metrics` 已出；**告警/看板/备份/回滚仍缺** |

## 一句话总结（2026-05-31 修订）

S0–S9 已把**运维面与信任边界**的硬伤基本补齐——CI、Prometheus/成本换算、离线模型、签名令牌、同步审计、异步执行都已就位，安全/工具层依旧是护城河。当前离生产最近的三块残留缺陷集中在**编排健壮性**：`WorkflowRun` 崩溃不可恢复、无 per-workflow 全局超时、Planner 失败无降级；其次是**记忆仍只写不回放**与 **Agent Core 无调用总量护栏**。这些是 agentic 主干的可靠性短板，应作为下一轮优先项。
