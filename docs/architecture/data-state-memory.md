# 数据与状态：Database、Session、Memory

> 最后更新: 2026-06-03

本章描述 CodeRunner 如何保存数据、上下文与用户状态。系统的数据按**生命周期与信任级别**分为四类，贯穿全章：

| 分类 | 含义 | 存储 | 典型对象 |
|---|---|---|---|
| **短期状态** | 当前对话上下文，会话结束即可丢弃 | 运行时消息列表 + Redis buffer | 消息窗口、SSE 事件流 |
| **长期记忆** | 学习偏好、历史薄弱点、教师设置 | MySQL（profile 表） | `StudentProfile`、`TeacherPreference`、`AIConversation.summary` |
| **业务数据** | 平台核心实体，权威事实 | MySQL | 用户、班级、题目、作业、提交、成绩 |
| **运行数据** | 每次执行的可观测记录 | MySQL（运行时中立模型） | `agent_trace_runs / spans / events`、eval 记录 |

存储分工：**MySQL**（业务 + 长期记忆 + 运行数据）、**Redis**（短期状态 + 限流 + SSE 缓冲）、**ChromaDB**（RAG 向量库，见 [tools-mcp-rag.md](tools-mcp-rag.md)）。

> 记忆模块的成熟度对标分析见 [memory-module-comparison](2026-06-03-memory-module-comparison.md)。本章描述"现状如何"，该文档讨论"应演进到何处"。

---

## 4.1 数据模型设计

### 双层 ORM

项目刻意采用**两套模型**，对应两种运行上下文：

| 层 | 目录 | ORM | 适用场景 |
|---|---|---|---|
| 业务模型 | `app/models/` | Flask-SQLAlchemy（`db.Model`） | 主应用、HTTP 请求上下文 |
| 运行时中立模型 | `core/db/models/` | 纯 SQLAlchemy 2.0 | Worker / MCP 网关 / 无 Flask 上下文的后台服务 |

运行数据（trace / eval）放在 `core/db/models/`，因为它们由 Flask API、Worker、MCP Gateway **多源写入**，不能依赖 Flask 应用上下文。

### 基础设施

- **数据库**：MySQL 8.0（业务层），通过 `DATABASE_URL` 亦支持 PostgreSQL。
- **连接池**：`core/config.py` `pool_size=5`、`pool_recycle=3600`。
- **时间戳**：统一用 `app/core/timezone.py:now_china()`，所有表 `created_at / updated_at` 时区感知。
- **迁移**：Alembic / Flask-Migrate，`migrations/versions/`。关键迁移：会话摘要（`add_conversation_summary`）、异步任务（`add_chat_tasks`）、工作流（`add_workflow_tables`）、MCP（`add_mcp_tables`）、完整 trace/eval（`complete_traces_evals`）。

> 注：迁移链当前无 baseline，schema 仍部分依赖 `create_all()`；演进策略见全局记忆 *Migration-first schema strategy*。

### 实体关系概览

```
users ─┬─ 1:N classrooms (teacher_id) ─ 1:N enrollments ─ N:1 users(student)
       ├─ 1:N submissions ─ N:1 questions ─ N:1 problems
       │                    └─ 1:N test_results ─ N:1 test_cases
       ├─ 1:N ai_conversations ─┬─ 1:N ai_messages
       │                        └─ 1:N chat_tasks
       ├─ 1:N quiz_attempts ─ N:1 quizzes ─ N:M problems (quiz_problems)
       ├─ 1:1 student_profiles          (长期记忆)
       └─ 1:1 teacher_preferences       (长期记忆)

agent_trace_runs ─ 1:N agent_trace_spans ─ 1:N agent_trace_events   (运行数据)
                 ├─ 1:N agent_trace_artifacts
                 └─ 1:N agent_trace_links ─ (target_table, target_id) → 业务数据
```

---

## 4.2 用户与角色模型

### User 与角色

`app/models/user.py`：

```python
class UserRole(Enum):
    STUDENT = "student"; TEACHER = "teacher"; ADMIN = "admin"

class User(db.Model):  # __tablename__ = "users"
    id, username(unique, indexed), email(unique, nullable),
    password,            # PBKDF2-SHA256 hash，见 auth.md
    role(Enum), created_at, updated_at
```

角色驱动整个权限体系（见 [security-permissions-reliability.md](security-permissions-reliability.md)）。

### 学生学习档案 —— StudentProfile（长期记忆）

`app/models/student_profile.py`，与 user 一对一（`student_id` unique）：

| 字段 | 类型 | 语义 | 写入路径 |
|---|---|---|---|
| `error_patterns` | JSON dict | `{WA, RE, CE, TLE, AC}` 计数 | ✅ `MemoryService.update_student_profile()`（近 50 次提交聚合） |
| `recent_questions` | JSON list | 最近 10 个题目 id | ✅ 同上 |
| `recent_topics` | JSON list | 近期接触主题 | ⚠️ 部分维护 |
| `knowledge_map` | JSON dict | `{topic: 掌握度 0~1}` | ❌ **读取但无自动写入** |
| `current_hint_level` | JSON dict | `{topic: 提示级别}` | ❌ **读取但无自动写入** |
| `learning_summary` | Text | 自然语言学习总结 | ❌ **读取但无自动写入** |
| `preferred_language` | String | 偏好语言（默认 python） | 手动 |

> ⚠️ 重要现状：`knowledge_map / current_hint_level / learning_summary` 在 prompt 构建时被读取（见 4.5），但缺少稳健的自动写入路径——schema 看似成熟，实际可能长期为空。详见 [memory-module-comparison](2026-06-03-memory-module-comparison.md) 第 3 节。

### 教师偏好 —— TeacherPreference（长期记忆）

与 user 一对一（`teacher_id` unique）：

| 字段 | 默认 | 自动学习来源 |
|---|---|---|
| `preferred_difficulty` / `preferred_language` | medium / python | `memory/preference.py:learn_from_generation()`（出题成功后） |
| `preferred_topics` | `[]` | 同上，最多保留若干 |
| `style_notes` | null | `refresh_teacher_style_summary()`（LLM 从近期已发布草稿推断风格） |
| `class_weak_areas` | `[]` | `analyze_class_weak_areas()`（聚合班级学生档案薄弱点） |
| `class_level` | intermediate | 手动 |

教师偏好是**模型推断 + 显式设置混合**的数据，当前未区分二者来源（治理边界弱，见对比文档第 1 节）。

---

## 4.3 会话与消息存储（短期状态 + 中期记忆）

### 对话头与消息

`app/models/ai_conversation.py`：

```python
class AIConversation(db.Model):   # ai_conversations
    id, user_id(FK), agent_type, context_type, context_id,
    title, summary(Text),          # summary = 中期记忆
    created_at, updated_at

class AIMessage(db.Model):        # ai_messages
    id, conversation_id(FK), role,          # "user" / "assistant"
    content(Text), tool_calls(JSON),        # Agent 调用的工具
    tokens_used, created_at
```

- `context_type / context_id`：可选业务锚点（如 `problem / 123`）。
- `summary`：对话摘要，由 LLM 生成（见 4.5），是**跨对话的中期记忆**。
- `AIMessage` 是短期上下文的持久化形态；查询按 `conversation_id` + `order by id`。

### Session 的两种语义

| 客户端 | 登录态 | 机制 |
|---|---|---|
| Web 前台 | Flask-Login `session`（`session_protection="strong"`） | 服务端签名 cookie + `current_user` |
| API / 移动端 | **不用 Flask session**，改 JWT | `Authorization: Bearer` / `auth_token` cookie |

认证细节见 [auth.md](auth.md)。本章关注的是 session 仅承载**身份**，对话状态由 DB + Redis 承载。

### 异步任务与 SSE 缓冲（短期状态）

聊天走异步：`ChatTask`（`chat_tasks` 表，UUID 主键）记录 `pending → processing → completed | failed`，并把进度写入 Redis。

`workers/redis_buffer.py` 的键模式：

```
chat_task:{task_id}:status   String   任务状态
chat_task:{task_id}:buffer   List     有序 SSE 事件（客户端可断线重连续读）
chat_task:{task_id}:agent    String   路由到的 agent
workflow:{run_id}:status     String   工作流状态
workflow:{run_id}:buffer     List     工作流 SSE 事件
```

- TTL 统一 `TASK_BUFFER_TTL`（默认 3600s）。
- Redis 中的事件流是**短期、可丢弃**的；权威结果落 DB（`ChatTask.result_message_id` / `error_detail`）。
- Redis 不可用时所有读写静默降级（返回空/None），不阻断主流程。

---

## 4.4 Agent 执行状态（运行数据 + 状态机）

执行状态有三个层级：单 Agent 任务（`AgentTask`）、多步工作流（`WorkflowRun/Step`）、细粒度 trace（`agent_trace_*`）。

### AgentTask 状态机

`app/models/agent_task.py`（`agent_tasks`，UUID）记录单个 Agent 任务；状态机在 `core/task_state.py` 显式声明并校验转移：

```
PENDING ──→ PLANNING ──→ EXECUTING ──→ VALIDATING ─┬─→ COMPLETED
   │            │            ↑              │        ├─→ REVIEW ──→ REVISING ──→ (回 VALIDATING)
   └─→ CANCELLED│            └──────────────┘        └─→ FAILED ──→ (可回 PENDING 重试)
```

`validate_transition(current, target)` 拒绝非法跳转。关键字段：`plan_steps(JSON)`、`current_step`、`attempt/max_attempts`、`review_status/review_feedback`（人工审查）。

### WorkflowRun / WorkflowStep

`app/models/workflow.py` 支持多步编排：

```python
WorkflowRun:   goal, workflow_type, status,        # planning→executing→validating→completed|failed|cancelled，外加 waiting_approval
               plan_json, current_step_index, total_steps,
               max_steps(10), max_retries_per_step(2), timeout_seconds(300),
               total_tokens_used, total_latency_ms

WorkflowStep:  step_index, step_type,              # agent_call / tool_call / validation / llm_call / human_gate
               status,                             # pending→running→completed|failed|skipped|waiting_approval
               risk_level, requires_approval,      # 人工审批门
               input_data, output_data,
               attempt/max_attempts(2),
               depends_on(JSON)                    # 步骤依赖（支持 DAG）
```

`waiting_approval` 是**有意暂停**（人工 gate），不是 orphan；崩溃恢复时不会被误判（见 [security-permissions-reliability.md](security-permissions-reliability.md) 5.7）。每步记 `tokens_used / latency_ms`，汇总到 run 级别。

### Trace 模型（运行数据）

`core/db/models/agent_trace.py`，运行时中立，多源写入：

| 表 | 粒度 | 关键字段 |
|---|---|---|
| `agent_trace_runs` | 一次 Agent 运行 | `trace_id(unique)`、source、agent_type、关联 id（conversation/chat_task/workflow_run/eval_run）、tokens、`cost_cny`、分项 latency（llm/tool/mcp/sandbox） |
| `agent_trace_spans` | 子操作 | parent_span_id、span_type、sequence、tokens、latency |
| `agent_trace_events` | 细粒度事件 | event_type、payload_json |
| `agent_trace_artifacts` | 中间产物 | artifact_type、storage_uri、preview_text |
| `agent_trace_links` | 与业务数据关联 | `(target_table, target_id)` → 如 trace→submission |
| `eval_runs / eval_case_runs / eval_case_grader_results` | 质量评估 | pass_rate、grader 评分 |

trace 的可见性与脱敏见安全章 5.3 / 5.6。

---

## 4.5 Memory 机制

记忆分三层，**注入点统一在系统 prompt**：

```
短期：compact_messages()        运行时消息列表（超窗压缩）
中期：AIConversation.summary     跨对话摘要
长期：StudentProfile / TeacherPreference   业务画像
                    │
                    ▼
       get_memory_context() 拼成字符串 → 注入 system prompt
```

实现集中在 `memory/service.py:MemoryService` 与 `memory/preference.py`。

### 短期：消息压缩 `compact_messages()`

`memory/service.py:153`。当消息数 > `max_messages`（默认 20）时：保留 system 消息 + 最近 20 条，中间早期消息用 FAST 档 LLM 压缩成摘要；LLM 失败则降级为简单截断拼接。

- 调用点：`agents/base.py` 的 `_invoke_with_mcp_tools()` / `_stream_with_mcp_tools()`。
- ⚠️ 一致性风险：`GeneratorAgent.stream()` 自组装消息列表，**未走** `compact_messages()`，长生成对话可能绕过压缩（对比文档第 4 节）。

### 中期：对话摘要

- **生成** `generate_conversation_summary()`（`memory/service.py:12`）：消息数 ≥ 4 时，取最近 10 条用 FAST LLM 生成 2-3 句摘要，写入 `AIConversation.summary`。由 `app/api/v1/ai.py:_maybe_generate_summary()` 异步触发。
- **回放** `_recent_conversation_summaries()`（`:74`）：取该用户最近 3 条有摘要的历史对话，**排除当前对话**避免自我引用。

### 长期画像注入 `get_memory_context()`

`memory/service.py:97`，按角色拼接：

- **学生**：`learning_summary` / `error_patterns` / `knowledge_map`(<0.5 的弱项) / `current_hint_level`。
- **教师**：`style_notes` / `class_weak_areas`。
- 二者都附加 **Recent Sessions**（中期摘要）。

整段 try/except 包裹——profile 表未迁移时返回空串，**优雅降级**不报错。

> 当前所有记忆被**扁平拼成一个字符串**注入，未区分"必须遵守的规则 / 用户可编辑偏好 / 模型推断画像 / 弱上下文摘要"，也无注入审计（哪段记忆进了哪次运行）。这是与成熟 Agent 平台的主要差距，目标形态见对比文档第 164 行起。

### 教师偏好学习 `memory/preference.py`

`learn_from_generation()`（出题后更新语言/难度/主题）、`refresh_teacher_style_summary()`（LLM 推断 `style_notes`）、`analyze_class_weak_areas()`（`Counter` 聚合班级学生薄弱点，取 top 项）。

---

## 4.6 学习进度数据（业务数据）

### 提交与成绩

`app/models/submission.py`：

```python
Submission:  student_id(FK), question_id(FK), code, score,
             status,            # pending → running → completed | error
             error_message, execution_time, memory_used, submitted_at
TestResult:  submission_id(FK), test_case_id(FK), passed,
             actual_output, error_message, execution_time
```

`SubmissionService.submit_code()`：建记录 → 执行（ExecutorService）→ 跑全部测试用例 → 计分 → **触发档案更新**（同一学生 60s cooldown，`_PROFILE_UPDATE_COOLDOWN`，避免高频重算）。

### 统计现状

`TeacherStatsService.get_teacher_stats()` 提供基础计数：题目数 / 班级数 / 学生数（去重）/ 提交数。

❌ 尚未实现的进度指标：`acceptance_rate`（通过率）、`streak`（连续天数）、`mastery`（量化掌握度，依赖未填充的 `knowledge_map`）。Analytics Agent 目前只做基础聚合。

---

## 4.7 缓存设计

无传统进程内缓存（极少量 `@lru_cache` 用于静态映射，如工具白名单），缓存职责交给外部系统：

| 用途 | 介质 | 键 / 机制 | TTL |
|---|---|---|---|
| 异步任务状态 / SSE 流 | Redis | `chat_task:* / workflow:*`（见 4.3） | `TASK_BUFFER_TTL`(3600s) |
| 限流计数 | Redis | `ai_rate:{user_id}:{agent_type}` | 60s（见安全章 5.8） |
| RAG 向量检索 | ChromaDB | `all-MiniLM-L6-v2` 嵌入，HTTP/persistent | 持久化 |

RAG 参数（`core/config.py`）：`RAG_CHUNK_SIZE=512`、`RAG_CHUNK_OVERLAP=64`、`RAG_CANDIDATE_K=20`、`RAG_FINAL_K=5`、`RAG_DEDUP_THRESHOLD=0.8`、rerank 默认关闭（避免冷启动）。检索与索引细节见 [tools-mcp-rag.md](tools-mcp-rag.md)。

**降级原则**：Redis 故障一律 fail-open（限流放行、buffer 读空），保证核心链路可用——可观测性与限流可暂时退化，但用户请求不被阻断。

---

## 数据分层小结

| 维度 | 短期状态 | 中/长期记忆 | 业务数据 | 运行数据 |
|---|---|---|---|---|
| 介质 | Redis / 运行时 | MySQL | MySQL | MySQL |
| 生命周期 | 会话 / 1h TTL | 永久 | 永久 | 永久（可归档） |
| 权威性 | 可丢弃 | 弱（含推断） | 强（事实） | 审计/可观测 |
| 代表 | 消息窗口、SSE | `summary`、`StudentProfile`、`TeacherPreference` | 用户/班级/题目/提交/成绩 | `agent_trace_*`、eval |
| 成熟度 | 高 | 中（画像字段部分未填充、无注入审计） | 高 | 高 |

---

## 相关文件速查

| 文件 | 职责 |
|---|---|
| `app/models/user.py` | User + UserRole |
| `app/models/student_profile.py` | StudentProfile / TeacherPreference（长期记忆） |
| `app/models/ai_conversation.py` | AIConversation / AIMessage（对话 + 中期摘要） |
| `app/models/agent_task.py` / `core/task_state.py` | 单 Agent 任务 + 状态机 |
| `app/models/workflow.py` | WorkflowRun / WorkflowStep（多步编排） |
| `app/models/submission.py` | Submission / TestResult（学习进度） |
| `core/db/models/agent_trace.py` | trace / eval（运行数据，运行时中立） |
| `memory/service.py` | 短/中/长期记忆：压缩、摘要、画像注入 |
| `memory/preference.py` | 教师偏好与班级薄弱点学习 |
| `workers/redis_buffer.py` | Redis 任务状态 + SSE 缓冲 |
| `app/services/submission_service.py` | 提交执行 + 档案更新触发 |
| `knowledge/store.py` | ChromaDB 向量库 |
