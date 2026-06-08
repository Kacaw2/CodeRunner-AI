# Agent Platform Remaining Improvements Plan

> 状态：Active  
> 日期：2026-06-05  
> 来源：从已归档的 `docs/plans/archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md` 中抽取未实现的真实提升项  
> 范围：`agents/`、`graph/`、`tools/protocol/`、`mcp_gateway/`、`evals/`、`core/observability/`

## 结论

`2026-06-04-claude-code-inspired-architecture-upgrade-plan.md` 的主体已经完成：Phase 1 runtime kernel、Phase 2 declarative registry、Phase 3 MCP/tool boundary、Phase 3.5 ToolRuntime hardening、Phase 4 planning/workflow execution 都已有对应实现、执行方案和回归测试。

后续不应继续把旧总路线当作 active 计划推进。真正还值得保留的提升项，是执行过程中被明确延后的平台能力：上下文/记忆治理、EvalOps/replay 质量门禁、streaming workflow 统一、任意 step replay 所需的幂等基础，以及 ToolRuntime 的运维级保护。

## 已完成基线

| 方向 | 当前状态 | 归档执行方案 |
|---|---|---|
| Agent runtime kernel | 已有 `AgentSession`、`AgentRuntime`、`LLMRunner`，工具调用 identity/trace 从 session 传递 | `docs/plans/archive/2026-06-04-phase1-agent-runtime-kernel-plan.md` |
| Declarative registry | `core/definitions.py` 已承载 budget、rate limit、handoff target、prompt ref；`agents/registry.py` 是 name -> class 入口 | `docs/plans/archive/2026-06-04-phase2-declarative-agent-registry-plan.md` |
| Unified Tool / MCP boundary | 内部 agent path 与外部 MCP path 共享 ToolRuntime policy core；边界角色和一致 envelope 已有测试 | `docs/plans/archive/2026-06-04-phase3-unified-tool-mcp-boundary-closeout-plan.md` |
| ToolRuntime hardening | `retry_policy` 已真实生效；output schema 已补全并支持 `MCP_OUTPUT_SCHEMA_ENFORCE` | `docs/plans/archive/2026-06-04-phase3.5-toolruntime-hardening-plan.md` |
| Planning / workflow execution | `WorkflowEngine` 已支持 trace 绑定、approval audit、tool-based delegation、多步入口选择、step context 裁剪、断点续跑 | `docs/plans/archive/2026-06-04-phase4-planning-task-execution-plan.md` |

## 后续真实提升项

### 1. Context and Memory Architecture

**为什么还没完成**：Phase 2 明确把 `context_policy` 延后；Phase 4 只做了 workflow step 间的残留裁剪，没有建立完整的 agent context/memory 分层。

**当前推进状态**：已于 2026-06-08 将 Phase 1-5 拆成四份按依赖顺序执行的 active 详细计划：

1. [Phase 1-2: MemoryContext / Policy](2026-06-08-agent-memory-context-governance-phase1-2-plan.md)
2. [Phase 3: Budget / Filter / Audit](2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md)
3. [Phase 4: Governed Lifecycle](2026-06-08-governed-memory-lifecycle-phase4-plan.md)
4. [Phase 5: Eval Replay Snapshot](2026-06-08-eval-memory-replay-snapshot-phase5-plan.md)

执行顺序不可互换：Phase 3 消费 Phase 1-2 的结构化上下文；Phase 4 依赖 Phase 3 的审计；Phase 5 依赖 Phase 3 的稳定 snapshot hash 和 Phase 4 的 governed active memory。

**真实需求**：

- 区分 user-visible conversation、agent scratch、tool residue、handoff summary、long-term memory。
- 让 handoff 和 workflow step 只携带结构化摘要，不把工具残留无差别带给下游。
- 为 compaction 建立 trace event，记录压缩前后保留、丢弃、摘要的内容边界。
- memory service 注入必须按 agent 目标和定义过滤，不能把所有 agent 共享同一份无差别记忆。
- eval/replay 需要保存必要上下文快照，避免回放依赖临时内存。

**建议验收**：

- agent run 的上下文大小有上限策略，长对话不因历史无限增长失控。
- handoff payload 和 workflow step context 可审计、短摘要、字段化。
- 任一 eval case 能记录并复原关键输入快照。
- registry 可以查询 agent 的 context 注入策略，但不引入无人消费的 dead field。

**触发条件**：出现上下文膨胀、handoff 摘要质量不稳定、memory 注入污染不同 agent、或 eval 无法复原关键输入时再启动。

### 2. EvalOps and Replay Quality Gate

**为什么还没完成**：项目已有 `evals/`、dataset 分层、report、CI harness 基础，但 eval 还不是 prompt/model/tool/runtime 变更的强质量门禁。

**真实需求**：

- eval dataset 分层固化为 `golden`、`regression`、`production_failure`、`security`、`hidden` 的使用规范。
- eval run 绑定 trace、agent version、model tier、prompt/version、tool catalog version、runtime version。
- CI 区分 fast eval 与 full eval：普通改动跑 fast，大改动或发布前跑 full。
- 线上失败可以从 trace 生成 production failure case，再沉淀为 regression case。
- eval report 能展示改动前后 diff，并定位到 agent、tool、trace span、输出 schema。

**建议验收**：

- prompt/model/tool/runtime 改动有可比较 eval diff。
- production failure case 可以通过命令回放。
- regression case 能阻止已修复问题再次出现。
- GitHub Actions 或本地 CI 有明确的 fast/full eval 入口。

**触发条件**：准备频繁改 prompt/model/tool catalog，或需要把线上失败纳入回归保护时启动。

### 3. Streaming Workflow Kernel Convergence

**为什么还没完成**：Phase 4 选择了正确的阶段边界：单轮流式对话和轮内 handoff 仍走 streaming agent path，显式多步任务才进入 `WorkflowEngine`。这是为了避免牺牲 token 流 UX 或过早建设 streaming workflow。

**真实需求**：

- `WorkflowEngine` 支持 token 级事件流和增量持久化。
- 轮内 handoff 可以像 workflow step 一样拥有 trace、approval、resume 语义。
- runner / harness / SSE 不再维护并行编排循环。

**建议验收**：

- streaming step 可以逐 token 产出事件，且可关联 workflow_run_id、step_index、trace_id。
- 流式 handoff 能进入统一 engine，不降低现有 SSE 延迟体验。
- 失败、中断、恢复语义不比现有 stream path 差。

**触发条件**：真实需求要求对轮内 handoff 做审批、恢复、统一 trace 关联或跨入口一致审计时启动。没有这些需求时不要做。

### 4. Workflow Replay, Idempotency, and Operational Safety

**为什么还没完成**：Phase 4 已支持从最近完成 step 之后继续执行，但任意 step replay 被明确延后，因为它依赖 step 幂等、写工具去重和配额策略。

**真实需求**：

- 定义 workflow step 的 idempotency key、输入快照、输出快照和 replay 边界。
- 写工具支持幂等键或 dedup，避免 replay 重复写入。
- 任意 step replay 与 approval 记录、tool audit、trace 关系一致。
- recovery 继续保持安全取向：自动恢复不能绕过审批或重复高风险写操作。

**建议验收**：

- replay 一个已完成 step 不会重复产生不可逆副作用。
- 高风险 tool replay 必须重新走 human gate 或命中幂等去重。
- replay 结果能和原 trace/eval run 做 diff。

**触发条件**：需要做任意 step 回放、失败定位、发布前 replay 验证，或 workflow 开始包含更多写操作时启动。

### 5. ToolRuntime Operational Guardrails

**为什么还没完成**：Phase 3.5 只做了 boundary-internal 且低风险的 hardening。per-tool/per-user 配额、写工具幂等、per-tool 熔断、live HTTP E2E 都被明确延后。

**真实需求**：

- per-tool / per-user quota：Redis-backed 计数、窗口策略、错误 envelope 和 audit。
- per-tool circuit breaker：连续失败时短路，保护下游服务。
- write-tool idempotency：与 approval/replay 语义对齐。
- live streamable-http integration test：启动真实 MCP transport，验证 token、caller resolution、ToolRuntime policy core 和 envelope。
- multi-tenant isolation 只在出现真实多租户要求时再做；当前没有消费者，不提前建设。

**建议验收**：

- quota/circuit breaker 命中时返回稳定 MCP error code，并写入 audit。
- live HTTP E2E 能覆盖至少一个 allow 和一个 deny。
- 写工具重复请求不会产生重复副作用。

**触发条件**：出现真实并发/滥用/发布门禁/多租户需求，或新增第二个以上高风险写工具时启动。

## 建议推进顺序

1. **Context and Memory Architecture**：先治理上下文边界，避免后续 eval/replay 记录的是污染输入。
2. **EvalOps and Replay Quality Gate**：在上下文快照稳定后，把 trace/eval/report/CI 连成质量闭环。
3. **Workflow Replay + ToolRuntime Guardrails**：当 replay 从“诊断能力”升级为“可执行能力”时，同步做幂等、配额和写安全。
4. **Streaming Workflow Kernel Convergence**：只在轮内 handoff 真的需要审批、恢复或统一审计时做，避免为了架构纯度牺牲流式体验。

## 文档归类

| 类别 | 文档 | 处理 |
|---|---|---|
| 当前 active 总入口 | `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md` | 作为 agent platform 后续提升的路线级入口 |
| 当前 active 子计划 | `docs/plans/active/2026-06-08-agent-memory-context-governance-phase1-2-plan.md` | 执行结构化 `MemoryContext` 和 agent-specific policy |
| 当前 active 子计划 | `docs/plans/active/2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md` | 执行预算、过滤、稳定 hash 和 trace audit |
| 当前 active 子计划 | `docs/plans/active/2026-06-08-governed-memory-lifecycle-phase4-plan.md` | 执行 governed item lifecycle、candidate、forget/suppress |
| 当前 active 子计划 | `docs/plans/active/2026-06-08-eval-memory-replay-snapshot-phase5-plan.md` | 执行 snapshot、eval replay、memory drift 和 CI controls |
| 已完成总路线 | `docs/plans/archive/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md` | 归档为路线基线，不再承载待办 |
| 已完成执行方案 | Phase 1、Phase 2、Phase 3、Phase 3.5、Phase 4 执行方案 | 归档为实现记录和验收证据 |
| 其他已完成基础设施方案 | `docs/plans/archive/2026-06-04-dual-orm-single-schema-source-plan.md` | 与 agent platform 分组隔离，归入数据库/schema 基础设施 |

## 非目标

- 不重开 Phase 1-4 的实现工作。
- 不把已完成执行方案继续留在 `active/`。
- 不建设没有真实消费者的 `context_policy`、multi-tenant guard 或 streaming workflow。
- 不把本文件写成逐行代码执行清单；等某一项被真实触发后，再为该项单独写可执行 plan。
