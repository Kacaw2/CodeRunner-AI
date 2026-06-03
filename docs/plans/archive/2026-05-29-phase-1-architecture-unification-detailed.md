# 阶段 1 — P1 架构合一 · 详细落地方案 (改动细节)

> 本文是 `2026-05-29-phase-1-4-architecture-hardening-plan.md` 中「阶段 1」的展开版，逐文件给出 before/after、删除清单、回归点与提交顺序。
> 状态：**规划，未执行修改。** 全部代码片段基于当前真实源码核对（2026-05-29）。
> 配套：Phase 0 安全三项见 `2026-05-29-0329-phase-0-security-hardening-plan.md`（已实现）。

---

## 0. 合一前必须知道的真实现状

| # | 事实 | 证据 |
|---|------|------|
| A | **网关进程不 bootstrap ToolRuntime**。`bootstrap_tool_runtime()` 仅在 `workers/task_runner.py:104,359` 调用；`mcp_gateway/__main__.py` 启动流程里没有。 | `mcp_gateway/__main__.py:33-77` |
| B | **三处工具清单当前内容一致**（低风险派生）：`AGENT_DEFINITIONS.*.allowed_tools`、各 agent 的 `*_MCP_TOOLS` 常量、`rbac._AGENT_TOOL_ALLOW` 三者逐项相等。 | `core/definitions.py:27-98`、`agents/*/agent.py`、`tools/protocol/policies/rbac.py:23-50` |
| C | **scope 模型不兼容**——合一最大回归点。API key 存的是「旧工具名集合」（如 `["search_knowledge"]`），而 `catalog` 的 `required_scopes` 是 `problem:read` / `code:execute` 这类权限串。 | `app/api/v1/mcp_keys.py:24`、`tests/test_mcp_gateway.py:154`、`tools/protocol/schemas/catalog.py:21,130` |
| D | **网关 handler 自带输入预校验**（如 `execute_code` 检查 `CODE_MAX_LENGTH`/`ALLOWED_LANGUAGES`），但 `runtime.call()` 目前**不做 input_schema 校验**——handler 收缩后无人兜底。 | `mcp_gateway/handlers/write.py:79-86`、`tools/protocol/runtime.py:132-134` |
| E | **审批落库在 handler 里**：`write.py:_create_approval` 写 `McpToolApproval` 行并返回 `approval_id`；而 `runtime` 的 `check_risk_policy` 只 `raise MCPApprovalRequired`，**不持久化**。 | `mcp_gateway/handlers/write.py:17-36`、`tools/protocol/policies/risk.py:15-20` |
| F | 网关暴露 **11** 个工具，`catalog` 注册 **14** 个 descriptor；差集（`submission.*`、`knowledge.search_error_patterns`、`analytics.student_stats`）是 agent 内部工具，不经网关。 | `mcp_gateway/server.py:21`、`tools/protocol/schemas/catalog.py` |

合一目标：**让 `mcp_gateway` 的 handler 退化为「鉴权 + 连接级限流」后直接调用 `runtime.call_sync()`**，把 RBAC / scope / risk / audit / 输入校验全部收敛到 `tools/protocol` 这一条管线，消除「网关一套、runtime 一套」的双轨。

---

## 1.1 RBAC 单一真相源（先做，风险低）

**目标**：`AGENT_DEFINITIONS` 成为 agent→工具清单的唯一来源；`agents/base.py` 与 `rbac.py` 都从它派生，删除两份重复常量。

### 改动 1 — `agents/base.py`：`mcp_tool_names` 改为派生 property

当前 (`agents/base.py:20-21`):
```python
    # Subclasses declare MCP tool names — never LangChain tool objects.
    mcp_tool_names: list[str] = []
```

改为:
```python
    @property
    def mcp_tool_names(self) -> list[str]:
        """Tool allowlist derived from the single source of truth."""
        from core.definitions import allowed_tools_for
        return list(allowed_tools_for(self.name))
```
- `allowed_tools_for` 已存在 (`core/definitions.py:120-125`)，返回 `tuple`，这里转 `list`。
- 依赖 `self.name`，四个 agent 都已声明（`name = "tutor"` 等），`BaseAgent.name = ""` 兜底返回 `[]`。

### 改动 2 — 四个 agent：删常量、invoke/stream 改用 `self.mcp_tool_names`

以 `agents/tutor/agent.py` 为例。

删除 (`tutor/agent.py:8-15` 整块) 以及 `mcp_tool_names = TUTOR_MCP_TOOLS` (`:22`)：
```python
TUTOR_MCP_TOOLS = [
    "coderunner.code.execute",
    "coderunner.problem.get_detail",
    ...
]
```

invoke/stream 入参改为 `self.mcp_tool_names` (`tutor/agent.py:89,92`):
```python
    def invoke(self, state: AgentState) -> AgentState:
        return self._invoke_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))
```

同样处理：
- `agents/reviewer/agent.py:8-11,18,32,35`（删 `REVIEWER_MCP_TOOLS`）
- `agents/analytics/agent.py:8-16,23,50,53`（删 `ANALYTICS_MCP_TOOLS`）
- `agents/generator/agent.py:16-20,87,152`（删 `GENERATOR_MCP_TOOLS`）

> **保留**：`generator/agent.py:56` 里 `_validate_solution` 用的字面量 `"coderunner.code.execute"` 不动（它是单工具直调，不属于 agent 工具清单）。

### 改动 3 — `tools/protocol/policies/rbac.py`：`_AGENT_TOOL_ALLOW` 从定义派生

当前 (`rbac.py:23-50`) 是硬编码 dict。改为：
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _agent_tool_allow() -> dict[str, frozenset[str]]:
    from core.definitions import AGENT_DEFINITIONS
    return {name: frozenset(d.allowed_tools) for name, d in AGENT_DEFINITIONS.items()}
```
`check_rbac` 内部把 `_AGENT_TOOL_ALLOW[agent]` 改为 `_agent_tool_allow().get(agent)`（`rbac.py:71-76`）:
```python
    agent = ctx.agent_type
    allow = _agent_tool_allow().get(agent)
    if allow is not None and tool_name not in allow:
        raise MCPPermissionDenied(
            f"Agent '{agent}' is not allowed to use tool '{tool_name}'.",
            trace_id=ctx.trace_id,
        )
```
- `_ROLE_OVERRIDES` (`rbac.py:13-21`) 保留不动——它是「角色级」覆盖，与 agent 清单正交。

### 改动 4 — 启动一致性自检 + 单测

在 `bootstrap_tool_runtime()`（`mcp_gateway/bootstrap.py:19`）末尾，注册完 registry 后加断言：
```python
    _assert_rbac_consistent(registry)
```
```python
def _assert_rbac_consistent(registry) -> None:
    """Fail fast if an agent declares a tool absent from the registry."""
    from core.definitions import AGENT_DEFINITIONS
    known = {d.name for d in registry.list_tools()}
    for agent, defn in AGENT_DEFINITIONS.items():
        missing = set(defn.allowed_tools) - known
        if missing:
            raise RuntimeError(f"Agent '{agent}' references unknown tools: {sorted(missing)}")
```

新增单测 `tests/test_rbac_single_source.py`：
- `allowed_tools_for(name)` == 实例化 agent 的 `.mcp_tool_names`（四个 agent）。
- `_agent_tool_allow()[name]` == `set(AGENT_DEFINITIONS[name].allowed_tools)`。
- agent 每个工具名都在 `TOOL_CATALOG` 中。

### 1.1 的测试连带修改
现有测试直接 import 旧常量，删常量后会 `ImportError`：
- `tests/test_tool_protocol.py:385,392,398,405`
- `tests/test_agent_features.py:295`

改为断言 `TutorAgent().mcp_tool_names` / `allowed_tools_for("tutor")`，语义等价。

---

## 1.2 MCP Gateway 合一走 ToolRuntime

### 1.2.0（前置）`__main__.py` 启动时 bootstrap

在 `mcp_gateway/__main__.py` 的 `init_db` 之后、`create_mcp_server()` 之前插入（参照 `task_runner.py:103-104`）：
```python
    # ── Bootstrap MCP ToolRuntime (single tool pipeline) ──
    from mcp_gateway.bootstrap import bootstrap_tool_runtime
    from core.db.session import get_session
    bootstrap_tool_runtime(session_factory=get_session)
    logger.info("ToolRuntime bootstrapped")
```
> 注意 `task_runner` 传的是 `lambda: session`（单 session）。网关是长驻进程，必须传 `get_session`（每次新 session），避免跨请求复用同一 session。需确认 `get_session()` 行为是「每调用返回新 session」——若是 scoped_session 需在 handler 内 `close()`，见 1.2.1。

### 1.2.1 新增 `call_via_runtime(mcp_tool, args)` 适配器

放在 `mcp_gateway/middleware/core.py`（或新建 `mcp_gateway/runtime_bridge.py`）。职责：把网关的 `caller_info` dict → `CallerContext`，调 `runtime.call_sync`，把 `ToolResult` → 网关返回的 JSON 字符串。

```python
def call_via_runtime(mcp_tool: str, args: dict) -> str:
    """Gateway → ToolRuntime bridge. Auth + rate-limit已在外层, 这里只转发。"""
    from tools.protocol import get_tool_runtime, ToolCallContext
    from core.auth.context import CallerContext

    caller = get_caller_info()  # 已由 __main__ set_caller_info 注入
    ctx = ToolCallContext(caller=CallerContext(
        actor_type="external_client",
        user_id=caller["user_id"],
        role=caller["role"],
        api_key_id=caller.get("api_key_id"),
    ))
    result = get_tool_runtime().call_sync(mcp_tool, args, ctx)
    return json.dumps(result.to_envelope(), ensure_ascii=False, default=str)
```
- `ToolResult.to_envelope()` 已实现（`runtime.py:52-68`），统一 `{ok, tool, trace_id, ...}` 或 `{ok:false, error:{code,message,retryable}, status, approval_id}`。
- **限流**：`runtime` 不做连接级限流，所以 `check_rate_limit(api_key_id, rpm)` 仍由网关侧保留（见 1.2.2 的包裹）。

### 1.2.2 六个 handler 收缩为单行 + 工具正名

下表是「网关旧工具名 → runtime 规范名」（依据 `_LEGACY_TO_MCP` + handler 现状核对）：

| handler 文件 | 旧 `@mcp.tool` 名 | runtime 规范名 |
|---|---|---|
| `knowledge.py` | `search_knowledge` | `coderunner.knowledge.search` |
| `knowledge.py` | `search_similar_problems` | `coderunner.knowledge.search_similar_problems` |
| `problems.py` | `get_problem_detail` | `coderunner.problem.get_detail` |
| `problems.py` | `get_problem_difficulty_stats` | `coderunner.analytics.problem_difficulty` |
| `analytics.py` | `get_student_activity` | `coderunner.analytics.student_activity` |
| `analytics.py` | `get_class_statistics` | `coderunner.analytics.class_statistics` |
| `traces.py` | `get_agent_trace` | `coderunner.trace.get_agent_trace` |
| `students.py` | `get_student_summary` | `coderunner.student.get_summary` |
| `write.py` | `execute_code` | `coderunner.code.execute` |
| `write.py` | `save_generated_problem` | `coderunner.problem.save_generated` |
| `write.py` | `check_approval` | （无 runtime 对应，见 1.2.5 保留） |

> **工具正名是破坏性变更**：旧客户端按 `search_knowledge` 调用会 404。决策点——是否保留旧名作 alias？建议**保留旧名一个过渡期**：`@mcp.tool(name="search_knowledge")` 函数体内调 `call_via_runtime("coderunner.knowledge.search", ...)`，即「正名走 runtime，但对外仍暴露旧名」。这样 1.2 不引入对外 API 破坏，正名留到后续单独版本。下面以「保留旧名」写法示范。

before — `knowledge.py:14-34`（`search_knowledge`，27 行含 guard/try/except/audit）。
after：
```python
def register_knowledge_tools(mcp: FastMCP):
    @mcp.tool(name="search_knowledge", description="...")
    def search_knowledge(query: str, owner_id: int | None = None) -> str:
        return _guarded(lambda: call_via_runtime(
            "coderunner.knowledge.search", {"query": query, "owner_id": owner_id}))
```
其中 `_guarded` 封装「auth 已在 contextvar + 连接级限流」：
```python
def _guarded(fn):
    caller = get_caller_info()
    if not caller:
        return json.dumps({"ok": False, "error": {"code": "MCP_AUTH_REQUIRED"}})
    if not check_rate_limit(caller["api_key_id"], caller.get("rate_limit_rpm", 30)):
        return json.dumps({"ok": False, "error": {"code": "MCP_RATE_LIMITED"}})
    return fn()
```
- RBAC / scope / risk / 审计 全部由 `runtime.call` 内部 `run_guard` + `_emit` 负责，handler 不再 import `run_mcp_guard`。
- `problems.py`、`analytics.py`、`traces.py`、`students.py` 同样套路（注意 `traces`/`students` 现有的 `sanitize_*` 输出脱敏——见 1.2.6）。
- `write.py` 的 `execute_code` / `save_generated_problem` 走 1.2.4 的审批下沉路径。

### 1.2.3 删除清单（`mcp_gateway/middleware/core.py`）

确认无引用后删除：
- `_LEGACY_TO_MCP`（`core.py:23-31`）
- `TOOL_RISK_LEVELS`（`core.py:45-57`）
- `run_mcp_guard` + `GuardResult` + `check_tool_permission` + `mcp_tool_middleware`（`core.py:34-41,76-161`）

连带：
- `mcp_gateway/middleware/__init__.py:2-12,14-24` 去掉对应导出。
- **保留** `set_caller_info` / `get_caller_info` / `CODE_MAX_LENGTH` / `ALLOWED_LANGUAGES`（仍被 `__main__`/`write` 用）。
- 测试 `tests/test_mcp_gateway.py` 中针对 `run_mcp_guard` / `check_tool_permission` / `TOOL_RISK_LEVELS` 的用例需改写为走 `runtime.call` 的等价断言（`:259-304` 一批 caller scopes 用例与 1.2 的 scope 决策强相关，见硬骨头 ①）。

### 1.2.4 错误 envelope 统一

handler 旧写法 `return json.dumps({"error": str(e)})`（散落各文件）全部由 `call_via_runtime` 的 `result.to_envelope()` 取代。异常不再在 handler `try/except`——`runtime.call` 已捕获并转 `MCPInternalError`（`runtime.py:152-157`），返回标准 envelope。前端/客户端解析逻辑需从 `data.error`（字符串）迁移到 `data.error.code` + `data.error.message`（破坏性，需同步改调用方）。

---

## 三个硬骨头（建议各拆独立子任务/提交）

### ① scope 模型统一（最大回归点）
现状（事实 C）：API key `scopes` = 旧工具名集合；`catalog.required_scopes` = `problem:read` 类权限串。`check_scope`（`scopes.py:10-28`）对 `actor_type == "agent_host"` 直接放行，但网关 caller 是 `external_client`，会真正校验 → 用现有 key 必然 `MCPScopeDenied`。

三种过渡策略：
- **(a) 过渡期放行**（最小改动，先合一后治理）：`call_via_runtime` 构造的 `CallerContext` 暂用 `actor_type="agent_host"`，或 `check_scope` 增加「`external_client` 且未携带新式 scope 时跳过」的过渡分支。代价：暂时丢失 external client 的 scope 隔离。
- **(b) 映射层**：建 `LEGACY_SCOPE_TO_REQUIRED = {"search_knowledge": "knowledge:read", ...}`，`call_via_runtime` 把 key 的旧 scopes 映射为 `granted_scopes` 传给 `runtime.call`（需给 `call`/`call_sync` 增加 `granted_scopes` 形参透传到 `run_guard`）。
- **(c) 重发 key**：迁移脚本把库里 `scopes` 批量改写为权限串，并改 `app/api/v1/mcp_keys.py` 的签发逻辑用新词表。最干净但需停机/迁移。

建议：**(a) 先合一**（标注 TODO + 单测固定「external client 过渡期放行」行为），scope 治理作为 1.2 之后的独立任务走 (b)→(c)。

### ② input_schema 在 runtime 校验
现状（事实 D）：`runtime.call`（`runtime.py:132-134`）只 `_sanitize_args` 后直接 `transport.call`，不校验 input。handler 收缩后，`execute_code` 的长度/语言预校验（`write.py:79-86`）会丢失。

改 `runtime.py` 在 `_sanitize_args` 后、`transport.call` 前插入：
```python
            sanitized = self._sanitize_args(args, caller)
            self._validate_input(descriptor, sanitized, trace_id)   # 新增
            raw = await self._transport.call(...)
```
```python
    @staticmethod
    def _validate_input(descriptor, args, trace_id):
        import jsonschema   # 已在 requirements
        try:
            jsonschema.validate(args, descriptor.input_schema)
        except jsonschema.ValidationError as e:
            raise MCPArgumentInvalid(e.message, trace_id=trace_id)
```
- `MCPArgumentInvalid` 已存在（`errors.py:131-132`，code=`MCP_ARGUMENT_INVALID`，422）。
- **坑**：`_sanitize_args` 注入了 `_caller_user_id` / `_caller_role` / `student_id` / `teacher_id`（`runtime.py:182-191`），而 catalog 多数 schema 是 `additionalProperties: False`（如 `catalog.py:28,58`）→ 校验必失败。两条路：
  - 校验**注入前**的 `args`（用原始 args 校验，sanitized 仅用于 transport）；或
  - schema 放开 `additionalProperties` / 显式允许 `_caller_*`。
  推荐**先校验原始 args**（语义正确：schema 描述的是调用者契约，不含内部注入字段）。
- schema 先松后紧：先对少数工具开启校验跑回归，再全量。

### ③ 高风险审批落库下沉到 `runtime.call`
现状（事实 E）：`risk.py:check_risk_policy` 对 `code.execute` / `problem.save_generated`（HIGH + TEACHER_REQUIRED）只 `raise MCPApprovalRequired`，**没建 `McpToolApproval` 行**；落库逻辑在 `write.py:_create_approval`。handler 收缩后审批行不再被创建，`check_approval` 轮询会查无此 id。

下沉方案：把 `_create_approval` 的持久化逻辑搬进 runtime 审批分支。`run_guard` 目前不接触 args/session，需让审批分支拿到二者：
- 在 `runtime.call` 检测到 `guard.error` 是 `MCPApprovalRequired` 时（`runtime.py:120-129`），调用一个可注入的 `approval_store.create(descriptor, caller, args) -> approval_id`，把返回的 `approval_id` 放进 `ToolResult`。
- `approval_store` 默认实现 = 现 `_create_approval` 的搬迁（写 `McpToolApproval`，`risk_level`、`tool_args`、`expires_at`），通过 `bootstrap_tool_runtime` 注入（避免 `tools/protocol` 反向依赖 `core.db.models`）。
- `check_approval` 工具保留在网关（1.2.5），其 `_execute_approved_tool`（`write.py:39-58`）改为审批通过后调 `runtime.call`（绕过 risk 再次拦截——需一个 `approved_resume_token` 或 `actor_type` 旁路，避免二次 `MCPApprovalRequired` 死循环）。

> 这是三块里最重的，建议独立提交并配端到端测试：发起 → pending → 教师 approve → check_approval 返回 executed+result。

### 1.2.5 `check_approval` 保留为网关原生工具
它不在 catalog、不走 runtime（纯审批轮询/落地执行）。保留 `write.py` 中 `check_approval`，但其内部 `_execute_approved_tool` 按硬骨头 ③ 改为走 runtime。

### 1.2.6 输出脱敏（traces/students）位置确认
`get_agent_trace` / `get_student_summary` 现在在 handler 里做 `sanitize_agent_trace` / `sanitize_student_summary`（`traces.py:33`、`students.py:34`）。收缩走 runtime 后，脱敏不能丢。两条路：
- 脱敏下沉为这两个工具的 transport handler 的一部分（在 `bootstrap.py` 的 `agent_trace`/`student_summary` 包装函数里调 sanitize）；**推荐**，保证任何调用方都脱敏。
- 或 `call_via_runtime` 后在网关侧对这两个工具结果再脱敏（不够彻底，agent 直调 runtime 时不脱敏）。

---

## 2. 回归验证步骤

1. **1.1 单测**：`pytest tests/test_rbac_single_source.py tests/test_tool_protocol.py tests/test_agent_features.py -x`。
2. **bootstrap 自检**：进程启动不抛 `RuntimeError`（一致性断言通过）。
3. **网关冒烟**：`python -m mcp_gateway --transport streamable-http`，用一把测试 key 依次调 11 个工具，断言：
   - 低风险只读工具返回 `ok:true`；
   - `code.execute` / `save_generated_problem` 返回 `status:approval_required` + `approval_id`，且 `McpToolApproval` 有对应行；
   - 教师 approve 后 `check_approval` → `executed` + result。
4. **scope 回归**：用 `scopes=["search_knowledge"]` 的受限 key，确认过渡期策略 (a) 下不误杀（并留 TODO 测试锁定行为）。
5. **错误 envelope**：故意传非法 args，断言返回 `{ok:false, error:{code:"MCP_ARGUMENT_INVALID"}}`。
6. **agent 链路**：跑一轮 tutor/generator 任务（经 `task_runner`），确认 agent 侧 `mcp_tool_names` property 生效、工具调用与 trace 正常。

---

## 3. 建议提交顺序（每步可独立回滚）

```
C1  1.1 RBAC 派生 + 自检 + 单测            （低风险，先合并）
C2  1.2.0 __main__ bootstrap ToolRuntime   （仅新增启动调用，行为不变）
C3  1.2.2 只读 handler 收缩（knowledge/problems/analytics/traces/students）
        + 1.2.6 脱敏下沉 + 1.2.4 envelope
C4  硬骨头② input_schema 校验（先少量工具→全量）
C5  硬骨头① scope 过渡策略 (a) + 锁定测试
C6  硬骨头③ 审批下沉 + write handler 收缩 + check_approval 改造（端到端测试）
C7  1.2.3 删除 _LEGACY_TO_MCP / TOOL_RISK_LEVELS / run_mcp_guard 等死代码 + 测试改写
```

**关键依赖**：C2 必须先于 C3（handler 走 runtime 前 runtime 必须已 bootstrap）；C7 放最后（确认无引用再删）。

**最高 ROI**：1.2 合一单点消除「网关一套 RBAC/risk/audit、runtime 一套」的双轨重复；但回归面最大，务必先稳住 1.1 再啃 1.2，并把三个硬骨头拆开提交。
