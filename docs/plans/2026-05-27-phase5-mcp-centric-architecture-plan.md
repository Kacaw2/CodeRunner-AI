# Phase 5 - 无兼容层 MCP 标准化架构改造计划

> 目标：把 CodeRunner-AI 的所有 Agent 工具调用、Workflow 工具步骤、外部工具入口统一收敛到 MCP 协议边界。
> 本计划不保留 LangChain `@tool` 兼容层、不保留 `USE_MCP_CLIENT` 双轨开关、不保留旧 `mcp_server/` 单体并行路径。

## 1. 设计原则

1. **MCP 是唯一工具边界**
   Agent、Workflow、外部客户端都只能通过 `mcp.client` 调用工具。禁止在 Agent 层直接 import `app.agents.tools.*`、`get_all_tools()` 或 `tool.invoke()`。

2. **身份不进入 LLM 可控参数**
   `user_id`、`role`、`tenant`、`trace_id` 等可信上下文由 MCP transport/auth 层注入 request context，不放入 tool args，也不允许 LLM 覆盖。

3. **工具 schema 以 MCP 为源头**
   工具输入、输出、错误、风险等级、审批策略、权限策略都在 `mcp/` 下定义。Agent 只消费 MCP registry 暴露的工具 schema。

4. **删除兼容层，而不是长期包裹旧实现**
   旧 LangChain `@tool` wrapper、旧 Agent 权限矩阵、旧 ContextVar DB session、旧单体 MCP server 都在本阶段清理。业务实现可以迁移为 domain service，但不能继续作为 Agent 工具体系存在。

5. **回滚依赖 Git 和部署版本**
   不做运行时双轨回退。回滚方式是回退提交、镜像 tag 或部署版本，避免生产长期存在两套工具执行路径。

## 2. 目标架构

```text
用户输入
  -> Flask / Agent Host API
  -> AgentTask worker
  -> SupervisorAgent / SpecialistAgent / WorkflowEngine
  -> mcp.client.ToolRuntime
  -> mcp.transport.ClientSession
  -> MCP Server domain boundary
  -> mcp.policies / mcp.auth / mcp.observability
  -> domain services / database / sandbox / knowledge base
```

目标目录：

```text
mcp/
├── client/              # Agent/Workflow 唯一工具调用入口
├── server/              # MCP Server 进程和领域工具注册
├── adapters/            # MCP schema/result 与 LLM/Agent 消息之间的转换
├── registry/            # 工具注册、发现、路由、健康检查、版本约束
├── schemas/             # canonical input/output/error JSON Schema
├── auth/                # service token、API key、用户身份、租户隔离
├── transport/           # stdio / SSE / streamable HTTP 通信封装
├── policies/            # RBAC、scope、risk level、Human Gate、白名单
├── observability/       # audit、trace、metrics、correlation id
└── errors/              # 错误码、异常映射、重试策略
```

领域 Server：

```text
mcp/server/
├── shared/
│   ├── lifecycle.py
│   ├── context.py
│   ├── db.py
│   └── bootstrap.py
├── db/
│   ├── server.py
│   └── tools/
│       ├── problems.py
│       ├── submissions.py
│       └── students.py
├── code/
│   ├── server.py
│   └── tools/
│       └── executor.py
├── knowledge/
│   ├── server.py
│   └── tools/
│       └── search.py
└── analytics/
    ├── server.py
    └── tools/
        ├── stats.py
        └── traces.py
```

## 3. 当前不符合目标的路径

| 当前路径 | 问题 | Phase 5 处理 |
|---|---|---|
| `app/agents/agents/base.py::_run_tools()` | 直接查权限、注入参数、调用 `tool.invoke()` | 删除直接工具执行，改为 `mcp.client.ToolRuntime.call()` |
| `app/agents/agents/base.py::_inject_security()` | 在 Agent 层修正 LLM 参数，安全边界太靠后 | 删除，迁移到 `mcp/auth` 和 `mcp/policies` |
| `app/agents/workflow/registry.py::_handle_tool_call()` | Workflow 可绕过 MCP 直接执行工具 | 改为 MCP tool step executor |
| `app/agents/tools/*.py` | LangChain `@tool` wrapper 是旧工具层 | 删除 wrapper，业务实现迁移到 domain service |
| `app/agents/tools/permissions.py` | Agent 侧权限矩阵与 MCP 权限重复 | 迁移到 `mcp/policies/rbac.py` |
| `app/agents/tools/db_context.py` | Agent Host 通过 ContextVar 给工具传 DB session | 删除，MCP Server 自主管理 DB session |
| `mcp_server/` | 单体 server，目录边界不标准 | 迁移到 `mcp/server/*` 后删除 |
| `mcp_server.middleware.mcp_tool_middleware()` | 标注为 backward-compat | 删除 decorator 兼容形态，只保留标准 guard pipeline |
| `MCP_API_KEY` 进程级身份 | 多用户 Agent 调用无法表达 per-request caller | 改为每次 MCP request 带 service token，服务端解析 caller context |

## 4. 标准模块职责

### 4.1 `mcp/client`

职责：

- 维护 MCP server 连接池。
- 从 registry 拉取工具 schema。
- 为 Agent/Workflow 过滤可见工具。
- 执行工具调用并返回标准 `ToolResult`。
- 对 transient transport error 做有限重试。
- 把 `approval_required`、`permission_denied`、`rate_limited` 等结果转换为 Agent/Workflow 可处理事件。

核心接口：

```python
class ToolRuntime:
    async def list_tools(self, scope: ToolScope) -> list[ToolDescriptor]:
        ...

    async def call(
        self,
        tool_name: str,
        args: dict,
        context: ToolCallContext,
    ) -> ToolResult:
        ...
```

禁止事项：

- 不接受 LangChain `BaseTool`。
- 不调用旧 `app.agents.tools`。
- 不通过 tool args 注入 `user_id`、`role`。

### 4.2 `mcp/adapters`

职责：

- `mcp_to_llm.py`：把 MCP input schema 转为模型 tool-calling schema。
- `llm_to_mcp.py`：把模型返回的 tool call 解析成 MCP call request。
- `result_to_message.py`：把 MCP result/error 转成 `ToolMessage`、SSE event 或 workflow step output。

边界：

- 这里是协议适配，不是旧工具兼容。
- 可以使用 LangChain LLM 客户端发送 tool schema，但不能把 MCP tool 包装成旧 `BaseTool`。

### 4.3 `mcp/registry`

职责：

- 注册 server endpoint、transport、健康状态。
- 建立 `tool_name -> server` 路由。
- 校验 tool name 全局唯一。
- 缓存 schema，并通过 version/hash 检测变更。
- 支持按 agent、role、risk level 过滤工具。

工具命名采用命名空间，避免多 server 冲突：

```text
coderunner.problem.get_detail
coderunner.submission.list_for_student
coderunner.submission.get_detail
coderunner.knowledge.search
coderunner.knowledge.search_similar_problems
coderunner.knowledge.search_error_patterns
coderunner.code.execute
coderunner.analytics.student_activity
coderunner.analytics.class_statistics
coderunner.analytics.problem_difficulty
coderunner.trace.get_agent_trace
coderunner.problem.save_generated
coderunner.approval.check
```

### 4.4 `mcp/schemas`

每个工具必须有：

- `name`
- `version`
- `description`
- `input_schema`
- `output_schema`
- `error_schema`
- `risk_level`
- `required_scopes`
- `approval_policy`
- `timeout_ms`
- `retry_policy`

示例：

```python
TOOL_DESCRIPTOR = {
    "name": "coderunner.code.execute",
    "version": "1.0.0",
    "risk_level": "high",
    "required_scopes": ["code:execute"],
    "approval_policy": "teacher_required",
    "timeout_ms": 10000,
    "retry_policy": {"max_attempts": 0},
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "maxLength": 10000},
            "language": {"type": "string", "enum": ["python", "c"]},
            "stdin_text": {"type": "string", "default": ""}
        },
        "required": ["code", "language"],
        "additionalProperties": False
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": ["integer", "null"]}
        },
        "required": ["status"]
    },
}
```

### 4.5 `mcp/auth`

职责：

- 校验 Agent Host 到 MCP Server 的 service token。
- 从 token 或 signed request 中解析 `user_id`、`role`、`tenant_id`、`session_id`。
- 校验外部 MCP API key。
- 生成不可被 LLM 修改的 `CallerContext`。

`CallerContext`：

```python
class CallerContext(TypedDict):
    actor_type: Literal["agent_host", "external_client"]
    user_id: int
    role: Literal["student", "teacher", "admin"]
    tenant_id: str | None
    api_key_id: str | None
    task_id: str | None
    conversation_id: str | None
    trace_id: str
```

规则：

- Agent Host 内部调用使用 service token + signed caller context。
- 外部客户端使用 MCP API key。
- tool args 中出现 `user_id`、`role`、`teacher_id`、`student_id` 时，按 policy 重写或拒绝。

### 4.6 `mcp/policies`

职责：

- RBAC：角色能否访问工具。
- Scope：API key 或 internal caller 是否有工具 scope。
- Risk：低/中/高风险工具策略。
- Human Gate：审批创建、审批状态、恢复执行。
- Data policy：学生只能访问自己的 submission，教师只能访问自己班级/题目范围。

示例策略：

```text
low:
  - 可直接执行
  - 必须审计

medium:
  - 教师/admin 可执行
  - 学生默认拒绝
  - 输出需要脱敏

high:
  - 默认进入 approval_required
  - 审批通过后由 server 执行
  - 不允许自动重试
```

### 4.7 `mcp/observability`

统一关联字段：

```text
trace_id
task_id
conversation_id
agent_type
tool_call_id
tool_name
server_name
user_id
role
status
latency_ms
error_code
approval_id
```

要求：

- Agent trace 记录 LLM tool call 请求。
- MCP audit 记录 server 实际执行。
- Human Gate 记录审批生命周期。
- SSE event 使用相同 `trace_id` 和 `tool_call_id`。
- metrics 至少包含 call count、latency、error count、approval wait time。

### 4.8 `mcp/errors`

标准错误码：

```text
MCP_AUTH_REQUIRED
MCP_PERMISSION_DENIED
MCP_SCOPE_DENIED
MCP_RATE_LIMITED
MCP_APPROVAL_REQUIRED
MCP_APPROVAL_PENDING
MCP_APPROVAL_REJECTED
MCP_TOOL_NOT_FOUND
MCP_SCHEMA_INVALID
MCP_ARGUMENT_INVALID
MCP_TRANSPORT_UNAVAILABLE
MCP_TOOL_TIMEOUT
MCP_INTERNAL_ERROR
```

错误返回 envelope：

```json
{
  "ok": false,
  "error": {
    "code": "MCP_PERMISSION_DENIED",
    "message": "Tool is not available for this role.",
    "retryable": false
  },
  "trace_id": "..."
}
```

## 5. 标准调用协议

### 5.1 成功结果

```json
{
  "ok": true,
  "tool": "coderunner.problem.get_detail",
  "data": {
    "problem_id": 1,
    "title": "Two Sum"
  },
  "trace_id": "...",
  "tool_call_id": "...",
  "latency_ms": 18
}
```

### 5.2 审批结果

```json
{
  "ok": false,
  "tool": "coderunner.code.execute",
  "status": "approval_required",
  "approval_id": "...",
  "resume_token": "...",
  "message": "代码执行需要教师审批。",
  "trace_id": "...",
  "tool_call_id": "..."
}
```

### 5.3 Agent 处理规则

- `ok=true`：作为 tool result 继续 LLM loop。
- `approval_required`：暂停当前 AgentTask，状态改为 `waiting_approval`，向 SSE 输出审批事件。
- `approval_pending`：保持等待，不重复创建审批。
- `approval_rejected`：把拒绝原因写回 AgentTask，允许 Agent 生成解释。
- `permission_denied`：作为受控工具错误返回模型，但不泄露内部策略细节。
- `transport_unavailable`：按 retry policy 重试，仍失败则任务失败或降级为可解释错误。

## 6. Agent 与 Workflow 改造

### 6.1 `BaseAgent`

删除：

- `_run_tools(tool_calls, tools, state)`
- `_inject_security(tool_name, args, state)`
- `tools: list[BaseTool]` 参数
- 旧 `check_tool_permission()` 调用
- 旧 `tool.invoke()` 调用

新增：

```python
async def _invoke_with_mcp_tools(
    self,
    state: AgentState,
    tool_names: list[str],
    system_ctx: str,
) -> AgentState:
    ...
```

同步入口如果仍存在，只能包装 async runtime，不能绕过 MCP。

### 6.2 Specialist Agent

每个 Agent 只声明工具名：

```python
TUTOR_TOOLS = [
    "coderunner.code.execute",
    "coderunner.problem.get_detail",
    "coderunner.submission.list_for_student",
    "coderunner.submission.get_detail",
    "coderunner.knowledge.search",
    "coderunner.knowledge.search_error_patterns",
]
```

禁止：

- `from app.agents.tools... import ...`
- `TUTOR_TOOLS = [execute_code, get_problem_detail]`

### 6.3 WorkflowEngine

`tool_call` step 改为：

```python
async def _handle_tool_call(step_def: dict, context: dict) -> dict:
    runtime = get_tool_runtime()
    return await runtime.call(
        tool_name=step_def["tool_name"],
        args=step_def.get("tool_args", {}),
        context=build_tool_context(context),
    )
```

这样 Workflow 不能绕过 MCP，也能统一审计、审批和权限。

### 6.4 Generator 多轮校验

Generator 中的校验循环也必须通过 MCP：

- 生成题目草稿。
- 调用 `coderunner.code.execute` 校验样例。
- 如需保存，调用 `coderunner.problem.save_generated`。
- 高风险调用进入 Human Gate。
- 恢复后继续同一个 AgentTask，不重新生成题目。

## 7. Server 拆分

### 7.1 DB Server

端口：`8201`

工具：

- `coderunner.problem.get_detail`
- `coderunner.submission.list_for_student`
- `coderunner.submission.get_detail`
- `coderunner.student.get_summary`
- `coderunner.problem.save_generated`

职责：

- 管理问题、提交、学生数据读取。
- 执行数据级权限过滤。
- 写操作必须走 Human Gate 或明确 teacher/admin policy。

### 7.2 Code Server

端口：`8202`

工具：

- `coderunner.code.execute`

职责：

- 调用 sandbox executor。
- 校验语言、代码长度、运行时限制。
- 高风险审批。
- 不允许自动重试执行代码。

### 7.3 Knowledge Server

端口：`8203`

工具：

- `coderunner.knowledge.search`
- `coderunner.knowledge.search_similar_problems`
- `coderunner.knowledge.search_error_patterns`

职责：

- 管理 RAG 检索。
- 输出脱敏。
- 记录 query、top_k、latency、kb status。

### 7.4 Analytics Server

端口：`8204`

工具：

- `coderunner.analytics.student_activity`
- `coderunner.analytics.class_statistics`
- `coderunner.analytics.problem_difficulty`
- `coderunner.trace.get_agent_trace`

职责：

- 聚合学习数据。
- 控制学生、教师、admin 的数据可见范围。
- trace 读取默认 medium risk。

## 8. Docker 与部署

新增专用 Dockerfile：

```text
docker/Dockerfile.mcp
```

要求：

- 安装 MCP server 所需依赖。
- 复制 `mcp/`、`app/domain` 或必要 service 模块。
- 不依赖 `agent_host` 目录作为运行入口。
- 不再使用 `python -m mcp_server`。

Compose 服务：

```yaml
services:
  mcp_db:
    build: { context: ., dockerfile: docker/Dockerfile.mcp }
    entrypoint: python -m mcp.server.db.server --transport streamable-http --host 0.0.0.0 --port 8201
    ports: ["8201:8201"]

  mcp_code:
    build: { context: ., dockerfile: docker/Dockerfile.mcp }
    entrypoint: python -m mcp.server.code.server --transport streamable-http --host 0.0.0.0 --port 8202
    ports: ["8202:8202"]

  mcp_knowledge:
    build: { context: ., dockerfile: docker/Dockerfile.mcp }
    entrypoint: python -m mcp.server.knowledge.server --transport streamable-http --host 0.0.0.0 --port 8203
    ports: ["8203:8203"]

  mcp_analytics:
    build: { context: ., dockerfile: docker/Dockerfile.mcp }
    entrypoint: python -m mcp.server.analytics.server --transport streamable-http --host 0.0.0.0 --port 8204
    ports: ["8204:8204"]
```

Agent Host 环境变量：

```text
MCP_REGISTRY_URL=http://mcp_registry:8210
MCP_INTERNAL_SERVICE_TOKEN=...
MCP_TRANSPORT=streamable-http
```

## 9. 实施阶段

### Phase 5.0 - 建立标准 MCP 内核

交付：

- `mcp/client`
- `mcp/adapters`
- `mcp/registry`
- `mcp/schemas`
- `mcp/auth`
- `mcp/policies`
- `mcp/transport`
- `mcp/observability`
- `mcp/errors`

验收：

- 工具 descriptor 可被 registry 发现。
- schema 有输入、输出、错误定义。
- registry 能检测重名工具。
- auth 能构造 per-request `CallerContext`。
- policies 能独立判断 role/scope/risk/approval。

### Phase 5.1 - 迁移 MCP Server

交付：

- `mcp_server/` 迁移到 `mcp/server/*`。
- 删除 `mcp_server.middleware.mcp_tool_middleware()`。
- 旧 `mcp_server/` 目录删除。
- `docker/Dockerfile.mcp` 新增。
- compose 拆分 4 个 MCP 服务。

验收：

- 4 个 server 可独立启动。
- 每个 server `tools/list` 返回命名空间工具名。
- 旧 `python -m mcp_server` 不再存在。
- MCP healthcheck 覆盖 registry 和各 server。

### Phase 5.2 - Agent 和 Workflow 一次性切换

交付：

- `BaseAgent` 使用 `mcp.client.ToolRuntime`。
- `_stream_with_tools` 使用同一 MCP runtime。
- Specialist Agent 只声明工具名。
- Workflow `tool_call` step 使用 MCP runtime。
- Generator 校验和保存路径使用 MCP runtime。

验收：

- `rg "tool.invoke|get_all_tools|check_tool_permission|app.agents.tools" app/agents agent_host` 不出现旧工具执行路径。
- Agent trace 和 MCP audit 用同一 `trace_id` 串联。
- 审批型工具能让 AgentTask 进入 `waiting_approval`。

### Phase 5.3 - 删除旧工具层

交付：

- 删除 `app/agents/tools/*.py` LangChain wrapper。
- 删除 `app/agents/tools/permissions.py`。
- 删除 `app/agents/tools/db_context.py`。
- 业务实现迁移到 `app/domain/*` 或 `mcp/server/*/services.py`。
- 测试从旧工具 wrapper 改为 MCP tool contract。

验收：

- `app/agents/tools` 不再作为 Agent 工具包存在。
- 没有 `@tool` decorator 用于 Agent 工具。
- 测试不再导入 `check_tool_permission("mcp", ...)`。

### Phase 5.4 - Runtime 验证和收口

交付：

- Compose 环境可启动 web、agent_host、4 个 MCP server。
- 创建内部 service token。
- 创建外部 MCP API key。
- 端到端验证 AI chat、streaming、workflow tool_call、Human Gate。

验收：

- 学生调用只能访问自己的数据。
- 教师调用只能访问被授权范围。
- 高风险工具默认不直接执行。
- SSE 断开后任务状态可恢复。
- MCP audit、Agent trace、approval record 可按 `trace_id` 关联。

## 10. 测试策略

### 10.1 单元测试

- schema validation
- registry route conflict
- auth caller context
- RBAC/scope/risk policy
- error mapping
- result envelope conversion

### 10.2 Contract 测试

每个 MCP tool 必须覆盖：

- valid input
- invalid input
- permission denied
- scope denied
- rate limited
- output schema validation
- audit emitted

### 10.3 Agent 集成测试

- Tutor 调用 problem/submission/knowledge/code 工具。
- Reviewer 调用 problem/code 工具。
- Analytics 调用 analytics/submission/problem 工具。
- Generator 调用 similar/code/save 工具。
- streaming 和 sync 共享同一 MCP 工具路径。

### 10.4 禁止回流测试

新增 grep gate：

```powershell
rg "tool\.invoke|get_all_tools|check_tool_permission|from app\.agents\.tools|import app\.agents\.tools" app agent_host tests
```

允许例外只能出现在迁移说明文档中，不能出现在运行时代码。

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 一次性删除兼容层导致范围大 | 短期改动多 | 先完成 MCP 内核和 contract 测试，再切 Agent |
| per-request auth 设计不严 | 用户隔离失效 | 身份只来自 signed context，不接受 tool args 身份字段 |
| schema 转换不完整 | 模型工具调用失败 | canonical schema 测试覆盖 object/array/enum/nullable/default |
| Human Gate 恢复复杂 | 任务卡住或重复执行 | approval 使用 `resume_token`，高风险工具幂等检查 |
| 多 server 运维复杂 | 部署成本增加 | 统一 Dockerfile、统一 healthcheck、registry 管理路由 |
| MCP server 故障 | Agent 工具不可用 | registry health + client retry + 明确错误返回，不回退旧工具 |

## 12. 最终验收标准

- [ ] `mcp/` 目录成为工具协议、schema、权限、审计、错误的唯一标准位置。
- [ ] `app/agents` 和 `agent_host` 中没有直接工具执行路径。
- [ ] `app/agents/tools/permissions.py`、`app/agents/tools/db_context.py` 删除。
- [ ] 旧 `mcp_server/` 目录删除。
- [ ] 不存在 `USE_MCP_CLIENT` 或类似运行时双轨开关。
- [ ] 不存在 `LangChain BaseTool` wrapper 作为 MCP 兼容层。
- [ ] 所有 Specialist Agent 只声明 MCP tool name。
- [ ] Workflow `tool_call` step 只通过 MCP runtime 执行。
- [ ] 所有 MCP tool 都有 input/output/error schema。
- [ ] 所有 MCP call 都有 audit log、trace correlation 和 metrics。
- [ ] 高风险工具统一进入 Human Gate。
- [ ] Docker Compose 启动 4 个 MCP server，healthcheck 全部通过。
- [ ] 端到端 AI chat sync/stream 行为一致。
- [ ] 禁止回流 grep gate 在 CI 中执行。

## 13. 明确不做

- 不保留 `USE_MCP_CLIENT=false` 回退。
- 不保留旧 `mcp_server/` 单体服务并行运行。
- 不把 MCP tool 包装成旧 LangChain `@tool`。
- 不让 Agent 或 Workflow 直接访问 DB session 执行工具。
- 不把可信身份放入 LLM 可控 tool args。
- 不为了兼容旧测试保留 middleware decorator。
