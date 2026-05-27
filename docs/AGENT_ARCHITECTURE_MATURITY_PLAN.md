# CodeRunner-AI Agent 架构成熟化改进计划

> 状态：待审查计划，不代表当前已全部实现。
> 目标：在保留在线编程教学业务定位的前提下，借鉴 Claude Code / Anthropic Agent Runtime 的成熟分层思想，把当前内部多 Agent 系统升级为更清晰、更可扩展、更安全的教学 Agent Runtime。

## 1. 结论先行

当前项目的定位应保持为：

```text
面向在线编程教学场景的内部多 Agent 智能辅助系统
+ 外部 DeepSeek LLM Provider
+ 标准化工具接入层
```

更准确的项目描述是：

```text
项目内部实现了 Tutor Agent、Reviewer Agent、Generator Agent 和 Analytics Agent，
用于学习辅导、代码评审、题目生成和学习分析等教学场景；
DeepSeek API 作为外部 LLM Provider，提供底层推理与生成能力；
后续通过 MCP 将代码运行器、题库、提交记录、RAG 和学习分析服务标准化为 Agent 可调用工具。
```

不要把 DeepSeek 称为外部 Agent。DeepSeek 是模型服务提供方，Agent 是项目内部定义的任务执行单元。

## 2. 对 Anthropic / Claude Code 对比文档的修正

对比文档的大方向是正确的：

- Agent 不是模型本身。
- Claude / DeepSeek 是底层模型能力。
- Agent = 任务目标 + 系统提示词 + 上下文 + 工具 + 执行循环 + 权限控制。
- MCP 是工具和资源接入层，不是模型，也不是 Agent 本体。
- 你的项目是垂直领域 Agent 应用；Claude Code 更接近通用 Agent Runtime。

需要修正或收紧的点：

1. **不要写成固定的 Opus -> Sonnet -> Haiku 流程**

   Claude Code 支持 subagent 独立配置模型，也支持根据任务委派给不同 subagent。但这不等于所有任务都会固定先由 Opus 拆解，再交给 Sonnet 或 Haiku。更稳妥的说法是：

   ```text
   Claude Code 可以基于 subagent 描述、工具权限和模型配置，把任务委派给合适的 subagent；
   subagent 可使用不同模型，以平衡能力、速度和成本。
   ```

2. **不要把当前项目描述成已经具备完整 Subagent Runtime**

   当前项目已有业务 Agent 和 LangGraph Orchestrator，但还没有完整具备：

   - subagent 独立上下文窗口
   - subagent 级模型配置
   - subagent 级工具权限隔离
   - 标准化 MCP 工具总线
   - 多模型路由
   - 可恢复的长任务状态机
   - 统一 trace / audit / approval 关联

3. **Anthropic 是参考架构，不是产品定位目标**

   本项目不需要变成通用 Claude Code。更合适的目标是：

   ```text
   把 Claude Code 的 Agent Runtime 思想领域化，
   做成面向编程教学平台的 Education Agent Runtime。
   ```

## 3. 当前项目架构现状

当前已有能力：

| 能力 | 当前状态 |
|---|---|
| 内部业务 Agent | 已有 Tutor / Reviewer / Generator / Analytics |
| Orchestrator | 已有 `AgentOrchestrator`，基于 LangGraph `StateGraph` |
| LLM Provider | DeepSeek API，使用 OpenAI-compatible `ChatOpenAI` |
| 工具调用 | Agent 通过 LangChain tool wrappers 调用代码执行、题目、提交、RAG、统计 |
| RAG | 已有 ChromaDB + sentence-transformers 知识库路径 |
| Trace | 已有 `TraceCollector` 和 AgentRun / AgentRunStep 写入 |
| 异步任务 | 已有 ChatTask / Redis / SSE 恢复方向 |
| MCP | 已有初步 `mcp_server/`，但未成为 Agent 唯一工具边界 |

当前主要不足：

| 不足 | 影响 |
|---|---|
| Agent 仍直接绑定 LangChain tools | 工具边界分散，权限、审计、schema 不统一 |
| Workflow 仍可直接 `get_all_tools()` / `tool.invoke()` | 可能绕过 MCP、安全策略和审计 |
| DeepSeek 配置是单模型入口 | 无法按任务复杂度做成本/速度/能力路由 |
| Agent 间 handoff 较轻量 | 不等同于独立 subagent 执行和结果聚合 |
| Agent Host 仍部分依赖 Flask 执行路径 | Runtime 边界不够清晰 |
| MCP Server 仍是单体实验形态 | 还不是标准工具协议层 |
| Human Gate 与 AgentTask 状态未完全打通 | 高风险工具审批后的恢复执行不够成熟 |
| 权限策略分散 | Agent、工具、API、MCP 之间容易出现重复或绕过 |

## 4. 目标架构

目标不是照搬 Claude Code，而是形成适合教学平台的分层架构：

```text
Frontend Chat UI / Teacher Workflows
  -> Flask API Gateway
  -> Agent Host / Task Runtime
  -> Education Orchestrator
  -> Intent Router / Task Planner
  -> Domain Subagents
       - Tutor Agent
       - Code Reviewer Agent
       - Problem Generator Agent
       - Analytics Agent
       - Safety / Policy Agent
  -> Model Router
       - fast model
       - balanced model
       - strong reasoning model
  -> MCP ToolRuntime
       - Question Bank MCP
       - Submission MCP
       - Code Runner MCP
       - Knowledge / RAG MCP
       - Analytics MCP
  -> Domain Services / Database / Sandbox / Vector DB
```

核心分层：

| 层 | 职责 |
|---|---|
| Flask API Gateway | 认证、业务 API、页面入口、用户会话 |
| Agent Host / Task Runtime | 长任务执行、队列、状态机、SSE 事件、恢复 |
| Education Orchestrator | 理解任务、拆解教学流程、选择 subagent、聚合结果 |
| Domain Subagents | 面向教学角色的专门任务执行单元 |
| Model Router | 按任务复杂度、成本、速度选择模型 |
| MCP ToolRuntime | Agent 唯一工具调用入口 |
| Domain MCP Servers | 标准化暴露题库、提交、代码执行、RAG、学习分析 |
| Observability | trace、audit、metrics、approval 关联 |

## 5. 成熟化设计原则

1. **业务 Agent 继续按教学场景划分**

   不把 Tutor / Reviewer / Generator / Analytics 改成通用代码开发 Agent。它们是教学产品能力，应该保留领域语义。

2. **Orchestrator 升级为 Education Orchestrator**

   当前 Orchestrator 主要做路由、handoff 和 schema 校验。目标 Orchestrator 应承担：

   - 意图识别
   - 用户角色判断
   - 任务拆解
   - subagent 选择
   - 工具权限过滤
   - 中间结果聚合
   - 最终回复风格控制

3. **Subagent 必须有独立上下文和工具边界**

   每个 subagent 至少应定义：

   - agent name
   - purpose / description
   - system prompt
   - allowed tools
   - allowed roles
   - default model tier
   - input schema
   - output schema
   - risk policy

4. **DeepSeek 是 LLM Provider，不是 Agent**

   模型调用必须被封装在 Model Router 后面。即使当前只有 DeepSeek，也不要让业务 Agent 直接依赖具体 provider。

5. **MCP 是唯一工具协议层**

   Agent 和 Workflow 不直接调用数据库、executor、service 或 LangChain tools。所有工具调用经过 MCP ToolRuntime。

6. **高风险动作必须 Human Gate**

   代码执行、保存题目、批量生成、影响学生记录的动作不能由 Agent 静默执行。需要审批、审计和可恢复状态。

## 6. 推荐目标模块

### 6.1 `agent_runtime/`

职责：长任务运行时。

建议模块：

```text
agent_runtime/
├── tasks.py              # AgentTask 状态机
├── worker.py             # 队列消费与任务执行
├── events.py             # SSE / Redis Streams 事件
├── checkpoints.py        # 中间状态持久化
└── recovery.py           # 任务恢复与孤儿任务处理
```

目标状态机：

```text
queued -> running -> waiting_approval -> running -> completed
                     -> rejected
running -> failed
running -> cancelled
```

### 6.2 `education_orchestrator/`

职责：教学任务编排。

建议模块：

```text
education_orchestrator/
├── router.py             # 意图识别和入口路由
├── planner.py            # 多步骤教学任务规划
├── dispatcher.py         # subagent 调度
├── aggregator.py         # 多 agent 结果聚合
└── policies.py           # 教学场景策略
```

### 6.3 `agents/`

职责：领域 subagent。

建议保留现有四类，但标准化定义：

```text
agents/
├── tutor/
│   ├── definition.py
│   ├── prompts.py
│   └── schemas.py
├── reviewer/
├── generator/
├── analytics/
└── safety/
```

每个 `definition.py` 包含：

```python
AGENT_DEFINITION = {
    "name": "tutor",
    "description": "Guide students through coding problems without giving away full answers.",
    "default_model_tier": "balanced",
    "allowed_roles": ["student", "teacher", "admin"],
    "allowed_tools": [
        "coderunner.problem.get_detail",
        "coderunner.submission.list_for_student",
        "coderunner.knowledge.search",
        "coderunner.code.execute",
    ],
    "output_schema": "TutorResponse",
}
```

### 6.4 `model_router/`

职责：模型抽象和路由。

```text
model_router/
├── providers/
│   ├── deepseek.py
│   ├── openai.py
│   └── anthropic.py
├── router.py
├── policy.py
└── usage.py
```

初期可以只有 DeepSeek provider，但接口要支持未来扩展：

```text
fast:
  用于意图分类、摘要、格式化

balanced:
  用于日常辅导、代码 review、普通解释

strong:
  用于复杂 debug、综合分析、题目生成、教学报告
```

### 6.5 `mcp/`

职责：标准化工具接入层。

沿用无兼容层 MCP 标准化计划：

```text
mcp/
├── client/
├── server/
├── adapters/
├── registry/
├── schemas/
├── auth/
├── transport/
├── policies/
├── observability/
└── errors/
```

优先暴露这些领域工具：

```text
coderunner.problem.get_detail
coderunner.problem.search
coderunner.problem.save_generated
coderunner.submission.list_for_student
coderunner.submission.get_detail
coderunner.code.execute
coderunner.knowledge.search
coderunner.knowledge.search_similar_problems
coderunner.analytics.student_activity
coderunner.analytics.class_statistics
coderunner.trace.get_agent_trace
```

## 7. 分阶段落地计划

### Phase A - 修正架构文档和项目定位

目标：先统一术语和真实状态，避免把目标能力写成已实现能力。

交付：

- 更新 `docs/AI_AGENTS.md`，区分当前实现和目标架构。
- 新增或更新架构图，明确：
  - 内部 Agent
  - DeepSeek LLM Provider
  - Agent Host
  - MCP ToolRuntime
  - Domain Services
- 把“外部 Agent”统一改为“外部 LLM Provider”。
- 标注当前 MCP 是部分实现，尚未成为唯一工具边界。

验收：

- 文档中不再把 DeepSeek 称为 Agent。
- 文档中不再把目标 subagent runtime 描述为当前已完成。
- `AI_AGENTS.md` 和本计划术语一致。

### Phase B - 建立 Model Router

目标：让 Agent 不再直接绑定 DeepSeek 具体配置。

交付：

- 新增 `app/agents/model_router/`。
- 抽象 `ModelTier`：`fast`、`balanced`、`strong`。
- DeepSeek 作为第一个 provider。
- Orchestrator 意图分类默认使用 `fast`。
- Tutor / Reviewer 默认使用 `balanced`。
- Generator / Analytics 综合报告默认使用 `strong`。

验收：

- `AIConfig.get_llm()` 不再是 Agent 唯一模型入口。
- 每个 Agent 可声明默认 model tier。
- 测试覆盖不同 tier 解析到 DeepSeek 当前模型。

### Phase C - 标准化 Agent Definition

目标：把 Agent 从“Python 类 + prompt”提升为“可声明、可检查、可路由的 subagent 定义”。

交付：

- 为 Tutor / Reviewer / Generator / Analytics 增加 definition。
- 定义每个 Agent 的：
  - name
  - description
  - allowed roles
  - allowed tools
  - model tier
  - input schema
  - output schema
  - risk level
- Orchestrator 通过 definition 做路由和工具过滤。

验收：

- 新增 Agent 不需要修改多个散落的权限表。
- 测试验证学生不能路由到 Generator 的高风险写入能力。
- Agent description 可用于自动路由。

### Phase D - 引入 Education Orchestrator

目标：从简单 route / handoff 升级为教学任务编排。

交付：

- 新增任务计划结构 `EducationPlan`。
- 支持单步任务：
  - 学生问答 -> Tutor
  - 代码评审 -> Reviewer
  - 教师出题 -> Generator
  - 学情分析 -> Analytics
- 支持多步任务：
  - 获取题目 -> 获取提交 -> 运行测试 -> Review -> Tutor 总结
  - 搜索相似题 -> 生成题目 -> 执行样例 -> 等待教师审批
- 增加 result aggregator。

验收：

- Orchestrator 能输出可追踪的步骤计划。
- 每一步都有 agent、tool、model tier、status。
- 多 Agent 结果可以汇总成最终回复。

### Phase E - MCP 成为唯一工具边界

目标：删除 Agent 直接工具调用路径。

交付：

- 落地 `docs/plans/2026-05-27-phase5-mcp-centric-architecture-plan.md`。
- Agent 和 Workflow 只通过 `mcp.client.ToolRuntime` 调用工具。
- 删除 LangChain `@tool` wrapper。
- 删除 `app/agents/tools/permissions.py` 和 `db_context.py`。
- MCP policies 接管 RBAC、scope、risk、Human Gate。

验收：

- `app/agents` 和 `agent_host` 中不再出现 `tool.invoke()`。
- Workflow `tool_call` 不能绕过 MCP。
- 所有工具调用有 schema、audit、trace、error envelope。

### Phase E2 - 顶层目录拆分（Agent Host / MCP 独立）

目标：MCP 唯一工具边界落地后，把 Agent Runtime 和 MCP 从 `app/` 中拆出为独立顶层模块，形成清晰的三层物理边界。

前置条件：Phase E 完成。Agent 不再直接 import `app.services.*`，所有工具调用经 MCP client。

交付：

- 顶层目录拆为三个独立模块：

  ```text
  CodeRunner-AI/
  ├── app/                 # Flask 主业务系统（登录、题库、提交、页面）
  ├── agent_host/          # FastAPI Agent Runtime（调度 Agent、任务状态机）
  ├── mcp/                 # 标准化工具协议层（Agent 唯一工具入口）
  ├── migrations/
  ├── tests/
  ├── docker/
  ├── docs/
  └── scripts/
  ```

- `app/` 保留业务系统，不放 Agent Runtime：

  ```text
  app/
  ├── api/                 # Flask REST API
  ├── web/                 # Flask 页面路由
  ├── templates/
  ├── static/
  ├── models/              # SQLAlchemy models
  ├── schemas/             # Flask/API schemas
  ├── services/            # 题库、提交、用户、统计等业务服务
  ├── auth/
  ├── core/
  └── utils/
  ```

- `agent_host/` 承载 Agent Runtime：

  ```text
  agent_host/
  ├── main.py              # FastAPI app entry
  ├── api/
  │   ├── chat.py
  │   ├── workflows.py
  │   ├── tasks.py
  │   └── health.py
  ├── runtime/
  │   ├── tasks.py         # AgentTask 状态机
  │   ├── worker.py        # 队列/任务执行
  │   ├── events.py        # SSE / Redis Streams
  │   ├── checkpoints.py
  │   └── recovery.py
  ├── orchestrator/
  │   ├── router.py        # 意图识别
  │   ├── planner.py       # 多步任务计划
  │   ├── dispatcher.py    # 调度 subagent
  │   ├── aggregator.py    # 聚合结果
  │   └── policies.py
  ├── agents/
  │   ├── tutor/
  │   │   ├── definition.py
  │   │   ├── prompts.py
  │   │   └── schemas.py
  │   ├── reviewer/
  │   ├── generator/
  │   ├── analytics/
  │   └── safety/
  ├── model_router/
  │   ├── router.py
  │   ├── policy.py
  │   ├── usage.py
  │   └── providers/
  │       └── deepseek.py
  ├── adapters/
  │   └── flask_client.py  # 必要的 Flask API 调用适配
  ├── core/
  └── models/
  ```

- `mcp/` 放顶层，不放进 `app/` 或 `agent_host/`：

  ```text
  mcp/
  ├── client/
  │   ├── runtime.py       # ToolRuntime，Agent 唯一工具调用入口
  │   ├── sessions.py
  │   └── discovery.py
  ├── server/
  │   ├── shared/
  │   ├── db/
  │   ├── code/
  │   ├── knowledge/
  │   └── analytics/
  ├── adapters/
  ├── registry/
  ├── schemas/
  ├── auth/
  ├── transport/
  ├── policies/
  ├── observability/
  └── errors/
  ```

- 测试按模块拆分：

  ```text
  tests/
  ├── app/                 # Flask 主业务测试
  ├── agent_host/          # FastAPI runtime / workflow / task 测试
  ├── mcp/                 # MCP schema / policy / server contract 测试
  ├── integration/         # Flask + Agent Host + MCP 集成测试
  └── e2e/
  ```

关键边界：

- `app/` 不 import `agent_host/` 或 `mcp/`（通过 HTTP/SSE 通信）
- `agent_host/` 依赖 `mcp/client`，不直接 import `app.services.*`
- `mcp/server` 依赖 `app/services`（数据库、沙箱等域服务）
- 三者可独立启动、独立测试、独立部署

验收：

- `agent_host/` 中不再出现 `from app.agents import ...` 或 `from app.services import ...`。
- `mcp/` 可独立 import，不依赖 Flask app context。
- `app/` 中删除 `agents/` 目录（或仅保留迁移期兼容入口）。
- 三个模块各自有独立的测试套件且全部通过。
- Docker compose 可独立启动 flask / agent_host / mcp_server 三个容器。

### Phase F - Human Gate 与 AgentTask 状态机打通

目标：让高风险工具审批成为 Agent Runtime 的一等能力。

交付：

- `approval_required` 结果让 AgentTask 进入 `waiting_approval`。
- 审批通过后用 `resume_token` 恢复任务。
- 拒绝后由 Agent 生成可解释回复。
- SSE 推送 approval 事件。
- 审批记录、trace、audit 通过 `trace_id` 串联。

验收：

- Generator 保存题目前必须审批。
- 高风险代码执行不会静默执行。
- 刷新页面后仍能看到等待审批状态。
- 审批通过不会重复生成或重复执行。

### Phase G - Observability 和评估闭环

目标：使 Agent 行为可追踪、可评价、可回放。

交付：

- 统一字段：
  - `trace_id`
  - `task_id`
  - `conversation_id`
  - `agent_type`
  - `model_tier`
  - `tool_call_id`
  - `approval_id`
- 增加 Agent run dashboard。
- 增加工具调用延迟、失败率、模型 token 用量。
- 增加离线 eval case：
  - Tutor 是否泄露完整答案
  - Reviewer 是否识别关键错误
  - Generator 是否生成可运行测试
  - Analytics 是否越权读取数据

验收：

- 每次 AI 回复可追踪到模型调用和工具调用。
- 可以按学生、教师、Agent 类型查看失败原因。
- 有最小 eval 集防止 Agent 行为退化。

## 8. 推荐优先级

推荐顺序：

```text
Phase A 文档和术语修正              ✅ 已完成
  -> Phase B Model Router           ✅ 已完成
  -> Phase C Agent Definition       ✅ 已完成
  -> Phase E MCP 唯一工具边界
  -> Phase E2 顶层目录拆分（Agent Host / MCP 独立）
  -> Phase F Human Gate 状态机
  -> Phase D Education Orchestrator 多步编排
  -> Phase G Observability / Eval
```

原因：

- Model Router 和 Agent Definition 是低风险抽象，能先整理边界。
- MCP 唯一工具边界是最大架构收益，应尽早做，但需要配合测试。
- **目录拆分必须在 MCP 唯一边界之后**：拆分前 agents 直接 import app.services，搬到 agent_host/ 会产生跨模块耦合；MCP 收敛后 agents 只依赖 mcp.client，拆分是干净的。
- 多步 Education Orchestrator 应在工具边界和目录结构稳定后做，否则会放大旧工具层问题。
- Observability / Eval 可以贯穿实现，但完整 dashboard 可后置。

## 9. 不建议做的事

- 不建议把项目描述为“接入外部 Agent”。
- 不建议为了模仿 Claude Code 把教学 Agent 改成通用 Coding Agent。
- 不建议在没有 MCP 工具边界前扩大多 Agent 并行编排。
- 不建议长期保留 LangChain tools 和 MCP tools 双轨。
- 不建议让用户身份通过 LLM tool args 传递。
- 不建议把 Human Gate 做成前端提示而不是后端状态机。

## 10. 可用于简历或项目介绍的表述

中文：

```text
设计并实现面向在线编程教学场景的内部多 Agent 智能辅助系统，包含 Tutor、Reviewer、Generator 和 Analytics 等领域 Agent，分别支持学习辅导、代码评审、题目生成和学习分析。系统将 DeepSeek 抽象为外部 LLM Provider，并规划通过 Model Router、Agent Definition、MCP ToolRuntime 和 Human Gate 审批机制，统一管理模型调用、工具权限、任务状态和可观测性。
```

英文：

```text
Designed and implemented a domain-specific multi-agent assistant for an online programming education platform. The system defines internal agents for tutoring, code review, problem generation, and learning analytics, while using DeepSeek as an external LLM provider. The target architecture introduces model routing, declarative agent definitions, an MCP-based tool runtime, human approval gates, and unified observability for safer and more maintainable agent workflows.
```

## 11. 最终目标

最终架构应满足：

- Agent 是项目内部定义的教学任务执行单元。
- DeepSeek 是可替换的外部 LLM Provider。
- Orchestrator 能按教学任务规划和调度 subagents。
- 每个 subagent 有独立定义、工具边界、模型 tier 和输出 schema。
- MCP 是唯一工具接入层。
- 高风险动作有 Human Gate。
- 长任务可恢复。
- 工具调用、模型调用、审批和最终回复可追踪。

这会让项目从“有多个 AI Agent 的教学功能模块”升级为“面向编程教育领域的成熟 Agent Runtime”。
