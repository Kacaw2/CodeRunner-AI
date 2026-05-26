# Phase 4 方案：Human Gate + 高风险工具

> 日期：2026-05-26
> 状态：待审阅
> 前置文档：`docs/plans/2026-05-26-phase3-mcp-server-plan.md`
> 前置条件：Phase 3 MCP Server 已交付 + 下文 §1 的 Phase 3 缺陷全部修复

---

## 〇、Phase 3 遗留缺陷清单

Phase 3 代码审计发现以下问题，必须在 Phase 4 启动前修复。这些缺陷直接影响 Phase 4 的
可靠性——Phase 4 要在 MCP Server 上叠加高风险写入工具，如果底层鉴权/审计有漏洞，
写入工具暴露后风险倍增。

### 0.1 \[P0\] 缺少数据库迁移文件

**现状**：`mcp_api_keys` 和 `mcp_audit_logs` 两张表只有 SQLAlchemy Model 定义
（`mcp_server/models/api_key.py`、`mcp_server/models/audit_log.py`），但
`migrations/versions/` 下没有对应的 Alembic 迁移脚本。当前仅靠
`app/__init__.py` → `_ensure_tables()` → `db.create_all()` 来补建缺失表。

**影响**：
- 生产环境若已有数据库，`create_all()` 只能创建新表，不能安全地对已有表加字段；
  后续想给 `mcp_api_keys` 加列（如 Phase 4 新增 `risk_scope` 字段）将无法走 Alembic。
- 团队协作时，别人 `flask db upgrade` 不会创建这两张表。

**修复**：运行 `flask db migrate -m "add mcp_api_keys and mcp_audit_logs"` 生成迁移脚本，
检查内容后 `flask db upgrade`。

### 0.2 \[P0\] MCP Tool 装饰器顺序倒置

**现状**：`mcp_server/tools/knowledge.py` 和 `mcp_server/tools/problems.py` 中：

```python
@mcp.tool(name="search_knowledge", ...)   # ← FastMCP 在此处读函数签名
@mcp_tool_middleware("search_knowledge")   # ← wraps → (*args, **kwargs)
def search_knowledge(query: str, ...) -> str:
```

`@mcp.tool()` 在外层，它内省到的是 `mcp_tool_middleware` 返回的 wrapper 函数的签名
`(*args, **kwargs)`，而不是原始 `(query: str, ...)` 签名。这导致 FastMCP 生成的
JSON Schema **参数列表为空**，MCP 客户端无法正确构造请求。

**影响**：所有 4 个 MCP 工具的 `tools/list` 返回的 schema 参数不正确；
客户端（Claude Desktop / Cursor）调用时会因参数校验失败而报错。

**修复方案 A（推荐）**：交换装饰器顺序——`@mcp_tool_middleware` 放外层，`@mcp.tool()` 放内层：

```python
@mcp_tool_middleware("search_knowledge")
@mcp.tool(name="search_knowledge", ...)
def search_knowledge(query: str, ...) -> str:
```

但需确认 `@mcp.tool()` 放内层时仍能正确注册。如不行，走方案 B。

**修复方案 B**：在 `mcp_tool_middleware` 中使用 `functools.wraps` + 手动复制
`__annotations__`，确保 wrapper 保留原函数签名。MCP SDK 内省时能看到正确参数。
需验证 `functools.wraps` 是否足够（当前代码已有 `@wraps(fn)` 但参数注解可能丢失——
Python `wraps` 会复制 `__wrapped__`，但部分框架不查 `__wrapped__`）。

**修复方案 C（最稳妥）**：不使用 decorator 嵌套，改为在 tool 函数体内调用 middleware：

```python
@mcp.tool(name="search_knowledge", ...)
def search_knowledge(query: str, ...) -> str:
    check = run_mcp_middleware("search_knowledge", {"query": query})
    if check.error:
        return check.error_json
    result = search_knowledge_impl(query)
    return json.dumps(result, ensure_ascii=False)
```

### 0.3 \[P0\] SSE 模式下鉴权为全局变量，不支持多客户端

**现状**：`mcp_server/middleware.py` 中 `_caller_info` 是模块级全局变量：

```python
_caller_info: dict | None = None          # 全局唯一
def set_caller_info(info: dict):
    global _caller_info
    _caller_info = info
```

`__main__.py` 启动时从 `MCP_API_KEY` 环境变量读取 key 并 `set_caller_info()` 一次。

- **stdio 模式**：可接受——每个 stdio 进程只服务一个客户端。
- **SSE 模式**：同一个进程可能被多个客户端访问（通过 HTTP）。当前设计下所有请求共享
  同一个 `_caller_info`，无法区分不同客户端。

**Phase 4 影响**：Phase 4 要暴露写入工具（`execute_code`），如果 SSE 模式下不能
区分客户端身份，一个低权限的 key 可能借用高权限 key 的身份执行代码。

**修复**：

- **短期（Phase 4 前）**：在文档中明确标注 SSE 模式当前为 **单 key 模式**
  （`MCP_API_KEY` 环境变量 = 该实例只服务一个客户端）。如需多客户端，启动多个
  MCP Server 实例（不同端口 / 不同 key）。
- **中期（Phase 4 中）**：改用 `contextvars.ContextVar` 存储 per-request 的
  caller info。需要在 FastMCP 的 transport 层注入——查看
  `mcp.server.sse.SseServerTransport` 是否支持 request-level middleware / hook。
  如不支持，考虑在 Starlette ASGI 中间件层做 Bearer token 提取。

### 0.4 \[P1\] Docker healthcheck 端点错误

**现状**：`compose.yaml` 中 `mcp_server` 的 healthcheck 为
`curl -f http://localhost:8200/sse`。FastMCP 在 SSE transport 模式下的实际端点路径
取决于 `sse_path` 参数（默认 `/sse`），但 curl 该路径会建立 SSE 长连接而非返回 200。

**修复**：改为 `curl -f http://localhost:8200/mcp` 或使用 TCP 检查
`["CMD-SHELL", "python -c \"import socket; s=socket.create_connection(('localhost',8200)); s.close()\""]`。

### 0.5 \[P2\] `app/agents/tools/__init__.py` 未导出知识库工具

**现状**：`__init__.py` 只导出 5 个工具（`execute_code`、`get_problem_detail` 等），
未导出 `search_similar_problems`、`search_knowledge`、`search_error_patterns` 等
重构后的工具。

**影响**：不影响功能（各 agent 直接从子模块 import），但公共 API 不完整。

**修复**：在 `__init__.py` 中补充导出。

### 0.6 \[P2\] `get_student_activity` 和 `get_class_statistics` 未抽取到 core

**现状**：Phase 3 计划只要求抽取 4 个 MCP 工具的核心逻辑。`get_student_activity` 和
`get_class_statistics` 仍内嵌在 `analytics_query.py` 的 `@tool` 装饰器下。

**影响**：Phase 4 如果要把这两个工具暴露到 MCP，需要先做抽取。

**修复**：在 Phase 4 Step 1 中一并完成。

---

## 一、Phase 4 目标

在 Phase 3 只读 MCP Server 基础上：

1. **开放 2 个中等风险只读工具**：`get_agent_trace`、`get_student_summary`——需数据脱敏
2. **开放 2 个高风险写入工具**：`execute_code`、`save_generated_problem`——需 Human Gate 审批
3. **MCP 工具调用审批流**：高风险工具调用时暂停，等待 MCP 客户端/教师确认后才执行

## 二、架构决策

### 2.1 数据脱敏策略

| 工具 | 原始数据 | 脱敏规则 | 理由 |
|------|---------|---------|------|
| `get_agent_trace` | `AgentRun.input_context`（可能含 system prompt）、`AgentRunStep.tool_input`（可能含学生代码/API key）| 移除 `input_context` 中的 `system_prompt` 字段；`tool_input` 中若含 `code` 字段则截断为前 200 字符；`tool_output_preview` 截断为 300 字符 | 防止内部 prompt 和学生代码经 MCP 泄露到第三方 AI |
| `get_student_summary` | `StudentProfile.error_patterns`（学习弱点）、`Submission.code`（完整代码）、`User.username/email` | 不返回 `username`/`email`（用 `student_id` 代替）；不返回原始 `code`；只返回聚合指标（通过率、活跃天数、薄弱知识点列表）| FERPA 类隐私保护，防止学生 PII 流入第三方 |

### 2.2 Human Gate 审批模型

当前 `WorkflowStep` 已有 `requires_approval` 和 `waiting_approval` 机制。但 MCP 工具
调用不走 Workflow Engine——它们是独立的 tool call。需要一个 **MCP 层面的审批机制**。

| 方案 | 说明 | 评价 | 结论 |
|------|------|------|------|
| A: MCP 客户端侧确认 | MCP 工具返回 "需要确认" 的 prompt，客户端 AI 自行决定是否再次调用 | 依赖客户端行为，不可靠——客户端可能直接忽略确认 | ❌ 淘汰 |
| **B: MCP Server 异步审批** | 高风险 tool call → 创建 pending approval 记录 → 返回 `approval_id` → 教师在 Flask 后台审批 → MCP 客户端轮询结果 | 可靠，审批权掌握在教师手中，与现有 Flask 后台集成 | ✅ **采用** |
| C: MCP Server 同步阻塞 | tool call 阻塞等待审批 | MCP 协议可能超时，客户端体验差 | ❌ 淘汰 |

**方案 B 详细流程**：

```
1. MCP 客户端调用 execute_code(code="...", language="python")
2. MCP Server 检查 → 该工具 risk_level = "high"
3. MCP Server 创建 McpToolApproval 记录（status=pending）
4. MCP Server 返回：
   {"status": "approval_required", "approval_id": "xxx", "message": "代码执行需要教师审批"}
5. 教师在 Flask 后台看到待审批列表 → 查看代码 → 批准/拒绝
6. MCP 客户端调用 check_approval(approval_id="xxx")
   → 已批准：MCP Server 执行工具，返回结果
   → 已拒绝：返回拒绝原因
   → 仍在等待：返回 pending 状态
```

**新增模型**：

```python
class McpToolApproval(db.Model):
    __tablename__ = "mcp_tool_approvals"

    id = db.Column(db.String(36), primary_key=True)
    api_key_id = db.Column(db.String(36), db.ForeignKey("mcp_api_keys.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    tool_name = db.Column(db.String(50), nullable=False)
    tool_args = db.Column(db.JSON, nullable=False)
    risk_level = db.Column(db.String(10), default="high")
    status = db.Column(db.String(20), default="pending")
    # pending → approved → executed | expired
    # pending → rejected
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    result = db.Column(db.JSON, nullable=True)    # 执行结果（批准后填入）
    created_at = db.Column(db.DateTime, default=now_china)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)  # 超时自动过期
```

### 2.3 工具风险分级

将 MCP 工具分为三个风险等级，不同等级走不同的执行路径：

| 风险等级 | 执行路径 | 工具 |
|---------|---------|------|
| **low** | 直接执行，审计日志 | `search_knowledge`、`search_similar_problems`、`get_problem_detail`、`get_problem_difficulty_stats` |
| **medium** | 直接执行，审计日志 + 结果脱敏 | `get_agent_trace`、`get_student_summary` |
| **high** | 异步审批 → 批准后执行 | `execute_code`、`save_generated_problem`、`check_approval` |

在 `mcp_server/middleware.py` 中新增风险等级配置：

```python
TOOL_RISK_LEVELS = {
    "search_knowledge":             "low",
    "search_similar_problems":      "low",
    "get_problem_detail":           "low",
    "get_problem_difficulty_stats": "low",
    "get_agent_trace":              "medium",
    "get_student_summary":          "medium",
    "execute_code":                 "high",
    "save_generated_problem":       "high",
    "check_approval":               "low",    # 查询审批状态本身不需要审批
}
```

### 2.4 权限矩阵扩展

```python
# Phase 4 新增
("mcp", "get_agent_trace"):          {"teacher", "admin"},
("mcp", "get_student_summary"):      {"teacher", "admin"},
("mcp", "execute_code"):             {"teacher", "admin"},
("mcp", "save_generated_problem"):   {"teacher", "admin"},
("mcp", "check_approval"):           {"teacher", "admin"},
```

---

## 三、实现方案

### 3.1 数据脱敏层

新增 `mcp_server/sanitizer.py`：

```python
def sanitize_agent_trace(run: dict, steps: list[dict]) -> dict:
    """对 AgentRun + AgentRunStep 数据做脱敏。"""
    # 1. 移除 input_context 中的 system_prompt
    ctx = run.get("input_context") or {}
    ctx.pop("system_prompt", None)
    ctx.pop("system_message", None)
    run["input_context"] = ctx

    # 2. 截断 tool_input / tool_output_preview
    for step in steps:
        tool_input = step.get("tool_input") or {}
        if "code" in tool_input:
            tool_input["code"] = tool_input["code"][:200] + "..."
        step["tool_input"] = tool_input
        if step.get("tool_output_preview"):
            step["tool_output_preview"] = step["tool_output_preview"][:300]

    return {"run": run, "steps": steps}


def sanitize_student_summary(
    student_id: int, profile: dict, stats: dict
) -> dict:
    """只返回聚合指标，不返回 PII。"""
    return {
        "student_id": student_id,
        "preferred_language": profile.get("preferred_language"),
        "weak_topics": (profile.get("error_patterns") or {}).keys(),
        "strong_topics": list((profile.get("knowledge_map") or {}).keys())[:10],
        "total_submissions": stats.get("total_submissions", 0),
        "acceptance_rate": stats.get("acceptance_rate", 0),
        "active_days": stats.get("active_days", 0),
        "current_streak": stats.get("current_streak", 0),
    }
```

### 3.2 核心逻辑抽取（补充 Phase 3 遗漏）

将 `get_agent_trace` 和 `get_student_summary` 的核心逻辑抽取到 `app/agents/tools/core/`：

```
app/agents/tools/core/
  traces.py          ← 新增：get_agent_trace_impl
  student_summary.py ← 新增：get_student_summary_impl
```

### 3.3 MCP 写入工具

```
mcp_server/tools/
  knowledge.py       ← 已有（Phase 3）
  problems.py        ← 已有（Phase 3）
  traces.py          ← 新增：get_agent_trace
  students.py        ← 新增：get_student_summary
  write.py           ← 新增：execute_code, save_generated_problem, check_approval
```

`write.py` 中的 `execute_code` 不直接执行，而是先创建审批记录：

```python
@mcp.tool(name="execute_code", ...)
def execute_code(code: str, language: str = "python", stdin_text: str = "") -> str:
    # middleware 已验证 auth + permission
    approval = create_approval(
        tool_name="execute_code",
        tool_args={"code": code, "language": language, "stdin_text": stdin_text},
    )
    return json.dumps({
        "status": "approval_required",
        "approval_id": approval.id,
        "message": f"代码执行需要审批，请教师在后台确认。approval_id: {approval.id}",
    })

@mcp.tool(name="check_approval", ...)
def check_approval(approval_id: str) -> str:
    approval = get_approval(approval_id)
    if approval.status == "approved":
        if approval.result is None:
            # 首次查询——执行工具
            result = execute_tool_impl(approval.tool_name, approval.tool_args)
            approval.result = result
            approval.status = "executed"
            save(approval)
        return json.dumps({"status": "executed", "result": approval.result})
    elif approval.status == "rejected":
        return json.dumps({"status": "rejected", "reason": approval.review_notes})
    else:
        return json.dumps({"status": "pending", "message": "等待教师审批"})
```

### 3.4 Flask 审批管理端点

```
POST   /api/v1/mcp/approvals                — 列出当前用户的待审批请求
GET    /api/v1/mcp/approvals/<id>            — 查看审批详情（含代码预览）
POST   /api/v1/mcp/approvals/<id>/approve    — 批准执行
POST   /api/v1/mcp/approvals/<id>/reject     — 拒绝（附拒绝理由）
```

教师可在 Flask 后台 → "MCP 审批" 页面查看所有待审批的工具调用，
逐条查看代码内容和调用参数后做出决策。

### 3.5 审批超时

`McpToolApproval.expires_at` 默认为创建后 30 分钟。超时未审批的请求自动标记为
`expired`。MCP 客户端调用 `check_approval` 时返回超时错误。

可通过定时任务或请求时惰性检查实现：

```python
def check_expiration(approval):
    if approval.status == "pending" and now_china() > approval.expires_at:
        approval.status = "expired"
        save(approval)
```

---

## 四、执行顺序

```
前置步骤  Phase 3 缺陷修复                                    (1.5 hr)
          §0.1 生成 Alembic 迁移脚本
          §0.2 修复 MCP tool 装饰器顺序（方案 B 或 C）
          §0.3 文档标注 SSE 单 key 限制 / 或改用 contextvars
          §0.4 修复 compose healthcheck
          §0.5 补全 __init__.py 导出
          → 验证 tools/list 返回正确 schema
          → 验证 29 个 MCP 测试 + 221 个已有测试全部通过

第一步    数据脱敏层 + 核心逻辑抽取                             (1 hr)
          mcp_server/sanitizer.py
          app/agents/tools/core/traces.py
          app/agents/tools/core/student_summary.py
          → 单元测试验证脱敏逻辑

第二步    中等风险 MCP 只读工具                                 (1 hr)
          mcp_server/tools/traces.py     — get_agent_trace（脱敏后返回）
          mcp_server/tools/students.py   — get_student_summary（脱敏后返回）
          权限矩阵扩展（teacher/admin only）
          → 验证 tools/list 返回 6 个工具
          → 验证 student 角色被拒

第三步    McpToolApproval 模型 + 迁移                           (30 min)
          mcp_server/models/approval.py
          Alembic 迁移脚本
          Flask 审批管理端点 (app/api/v1/mcp_approvals.py)
          → 验证 CRUD 端点

第四步    高风险 MCP 写入工具                                   (1.5 hr)
          app/agents/tools/core/code_executor.py（抽取 execute_code 核心逻辑）
          app/agents/tools/core/question_save.py（抽取 save_generated_problem）
          mcp_server/tools/write.py
          middleware 风险等级路由
          → 验证 execute_code 返回 approval_required
          → 验证 check_approval 轮询流程
          → 验证审批后执行 + 审计日志

第五步    端到端测试 + 文档                                     (1 hr)
          test_mcp_phase4.py — 覆盖脱敏、审批流、权限、超时
          更新 Claude Desktop 配置示例
          tools/list → 8 个工具（含 check_approval）
          → 全量回归测试
```

---

## 五、验证矩阵

| # | 测试项 | 操作 | 预期结果 |
|---|--------|------|---------|
| 1 | Phase 3 修复回归 | 运行全部现有测试 | 250+ 测试通过 |
| 2 | tools/list | MCP 客户端连接 | 返回 8 个工具及正确 schema |
| 3 | get_agent_trace | 传入有效 run_id | 返回脱敏后的 trace（无 system_prompt，代码截断） |
| 4 | get_agent_trace 无权限 | student role 调用 | 拒绝 |
| 5 | get_student_summary | 传入有效 student_id | 返回聚合指标（无 username/email/code） |
| 6 | get_student_summary 无权限 | student role 调用 | 拒绝 |
| 7 | execute_code | 提交代码 | 返回 `approval_required` + `approval_id` |
| 8 | check_approval (pending) | 用 approval_id 查询 | 返回 `pending` |
| 9 | Flask 审批 — 批准 | 教师在后台批准 | approval 状态变为 `approved` |
| 10 | check_approval (approved) | 批准后再查询 | 执行代码，返回结果 |
| 11 | Flask 审批 — 拒绝 | 教师拒绝 | 返回 `rejected` + 拒绝理由 |
| 12 | 审批超时 | 等 30 分钟不审批 | check_approval 返回 `expired` |
| 13 | save_generated_problem | 提交题目数据 | 返回 `approval_required` |
| 14 | save_generated_problem 审批后 | 批准后 check_approval | 题目写入 DB，返回 problem_id |
| 15 | scope 限制 | Key scopes 不含 execute_code | 拒绝 |
| 16 | rate limit | 短时间超出限制 | 返回 rate limit error |
| 17 | 审计日志 | 调用工具后查 mcp_audit_logs | 记录完整（含 approval_id） |
| 18 | 脱敏验证 | get_agent_trace 返回的 trace 检查 | 不含 system_prompt、code 已截断 |
| 19 | 现有 chat 回归 | 前端 AI chat 正常使用 | 不受 MCP 改动影响 |

---

## 六、风险与注意事项

### 6.1 execute_code 安全边界

`execute_code` 通过 MCP 暴露后，需要额外的安全约束：

- **代码长度限制**：MCP 层限制 `code` 参数最大 10,000 字符
- **语言白名单**：只允许 `python` 和 `c`（与现有 executor 一致）
- **per-key 执行配额**：除 rate_limit_rpm 外，新增 `daily_execution_limit`
  （每个 API Key 每天最多执行 50 次代码）
- **结果截断**：stdout/stderr 截断为 2000/1000 字符（与现有一致）

### 6.2 审批通知

Phase 4 第一版不做主动通知（push），教师需定期查看后台。
后续可叠加 WebSocket / 邮件通知。

### 6.3 审批记录保留

`mcp_tool_approvals` 表记录保留 90 天（可通过定时任务清理过期记录），
作为安全审计依据。

### 6.4 SSE 多客户端

Phase 4 暂不解决 SSE 多客户端鉴权问题（§0.3 做文档标注即可）。
写入工具已有 Human Gate 保护，即使身份混淆也需要教师在 Flask 后台手动批准。
完整的 per-request 鉴权留到 Phase 5（OAuth 2.0）。

### 6.5 save_generated_problem 与现有 draft 系统的关系

`save_generated_problem` 应生成 `GeneratedQuestionDraft` 记录（`status=pending_review`），
而非直接写入 `problems` 表。教师审批 MCP 工具调用 ≠ 审批题目内容——
两个审批是独立的：

1. MCP 审批（Human Gate）：教师确认"是否允许 AI 执行这个保存操作"
2. 题目审批（Draft Review）：教师审核题目内容质量，决定是否发布

MCP 审批通过后，题目进入 Draft，仍需走 Draft Review 流程才能发布。

---

## 七、不动的部分

- `agent_host/` — Agent Host 不变
- `app/agents/agents/` — 四个 specialist agent 不变
- `app/agents/orchestrator.py` — 编排逻辑不变
- `app/static/js/ai_chat.js` — 前端 AI chat 不变
- Phase 3 的 4 个只读 MCP 工具 — 行为不变（仅修复 §0 中的 bug）

---

## 八、Phase 4 启动条件清单

| # | 条件 | 验证方式 | 当前状态 |
|---|------|---------|---------|
| 1 | Phase 3 的 4 个只读工具正常工作 | `tools/list` 返回 4 个工具且参数 schema 正确 | ❌ 待修复 §0.2 |
| 2 | Alembic 迁移存在且可运行 | `flask db upgrade` 成功创建 `mcp_api_keys`、`mcp_audit_logs` | ❌ 待修复 §0.1 |
| 3 | API Key 全链路可用 | 创建 key → 配置到 Claude Desktop → tools/list 成功 | ❌ 待修复 §0.2 |
| 4 | 审计日志落库 | 调用工具后 `mcp_audit_logs` 有记录 | ⚠️ 依赖 §0.1 |
| 5 | 所有测试通过 | `pytest tests/` 全部通过 | ✅ 250 测试通过 |
| 6 | SSE 模式单 key 限制已文档化 | README 或配置文档中说明 | ❌ 待完成 §0.3 |

**结论**：必须先完成 §0 的 6 项修复，才能启动 Phase 4 的第一步。
预估修复工时 1.5 小时。

---

## 九、后续（Phase 5 展望）

Phase 4 完成后，下一阶段可考虑：

1. ⬜ OAuth 2.0 鉴权（替换 API Key，支持 SSE 多客户端）
2. ⬜ MCP 工具 streaming（长时间 execute_code 返回实时输出）
3. ⬜ 审批通知（WebSocket / 邮件推送）
4. ⬜ 更多写入工具：`create_classroom`、`enroll_student`（管理操作）
5. ⬜ MCP 客户端 SDK / CLI 工具（简化教师配置）
