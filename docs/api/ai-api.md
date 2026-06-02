# AI API 端点参考

> 最后更新: 2026-06-02

AI Agent 模块的 REST API 分两条独立路径：

| 路径 | 服务 | 端口 | 风格 | 用途 |
|---|---|---|---|---|
| `/api/v1/ai/*` | **Flask Web** | 9900 | 同步 / 流式 | 主要面向浏览器，与现有受保护 API 一致的鉴权链路 |
| `/api/chat`, `/api/workflows`, `/api/traces` | **Workers (FastAPI)** | 8100 | 异步任务 + SSE 续传 | 长任务、断线续传、工作流编排，由前端 dashboard 调用 |

两者共享同一数据库与 Redis；JWT `SECRET_KEY` 必须一致以便互认令牌。本文档前半部分（一至五节）描述 Flask 路径，最后一节[Workers 异步路径](#七workers-异步-api路径prefix-api)概述 FastAPI 路径。

API 前缀（Flask）：`/api/v1/ai`

---

## 一、对话

### POST /api/v1/ai/chat

通用对话接口。同步返回完整响应。

**权限**：任意已登录用户

**请求体**：

```json
{
  "message": "我的代码哪里出了问题？",
  "agent_type": "tutor",
  "conversation_id": null,
  "question_id": 5,
  "submission_id": 42,
  "code": "#include <stdio.h>\nint main() { ... }"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 用户消息 |
| agent_type | string | 否 | `tutor` / `reviewer` / `generator` / `analytics`，不填则自动路由 |
| conversation_id | int | 否 | 续接已有对话，不填则新建 |
| question_id | int | 否 | 关联题目 |
| submission_id | int | 否 | 关联提交 |
| code | string | 否 | 当前代码（未提交的代码可直接传入） |

**响应** `200`：

```json
{
  "conversation_id": 1,
  "message_id": 3,
  "agent_type": "tutor",
  "response": "你的循环条件看起来有个问题...",
  "tokens_used": 856
}
```

---

### POST /api/v1/ai/chat/stream

流式对话接口。通过 SSE 逐步返回响应，适合 Tutor 等需要实时交互的场景。

**权限**：任意已登录用户

**请求体**：同 `/chat`

**响应**：`text/event-stream`

```
data: {"type": "start", "conversation_id": 1, "agent_type": "tutor"}

data: {"type": "token", "content": "你的"}

data: {"type": "token", "content": "循环条件"}

data: {"type": "tool_call", "tool": "get_question_detail", "input": {"question_id": 5}}

data: {"type": "tool_result", "tool": "get_question_detail", "summary": "已获取题目信息"}

data: {"type": "token", "content": "看起来有个问题..."}

data: {"type": "done", "message_id": 3, "tokens_used": 856}

data: [DONE]
```

**SSE 事件类型**：

| type | 说明 |
|------|------|
| `start` | 流开始，返回 conversation_id 和路由结果 |
| `token` | 增量文本输出 |
| `tool_call` | Agent 正在调用工具（可在前端显示加载状态） |
| `tool_result` | 工具调用完成 |
| `done` | 流结束，返回 message_id 和统计 |
| `error` | 发生错误 |

---

## 二、代码审查

### POST /api/v1/ai/review

对一段代码进行结构化审查。返回 JSON 格式的审查报告。

**权限**：任意已登录用户

**请求体**：

```json
{
  "code": "...",
  "question_id": 5,
  "language": "c"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | string | 是 | 待审查代码 |
| question_id | int | 否 | 关联题目（提供则审查会结合题目要求） |
| language | string | 否 | 编程语言，默认从 question 读取 |

**响应** `200`：

```json
{
  "conversation_id": 2,
  "review": {
    "overall_score": "B",
    "summary": "逻辑基本正确，但有边界条件遗漏",
    "issues": [
      {
        "severity": "warning",
        "line": 12,
        "message": "未处理空数组情况",
        "suggestion": "在循环前添加长度检查"
      },
      {
        "severity": "info",
        "line": 5,
        "message": "变量名 x 含义不明确",
        "suggestion": "建议改为 count 或 index"
      }
    ],
    "strengths": [
      "整体结构清晰",
      "正确使用了 malloc/free"
    ]
  }
}
```

---

## 三、AI 出题

### POST /api/v1/ai/generate

根据指定条件生成编程题目，含测试用例和参考答案。参考答案经过沙箱验证。

**权限**：Teacher / Admin

**请求体**：

```json
{
  "prompt": "生成一道关于链表反转的题目",
  "topic": "链表",
  "difficulty": "medium",
  "language": "c",
  "test_case_count": 4,
  "quiz_id": 3
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| prompt | string | 是 | 出题要求描述 |
| topic | string | 否 | 知识点标签 |
| difficulty | string | 否 | `easy` / `medium` / `hard`，默认 medium |
| language | string | 否 | 编程语言，默认 python |
| test_case_count | int | 否 | 生成的测试用例数量，默认 4 |
| quiz_id | int | 否 | 直接关联到某个 Quiz |

**响应** `200`：

```json
{
  "conversation_id": 3,
  "question": {
    "title": "链表反转",
    "description": "给定一个单链表的头节点...",
    "programming_language": "c",
    "difficulty": "medium",
    "starter_code": "struct ListNode* reverseList(struct ListNode* head) {\n    // your code\n}",
    "solution": "...",
    "solution_explanation": "使用三指针法...",
    "test_cases": [
      {
        "input": "1 2 3 4 5",
        "expected_output": "5 4 3 2 1",
        "is_hidden": false,
        "weight": 1.0
      }
    ],
    "verified": true
  }
}
```

### POST /api/v1/ai/generate/save

将 AI 生成的题目保存到数据库。

**权限**：Teacher / Admin

**请求体**：

```json
{
  "conversation_id": 3,
  "quiz_id": 3
}
```

**响应** `201`：

```json
{
  "question_id": 15,
  "test_case_count": 4,
  "message": "题目已保存"
}
```

---

## 四、学习分析

### GET /api/v1/ai/analytics/:student_id

生成指定学生的 AI 学习分析报告。

**权限**：
- Student：仅可查看自己（`student_id` = 当前用户）
- Teacher：可查看自己班级内的学生
- Admin：可查看任意学生

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question_id | int | 否 | 限定分析某道题的表现 |
| period | string | 否 | 时间范围：`7d` / `30d` / `all`，默认 `30d` |

**响应** `200`：

```json
{
  "conversation_id": 4,
  "report": {
    "summary": "最近 30 天提交 45 次，正确率从 52% 提升到 78%",
    "error_patterns": [
      {
        "type": "边界条件遗漏",
        "frequency": 12,
        "example_question_ids": [3, 7, 11]
      }
    ],
    "progress": {
      "total_submissions": 45,
      "acceptance_rate": 0.78,
      "trend": "improving"
    },
    "weak_areas": ["数组边界处理", "指针操作"],
    "recommendations": [
      {
        "question_id": 9,
        "title": "数组旋转",
        "reason": "针对边界条件的练习题"
      }
    ]
  }
}
```

---

## 五、对话历史

### GET /api/v1/ai/conversations

获取当前用户的 AI 对话列表。

**权限**：任意已登录用户

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_type | string | 否 | 按 Agent 类型过滤 |
| limit | int | 否 | 默认 20 |
| offset | int | 否 | 默认 0 |

**响应** `200`：

```json
{
  "items": [
    {
      "id": 1,
      "agent_type": "tutor",
      "title": "关于第5题的求助",
      "context_type": "question",
      "context_id": 5,
      "message_count": 6,
      "created_at": "2026-05-19T10:30:00",
      "updated_at": "2026-05-19T10:35:00"
    }
  ],
  "total": 15
}
```

### GET /api/v1/ai/conversations/:id

获取单个对话的完整消息列表。

**权限**：对话所有者 / Admin

**响应** `200`：

```json
{
  "id": 1,
  "agent_type": "tutor",
  "title": "关于第5题的求助",
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "我的代码哪里出了问题？",
      "created_at": "2026-05-19T10:30:00"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "你的循环条件看起来有个问题...",
      "tool_calls": [
        {"tool": "get_question_detail", "input": {"question_id": 5}}
      ],
      "tokens_used": 856,
      "created_at": "2026-05-19T10:30:05"
    }
  ]
}
```

### DELETE /api/v1/ai/conversations/:id

删除一个对话及其所有消息。

**权限**：对话所有者 / Admin

**响应** `204`

---

## 五-B、Trace 与 Eval

完整的运行时可观测面。Trace/eval 数据落在 runtime-neutral 表（`agent_trace_*` / `eval_*`，
plain SQLAlchemy），由 workers / eval harness 直接写入；下列端点只读聚合并按角色脱敏。

**权限**：Teacher / Admin（学生仅可见自己的 trace，且隐藏 tool args / system prompt）

### GET /api/v1/ai/traces

Trace 列表。支持过滤参数：`agent_type`、`status`、`source`、`eval_run_id`、`conversation_id`、
`chat_task_id`、`from`、`to`、`q`、`limit`、`offset`。

### GET /api/v1/ai/traces/:trace_id

返回单条完整 trace。旧 `agent_runs.id` 走只读 fallback。

```json
{
  "run": { "trace_id": "...", "agent_type": "tutor", "status": "completed",
           "tokens_input": 120, "tokens_output": 80, "cost_cny": 0.0021,
           "total_latency_ms": 1500 },
  "spans": [ { "span_type": "llm", "name": "deepseek-chat", "latency_ms": 900 },
             { "span_type": "tool", "name": "coderunner.search", "status": "completed" } ],
  "events": [ ... ],
  "artifacts": [ ... ],
  "links": [ { "link_type": "chat_task", "target_table": "agent_tasks", "target_id": "..." } ]
}
```

### POST /api/v1/ai/evals/run

运行 eval suite（harness）。请求体 `{ "selector": "golden:tutor", "model_name": "deepseek-chat" }`，
返回 `{ "report": { "eval_run_id": N, ... } }`。

### GET /api/v1/ai/evals/history

eval 运行历史列表（`?limit=30`）。

### GET /api/v1/ai/evals/runs/:run_id

完整 eval 报告：`summary`（pass_rate、cost_cny、latency_ms、grader_pass_rates、failure_types、
regressions）+ `cases`（逐 case，含 `trace_id`）。`?compare_to=<eval_run_id>` 指定回归对比基线。

### GET /api/v1/ai/evals/cases/by-trace/:trace_id

按 trace 反查 eval case 及其 grader 结果；无匹配返回 `{ "case": null }`。

### POST /api/v1/ai/evals/promote-regression

把一条失败 trace 提升为 regression dataset case。请求体 `{ "trace_id": "...", "reason": "..." }`。

---

## 六、错误响应

所有 AI 端点共用以下错误格式：

```json
{
  "error": "ai_rate_limit",
  "message": "请求过于频繁，请稍后再试"
}
```

| HTTP 状态码 | error 值 | 说明 |
|------------|---------|------|
| 400 | `invalid_request` | 请求参数校验失败 |
| 401 | `unauthorized` | 未登录 |
| 403 | `forbidden` | 无权访问（如学生访问出题接口） |
| 429 | `ai_rate_limit` | 超过每分钟请求限制 |
| 500 | `ai_service_error` | LLM 调用失败 |
| 503 | `ai_unavailable` | AI 服务暂不可用（API Key 未配置等） |

---

## 七、Workers 异步 API（路径前缀 `/api`）

`workers/__main__.py` 通过 FastAPI 暴露在 `:8100`，由前端 dashboard 直接调用以承载长任务和续传场景。所有端点同样要求 JWT（同 Flask `SECRET_KEY`）。

### 7.1 异步聊天 — `app/api/v1/agents/chat.py`

| 方法 + 路径 | 说明 |
|---|---|
| `POST /api/chat` | 创建异步聊天任务，返回 `task_id` |
| `GET /api/chat/task/{id}` | 轮询任务状态（pending/running/done/error）|
| `GET /api/chat/task/{id}/stream` | SSE 流式输出，支持 `Last-Event-ID` 头实现断线续传 |

`/api/chat` 请求体：

```json
{ "message": "...", "agent_type": "auto", "conversation_id": null }
```

### 7.2 工作流 — `app/api/v1/agents/workflows.py`

| 方法 + 路径 | 说明 |
|---|---|
| `POST /api/workflows` | 启动一个工作流 run（如批量题目生成）|
| `GET /api/workflows/{run_id}` | 查询 run + 全部 step 状态 |
| `POST /api/workflows/{run_id}/cancel` | 取消未完成的 run |

### 7.3 Trace 查询 — `app/api/v1/agents/traces.py`

| 方法 + 路径 | 说明 |
|---|---|
| `GET /api/traces?agent_type=tutor&user_id=...` | 列出 AgentRun |
| `GET /api/traces/{run_id}` | 获取单个 run 的完整 step 序列（含 tool_calls / tool_results）|

> 这三套端点也使用本文档 §六 定义的错误响应格式，并额外可能返回：
> - `404 task_not_found` / `run_not_found` — 任务或运行不存在
> - `409 task_already_done` — 重复取消已完成任务
