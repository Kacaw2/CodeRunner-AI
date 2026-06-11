# Agent Memory / Context 改进议题

> 状态: Phase 4 Completed（Phase 5 active）
> 更新日期: 2026-06-10
> 范围: `ai/memory/`、`ai/agents/`、`core/definitions.py`、`core/observability/`、`ai/evals/`、`docs/architecture/data-state-memory.md`
> 执行计划:
> [Phase 1-2: MemoryContext / Policy](../plans/archive/2026-06-08-agent-memory-context-governance-phase1-2-plan.md) |
> [Phase 3: Budget / Filter / Audit](../plans/archive/2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md) |
> [Phase 4: Governed Lifecycle](../plans/archive/2026-06-08-governed-memory-lifecycle-phase4-plan.md) |
> [Phase 5: Eval Replay Snapshot](../plans/active/2026-06-08-eval-memory-replay-snapshot-phase5-plan.md)

## 审核结论

这项工作不应被理解为“补一个 memory 功能”。CodeRunner-AI 已经有运行时记忆: `MemoryService.get_memory_context()` 会读取 `StudentProfile`、`TeacherPreference` 和最近对话摘要, `LLMRunner.compact()` 也会压缩长消息窗口。

当前真正缺口是 **memory / context governance**:

- 记忆仍以自然语言字符串扁平拼接进 system prompt, 缺少结构化边界。
- 记忆注入主要按 `user_role` 区分, 还没有按 agent 目标、来源、可信度、敏感级别和 token budget 做策略化筛选。
- 本次 agent run 注入了哪些 memory、丢弃了哪些 memory、为什么注入, 还没有进入 trace / eval / replay 的审计面。
- Codex / Claude Code 的 AGENTS.md、skills、memories 分层可以借鉴, 但不能直接照搬为产品架构; 本项目需要面向教育平台、学生画像、教师偏好、课程知识和 agent 执行审计做本地化设计。

一句话目标: **把 memory 从“拼接到 prompt 的文本”升级为可过滤、可审计、可回放、可删除的上下文资产, 并优先服务用户能感知到的 agent 质量提升。**

## 当前事实

### 已有能力

| 层级 | 当前实现 | 说明 |
|---|---|---|
| 短期上下文 | `MemoryService.compact_messages()` / `LLMRunner.compact()` | 长对话超过阈值后压缩早期消息, 保留 system message 和最近消息窗口 |
| 中期记忆 | `AIConversation.summary` | 对话消息达到阈值后生成摘要; 后续 `get_memory_context()` 会回放最近摘要并排除当前 conversation |
| 长期画像 | `StudentProfile` | 包含错误模式、近期题目、知识掌握、提示级别、学习摘要等字段 |
| 教师偏好 | `TeacherPreference` | 包含出题风格、偏好语言/难度/topic、班级薄弱点等字段 |
| Agent 注入 | `TutorAgent`、`GeneratorAgent`、`AnalyticsAgent` | 三者当前直接调用 `MemoryService.get_memory_context()` 并拼入 system context |
| 长消息执行入口 | `AgentRuntime` | 通用 LLM/tool loop 通过 `LLMRunner.compact()` 使用消息压缩 |

需要注意: `ReviewerAgent` 当前不直接注入 `MemoryService.get_memory_context()`。如果后续要让 reviewer 读取 memory, 应先定义明确策略, 避免把学生画像或教师偏好无差别带入代码评审。

### 当前主要缺口

| 缺口 | 风险 | 证据位置 |
|---|---|---|
| 缺少 agent-specific memory policy | tutor / generator / analytics 可能共享过宽的上下文, reviewer 后续接入时也容易污染 | `ai/agents/*/agent.py`、`core/definitions.py` |
| 缺少结构化 `MemoryContext` | 无法稳定测试、过滤、审计、回放; prompt 拼接规则散落在各 agent | `ai/memory/service.py` |
| 缺少 memory 注入预算 | 长期画像、摘要、RAG、工具结果叠加后可能造成上下文膨胀 | `ai/agents/runtime.py`、`ai/agents/llm_runner.py` |
| 缺少来源与可解释性 | agent 不能说明某条记忆来自哪次对话、哪次提交、哪位教师偏好或哪条系统规则 | `ai/memory/service.py`、trace schema |
| 缺少 forget / TTL / 冲突治理 | 临时偏好、错误推断、旧课堂状态可能长期污染后续回答 | `StudentProfile`、`TeacherPreference` |
| 缺少 eval/replay snapshot | 线上失败或 eval 回放无法确认当时模型看到的 memory 是什么 | `core/observability/`、`ai/evals/` |

## 分层边界

项目应保留以下边界, 不要把所有上下文都归入 memory:

| 层级 | 存什么 | 不存什么 | 当前或目标载体 |
|---|---|---|---|
| Rules / Instructions | 必须遵守的稳定规则、权限红线、项目约束 | 用户某次临时偏好、课程资料全文 | 未来可用项目级 `AGENTS.md` 或 checked-in docs 承载 |
| Memory | 稳定偏好、学习画像、历史摘要、常见错误模式、课堂/教师风格 | 课程知识库全文、代码文档全文、完整执行轨迹 | `StudentProfile`、`TeacherPreference`、`AIConversation.summary`、未来 `MemoryContext` |
| Skills / Workflows | 可复用流程、操作步骤、评审方法 | 用户画像、课程内容 | checked-in docs / future skill surface |
| RAG / Knowledge | 课程资料、知识点、题目、错误模式语料、项目文档 | 个体用户隐私画像、一次 agent run 的工具残留 | `ai/knowledge/store.py` + Chroma |
| Trace | agent 执行过程、tool call、LLM span、memory 注入审计、artifact | 应长期作为偏好使用的规则 | `agent_trace_*`、eval/replay artifacts |
| Runtime Context | 当前任务状态、页面上下文、handoff summary、workflow step input/output | 跨用户长期记忆 | `AgentSession.context`、workflow step context |

借鉴 Codex / Claude Code 时, 重点不是复制目录结构, 而是借鉴“规则、记忆、技能、检索、执行轨迹各司其职”的分层原则。

## 目标设计方向

### 1. Agent-specific memory policy

在 `core/definitions.py` 的 `AgentDefinition` 中引入可消费的 `memory_policy`, 但前提是它必须立刻被 `MemoryService` 或 prompt assembler 使用, 不能成为 dead field。

建议策略维度:

| 策略项 | 示例 |
|---|---|
| `include_profile` | tutor 可读学生画像; generator 可读教师偏好; analytics 按角色和 target_student_id 读取 |
| `include_recent_summaries` | tutor 可读最近学习摘要; generator 只读教师相关生成摘要; reviewer 默认不读 |
| `include_rag` | tutor / generator 继续通过现有 KB 预取或工具读取; analytics 默认不直接访问 Chroma |
| `include_handoff_summary` | handoff 只读取结构化摘要, 不读取上游完整 tool residue |
| `sensitivity` | 成绩、身份、token、隐私字段默认不进入 prompt; 需要工具权限或聚合脱敏 |
| `max_memory_chars` / `max_memory_tokens` | 每个 agent 明确 memory 注入上限 |

### 2. 结构化 `MemoryContext`

把 `MemoryService.get_memory_context()` 从“直接返回字符串”演进为两步:

1. `build_memory_context(...) -> MemoryContext`
2. `render_memory_context(context, agent_name, policy) -> str`

`MemoryContext` 至少应包含:

```text
student_profile:
  learning_summary
  weak_areas
  error_patterns
  current_hint_level

teacher_preference:
  style_notes
  preferred_language
  preferred_difficulty
  class_weak_areas

recent_sessions:
  conversation_id
  agent_type
  summary
  created_at

metadata:
  source
  confidence
  sensitivity
  expires_at
  reason_included
```

这样做的收益:

- prompt 渲染可集中管理, 不再散落到每个 agent。
- trace 可以记录结构化快照, 而不是只能看到最终 prompt 文本。
- eval replay 可以复原当次 memory 输入。
- forget / TTL / conflict resolution 有明确操作对象。

### 3. Memory retriever / extractor

不建议每次用户请求都把所有 memory 塞入上下文。应拆成两个方向:

- **Retriever**: 本次 agent run 前, 根据 agent、角色、任务、上下文、预算筛选 memory。
- **Extractor**: agent run 后或后台任务中, 从对话、提交、生成题、教师修改记录中提取可保存的 memory candidate。

Extractor 保存前必须经过:

- 权限隔离: student / teacher / classroom / course 边界清晰。
- 来源记录: 每条 memory 能追溯到 conversation、submission、draft、manual edit 或 system event。
- 敏感信息过滤: 密码、token、个人隐私、健康、身份信息默认不保存; 成绩类信息默认聚合或脱敏。
- 冲突检测: 新旧 memory 矛盾时进入 pending / superseded 状态, 不静默覆盖。
- TTL: 临时偏好、当前任务状态、短期课堂安排需要过期。
- 用户可删除: 支持 forget / delete / suppress。

### 4. Trace audit + eval replay

每次 agent run 应记录 memory 注入审计:

| 字段 | 说明 |
|---|---|
| `agent_name` / `trace_id` | 哪个 agent 在哪次运行使用 |
| `memory_item_id` 或 source key | 哪条 memory 被使用 |
| `reason_included` | 因为什么策略或任务上下文被注入 |
| `rendered_chars` / estimated tokens | 注入成本 |
| `filtered_items` | 因预算、权限、敏感级别、TTL 被过滤的数量和原因 |
| `snapshot_hash` | eval/replay 对齐使用 |

Eval case 应能选择:

- 使用记录下来的 memory snapshot 回放。
- 使用当前最新 memory 回放。
- 对比两者差异, 判断问题来自 prompt/model/tool 改动, 还是 memory 输入漂移。

## 用户可感知收益

优先验收不应只看“字段是否更多”, 而应看用户是否明显感到 agent 更懂上下文:

| 用户体验目标 | 可观察行为 |
|---|---|
| Tutor 少重复 | 学生反复犯同类错误时, tutor 能基于历史弱点给出更短、更贴切的提示 |
| Tutor 不越界 | 不因为历史画像直接给答案, 仍遵守渐进提示和当前题目上下文 |
| Generator 更贴合教师 | 出题语言、难度、风格、班级薄弱点更稳定, 但不会复制历史题 |
| Analytics 更可信 | 明确区分当前学生、目标学生、班级聚合, 不串用户 memory |
| Handoff 更干净 | 下游 agent 只看到必要摘要, 不看到上游工具残留和无关推理过程 |
| 回归更可查 | 失败案例能复原当时 memory 输入, 不靠猜测排查 |

## 建议推进阶段

### Phase 1: MemoryContext 与渲染边界

目标: 先把现有字符串上下文结构化, 外部行为尽量不变。

- 新增 `MemoryContext` / `MemoryItem` 数据结构。
- 保留现有 `get_memory_context()` 兼容接口, 内部改为 build + render。
- 补测试: 学生画像、教师偏好、recent summaries、当前 conversation 排除、空表降级。
- 验收: 三个已接入 memory 的 agent 输出 system context 内容不回退。

### Phase 2: Agent memory policy

目标: 让 agent definition 真正决定 memory 注入范围。

- 在 `AgentDefinition` 中增加被真实消费的 `memory_policy`。
- 为 tutor / generator / analytics / reviewer 定义默认策略。
- Reviewer 默认不读长期画像, 除非后续有明确代码评审需求。
- 验收: 不同 agent 的 memory 注入结果可单测断言; 角色不允许的 memory 不会进入 prompt。

### Phase 3: Budget、过滤与审计

详细执行计划：[Agent Memory Budget, Filtering, and Audit Phase 3 Plan](../plans/archive/2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md)

目标: 控制上下文膨胀, 并让 memory 注入进入 trace。

- 为每个 agent 设置 memory 字符/token 预算。
- 记录 included / filtered / dropped memory 的 trace event 或 artifact。
- 对敏感字段、TTL、跨用户数据做过滤。
- 验收: 超预算时优先保留当前任务相关 memory; trace 能看到注入摘要和过滤原因。

### Phase 4: Extractor、forget 与冲突治理

详细执行计划：[Governed Memory Lifecycle Phase 4 Plan](../plans/active/2026-06-08-governed-memory-lifecycle-phase4-plan.md)

目标: 让 memory 写入变得可控。

- 后台 memory extractor 只产生 candidate, 不直接无条件覆盖长期画像。
- 支持用户或教师删除/抑制特定 memory。
- 支持 TTL 和 superseded 状态。
- 验收: 冲突 memory 不静默覆盖; forget 后不会再次注入。

### Phase 5: Eval replay snapshot

详细执行计划：[Eval Memory Replay Snapshot Phase 5 Plan](../plans/active/2026-06-08-eval-memory-replay-snapshot-phase5-plan.md)

目标: 把 memory 纳入质量门禁。

- eval case 记录 memory snapshot hash / rendered memory。
- production failure 可沉淀为 regression case。
- 支持 current memory 与 recorded snapshot 两种回放模式。
- 验收: 同一 eval case 能复原当时上下文, 并能解释和当前 memory 的差异。

## 非目标

- 不把 Codex / Claude Code memory 目录结构照搬到产品中。
- 不把课程资料、项目文档、代码知识全文存进用户 memory; 这些属于 RAG。
- 不把 trace 当长期记忆使用; trace 是审计和 replay 证据。
- 不提前建设没有消费者的多租户 memory 平台。
- 不在没有策略和审计前让 reviewer 无差别读取学生/教师 memory。
- 不为了“架构完整”重开已经完成的 Agent runtime kernel、ToolRuntime boundary 或 WorkflowEngine Phase 1-4 工作。

## 建议下一步

Phase 1-5 已分别形成 active 详细执行计划。实施时必须严格按依赖顺序推进：

1. Phase 1-2 先建立结构化 `MemoryContext` 和真实被消费的 agent policy。
2. Phase 3 再加入预算、TTL/sensitivity 过滤和 trace audit。
3. Phase 4 在审计能力稳定后引入持久化 item lifecycle、candidate extractor 和 forget/suppress。
4. Phase 5 最后把稳定 snapshot 接入 eval dataset、replay、report 和 CI。

每一阶段完成后单独归档对应计划并回写本 issue；不得为了并行推进而让 Phase 4/5 绕过前置契约。

## 实施结果（Phase 1-2，2026-06-08）

本次只关闭“缺少结构化 `MemoryContext`”和“缺少 agent-specific memory policy”两项缺口；其余 Phase 3-5 缺口仍未实现。

### 完成证据

- 新增 `ai/memory/context.py`：纯数据契约 `MemorySensitivity`、`MemoryMetadata`、`MemoryItem`、`RecentSessionMemory`、`MemoryContext`，不引用 ORM 实例。
- `MemoryService` 拆分为 `build_memory_context()`（结构化）+ `render_memory_context()`（唯一字符串渲染入口），并保留 legacy `get_memory_context()` 兼容接口。
- `core/definitions.py` 引入被真实消费的 `MemoryPolicy` / `MemoryProfileKind`，为 tutor / generator / analytics / reviewer 声明默认策略。
- tutor / generator / analytics 改为按 definition policy 注入；reviewer 保持无长期 memory；analytics 实现 target student 隔离（学生只读自己，教师/admin 可读目标学生 profile 但不读其 summary）。
- `domain/statements/chat.py` 与 `domain/repositories/chat.py` 的 recent summary 查询增加可选 `agent_types` 过滤。
- generation pipeline 仍接收字符串 teacher context，兼容性已加测试守护。

### 测试命令与结果

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py tests/test_domain_chat_repository.py tests/test_definitions_consistency.py tests/test_model_router_and_definitions.py tests/test_agent_features.py -q
```

结果：`129 passed, 2 warnings`（仅 SQLAlchemy 1.x `Query.get()` legacy 警告，与本次改造无关）。

### 仍未实现（后续阶段）

- Phase 3：budget、sensitivity/TTL 过滤、trace 注入审计、稳定 snapshot hash。
- Phase 4：item 级 candidate/active/superseded/suppressed/expired 生命周期、extractor、forget/suppress。
- Phase 5：版本化 memory snapshot、eval replay、memory drift 报告。

## 实施结果（Phase 3，2026-06-08）

Phase 3 Completed: budget/filter/audit 已完成；Phase 4-5 仍 active。本次关闭“记忆注入缺少确定性预算/过滤”和“缺少注入审计”两项缺口。

### 完成证据

- 新增 `ai/memory/governance.py`：纯函数 `select_memory_context()`，按 `priority`→section→`source`→`key` 稳定排序后应用 TTL（`expires_at`）、sensitivity allowlist、空值、char/token 预算过滤，产出 `MemorySelection`（rendered、每 item 决策与原因、canonical snapshot hash）。
- `MemoryMetadata.priority` 与 `MemoryPolicy.max_memory_chars` / `max_memory_tokens` 落地；预算 `0`（或非正值）表示禁止注入而非 unlimited，比较使用 `>` 使恰好用满预算的 item 仍被包含。reviewer 的 `0/0` 不注入任何记忆。
- token 计数是 deterministic estimate（`(len+3)//4`），预算裁剪不再调用 LLM。
- `MemoryService.prepare_memory_context()` 成为受治理统一入口；`get_memory_context()` 内部走它只返回 `.rendered`；selection 经 `AgentSession.memory_selection` 传到 `AgentRuntime`。
- 审计复用现有 trace 存储：`AgentRuntime` 在首次 LLM 调用前写入 `memory_context_selected` event 与 `memory_injection_audit` artifact（`AgentTraceEvent` / `AgentTraceArtifact`），现有 trace detail API 自动暴露，无新 endpoint、无 schema migration。
- 审计只保存决策元数据、计数和 snapshot hash，不保存完整 rendered memory 或原始 value；`_redact_secrets()` 仍是最终脱敏兜底。
- 移除 Phase 1-2 遗留的死代码 `MemoryService._policy_options`（已被 `prepare_memory_context` 取代）。

### 测试命令与结果

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_memory_governance.py tests/test_memory_trace_audit.py tests/test_agents.py tests/test_agent_session.py tests/test_agent_runtime_kernel.py tests/test_trace_store_runtime_neutral.py tests/test_trace_api_complete.py tests/test_definitions_consistency.py -q
```

结果：`94 passed, 2 warnings`（仅 SQLAlchemy 1.x `Query.get()` legacy 警告，与本次改造无关）。

### 仍未实现（Phase 4-5）

- Phase 4：item 级 candidate/active/superseded/suppressed/expired 生命周期、extractor、forget/suppress。
- Phase 5：版本化 memory snapshot、eval replay、memory drift 报告。

## 实施结果（Phase 4，2026-06-10）

Phase 4 Completed: item 级治理生命周期、candidate extractor、forget/suppress 与 legacy profile 物化视图已完成；Phase 5 仍 active。本次关闭“缺少 forget / TTL / 冲突治理”缺口的写入侧治理部分。

### 完成证据

- 新增 `domain/models/memory.py::MemoryItemRecord`（表 `memory_items`），`status` 表示 `candidate / active / rejected / superseded / suppressed / expired`；migration `e3f4a5b6c7d8_add_memory_items` 与 metadata 双覆盖，schema gate 测试守护。
- 新增 `domain/repositories/memory.py::SyncMemoryRepository`，持有全部状态转换与 canonical value-hash 去重；`promote()` 是唯一会 supersede 已有 active item 的路径，duplicate value 被 reject 而非创建第二条 active；`active_for_subject()` 查询时惰性标记并排除 `expired`。
- 新增 `ai/memory/extractor.py`：确定性 candidate extractor，仅读已结构化字段（生成参数、生成题元数据、已持久化会话摘要），不调 LLM、不读向量库，只产生 candidate。
- `MemoryService` 读路径优先 active 治理项；仅当 subject 完全无任何治理项时才回退 legacy profile，suppressed/superseded item 不会被 fallback 重新注入。
- 新增 `app/api/v1/ai_memory.py` 治理 API（list / approve / reject / suppress=DELETE），subject 级严格鉴权（student/teacher 仅限本人 subject，admin 全部），未实现的 course/classroom scope 直接 403 `memory_forbidden` 不静默放行；forget = suppress 仅置状态，审计行保留。
- `ai/memory/lifecycle.py::sync_legacy_profile_from_active_items()` 在 approve/suppress 后把 active item 物化回 `StudentProfile` / `TeacherPreference`，旧 profile API 保持兼容。

### 测试命令与结果

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_domain_memory_repository.py tests/test_memory_lifecycle.py tests/test_memory_api.py tests/test_agents.py tests/test_api_ai.py tests/test_migration_full_schema.py tests/test_trace_schema_contract.py -q
```

结果：`115 passed`（另有 SQLAlchemy 1.x `Query.get()` 与 Flask-Migrate `get_engine` legacy 警告，与本次改造无关）。

### 仍未实现（Phase 5）

- Phase 5：版本化 memory snapshot、eval replay、memory drift 报告。
