# Phase 3 方案：只读 MCP Server

> 日期：2026-05-26
> 状态：待审阅
> 前置文档：`docs/archive/plans/FASTAPI_AGENT_HOST_MCP_WORKFLOW_PLAN_ZH.md`、`docs/plans/2026-05-26-phase1-phase2-repair-plan.md`
> 前置条件：Phase 1/2 修复完成（Agent Host 直接执行 Agent、Supervisor 接入主链路）

## 一、Phase 3 目标

让外部 AI 客户端（Claude Desktop、Cursor 等）通过标准 MCP 协议调用 CodeRunner 的只读能力。

## 二、架构决策审查

### 2.1 MCP Server 部署位置

| 方案 | 说明 | 评价 | 结论 |
|------|------|------|------|
| A: 嵌入 Agent Host | 在 `agent_host/main.py` 中加 MCP 路由 | MCP 是面向外部客户端的 API 边界，与 Agent Host 的"内部编排"职责不同。两者流量模式、鉴权需求、限流策略完全不同。混在一起后 Agent Host 既服务前端 chat 又服务外部 MCP 客户端 | ❌ 淘汰 |
| **B: 独立进程/模块** | `mcp_server/` 独立目录，独立端口 | MCP Server 是面向外部客户端的 API 边界，应有独立进程、鉴权、限流、审计。与 Agent Host 共享 service 层代码但独立部署 | ✅ **采用** |

**理由**：

- MCP 客户端是**外部用户**（Claude Desktop、Cursor、第三方），Agent Host chat 是**内部前端**——两者信任级别不同
- MCP 需要独立的 rate limiting（按 client_id/api_key 限流，不是按 user_id）
- MCP 需要独立的审计日志（谁在调什么工具，频率多少）
- 独立部署意味着 MCP Server 挂了不影响 chat，chat 挂了不影响 MCP
- Agent Host 未来可能需要内部变更（Agent 编排逻辑迭代），不应影响 MCP 对外接口的稳定性

**目录结构**：

```
mcp_server/
  __init__.py
  server.py          # MCP Server 入口，tool 注册
  auth.py            # API Key 验证
  config.py          # 配置
  tools/             # MCP tool handlers（包装共享核心逻辑）
    knowledge.py
    problems.py
  models/
    api_key.py        # MCP API Key 表
```

### 2.2 MCP 协议实现

| 方案 | 说明 | 评价 | 结论 |
|------|------|------|------|
| **A: `mcp` Python SDK** | `pip install mcp`，标准 transport | 标准实现，兼容所有 MCP 客户端（Claude Desktop / Cursor / 自定义），Anthropic 维护，协议升级时自动跟进 | ✅ **采用** |
| B: 手写 JSON-RPC 2.0 | 自己实现协议层 | 重复造轮，协议升级需手动跟进，测试覆盖不足，客户端兼容性需自己验证 | ❌ 淘汰 |

### 2.3 Transport 选择

原方案未讨论 transport，但这是关键决策。

| Transport | 适用场景 | 评价 |
|-----------|---------|------|
| **Streamable HTTP (SSE)** | 远程 MCP server，部署在服务器上 | 主要模式：教师/管理员从任意设备通过 MCP 客户端连接 |
| **stdio** | 本地 MCP server（Claude Desktop 插件） | 辅助模式：开发/调试用，教师在本机直接运行 |

**结论：同时支持两种 transport**。

`mcp` SDK 原生支持两种 transport，实现成本几乎为零：

```python
# server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.sse import SseServerTransport

server = Server("coderunner")

# stdio 模式（本地开发）
# python -m mcp_server --transport stdio

# HTTP+SSE 模式（远程部署）
# python -m mcp_server --transport sse --port 8200
```

### 2.4 鉴权方案

原方案写"加 token/JWT 鉴权"，但 MCP 客户端不是浏览器，不持有 Flask 签发的 JWT。

| 方案 | 说明 | 评价 | 结论 |
|------|------|------|------|
| A: 复用 Flask JWT | MCP 客户端头部携带 JWT | 客户端从哪里获取 JWT？需要先登录 Flask 再复制 token——体验极差，token 有 expiry 需反复刷新 | ❌ 淘汰 |
| **B: 独立 API Key** | 每个 MCP 客户端分配一个 API Key，绑定 user_id + role + scopes | MCP 标准做法，长期有效，可独立吊销，可设置权限范围，体验类似 GitHub Personal Access Token | ✅ **采用** |
| C: OAuth 2.0 | 标准 OAuth 流程 | 最规范，但对教育平台 MVP 来说过重 | ⬜ 后续可叠加，当前不做 |

**API Key 数据模型**：

```python
class McpApiKey(db.Model):
    __tablename__ = "mcp_api_keys"

    id = db.Column(db.String(36), primary_key=True)     # UUID
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    key_hash = db.Column(db.String(128), nullable=False) # SHA-256 of raw key
    name = db.Column(db.String(100), nullable=False)     # "我的 Claude Desktop"
    role = db.Column(db.String(20), nullable=False)      # 继承 user 的 role
    scopes = db.Column(db.JSON, nullable=True)           # 允许的工具列表，null = 全部
    rate_limit_rpm = db.Column(db.Integer, default=30)   # 每分钟请求上限
    created_at = db.Column(db.DateTime, default=now_china)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)   # 非 null 则已吊销
```

**使用流程**：

```
1. 教师在 Flask 后台 "API Key 管理" 页面生成 Key
   → 系统显示一次完整 Key（类似 sk-xxx...）
   → DB 存储 SHA-256 hash

2. 教师将 Key 配置到 Claude Desktop / Cursor 的 MCP 设置中

3. MCP 客户端每次请求携带 Key
   → MCP Server 验证 hash → 提取 user_id / role / scopes
   → 检查 rate limit → 执行 tool → 记录审计日志
```

**stdio 模式鉴权**：通过环境变量传入 `MCP_API_KEY`，启动时验证。

### 2.5 工具范围

原方案列了 5 个只读工具。逐个审查外部暴露的安全性：

| 工具 | 实现状态 | 对外部 MCP 的价值 | 隐私/安全风险 | 第一版纳入？ |
|------|---------|------------------|-------------|------------|
| `search_knowledge` | ✅ 已实现 | 高 — 外部 AI 检索课程知识点 | 低 — 课程知识是教学内容 | ✅ |
| `search_similar_problems` | ✅ 已实现 | 高 — 查重、检索题库 | 低 — 题目元数据 | ✅ |
| `get_problem_detail` | ✅ 已实现 | 高 — 获取题目、测试用例 | 低 — 已过滤 hidden test cases | ✅ |
| `get_problem_difficulty_stats` | ✅ 已实现 | 中 — 题目难度分析 | 低 — 聚合统计无 PII | ✅ |
| `get_agent_trace` | ❌ 未实现 | 低 — 调试/审计用，外部客户端很少需要 | **中** — 泄露内部 LLM 调用链、prompt、中间结果 | ❌ 推迟到 Phase 4 |
| `get_student_summary` | ❌ 未实现 | 中 — 教师用 AI 查学生数据 | **高** — 学生 PII、成绩数据可能流入第三方 AI 服务 | ❌ 推迟到 Phase 4 |

**结论：第一版暴露 4 个低风险只读工具**。

`get_agent_trace` 和 `get_student_summary` 的推迟理由：

- **`get_agent_trace`**：暴露内部 LLM 调用链（包括 system prompt、tool 调用参数、中间推理），对外部客户端价值低但安全风险不为零。应在 Phase 4 审计完善后，做数据脱敏再开放。
- **`get_student_summary`**：涉及学生隐私数据（成绩、活跃度、错误模式）。通过外部 MCP 客户端暴露意味着数据可能流入第三方 AI 服务的上下文窗口甚至训练数据。必须等 Phase 4 完成以下条件后再开放：
  - 学生本人同意或教师角色限制
  - 数据脱敏（只返回聚合指标，不返回个人标识信息）
  - 审计日志记录每次访问

**可选追加**（已有实现，低风险）：

| 工具 | 说明 | 是否追加 |
|------|------|---------|
| `list_problems` | 浏览题库列表（需新建，查询 Problem 表返回 id/title/difficulty 列表） | ⬜ 可选，看第一版工期 |
| `search_error_patterns` | 错误模式搜索（已实现在 `knowledge_tools.py`） | ⬜ 可选 |

### 2.6 工具注册架构

原方案未讨论。这是最核心的工程决策——**MCP 工具和 LangChain 工具是否共享注册？**

当前状态：

- LangChain 工具用 `@tool` 装饰器，注册在 `app/agents/tools/*.py`
- MCP 工具需要 `mcp` SDK 的 `@server.tool()` 注册，需要自己的 schema
- 两者的工具核心逻辑完全相同（调用同一个 KB、同一个 DB 查询）

| 方案 | 说明 | 评价 | 结论 |
|------|------|------|------|
| A: MCP 工具重新写一套 handler | MCP Server 里 copy 已有工具逻辑，重新实现 | 每个工具写两遍，核心逻辑重复，容易不同步，改了一边忘了另一边 | ❌ 淘汰 |
| **B: 共享核心逻辑，各自包装注册** | 抽取工具核心逻辑为普通 Python 函数（无框架依赖），LangChain `@tool` 和 MCP `@server.tool()` 分别包装 | 核心逻辑一份代码，注册层各自独立，互不影响 | ✅ **采用** |

**方案 B 的具体做法**：

将工具核心逻辑从 `@tool` 装饰器下抽出，放入 `app/agents/tools/core/`：

```
app/agents/tools/
  core/                         ← 新增：纯业务逻辑，无框架依赖
    __init__.py
    knowledge.py                # search_similar_problems_impl, search_knowledge_impl
    problems.py                 # get_problem_detail_impl
    analytics.py                # get_problem_difficulty_stats_impl
  knowledge_tools.py            ← 现有：LangChain @tool 包装
  question_query.py             ← 现有：LangChain @tool 包装
  analytics_query.py            ← 现有：LangChain @tool 包装
  db_context.py                 ← 现有：contextvars session
  permissions.py                ← 现有：权限矩阵

mcp_server/
  tools/
    knowledge.py                ← 新增：MCP @server.tool() 包装
    problems.py                 ← 新增：MCP @server.tool() 包装
```

**示例**：

```python
# ── app/agents/tools/core/knowledge.py ── 纯业务逻辑

def search_similar_problems_impl(
    query: str,
    language: str = "python",
    limit: int = 5,
    session=None,
) -> dict:
    """搜索题库中的相似题目。"""
    from app.agents.knowledge_base import get_knowledge_base

    try:
        kb = get_knowledge_base()
        results = kb.search_similar_problems(query, n=limit, language=language)
        return {"similar_problems": results}
    except Exception as e:
        return {"similar_problems": [], "error": str(e)}
```

```python
# ── app/agents/tools/knowledge_tools.py ── LangChain 包装（改造后）

from langchain_core.tools import tool
from app.agents.tools.core.knowledge import search_similar_problems_impl
from app.agents.tools.db_context import get_current_session

@tool
def search_similar_problems(query: str, language: str = "python", limit: int = 5) -> dict:
    """Search existing problem bank for similar problems..."""
    return search_similar_problems_impl(query, language, limit, session=get_current_session())
```

```python
# ── mcp_server/tools/knowledge.py ── MCP 包装

from app.agents.tools.core.knowledge import search_similar_problems_impl

def register_knowledge_tools(server, get_session):
    @server.tool()
    async def search_similar_problems(query: str, language: str = "python", limit: int = 5) -> str:
        """Search existing problem bank for similar problems..."""
        result = search_similar_problems_impl(query, language, limit, session=get_session())
        return json.dumps(result, ensure_ascii=False)
```

**好处**：

- 核心逻辑只维护一份，bug fix 自动同步
- LangChain 和 MCP 的包装层可以有不同的参数校验、错误处理、返回格式
- 新增工具时只写一个 `_impl` 函数 + 两个轻量包装
- 未来如果换 LLM 框架（LangChain → LlamaIndex 等），只需要改包装层

### 2.7 权限模型

原方案的 `TOOL_PERMISSIONS` 的 key 是 `(agent_type, tool_name)`，对 MCP 不适用——MCP 没有 `agent_type` 概念。

**扩展权限矩阵**：

```python
TOOL_PERMISSIONS = {
    # ── 现有 entries（Agent 内部调用）──
    ("tutor", "search_knowledge"):             {"student", "teacher", "admin"},
    ("generator", "search_similar_problems"):  {"teacher", "admin"},
    ("analytics", "get_problem_detail"):       {"student", "teacher", "admin"},
    # ...

    # ── MCP Server 权限（外部调用，默认更严格）──
    ("mcp", "search_knowledge"):              {"teacher", "admin"},
    ("mcp", "search_similar_problems"):       {"teacher", "admin"},
    ("mcp", "get_problem_detail"):            {"teacher", "admin"},
    ("mcp", "get_problem_difficulty_stats"):  {"teacher", "admin"},
}
```

**要点**：

- MCP 权限默认比内部 Agent 调用更严格——学生暂不通过外部 MCP 客户端访问系统
- `check_tool_permission("mcp", tool_name, api_key.role)` 复用现有函数
- API Key 的 `scopes` 字段提供额外的细粒度控制（可限制 Key 只能调某几个工具）

**权限检查顺序**：

```
1. API Key 有效性（未过期、未吊销）
2. Rate limit（该 Key 每分钟请求数）
3. TOOL_PERMISSIONS 矩阵（role + tool_name）
4. API Key scopes（该 Key 是否被限制了工具范围）
```

## 三、实现方案

### 3.1 MCP Server 核心

**mcp_server/server.py**:

```python
import json
import logging
from mcp.server import Server

from mcp_server.auth import verify_api_key
from mcp_server.tools.knowledge import register_knowledge_tools
from mcp_server.tools.problems import register_problem_tools

logger = logging.getLogger(__name__)

server = Server("coderunner-mcp")


def create_server(session_factory):
    """创建并配置 MCP Server，注册所有工具。"""

    def get_session():
        return session_factory()

    register_knowledge_tools(server, get_session)
    register_problem_tools(server, get_session)

    return server
```

**mcp_server/__main__.py**（入口）:

```python
import argparse
import logging

from mcp_server.config import get_settings
from mcp_server.server import create_server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="sse")
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()

    settings = get_settings()
    session_factory = create_db_session_factory(settings)
    server = create_server(session_factory)

    if args.transport == "stdio":
        from mcp.server.stdio import stdio_server
        stdio_server(server)
    else:
        from mcp.server.sse import SseServerTransport
        sse = SseServerTransport("/messages/")
        # ... 启动 HTTP 服务 ...

if __name__ == "__main__":
    main()
```

### 3.2 API Key 管理

**Flask 端新增端点**（教师后台）:

```
POST   /api/v1/mcp/keys         — 生成新 API Key
GET    /api/v1/mcp/keys         — 列出当前用户的所有 Key
DELETE /api/v1/mcp/keys/<id>    — 吊销（revoke）Key
```

**MCP Server 端验证**:

```python
# mcp_server/auth.py
import hashlib
from mcp_server.db import get_session
from mcp_server.models.api_key import McpApiKey

def verify_api_key(raw_key: str) -> dict | None:
    """验证 API Key，返回 {user_id, role, scopes, rate_limit_rpm} 或 None。"""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with get_session() as session:
        key = session.query(McpApiKey).filter_by(
            key_hash=key_hash,
            revoked_at=None,
        ).first()
        if not key:
            return None
        # 更新 last_used_at
        key.last_used_at = now_china()
        session.commit()
        return {
            "user_id": key.user_id,
            "role": key.role,
            "scopes": key.scopes,
            "rate_limit_rpm": key.rate_limit_rpm,
        }
```

### 3.3 审计日志

每次 MCP tool call 记录审计日志：

```python
class McpAuditLog(db.Model):
    __tablename__ = "mcp_audit_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    api_key_id = db.Column(db.String(36), db.ForeignKey("mcp_api_keys.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    tool_name = db.Column(db.String(50), nullable=False)
    tool_args = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20))  # "success" | "denied" | "error"
    latency_ms = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=now_china)
```

## 四、执行顺序

```
第一步  工具核心逻辑抽取                              (1 hr)
        app/agents/tools/core/ ← 从 @tool 函数体抽出
        现有 LangChain @tool 改为调用 core impl
        → 验证现有 Agent chat 功能不受影响

第二步  MCP Server 骨架                               (1 hr)
        mcp_server/ 目录 + server.py + __main__.py
        注册 4 个 tool（调用 core impl）
        → 验证 mcp dev 或 stdio 模式下 tools/list 返回正确

第三步  API Key 鉴权                                  (1 hr)
        McpApiKey 模型 + migration
        Flask 端 Key 管理 API
        MCP Server 端验证逻辑
        → 验证无 Key 被拒，有效 Key 通过

第四步  权限 + 限流 + 审计                             (30 min)
        TOOL_PERMISSIONS 扩展 ("mcp", ...) 维度
        per-key rate limiting
        McpAuditLog 落库
        → 验证权限矩阵生效

第五步  端到端测试                                     (30 min)
        stdio 模式 + Claude Desktop 实测
        SSE 模式 + HTTP 客户端实测
        tools/list → 4 个工具
        tools/call → 正确返回数据
        非法 Key → 拒绝
        超出 scope → 拒绝
        rate limit → 触发后返回 429
```

## 五、验证矩阵

| # | 测试项 | 操作 | 预期结果 |
|---|--------|------|---------|
| 1 | tools/list | MCP 客户端连接后列出工具 | 返回 4 个工具及 schema |
| 2 | search_knowledge | 搜索"数组" | 返回知识点列表 |
| 3 | search_similar_problems | 搜索"two sum" | 返回相似题目 |
| 4 | get_problem_detail | 传入有效 problem_id | 返回题目详情 + public test cases |
| 5 | get_problem_difficulty_stats | 传入有效 problem_id | 返回统计数据 |
| 6 | 无 API Key | 不传 Key 直接调 tool | 拒绝，返回认证错误 |
| 7 | 已吊销 Key | 使用已 revoke 的 Key | 拒绝 |
| 8 | 权限不足 | student role 的 Key 调 teacher-only 工具 | 拒绝 |
| 9 | scope 限制 | Key scopes 只含 search_knowledge，调 get_problem_detail | 拒绝 |
| 10 | Rate limit | 短时间内超过 rpm 限制 | 返回 429 / rate limit error |
| 11 | 审计日志 | 调用工具后查 mcp_audit_logs | 有记录，含 tool_name、user_id、latency |
| 12 | Claude Desktop 集成 | stdio 模式配置到 Claude Desktop | 能列出工具并正常调用 |
| 13 | 现有功能回归 | 运行 MCP Server 后，前端 chat 功能不受影响 | 正常 |

## 六、风险与注意事项

### 6.1 ChromaDB 进程共享

`search_knowledge` 和 `search_similar_problems` 底层调用 ChromaDB。如果 MCP Server 是独立进程，需要确保 ChromaDB 支持多进程访问（HTTP mode），或 MCP Server 复用 Agent Host 的 ChromaDB 连接。

当前 ChromaDB 使用方式需要确认：
- 如果是 persistent client（文件模式），多进程同时读没问题
- 如果是 in-memory，MCP Server 需要自己初始化 KB

### 6.2 embedding 模型加载

`KnowledgeBase` 首次初始化会加载 sentence-transformers 模型。MCP Server 独立进程意味着需要独立加载，首次请求可能有冷启动延迟（10-30 秒）。

**缓解**：MCP Server 启动时预加载 KB（在 `__main__.py` 的 startup 阶段完成）。

### 6.3 数据库迁移

新增 `mcp_api_keys` 和 `mcp_audit_logs` 两张表，需要 migration。

### 6.4 stdio 模式的 DB 连接

stdio 模式下 MCP Server 在本地运行，需要能连接到远程数据库。教师本地环境需要配置 DB 连接串（通过 `.env` 文件或环境变量）。

替代方案：stdio 模式下 MCP Server 不直连 DB，而是通过 HTTP 调用远程 MCP Server（SSE 模式）的 API。这样本地不需要 DB 配置。但这需要额外的 client/server 分层，第一版可暂不做。

## 七、不动的部分

以下在 Phase 3 中不修改：

- `agent_host/` — Agent Host 独立运行，不受 MCP Server 影响
- `app/agents/agents/` — 四个 specialist agent 不变
- `app/agents/orchestrator.py` — 编排逻辑不变
- `app/static/js/ai_chat.js` — 前端不变
- `app/agents/chat_worker.py` — chat worker 不变

## 八、后续（Phase 4 启动条件）

Phase 3 完成后，Phase 4（Human Gate + 高风险工具）的工作包括：

1. ⬜ 开放 `get_agent_trace`（需数据脱敏：移除 system prompt、tool 参数中的敏感数据）
2. ⬜ 开放 `get_student_summary`（需角色限制 + 数据脱敏 + 审计）
3. ⬜ 开放写入工具（`execute_code`、`save_generated_problem`）——需 Human Gate 审批
4. ⬜ MCP 客户端端审批 UI（tool call 需要用户确认后才真正执行）
5. ⬜ 可选：OAuth 2.0 鉴权叠加
