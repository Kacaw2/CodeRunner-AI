# 2026-06-07 · CodeRunner-AI 架构 03｜数据、状态与记忆

> 文档编号 03 ｜ 最后更新 2026-06-07 ｜ 范围: 数据模型、会话与业务状态、短期/中期/长期记忆、RAG 状态、缓存限流降级

本章按当前代码状态说明 CodeRunner-AI 如何保存业务数据、对话上下文、Agent 运行状态和记忆。这里描述的是**现状**；仍待演进的治理项见 [Agent Platform Remaining Improvements Plan](../plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md) 与 [memory-module-comparison](../research/2026-06-03-memory-module-comparison.md)。

系统数据按生命周期和权威性分为五类：

| 分类 | 含义 | 当前存储 | 典型对象 |
|---|---|---|---|
| **短期状态** | 单次请求、当前消息窗口、可重连 SSE 缓冲 | 运行时内存 + Redis | `AgentSession.messages`、`chat_task:*:buffer`、`workflow:*:buffer` |
| **中期记忆** | 跨当前对话可复用的自然语言摘要 | MySQL | `AIConversation.summary` |
| **长期记忆** | 受治理的 item 级长期记忆，prompt 注入的权威源 | MySQL | `memory_items`（active/candidate/...） |
| **长期画像（兼容物化视图）** | 学生学习档案、教师偏好、班级薄弱点 | MySQL | `StudentProfile`、`TeacherPreference` |
| **业务数据** | 平台权威事实 | MySQL | 用户、班级、Problem、Question variant、测例、提交、测验、草稿 |
| **运行数据** | Agent / workflow / eval 的可观测与审计记录 | MySQL | `agent_trace_*`、`workflow_*`、`eval_*`、MCP audit/approval |

存储分工：

- **MySQL**：业务数据、中长期记忆、workflow/trace/eval/MCP 审计。
- **Redis**：AI 限流、MCP rate limit、短期 SSE 缓冲和任务状态；不可用时多数路径 fail-open 或返回空缓冲。
- **ChromaDB**：RAG 向量库，包含 `questions`、`knowledge_points`、`error_patterns` 三个 collection；详见 [tools-mcp-rag.md](tools-mcp-rag.md)。

---

## 4.1 数据模型与迁移状态

### 单一 SQLAlchemy 2.0 Domain（双层 ORM 已收敛）

项目已收敛到唯一的 mapped-class registry：`domain/base.py:DomainBase(DeclarativeBase)` 承载唯一 registry 和 metadata，Flask-SQLAlchemy 通过 `SQLAlchemy(model_class=DomainBase)` 复用同一 registry。每张表只有一个 mapped class。

| 关注点 | 当前形态 |
|---|---|
| 唯一基类 | `domain/base.py:DomainBase` |
| mapped classes | `domain/models/*`（user、chat、workflow、observability、mcp），不 import Flask/FastAPI |
| sync/async 访问 | `domain/repositories/*` 提供 Sync/Async repository；`core/db/session.py`（sync）与 `core/db/async_session.py`（async）各自建 engine |
| Flask adapter | `app/core/extensions.py` 用 `SQLAlchemy(model_class=DomainBase)`；`app/models/__init__.py` 直接从 `domain.models` 导入已迁移模型 |

最终形态是 **“shared Domain + process-local sessions”**：统一的是模型、metadata、事务接口和 schema 契约，而**不是**跨进程共享连接池，也**不是**让所有进程共享 Flask context。Flask、FastAPI Agent Runtime、MCP Gateway、Eval CLI 各自拥有进程内 engine/session，但导入同一组 mapped class。

P1 迁移基线（早先已关闭）保持有效：

- `migrations/versions/e21895a59f7d_baseline_full_schema.py` 是完整 schema baseline，`down_revision = None`。
- `migrations/env.py` 通过 `core/db/metadata.py:build_target_metadata()`（现直接返回 `DomainBase.metadata`）暴露目标 metadata。
- `app/__init__.py:_ensure_tables()` 只检查必要表并提示 `flask db upgrade head`，不再调用 `db.create_all()` 作为生产兜底。
- `tests/test_migration_full_schema.py` 与 `tests/test_single_domain_registry.py` 守住“单 registry + 空库可 `upgrade head`”。

收敛路线见 [shared-domain plan](../plans/archive/2026-06-06-shared-sqlalchemy-domain-fastapi-agent-runtime-plan.md) 与已关闭的 [dual-orm-database-issues](../issues/2026-06-04-dual-orm-database-issues.md)。

### 核心实体关系

```text
users
  ├─ classrooms ─ enrollments ─ users(student)
  ├─ ai_conversations ─ ai_messages
  │                    └─ chat_tasks
  ├─ student_profiles
  ├─ teacher_preferences
  ├─ submissions ─ questions(language variant) ─ problems
  │               └─ test_results ─ test_cases(problem-level)
  ├─ quiz_attempts ─ quizzes ─ quiz_problems ─ problems
  └─ generated_question_drafts

workflow_runs ─ workflow_steps
              └─ workflow_approvals

agent_trace_runs
  ├─ agent_trace_spans
  ├─ agent_trace_events
  ├─ agent_trace_artifacts
  └─ agent_trace_links

eval_runs ─ eval_case_runs ─ eval_case_grader_results
```

当前公开题目单位已经是 **Problem**，`Question` 是语言维度的可执行 variant；提交仍保存 `question_id`，API 响应同时返回 `problem_id`、`question_id` 和 `language`，用于兼顾用户可见题目与执行/历史追踪。

---

## 4.2 用户、会话与业务状态

### User 与角色

`domain/models/user.py` 定义三类角色：

```python
class UserRole(Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
```

角色同时影响 Web/API 权限、Agent 路由、MCP tool RBAC、teacher-only 写工具审批等边界。认证、权限与可靠性见 [security-permissions-reliability.md](security-permissions-reliability.md)。

### Web session 与 API token

`session` 在本章中只表示身份会话，不承载 AI 对话历史：

| 客户端 | 身份机制 | 对话状态来源 |
|---|---|---|
| Web 页面 | Flask-Login session cookie | `ai_conversations`、`ai_messages`、Redis SSE buffer |
| API / 移动端 | JWT bearer 或 `auth_token` cookie | 同上 |
| MCP 外部 client | API key / signed internal token | MCP caller context + audit logs |

### Problem / Question / Submission

当前数据边界：

- `Problem` 是 dashboard、quiz、problem runner 展示的父题目，包含标题、描述、难度、分值、创建者。
- `Question` 是 `Problem` 下的语言 variant，保存 `programming_language`、`starter_code`、`solution`、`solution_explanation`。
- `TestCase` 绑定 `problem_id`，是 problem-level 测例，被所有语言 variant 共享。
- `Submission` 绑定 `question_id`，因为提交执行必须落到具体语言 variant；服务层会通过 `question.problem_id` 回填用户可见题目。

`SubmissionService.submit_problem_code()` 先按语言选择 variant，再进入 `submit_code()` 创建提交、运行测例、写入 `TestResult`，最后异步触发学生画像更新。

---

## 4.3 对话、异步任务与短期状态

### AIConversation / AIMessage

`domain/models/chat.py`：

```python
class AIConversation(DomainBase):
    id, user_id, agent_type, context_type, context_id,
    title, summary, created_at, updated_at

class AIMessage(DomainBase):
    id, conversation_id, role, content, tool_calls,
    tokens_used, created_at
```

- `AIMessage` 是持久化后的对话消息，不等同于本次 LLM 调用的完整上下文窗口。
- `AIConversation.summary` 是中期记忆，由 `MemoryService.generate_conversation_summary()` 在消息数达到阈值后异步生成。
- 当前 summary 生成触发点主要在 `app/api/v1/ai.py`（同步路径）和 `ai/agent_runtime/services/chat_runner.py`（remote 异步路径），阈值为消息数 `>= 10` 且当前 conversation 还没有 summary。

### ChatTask 与 Redis SSE buffer

异步聊天使用 `ChatTask` 持久化任务生命周期：

```text
pending -> processing -> completed | failed
```

DB 中保存权威结果字段，例如 `status`、`routed_agent`、`result_message_id`、`error_detail`。Redis 只保存可丢弃的实时状态与 SSE buffer：

```text
chat_task:{task_id}:status
chat_task:{task_id}:buffer
chat_task:{task_id}:agent
workflow:{run_id}:status
workflow:{run_id}:buffer
```

`TASK_BUFFER_TTL` 默认 3600 秒。Redis 不可用时，buffer 读写返回空或 `None`，主流程不因此中断；这意味着 Redis 不是权威状态源。

---

## 4.4 Agent Runtime 与 Workflow 状态

### AgentSession 是单次运行的内存载体

当前 Agent 不再只依赖松散的 raw state dict。`ai/agents/session.py:AgentSession` 是单次 Agent run 的内存载体：

| 字段 | 含义 |
|---|---|
| `agent_name`、`user_id`、`user_role` | 当前运行身份 |
| `messages` | 本次 LLM 调用可见消息窗口 |
| `context` | 页面/业务上下文，如 `conversation_id`、`question_id`、`workflow_run_id` |
| `trace_id`、`trace` | 运行 trace 绑定 |
| `definition`、`budget` | 来自 `core/definitions.py` 的 agent 定义和预算配置 |
| `extra_state` | handoff 等历史状态的兼容承载 |

`AgentRuntime` 负责同步和流式 loop：获取 trace、绑定工具 schema、压缩消息、调用 LLM、执行工具、记录 token/latency/artifact，并在结束时 finalize trace。`LLMRunner.compact_window()` 通过 `MemoryService.compact_window()` 运行 token-budget 触发的短期消息压缩；`compact()` 作为兼容 shim 保留。

### Tool-based handoff

handoff 当前是结构化工具调用，不是自由文本 marker：

```text
LLM -> coderunner.agent.delegate
    -> ToolCallExecutor
    -> MCP client/gateway/ToolRuntime
    -> mcp_gateway.bootstrap delegate handler
    -> graph.handoff.validate_handoff_target()
    -> handoff_to / handoff_reason / handoff_summary
```

关键边界：

- `core/definitions.py` 为每个 Agent 声明 `handoff_targets`。
- `coderunner.agent.delegate` 是 `internal_only=True`，外部 API key client 不能直接调用。
- delegate handler 使用 caller identity 中的 source agent 和 role 做校验，不信任 LLM 参数自报身份。
- `ai/graph/handoff.py` 将下一位 Agent 的消息重建为“原始用户请求 + 上一 Agent 摘要”，`HANDOFF_SUMMARY_LIMIT = 1500`，`MAX_HANDOFFS = 2`。

这已经比早期 marker-based handoff 更可审计，但仍未形成完整的 context/memory policy：handoff summary、tool residue、长期记忆注入和 eval replay snapshot 还没有统一治理。

### WorkflowRun / WorkflowStep / WorkflowApproval

显式多步任务进入 `WorkflowEngine`，而普通单轮流式对话和 bounded handoff 继续留在 streaming agent path。这个边界在 `ai/graph/supervisor.py` 中按任务形态判断。

`domain/models/workflow.py` 当前包含：

| 模型 | 职责 |
|---|---|
| `WorkflowRun` | 目标、计划、状态、当前 step、结果、token/latency 汇总 |
| `WorkflowStep` | step 类型、agent/tool 指令、依赖、审批要求、input/output、trace_id、attempt |
| `WorkflowApproval` | human gate 的不可变审批审计记录 |

Workflow 状态支持：

```text
planning -> executing -> validating -> completed | failed | cancelled
executing -> waiting_approval -> executing | cancelled
```

`WorkflowEngine.select_step_outputs()` 已经避免把所有上游 step residue 无差别传给下游：声明了 `depends_on` 的 step 才拿完整上游输出；未声明依赖的 step 只拿截断摘要。这是上下文治理的一部分，但不是完整 memory architecture。

当前恢复语义是“从最后完成 step 之后继续”，不是任意 step replay。任意 step replay 仍需要幂等键、写工具去重、approval/replay 关系等基础设施。

### Trace / Eval 运行数据

`domain/models/observability.py` 是 shared-Domain trace/eval 映射（sync 走 `domain/repositories/traces.py`、`evals.py`，FastAPI Runtime 走对应 async repository），主要表：

| 表 | 粒度 |
|---|---|
| `agent_trace_runs` | 一次 Agent run，含 `trace_id`、source、agent、conversation/task/workflow/eval 关联、token、cost、latency |
| `agent_trace_spans` | LLM/tool/MCP/sandbox 等子操作 |
| `agent_trace_events` | 细粒度事件 |
| `agent_trace_artifacts` | 代码执行结果、生成题等中间产物 |
| `agent_trace_links` | trace 到业务表的逻辑关联 |
| `eval_runs / eval_case_runs / eval_case_grader_results` | Eval 执行与 grader 结果 |

Trace 当前已经能绑定 workflow step 和 MCP tool audit，但 EvalOps/replay 还没有成为所有 prompt/model/tool/runtime 改动的强质量门禁。

---

## 4.5 Memory 机制

当前记忆分三层注入 system prompt：

```text
短期：MemoryService.compact_window() / compact_messages() (compat shim)
中期：AIConversation.summary
长期：memory_items (active 治理项)  ← 权威注入源
        └ fallback: StudentProfile / TeacherPreference (仅在 subject 无任何治理项时)
        |
        v
MemoryService.get_memory_context()
        |
        v
各 Agent _build_system_context()
```

### 短期：消息压缩

Short-term message compaction is implemented in `ai/memory/compaction.py` (`compact_window`) and wired into `MemoryService.compact_window`, `LLMRunner.compact_window`, and `AgentRuntime`.

**Trigger — token budget, not message count.**
Compaction fires when the estimated token total of the current window exceeds `DEFAULT_CONTEXT_TOKEN_BUDGET` (12 000). The estimate is a character heuristic (≈ 4 chars per token) — an internal budget metric, not an exact provider tokenizer count.

**When and where it runs.**
`AgentRuntime` calls compaction at agent-loop entry (`_acquire`) and rolls it forward in-loop after each round of tool calls, for both the non-streaming `run()` loop and the streaming `stream()` loop. When the window is under budget the call is a no-op: no LLM is invoked and the message list is returned unchanged, so in-loop checks are cheap.

**Pairing-safe split.**
The kept tail is backed up so it never starts with a `ToolMessage`. This ensures every `ToolMessage` in the kept window has its parent `AIMessage(tool_calls)` present — no orphaned `tool_call_id` is sent to the provider.

**Observability.**
Each actual compaction (i.e. something was dropped) records one `compaction` trace span via `TraceCollector.trace_compaction`, capturing before/after token estimates and dropped/kept message counts. No-op compactions write no span.

**Summary and fallback.**
The LLM summary uses the FAST tier. If the summarizer raises or returns nothing, `compact_window` falls back to structured truncation. The function never raises.

`MemoryService.compact_messages(list) -> list` and `LLMRunner.compact(list) -> list` are retained as backward-compatible shims for callers that have not yet migrated to the `CompactionResult`-returning API.

### 中期：对话摘要

`MemoryService.generate_conversation_summary(conversation_id)`：

- 少于 4 条消息直接返回空。
- 取最近 10 条消息，用 FAST LLM 生成 2-3 句 tutoring conversation summary。
- `MemoryService._recent_conversation_summaries()` 取同一用户最近 3 条非空 summary，并排除当前 conversation，避免自我引用。

### 长期：学生画像与教师偏好

`StudentProfile`：

| 字段 | 当前写入状态 |
|---|---|
| `error_patterns` | `update_student_profile()` 从最近 50 次提交重建 `{WA, RE, CE, TLE, AC}` |
| `recent_questions` | `update_student_profile()` 保存最近 10 个 `question_id` |
| `recent_topics` | 字段存在，当前自动维护较弱 |
| `knowledge_map` | 会被读取用于 weak areas，但缺少稳定自动写入 |
| `current_hint_level` | 会被读取，但缺少稳定自动写入 |
| `learning_summary` | 会被读取，但缺少稳定自动写入 |
| `preferred_language` | 字段存在，默认 `python` |

`TeacherPreference`：

| 字段 | 当前来源 |
|---|---|
| `preferred_difficulty`、`preferred_language` | `learn_from_generation()` 根据生成结果/请求参数更新 |
| `preferred_topics` | `learn_from_generation()` 累积最近 topic，最多保留 20 个 |
| `style_notes` | `refresh_teacher_style_summary()` 从最近生成草稿用 LLM 总结 |
| `class_weak_areas` | `analyze_class_weak_areas()` 聚合班级学生画像 |
| `class_level` | 字段存在，默认 `intermediate` |

`get_memory_context()` 当前按角色拼接自然语言字符串：

- 学生：`learning_summary`、`error_patterns`、`knowledge_map` 中掌握度 `< 0.5` 的弱项、`current_hint_level`。
- 教师：`style_notes`、`class_weak_areas`。
- 二者都会追加 recent conversation summaries。

Phase 1-3 之前的主要缺口是治理不足：所有记忆被扁平拼接为字符串，没有按 agent 目标、来源可信度、敏感级别、强/弱上下文结构化区分，也缺少“本次运行注入了哪些记忆”的审计记录。结构化 `MemoryContext`（Phase 1-2）与确定性预算/过滤/注入审计（Phase 3）补上了这部分；item 级 candidate lifecycle 与 forget（Phase 4）已落地，见下文；剩余缺口是 eval recorded snapshot 回放（Phase 5）。

### 结构化 MemoryContext 与 Agent Policy

Phase 1-2 已落地结构化记忆契约与按 agent 的注入策略：

- `MemoryService.build_memory_context()` 返回结构化 `MemoryContext`（`ai/memory/context.py` 中的纯数据契约，不引用 ORM 实例）。
- `MemoryService.render_memory_context()` 是唯一字符串渲染入口。
- `AgentDefinition.memory_policy` 决定 profile 类型、summary 范围和 target student 权限。
- Reviewer 默认不读取长期画像或历史 summary。
- Legacy `MemoryService.get_memory_context()` API 仍供 generation pipeline 等现有调用使用，渲染文本保持兼容。

### Phase 3：预算、过滤与注入审计

Phase 3 在结构化 `MemoryContext` 上增加了确定性的选择、预算裁剪和 trace 审计：

- `ai/memory/governance.py::select_memory_context()` 是纯函数选择器：按 `priority` 降序、section 顺序、`source`、`key` 稳定排序后，依次应用 TTL（`expires_at`）、sensitivity allowlist、空值和 char/token 预算过滤，产出 `MemorySelection`（rendered 文本、每 item 的 included/filtered 决策与原因、canonical snapshot hash）。
- `MemoryPolicy.max_memory_chars` / `max_memory_tokens` 是每 agent 预算；`0`（或任意非正值）表示**禁止注入**，不是 unlimited。预算比较使用 `>`，恰好用满预算的 item 仍被包含。reviewer 的 `0/0` 因此不注入任何记忆。
- Token 计数是 **deterministic estimate**（`(len(text)+3)//4`），不是 provider tokenizer 的精确 token 数；预算裁剪绝不为此再调用 LLM。
- `MemoryService.prepare_memory_context()` 是受治理的统一入口，返回 `MemorySelection`；`get_memory_context()` 现在内部走它并只返回 `.rendered`。Agent 在创建 `AgentSession` 前完成选择，结果经 `AgentSession.memory_selection` 传到 `AgentRuntime`。
- 审计**复用现有 trace 存储**：`AgentRuntime` 取得 trace 后、首次 LLM 调用前，写入一个 `memory_context_selected` event 和一个 `memory_injection_audit` artifact（`AgentTraceEvent` / `AgentTraceArtifact`），现有 trace detail API 自动暴露，无需新 endpoint 或第二套 observability 存储。
- 审计只保存 included/filtered 决策的元数据（source/key/reason/字符与 token 计数/priority）、计数和 snapshot hash，**不保存完整 rendered memory 或原始 value**；`_redact_secrets()` 仍是最终持久化前的兜底脱敏。
- snapshot hash payload 覆盖 source/key/value/sensitivity/expires_at（不含 `reason_included`），同输入稳定、value 变化即变化，为 Phase 5 eval replay 预留可比对锚点。

eval recorded snapshot 回放（Phase 5）继续作为后续阶段，不得描述成当前能力。

### Phase 4：item 级治理生命周期（memory_items）

Phase 4 把长期记忆从不可删除的聚合 profile 字段升级为 item 级治理对象：

- `domain/models/memory.py::MemoryItemRecord`（表 `memory_items`）以 `status` 表示生命周期：`candidate → active`，以及 `rejected / superseded / suppressed / expired`。`domain/repositories/memory.py::SyncMemoryRepository` 持有全部状态转换与按 canonical value-hash 去重。
- **`memory_items` 的 active item 是 prompt 注入的治理源。** `MemoryService` 优先读取 active 治理项；只有当某 subject **完全没有任何治理项**（任意 status）时才回退到 legacy profile，因此被 suppress/superseded 的 item 不会再被 legacy fallback 重新注入。
- **`StudentProfile` / `TeacherPreference` 已降级为兼容物化视图**，不再是唯一 prompt source。`ai/memory/lifecycle.py::sync_legacy_profile_from_active_items()` 在 approve/suppress 后把当前 active item 写回 legacy 列（被治理的 key 才会写/清，未治理列不动），保证旧 profile API 仍可用。
- **Extractor 只产生 candidate，永不直接写 active。** `ai/memory/extractor.py` 的确定性 extractor 仅读取已结构化字段（生成请求参数、生成题元数据、已持久化的会话摘要），不调用 LLM、不解析自由文本、不读向量库；每个抽取值都是 `candidate`，必须经人工 approve 才进入 prompt。`promote()` 是唯一会 supersede 已有 active item 的路径。
- **forget = suppress，不是物理删除。** `DELETE /api/v1/ai/memory/<id>` 只把 status 置为 `suppressed`，审计行保留。
- 治理 API（`app/api/v1/ai_memory.py`）按 subject 严格鉴权：student 只能操作自己的 `student` item，teacher 只能操作自己的 `teacher` item，admin 全部。**course/classroom scope 当前直接拒绝（403 `memory_forbidden`）未实现的权限路径，不静默放行。**
- TTL 通过 `expires_at` 在 `active_for_subject()` 查询时惰性标记 `expired` 并排除，不进入注入。

---

## 4.6 RAG 与知识状态

`ai/knowledge/store.py` 使用 SentenceTransformer + ChromaDB：

| Collection | 写入来源 | 读取者 |
|---|---|---|
| `questions` | `index_all_problems()` 将 `Problem` 标题/描述按 chunk 写入，metadata 记录语言、难度、创建者 | `GeneratorAgent`、`search_similar_problems` |
| `knowledge_points` | `scripts/seed_knowledge.py`、教师知识库接口 | `TutorAgent`、`search_knowledge` |
| `error_patterns` | seed 脚本和教师新增错误模式 | `TutorAgent`、`search_error_patterns` |

关键配置来自 `core/config.py`：

```text
RAG_EMBED_MODEL=all-MiniLM-L6-v2
RAG_RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RAG_RERANK_ENABLED=False
RAG_CHUNK_SIZE=512
RAG_CHUNK_OVERLAP=64
RAG_CANDIDATE_K=20
RAG_FINAL_K=5
RAG_DEDUP_THRESHOLD=0.8
```

RAG 当前既被 Agent 直接消费，也通过 MCP 工具暴露给 Agent/tool path：

- `TutorAgent` 根据 error status、代码片段、topic 或最近用户消息预取知识点和错误模式。
- `GeneratorAgent` 使用相似题检索做生成参考和去重。
- `coderunner.knowledge.search*` 工具经 ToolRuntime/MCP 边界提供结构化检索。
- startup 可通过 `ENABLE_KB_STARTUP_INDEX` 触发后台索引。

RAG 搜索失败时通常返回空结果或 degraded health，而不是阻断主请求。

---

## 4.7 缓存、限流与降级

当前没有大量进程内业务缓存；短期状态和限流主要交给 Redis：

| 用途 | key / 机制 | TTL / 行为 |
|---|---|---|
| AI 请求限流 | `ai_rate:{user_id}:{agent_type}` | 60s 窗口；Redis 不可用时放行 |
| MCP gateway rate limit | `mcp_rate:{api_key_id}` | 60s 窗口；Redis 不可用时 fail-open |
| MCP internal token replay 防护 | jti claim | Redis 不可用时 fail-open |
| Chat SSE buffer | `chat_task:*` | `TASK_BUFFER_TTL` 默认 3600s |
| Workflow SSE buffer | `workflow:*` | `TASK_BUFFER_TTL` 默认 3600s |
| RAG 向量检索 | ChromaDB | 持久化或 HTTP 模式 |

降级原则：Redis 和 RAG 故障不应让核心 Web/API 请求不可用；代价是限流、实时重连、知识增强或可观测性可能暂时退化。

---

## 当前成熟度总结

| 维度 | 当前状态 | 主要缺口 |
|---|---|---|
| 业务数据 | Problem/variant/submission/quiz/classroom 主链路较完整 | 仍有历史 Question 兼容面需要持续审计 |
| Schema 迁移 | 完整 Alembic baseline 已落地；ORM 已收敛为单一 `DomainBase` registry | 跨进程仍是 process-local engine（按设计），非进程内双池 |
| 短期状态 | AgentSession、Redis SSE buffer、message compaction 已存在 | 专用 stream path 与统一 compaction/context policy 仍需收敛 |
| 中长期记忆 | summary/profile/preference 可读写；结构化 `MemoryContext` + 确定性预算/TTL/sensitivity 过滤 + trace 注入审计（Phase 1-3）；item 级 `memory_items` candidate/active/suppress 治理生命周期 + legacy profile 物化视图（Phase 4）已落地 | 画像字段自动填充不均衡；eval recorded snapshot 回放仍待 Phase 5 |
| Agent 状态 | AgentRuntime、trace、tool-based handoff、bounded context rebuild 已落地 | handoff/workflow/eval 的 context snapshot 尚未形成统一治理 |
| Workflow 状态 | 持久化 step、approval audit、resume from breakpoint 已存在 | 任意 step replay、幂等和写工具去重仍未完成 |
| RAG | ChromaDB 三 collection + Agent/MCP 消费路径存在 | 检索质量门禁和 eval replay 仍需产品化 |

---

## 相关文件速查

| 文件 | 职责 |
|---|---|
| `domain/base.py` | 唯一 `DomainBase` registry / metadata |
| `domain/models/user.py` | User / UserRole |
| `app/models/problem.py`、`app/models/question.py` | Problem 父题与 Question 语言 variant（未迁移业务模型，仍在 `app/models`） |
| `app/models/submission.py` | Submission / TestResult |
| `domain/models/chat.py` | Conversation / Message / summary / ChatTask |
| `app/models/student_profile.py` | StudentProfile / TeacherPreference（兼容物化视图） |
| `domain/models/memory.py` | `MemoryItemRecord`（`memory_items` 治理项与生命周期 status） |
| `domain/repositories/memory.py` | 治理项 candidate/active/supersede/suppress/expire 仓储与 value-hash 去重 |
| `ai/memory/lifecycle.py` | legacy profile backfill 与 active item → legacy 物化视图回写 |
| `ai/memory/extractor.py` | 确定性 candidate extractor（只产生 candidate，不写 active） |
| `app/api/v1/ai_memory.py` | 治理 API（list / approve / reject / suppress），subject 级鉴权 |
| `ai/memory/service.py` | 对话摘要、学生画像更新、memory context、消息压缩 |
| `ai/memory/governance.py` | 确定性 memory 选择、TTL/sensitivity/预算过滤、canonical snapshot hash |
| `ai/memory/preference.py` | 教师偏好、风格摘要、班级薄弱点 |
| `ai/agents/session.py`、`ai/agents/runtime.py`、`ai/agents/llm_runner.py` | Agent 单次运行状态、LLM/tool loop、压缩入口 |
| `core/definitions.py` | Agent 定义、工具白名单、handoff target、预算/限流 |
| `ai/graph/handoff.py` | tool-based handoff 校验后的上下文重建 |
| `ai/graph/engine.py` | WorkflowEngine、step 输出选择、resume |
| `domain/models/workflow.py` | WorkflowRun / WorkflowStep / WorkflowApproval |
| `domain/models/observability.py` | trace / eval shared-Domain 映射 |
| `domain/repositories/*` | Sync/Async repository（user/chat/workflow/traces/evals/mcp） |
| `ai/agent_runtime/` | FastAPI Agent Runtime（chat/workflow remote 执行） |
| `ai/knowledge/store.py` | ChromaDB RAG store |
| `ai/workers/redis_buffer.py` | Redis SSE buffer |
| `migrations/versions/e21895a59f7d_baseline_full_schema.py` | 当前完整 schema baseline |
| `core/db/metadata.py` | Alembic 合并 metadata bridge |
