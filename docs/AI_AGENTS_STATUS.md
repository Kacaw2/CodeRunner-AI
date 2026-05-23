# AI Agents 模块能力总览

> 最后更新: 2026-05-24 (Phase A/B/C 全部完成)

---

## 一、系统架构概述

CodeRunner-AI 的 AI 模块基于 **Flask + LangGraph + LangChain + DeepSeek API** 构建，采用多 Agent 协作架构：

```
用户请求 → API 端点 (ai.py)
           ├── 安全检测 (detect_injection + sanitize_user_input)
           ├── 限流 (Redis rate limiting)
           ├── Orchestrator (LangGraph 状态图)
           │    ├── 意图分类 (_classify_intent)
           │    ├── Agent 路由 (tutor/reviewer/generator/analytics)
           │    ├── 工具调用 (_run_tools + 权限检查)
           │    ├── Handoff 检测 (detect_handoff)
           │    └── Trace 记录 (TraceCollector)
           └── 输出过滤 (filter_output) → DB 存储
```

---

## 二、已实现且运行中的能力 (ACTIVE)

### 2.1 Agent 类型

| Agent | 文件 | 用途 | 工具集 |
|-------|------|------|--------|
| **TutorAgent** | `agents/tutor.py` | 学生编程辅导、提示、解释 | execute_code, get_question_detail, get_student_submissions, get_submission_detail, search_knowledge, search_error_patterns |
| **ReviewerAgent** | `agents/reviewer.py` | 代码审查、结构化评分报告 | execute_code, get_question_detail |
| **GeneratorAgent** | `agents/generator.py` | 教师出题（含自验证循环） | execute_code, search_similar_questions |
| **AnalyticsAgent** | `agents/analytics.py` | 学习分析报告、成绩趋势 | get_question_detail, get_student_submissions, get_submission_detail, get_student_stats, get_student_activity, get_class_statistics, get_question_difficulty_stats |

### 2.2 核心基础设施

| 能力 | 文件 | 说明 |
|------|------|------|
| **Orchestrator 路由** | `orchestrator.py` | LangGraph 状态图，支持 LLM 意图分类自动路由，`agent_type=auto` 时自动选择 Agent |
| **Agent Handoff** | `handoff.py` | Agent 间交接机制，最多 2 次 handoff，阻止循环和学生→generator |
| **工具权限检查** | `tools/permissions.py` | 按 agent_type + user_role 控制工具访问 |
| **安全参数注入** | `base.py:_inject_security` | 覆盖工具参数中的 user_id/student_id，防止越权访问 |
| **LLM 调用重试** | `base.py:_llm_invoke` | 自动重试 2 次，指数退避 |
| **工具调用重试** | `base.py:_run_tools` | 单工具失败自动重试 1 次 |

### 2.3 安全能力 (Phase A 已完成)

| 能力 | 状态 | 说明 |
|------|------|------|
| **注入检测** | ✅ 已接入 | 12 种 regex 模式检测 prompt injection，在 /chat 和 /chat/stream 入口检查 |
| **输入消毒** | ✅ 已接入 | 移除 `<system>` 标签和 `system:` 前缀 |
| **输出过滤** | ✅ 已接入 | 对学生隐藏 `is_hidden: true` 测试用例，截断超长代码块 (>8行) |
| **动态安全警告** | ✅ 已接入 | 检测到注入时，在 system prompt 头部追加安全警告（不阻断请求） |
| **审计日志** | ✅ 已接入 | 注入检测命中时写入 `AIAuditLog` |

### 2.4 追踪 (Tracing)

| 能力 | 状态 | 说明 |
|------|------|------|
| **AgentRun 记录** | ✅ 已接入 | 每次 invoke/stream 调用写入 `agent_runs` 表 |
| **AgentRunStep 记录** | ✅ 已接入 | 每个 LLM/工具调用步骤写入 `agent_run_steps` 表 (Phase B4) |
| **LLM 调用计时** | ✅ 已接入 | `trace_llm_call()` 记录每次 LLM 调用耗时 |
| **工具调用计时** | ✅ 已接入 | `trace_tool_call()` 记录每次工具调用耗时和成功/失败 |
| **Token 采集 (流式+同步)** | ✅ 已接入 | 从 response 的 `response_metadata` / `usage_metadata` 提取 token 数 (Phase B5) |
| **Trace API** | ✅ 已接入 | `GET /api/v1/ai/traces` 和 `GET /api/v1/ai/traces/<run_id>` |

### 2.5 API 端点

| 端点 | 方法 | 状态 | 说明 |
|------|------|------|------|
| `/api/v1/ai/chat` | POST | ✅ | 同步聊天，走 Orchestrator 完整管道 |
| `/api/v1/ai/chat/stream` | POST | ✅ | SSE 流式聊天，支持 auto-route |
| `/api/v1/ai/review` | POST | ✅ | 结构化代码审查 |
| `/api/v1/ai/generate` | POST | ✅ | 单题生成（含自验证） |
| `/api/v1/ai/generate/save` | POST | ✅ | 保存生成题目到题库 |
| `/api/v1/ai/generate/batch` | POST | ✅ | 批量题目生成（BatchTaskRunner） |
| `/api/v1/ai/generate/pipeline` | POST | ✅ | 多阶段生成管线（生成→验证→去重→质量审查） |
| `/api/v1/ai/generate/to-draft` | POST | ✅ | 保存为草稿待审 |
| `/api/v1/ai/generate/drafts` | GET | ✅ | 列出待审草稿 |
| `/api/v1/ai/generate/drafts/<id>` | GET | ✅ | 获取草稿详情 |
| `/api/v1/ai/generate/drafts/<id>/review` | POST | ✅ | 审批/拒绝/修订草稿 |
| `/api/v1/ai/conversations` | GET | ✅ | 列出对话 |
| `/api/v1/ai/conversations/<id>` | GET/DELETE | ✅ | 获取/删除对话 |
| `/api/v1/ai/analytics/<student_id>` | GET | ✅ | 学生学习分析报告 |
| `/api/v1/ai/profile` | GET/PUT | ✅ | 学生画像 / 教师偏好 |
| `/api/v1/ai/profile/refresh` | POST | ✅ | 手动刷新学生画像 |
| `/api/v1/ai/profile/refresh-style` | POST | ✅ | 刷新教师风格摘要 |
| `/api/v1/ai/profile/refresh-class-analysis` | POST | ✅ | 班级薄弱点分析 |
| `/api/v1/ai/tasks/<task_id>` | GET | ✅ | 查询异步任务状态 |
| `/api/v1/ai/tasks/<task_id>/retry` | POST | ✅ | 重试失败任务 |
| `/api/v1/ai/knowledge/index` | POST | ✅ | 手动触发知识库索引 |
| `/api/v1/ai/traces` | GET | ✅ | Agent 运行追踪列表 |
| `/api/v1/ai/traces/<run_id>` | GET | ✅ | Agent 运行详情 |
| `/api/v1/ai/evals/run` | POST | ✅ | 运行评估套件 |
| `/api/v1/ai/evals/history` | GET | ✅ | 评估历史 |

### 2.6 消息处理 (Phase B)

| 能力 | 状态 | 说明 |
|------|------|------|
| **长对话压缩** | ✅ 已接入 | `compact_messages()` 在 `_invoke_with_tools` / `_stream_with_tools` 中自动压缩超过 20 条的消息 (Phase B1) |
| **对话摘要生成** | ✅ 已接入 | 消息数 ≥10 时异步生成摘要，存入 `AIConversation.summary` (Phase B2) |
| **Schema 输出校验** | ✅ 已接入 | orchestrator `_respond` 节点校验 generator/reviewer/analytics 输出，失败自动重试 (Phase B3) |

### 2.7 启动集成 & 自动化 (Phase C)

| 能力 | 状态 | 说明 |
|------|------|------|
| **孤儿任务恢复** | ✅ 已接入 | `create_app()` 启动时同步调用 `recover_orphaned_tasks()`，将 executing 状态任务重置为 pending (C1) |
| **知识库自动索引** | ✅ 已接入 | `create_app()` 启动后台线程异步执行 `index_all_questions()`，不阻塞启动 (C2) |
| **学生画像自动更新** | ✅ 已接入 | 提交判题后异步调用 `update_student_profile()`，60 秒每学生节流 (C3) |
| **新题增量索引** | ✅ 已接入 | 题目发布为正式 Problem 时自动调用 `kb.index_question()` (C4) |

### 2.8 其他已接入能力

| 能力 | 说明 |
|------|------|
| **记忆上下文** | `MemoryService.get_memory_context()` 为每个 Agent 注入学生画像或教师偏好 |
| **教师偏好学习** | 成功生成题目后自动调用 `learn_from_generation()` 更新偏好 |
| **知识库搜索** | Tutor 可搜索知识点 (`search_knowledge`) 和错误模式 (`search_error_patterns`) |
| **相似题搜索** | Generator 可搜索相似题目避免重复 (`search_similar_questions`) |
| **批量任务** | BatchTaskRunner 支持多题批量生成，含重试和进度追踪 |
| **生成管线** | 多阶段管线：生成→验证→去重→质量审查→定稿 |
| **草稿工作流** | 生成→草稿→教师审批→发布到题库，支持修订循环 |
| **评估框架** | EvalRunner 支持 JSON 测试套件，可验证 Agent 输出质量 |

---

## 三、已定义但未接入的能力 (待实现)

### 3.1 Phase D — RAG 与知识库深度集成 (优先级: 低)

| 能力 | 文件 | 现状 | 计划 |
|------|------|------|------|
| **错误模式种子数据** | 待新建 `scripts/seed_knowledge.py` | error_patterns 集合为空 | 预填充 CE/RE/WA/TLE 常见错误模式（Python + C） |
| **知识点种子数据** | 待新建 `scripts/seed_knowledge.py` | knowledge_points 集合为空 | 按课程大纲填充数据结构/算法/编程基础知识点 |
| **教师知识库管理 API** | 待添加到 `ai.py` | 无管理接口 | 添加知识点的增删查 API + 前端管理页面 |

### 3.2 Generator 流式路径 (Phase A5 遗留)

GeneratorAgent 的 `stream()` 方法仍使用直接 LLM 调用，未通过 `_invoke_with_tools` / `_run_tools` 管道。这意味着：
- 流式路径的验证执行无权限检查
- 流式路径的 LLM 调用无独立 trace (依赖 base 的 stream 实现时除外)

`invoke()` 路径已完成统一。

---

## 四、各 Phase 完成度

```
Phase A (安全修复)     ████████░░  ~85%
  A1 filter_output stream   ✅ 完成
  A2 stream orchestrator    ✅ 完成
  A3 stream tracing         ✅ 完成
  A4 stream handoff         ✅ 完成
  A5 generator 统一管道      ⚠️ invoke 完成, stream 待补
  A6 注入检测增强            ✅ 完成

Phase B (死代码激活)   ██████████  100%
  B1 长对话压缩             ✅ 完成
  B2 对话摘要               ✅ 完成
  B3 schema 校验            ✅ 完成
  B4 TraceStep 写入         ✅ 完成
  B5 token 采集             ✅ 完成 (流式+同步)

Phase C (启动集成)     ██████████  100%
  C1 孤儿任务恢复           ✅ 完成
  C2 知识库自动索引         ✅ 完成
  C3 学生画像自动更新       ✅ 完成
  C4 新题增量索引           ✅ 完成

Phase D (RAG 深度集成)  ░░░░░░░░░░  ~0%
  D1 error_patterns 种子    ❌ 未开始
  D2 knowledge_points 种子  ❌ 未开始
  D3 教师知识库管理 API     ❌ 未开始
```

---

## 五、文件清单

### 核心模块 (`app/agents/`)

| 文件 | 用途 |
|------|------|
| `__init__.py` | 导出 AgentOrchestrator |
| `config.py` | AIConfig (LLM 配置)、限流参数、最大迭代数 |
| `state.py` | AgentState TypedDict 定义 |
| `exceptions.py` | AIError、LLMError、RateLimitError 等 |
| `orchestrator.py` | LangGraph 状态图、意图分类、handoff 路由 |
| `security.py` | 注入检测、输入消毒、输出过滤、安全 prompt |
| `handoff.py` | Agent 间交接检测与 prompt 附录 |
| `tracing.py` | TraceCollector 类 (AgentRun 写入) |
| `memory.py` | MemoryService (记忆上下文、压缩、摘要、画像更新) |
| `knowledge_base.py` | ChromaDB 知识库 (索引、搜索、RAG) |
| `schemas.py` | Agent 输出 JSON Schema 定义与校验 |
| `recovery.py` | 孤儿任务恢复 |
| `batch_runner.py` | 批量任务运行器 |
| `generation_pipeline.py` | 多阶段生成管线 |
| `preference_learner.py` | 教师偏好学习 |

### Agent 实现 (`app/agents/agents/`)

| 文件 | Agent |
|------|-------|
| `base.py` | BaseAgent 抽象基类 |
| `tutor.py` | TutorAgent |
| `reviewer.py` | ReviewerAgent |
| `generator.py` | GeneratorAgent |
| `analytics.py` | AnalyticsAgent |

### 工具 (`app/agents/tools/`)

| 文件 | 工具 |
|------|------|
| `code_executor.py` | execute_code (沙箱执行) |
| `question_query.py` | get_question_detail |
| `submission_query.py` | get_student_submissions, get_submission_detail |
| `analytics_query.py` | get_student_stats, get_student_activity, get_class_statistics, get_question_difficulty_stats |
| `knowledge_tools.py` | search_knowledge, search_error_patterns, search_similar_questions |
| `permissions.py` | check_tool_permission |

### 数据模型

| 文件 | 模型 |
|------|------|
| `models/ai_conversation.py` | AIConversation, AIMessage |
| `models/agent_trace.py` | AgentRun, AgentRunStep |
| `models/agent_task.py` | AgentTask |
| `models/ai_audit_log.py` | AIAuditLog |
| `models/student_profile.py` | StudentProfile, TeacherPreference |
| `models/generated_question_draft.py` | GeneratedQuestionDraft |
| `models/eval_run.py` | EvalRun |
