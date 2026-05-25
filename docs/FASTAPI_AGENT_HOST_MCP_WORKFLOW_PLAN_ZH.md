# FastAPI Agent Host、MCP Server 与完整多 Agent Workflow 方案

> 日期：2026-05-25
> 状态：已审查，待实施
> 范围：CodeRunner-AI 的 AI Agent 架构升级设计

## 一、结论

该方案可行，但在推进新架构之前，现有系统有三个必须优先修复的问题：

1. **AI 工具命名与 Problem/Question 迁移不一致** — 工具名仍用旧术语，造成系统内外混淆。
2. **Agent 能力边界暴露** — 用户可手动选择 Agent 导致请求与 Agent 职责不匹配，且 Generator 输出原始 JSON 体验差。
3. **对话持久化缺失** — 用户离开页面后对话中断、内容丢失。

推荐路线：

```text
Phase 0：修复现有系统的三个核心缺陷（不需要 FastAPI）
Phase 1：FastAPI Agent Host 服务化
Phase 2：Supervisor 多 Agent Workflow
Phase 3：只读 MCP Server
Phase 4：高风险工具与人工审批
```

推荐架构：

```text
Flask 主站
  - 用户、认证、题库、提交、判题、教师后台、现有页面

FastAPI Agent Host
  - Supervisor / Main Agent
  - 多 Agent Workflow Runtime
  - Planner / Executor / Critic / Human Gate
  - SSE 或 WebSocket 流式输出
  - 调用 DeepSeek API
  - 调用现有业务服务、数据库、Redis、ChromaDB

MCP Server
  - 向外部 AI 客户端暴露 CodeRunner 工具
  - 第一版只开放低风险只读工具

DeepSeek API
  - 继续作为 LLM provider
  - 使用 OpenAI-compatible 调用方式
```

核心原则：Flask 继续负责业务系统，FastAPI 负责 AI 主控编排，MCP 负责标准化工具出口。

## 二、当前系统能力现状

### 2.1 已实现的能力

以下能力已在当前 Flask 架构中运行：

| 能力 | 实现位置 | 说明 |
|------|---------|------|
| 四个 Specialist Agent | `app/agents/agents/` | TutorAgent、ReviewerAgent、GeneratorAgent、AnalyticsAgent |
| LangGraph 编排 | `app/agents/orchestrator.py` | StateGraph 条件路由、意图分类、handoff（最多 2 跳） |
| LangChain 工具 + 权限矩阵 | `app/agents/tools/` | 10+ 工具，`permissions.py` 按 (agent, tool, role) 三元组控制 |
| RAG 知识库 | `app/agents/knowledge_base.py` | ChromaDB + SentenceTransformers，3 个 collection（题目/知识点/错误模式） |
| Trace 追踪 | `app/agents/tracing.py` | AgentRun + AgentRunStep 持久化，LLM/工具延迟、token 统计 |
| Memory 记忆 | `app/agents/memory.py` | StudentProfile / TeacherPreference，消息压缩 |
| Eval 评估 | `evals/` | 评估套件，通过 API 触发 |
| SSE 流式输出 | `app/api/v1/ai.py` POST `/chat/stream` | token/route/handoff/tool_call 等事件，心跳机制 |
| 结构化出题流水线 | `app/agents/generation_pipeline.py` | 生成 -> 验证 -> 查重 -> 质量审查 -> 定稿，五阶段 LangGraph |
| 批量任务 | `app/agents/batch_runner.py` | AgentTask 状态机，步骤分解，重试 |
| Draft 审批 | `app/api/v1/ai.py` POST `/drafts/<id>/review` | 教师审批：approve / reject / request_revision |
| 任务恢复 | `app/agents/recovery.py` | 孤儿任务检测与恢复 |
| 审计日志 | `app/models/ai_audit_log.py` | 注入检测、IP、操作记录 |
| 安全检测 | `app/agents/security.py` | 注入检测、输入清洗、输出过滤 |
| 速率限制 | `app/api/v1/ai.py` | Redis 滑动窗口，per-user per-agent |

### 2.2 已存在但需要增强的能力

| 能力 | 当前状态 | 问题 |
|------|---------|------|
| 意图分类 / 路由 | Orchestrator `_classify_intent()` 可自动路由 | 前端允许手动选 Agent，绕过路由；Agent prompt 无能力边界声明 |
| 出题闭环 | generation_pipeline 已实现完整流程 | Generator 输出原始 JSON，前端不做解析渲染 |
| 对话持久化 | AIConversation + AIMessage 模型存在 | 流式响应仅在完成后保存，断连则丢失 |
| 循环限制 | MAX_TOOL_ITERATIONS=5, MAX_HANDOFFS=2 | 缺少 token 成本上限和总执行时间限制 |

### 2.3 确实缺失的能力

| 能力 | 说明 |
|------|------|
| 通用 Supervisor Workflow | 现有流水线仅服务出题场景，缺少通用的"拆解任意目标 -> 调度 Agent -> 验证结果"框架 |
| MCP Server | 无任何 MCP 协议代码 |
| 异步任务队列 | 当前 chat 依赖 HTTP 连接存活，断连即中断 |
| 跨 Agent 通用工作流状态表 | AgentTask 仅用于批量任务，非通用 |

## 三、目标架构

```text
用户请求
  |
Flask UI / API
  |
FastAPI Agent Host
  |
Supervisor Agent
  |
Planner 生成结构化计划
  |
Workflow Executor
  +-- TutorAgent
  +-- ReviewerAgent
  +-- GeneratorAgent
  +-- AnalyticsAgent
  +-- RAG Tools
  +-- Executor Tools
  |
Critic / Verifier
  |
Human Gate（需要时）
  |
最终结果 / Draft / Report / Trace
```

## 四、Phase 0：修复现有系统的三个核心缺陷

> 不需要 FastAPI，全部在现有 Flask 架构内完成。这些问题影响当前用户体验，必须在新架构工作之前修复。

### 4.1 工具命名对齐 Problem/Question 迁移

#### 背景

项目已完成 Problem/Question 数据模型迁移（参见 `docs/superpowers/plans/2026-05-22-problem-variant-migration.md`）：

- **Problem** = 面向用户的题目单位（标题、描述、共享测试用例）
- **Question** = 语言变体（starter_code、solution，属于 Problem 子项）

但 AI 子系统的工具名、权限矩阵、Agent prompt 仍使用旧术语 "question"，造成内外命名混淆。

#### 需要修改的内容

**工具重命名：**

| 当前名称 | 目标名称 | 文件 |
|---------|---------|------|
| `search_similar_questions` | `search_similar_problems` | `app/agents/tools/knowledge_tools.py` |
| `get_question_detail` | `get_problem_detail` | `app/agents/tools/question_query.py`（参数从 question_id 改为 problem_id） |
| `get_question_difficulty_stats` | `get_problem_difficulty_stats` | `app/agents/tools/analytics_query.py` |

**权限矩阵同步更新：**

`app/agents/tools/permissions.py` 中所有 key 同步修改：

```python
# 旧
("generator", "search_similar_questions"): {"teacher", "admin"},
("analytics", "get_question_detail"):      {"student", "teacher", "admin"},
("analytics", "get_question_difficulty_stats"): {"student", "teacher", "admin"},

# 新
("generator", "search_similar_problems"): {"teacher", "admin"},
("analytics", "get_problem_detail"):      {"student", "teacher", "admin"},
("analytics", "get_problem_difficulty_stats"): {"student", "teacher", "admin"},
```

**KnowledgeBase 方法重命名：**

`app/agents/knowledge_base.py`:
- `search_similar_questions()` -> `search_similar_problems()`
- `index_question()` -> 确认已废弃，只保留 `index_problem()`

**Agent prompt 措辞更新：**

所有 `app/agents/prompts/*.py` 中的 "question" 改为 "problem"（指题目整体时），保留 "question" 仅用于指代语言变体（variant）。

**Agent 工具列表更新：**

各 Agent 类中引用的工具名同步修改：
- `app/agents/agents/tutor.py`
- `app/agents/agents/generator.py`
- `app/agents/agents/reviewer.py`
- `app/agents/agents/analytics.py`

**generation_pipeline 同步更新：**

`app/agents/generation_pipeline.py` 中 `_check_duplicates()` 调用的 `search_similar_questions` 改为 `search_similar_problems`。

### 4.2 Agent 能力边界：去除手动选择器，强制自动路由

#### 问题描述

当前前端 AI Chat 界面允许用户手动选择 Agent（tutor / reviewer / generator / analytics）。这导致：

1. 用户选择 Analytics Agent 后说"出一道题目"，Analytics Agent 用对话能力凭空生成了题目文本（不经过工具调用，权限矩阵拦不住），但无法执行保存操作。
2. Agent prompt 没有明确的能力边界声明，LLM 在没有限制的情况下会尝试回答任何请求。
3. Orchestrator 在 `agent_type` 已指定时直接跳过意图分类（`orchestrator.py:41-43`），不做匹配校验。

#### 修复方案

**前端：去除 Agent 手动选择器**

- 移除 `app/templates/ai/chat.html` 和 `app/static/js/ai_chat.js` 中的 Agent 类型选择 UI。
- 所有请求统一发送 `agent_type: "auto"`。
- 路由完全由 Orchestrator 的 LLM 意图分类 + handoff 机制完成。
- 前端仍显示当前会话被路由到了哪个 Agent（通过 SSE `route` 事件），但用户不可手动切换。

**后端：Agent prompt 增加能力边界声明**

每个 Agent 的 system prompt 末尾追加明确的能力限制。示例：

```text
# AnalyticsAgent prompt 追加
## 能力边界
你只能执行数据查询和分析任务。以下请求不在你的职责范围内：
- 生成或创建题目 -> 应由 generator 处理
- 代码审查 -> 应由 reviewer 处理
- 辅导学生解题 -> 应由 tutor 处理
如果收到超出你职责范围的请求，必须使用 [HANDOFF: agent_type | reason] 转移，不要尝试自行回答。
```

每个 Agent 都需要类似的声明，确保 LLM 在收到不匹配请求时主动 handoff 而不是勉强回答。

**前端：Generator 输出 JSON 渲染为格式化卡片**

当前 GeneratorAgent 返回结构化 JSON（题目、测试用例、solution），前端直接显示原始 JSON 文本，体验差。

修复方案：

- Generator 的 JSON 输出格式保持不变（JSON 结构是保存/验证的基础）。
- 前端 `ai_chat.js` 在收到 `done` 事件后，检测 `agent_type == "generator"`。
- 对 generator 的 JSON 响应做解析，渲染为格式化的题目卡片：

```text
+------------------------------------------+
| [题目标题]                    难度: medium |
|------------------------------------------|
| [题目描述]                                |
|------------------------------------------|
| 示例测试用例:                              |
| Input: 5 3    Expected: 8               |
|------------------------------------------|
| [保存为草稿]  [编辑]  [丢弃]              |
+------------------------------------------+
```

- 点击"保存为草稿"调用现有 `POST /api/v1/ai/generate/to-draft` 接口。
- 非 generator 的响应继续以 markdown 渲染。

### 4.3 对话持久化：异步任务队列模型

#### 问题描述

当前流式 Chat 端点（`POST /chat/stream`）依赖 HTTP 连接存活：

- 用户消息在流开始前保存到 DB。
- AI 回复仅在流式传输完全结束后才写入 DB。
- 用户离开页面 -> 连接断开 -> `db.session.rollback()` -> AI 回复丢失。
- 前端无 `beforeunload` 保护、无 localStorage 缓存、无断线重连。

#### 修复方案：任务队列模型

将所有 AI Chat 交互从"同步 SSE 流式"改为"异步任务 + 前端订阅"模型：

**核心流程：**

```text
1. 用户发送消息
   -> POST /api/v1/ai/chat
   -> 创建 ChatTask 记录（status: pending）
   -> 立即返回 { task_id, conversation_id }

2. 后端 Worker 异步执行
   -> 从队列取出 ChatTask
   -> 调用 Orchestrator / Agent
   -> 流式 token 写入 Redis 缓冲区（key: chat_task:{task_id}:buffer）
   -> 完成后写入 DB（AIMessage），更新 ChatTask status: completed
   -> 失败则记录错误，更新 status: failed

3. 前端订阅任务状态
   -> GET /api/v1/ai/chat/task/{task_id}/stream（SSE）
   -> 从 Redis 缓冲区读取已有 token 并追赶（catch-up）
   -> 然后实时接收增量 token
   -> 如果 task 已完成，直接返回完整结果

4. 用户离开页面
   -> 前端断开 SSE 连接
   -> 后端 Worker 不受影响，继续执行
   -> Redis 缓冲区保留中间结果

5. 用户回到页面
   -> 加载 conversation，看到所有已保存的消息
   -> 如果有 in-progress 的 ChatTask，自动重新订阅
   -> 从 Redis 缓冲区追赶已产生的 token
   -> 继续实时接收后续 token
   -> 如果已完成，直接显示完整结果
```

**数据模型扩展：**

扩展现有 `AgentTask` 或新建 `ChatTask`：

```python
class ChatTask(db.Model):
    __tablename__ = "chat_tasks"

    id = db.Column(db.String(36), primary_key=True)  # UUID
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_conversations.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    user_message_id = db.Column(db.Integer, db.ForeignKey("ai_messages.id"))
    status = db.Column(db.String(20), default="pending")
        # pending -> processing -> completed / failed
    agent_type = db.Column(db.String(20))  # 路由结果
    result_message_id = db.Column(db.Integer, db.ForeignKey("ai_messages.id"), nullable=True)
    error_detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
```

**Redis 缓冲区结构：**

```text
chat_task:{task_id}:status   -> "processing" | "completed" | "failed"
chat_task:{task_id}:buffer   -> List of SSE event JSON strings
chat_task:{task_id}:agent    -> 路由到的 agent_type
```

缓冲区 TTL：任务完成后保留 10 分钟，之后清除（完整结果已在 DB）。

**前端改动：**

- `ai_chat.js` 发送消息后，收到 `task_id`，立即建立 SSE 订阅。
- 添加 `beforeunload` 提示（可选，因为后端会续跑）。
- 页面加载时检查是否有 in-progress 的 ChatTask，有则自动重连。
- 添加任务状态指示器（"AI 正在思考..."  / "AI 正在生成..." / "已完成"）。

**后端 Worker 实现方案：**

第一版使用线程池（`concurrent.futures.ThreadPoolExecutor`）+ Redis 队列，避免引入 Celery 等重依赖。后续迁移到 FastAPI Agent Host 时再考虑更完善的 Worker 架构。

```python
# 简化示意
import threading
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)

def submit_chat_task(task_id):
    executor.submit(_run_chat_task, task_id)

def _run_chat_task(task_id):
    task = ChatTask.query.get(task_id)
    # ... 执行 Agent，token 写入 Redis buffer ...
    # ... 完成后写入 DB ...
```

**API 端点变更：**

```text
# 旧
POST /api/v1/ai/chat/stream  -> SSE 流式（连接依赖）

# 新
POST /api/v1/ai/chat         -> 返回 { task_id, conversation_id }（立即返回）
GET  /api/v1/ai/chat/task/{task_id}/stream  -> SSE 订阅（可断线重连）
GET  /api/v1/ai/chat/task/{task_id}         -> 查询任务状态（轮询备选）
```

旧的同步 `/chat` 端点和流式 `/chat/stream` 端点可保留一段时间作为兼容，但前端切换到新模型后废弃。

## 五、模块划分

### 5.1 Flask 主站

继续保留现有职责：

- 用户注册、登录、JWT/session。
- 学生和教师页面。
- 题库、Problem/Question、Quiz、Submission。
- 判题入口和已有业务 API。
- Phase 0 的修复工作在此完成。

不建议在第一阶段迁移这些业务到 FastAPI。

### 5.2 FastAPI Agent Host

建议新增独立目录：

```text
agent_host/
  main.py
  api/
    chat.py
    workflows.py
    traces.py
  core/
    config.py
    db.py
    auth.py
  workflow/
    supervisor.py
    planner.py
    executor.py
    critic.py
    state.py
  worker/
    task_runner.py
    redis_buffer.py
  adapters/
    coderunner_services.py
    agent_tools.py
```

职责：

- 接收 AI workflow 请求。
- 校验来自 Flask 的 JWT 和 user role。
- 调用 DeepSeek API。
- 调度现有 agents。
- 管理 ChatTask / WorkflowTask 生命周期。
- 持久化 workflow run、step、trace、approval request。
- 对前端输出 SSE 事件（可断线重连）。

### 5.3 MCP Server

MCP Server 用来让外部 AI 客户端调用 CodeRunner 能力。

第一版只暴露只读工具（名称已对齐 Problem/Question 迁移后的术语）：

- `search_knowledge`
- `search_similar_problems`（对应工具 `search_similar_problems`）
- `get_problem_detail`（对应工具 `get_problem_detail`，接收 problem_id）
- `get_agent_trace`（封装 `GET /api/v1/ai/traces/<run_id>` 端点）
- `get_student_summary`（封装 AnalyticsAgent + Profile API）

暂时不要开放：

- `execute_code`
- `save_generated_problem`
- `delete_knowledge`
- `update_profile`
- `run_eval`
- 任意 SQL 查询

这些工具涉及执行、写入、成本或隐私，必须等权限、限流、审计、人工确认完善后再开放。

## 六、多 Agent Workflow 设计

第一版 workflow 应该使用结构化计划，而不是让模型自由循环。

建议计划结构：

```json
{
  "goal": "生成一道 Python 中等难度数组题",
  "steps": [
    {
      "step_id": "step_1",
      "agent_type": "generator",
      "instruction": "生成题目草稿",
      "risk_level": "medium",
      "requires_approval": false
    },
    {
      "step_id": "step_2",
      "agent_type": "rag",
      "instruction": "检查是否与现有题目重复",
      "risk_level": "low",
      "requires_approval": false
    },
    {
      "step_id": "step_3",
      "agent_type": "executor",
      "instruction": "运行参考解法验证测试用例",
      "risk_level": "medium",
      "requires_approval": false
    },
    {
      "step_id": "step_4",
      "agent_type": "critic",
      "instruction": "检查质量和格式",
      "risk_level": "low",
      "requires_approval": false
    },
    {
      "step_id": "step_5",
      "agent_type": "publisher",
      "instruction": "保存为 Draft",
      "risk_level": "high",
      "requires_approval": true
    }
  ]
}
```

每个 step 应该记录：

- `step_id`
- `workflow_run_id`
- `agent_type`
- `instruction`
- `status`
- `input`
- `output`
- `error`
- `risk_level`
- `requires_approval`
- `started_at`
- `finished_at`

> 注意：当前 `generation_pipeline.py` 已实现了出题场景的五阶段流水线（生成 -> 验证 -> 查重 -> 质量审查 -> 定稿）。Phase 2 的目标是将这种结构化流水线泛化为通用 Workflow 框架，而不是重复建设。

## 七、教师出题闭环现状

以下闭环已在 `POST /api/v1/ai/generate/pipeline` 中实现：

```text
教师输入：帮我生成一道中等难度 Python 数组题
  |
GeneratorAgent 生成题目 JSON
  |
_validate_solution() 运行参考解法验证测试用例
  |
_check_duplicates() RAG 查重（SIMILARITY_THRESHOLD=0.8）
  |
_review_quality() LLM 质量审查
  |
保存为 GeneratedQuestionDraft
  |
教师通过 POST /drafts/<id>/review 审批（approve/reject/revision）
  |
approve 后发布为 Problem + Question variants
  |
Trace 全程记录（AgentRun + AgentRunStep）
```

Phase 0 的改进点：
- Generator JSON 输出改为前端格式化卡片渲染。
- 通过自动路由到达 generator，而非手动选择。
- 对话过程使用异步任务队列，不再依赖连接存活。

## 八、实施阶段

### Phase 0：修复现有系统核心缺陷

> 在现有 Flask 架构内完成，不引入 FastAPI。

**目标：**

- 完成 AI 工具名称与 Problem/Question 迁移的对齐（详见 4.1）。
- 去除前端 Agent 手动选择器，强制自动路由 + handoff（详见 4.2）。
- 各 Agent prompt 增加能力边界声明（详见 4.2）。
- Generator JSON 输出前端渲染为格式化卡片（详见 4.2）。
- 实现异步任务队列模型，解决对话持久化问题（详见 4.3）。

**不做：**

- 不迁移 Flask 业务 API。
- 不引入 FastAPI 或 MCP。
- 不做通用 Workflow 框架。

### Phase 1：Agent Host 服务化

**目标：**

- 新建 FastAPI Agent Host。
- 将 Phase 0 的 ChatTask + Worker 迁移到 FastAPI。
- 支持 `/workflows` 创建任务。
- 支持 `/workflows/{id}` 查询任务状态。
- 支持 SSE 输出 workflow 事件（可断线重连）。
- 复用现有 DeepSeek 配置。

**不做：**

- 不迁移 Flask 业务 API。
- 不开放高风险 MCP tools。

### Phase 2：Supervisor Workflow

**目标：**

- 实现 `SupervisorAgent`。
- 实现结构化 planner。
- 实现 step executor。
- 将现有 `generation_pipeline.py` 泛化为通用 Workflow 框架。
- 调用现有 Agent（GeneratorAgent、RAG、executor、critic）。
- 写入 workflow run/step 表。

### Phase 3：MCP Server

**目标：**

- 新增 MCP server。
- 暴露只读 CodeRunner tools（名称已对齐 Problem 术语）。
- 加 token/JWT 鉴权。
- 加 tools/list 和 tools/call 基础测试。

### Phase 4：Human Gate 与高风险动作

**目标：**

- 对发布题目、执行代码、删除知识、批量生成等操作加审批。
- 审批请求落库。
- 前端显示待确认动作。
- 审计所有高风险 tool call。

## 九、关键风险

### 9.1 Flask 上下文耦合

现有代码大量依赖 Flask app context 和 SQLAlchemy session。FastAPI Agent Host 如果直接 import Flask app，容易造成上下文和生命周期混乱。

建议：

- Phase 0 的异步 Worker 在 Flask app context 内运行（`with app.app_context():`）。
- Phase 1 迁移到 FastAPI 时用 adapter 调用现有 HTTP API 或抽 service 层。
- 不要让 FastAPI 直接深度依赖 Flask request/current_app。

### 9.2 权限绕过

MCP 和 Agent Host 都不能绕过现有权限体系。

当前已有措施：
- `TOOL_PERMISSIONS` 矩阵 + `check_tool_permission()` 运行时检查。
- `_inject_security()` 覆盖敏感参数（不信任模型传入的 user_id/student_id）。
- 高风险工具（generator 相关）仅 teacher/admin 可用。

Phase 0 增强：
- Agent prompt 增加能力边界声明，从 LLM 层面也限制越权行为。
- 去除手动 Agent 选择器，避免用户绕过意图分类。

后续要求：
- 所有 tool call 必须有 `user_id` 和 `user_role`。
- server-side 覆盖敏感参数，不信任模型传入的 user_id/student_id/owner_id。
- 高风险工具默认关闭。

### 9.3 模型无限循环

完整 workflow 不能让模型无限自主运行。

当前已有措施：
- `MAX_TOOL_ITERATIONS = 5`（每次 Agent 调用最多 5 次工具）。
- `MAX_HANDOFFS = 2`（最多 2 次跨 Agent 转移）。
- per-agent 速率限制（tutor:20, reviewer:10, generator:5, analytics:10 / 分钟）。
- 30 秒请求超时。

仍需补充：
- 最大 token 成本限制（per-task 和 per-user-daily）。
- 最大执行时间限制（per-task）。
- 明确终止条件。
- Phase 0 的 ChatTask 应包含 timeout 机制。

### 9.4 RAG 冷启动

当前 ChromaDB + sentence-transformers 首次加载 embedding 模型较慢，并可能访问 HuggingFace。

当前已有缓解：
- `app/__init__.py` 启动时做异步 KB 索引。

建议补充：
- 将 embedding 模型预下载进 Docker 镜像或挂载缓存卷。
- Agent Host 启动时做健康检查。
- 对 RAG 初始化失败做降级。

### 9.5 异步任务队列的新风险

Phase 0 引入 ChatTask + Worker 后的新风险：

- **Worker 崩溃**：需要心跳检测 + 超时回收机制，防止 task 永远卡在 processing。
- **Redis 缓冲区过大**：需要设置单 task 缓冲区上限和 TTL。
- **并发限制**：ThreadPoolExecutor `max_workers` 需要与速率限制协调，避免耗尽 DeepSeek API 配额。
- **任务堆积**：需要队列深度监控和拒绝策略。

## 十、审查重点

审查时建议重点看这些问题：

1. Phase 0 三项修复的优先级排序（建议：4.1 命名对齐 -> 4.2 Agent 边界 -> 4.3 任务队列）。
2. 是否接受保留 Flask 主站，而不是全量迁移 FastAPI。
3. MCP 第一版是否只开放只读工具。
4. 高风险动作是否必须人工确认。
5. FastAPI Agent Host 是通过 HTTP adapter 调 Flask，还是抽 shared service 层。
6. Workflow 状态表是否需要和现有 `AgentTask` 合并，还是新建独立表。
7. ChatTask 的 Worker 第一版用 ThreadPoolExecutor 是否足够，还是直接引入 Celery。

## 十一、建议结论

该方案可行，推荐按以下路线执行：

```text
Phase 0：修复现有系统核心缺陷
  - 工具名称对齐 Problem/Question 迁移
  - 去除手动 Agent 选择器 + 能力边界声明 + Generator 卡片渲染
  - 异步任务队列模型（ChatTask + Worker + Redis 缓冲）

Phase 1：FastAPI Agent Host 服务化

Phase 2：Supervisor 多 Agent Workflow

Phase 3：只读 MCP Server

Phase 4：高风险工具与人工审批
```

Phase 0 完成后，项目将解决当前用户体验的三个核心问题：
- AI 工具命名与数据模型一致，内外术语统一。
- Agent 路由自动化，消除用户选错 Agent 的困惑；Generator 输出可视化。
- 对话过程不再依赖连接存活，用户可随时离开和返回。
