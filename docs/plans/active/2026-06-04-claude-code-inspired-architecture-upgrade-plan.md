# Claude Code-Inspired Architecture Upgrade Plan

> 状态：Active  
> 日期：2026-06-04  
> 范围：`agents/`、`graph/`、`workers/`、`mcp_gateway/`、`tools/protocol/`、`core/definitions.py`、`core/observability/`、`evals/`

## 目标

把 CodeRunner-AI 从“带 AI 功能的在线评测平台”升级为“Claude Code 风格的 agentic coding education platform”。

这里的目标不是复制 Claude Code 的产品界面，而是学习它的工程思想：工具优先、运行时角色隔离、声明式 agent 定义、平台强制权限、可管理上下文、可观测 trace、可回放 eval，以及计划与执行分离。

## 当前状态

项目已经具备成熟 agentic 系统的若干基础，但还没有完全收束成统一平台内核。

| 领域 | 当前已有能力 | 主要不足 |
|---|---|---|
| Agent 定义 | `core/definitions.py` 已声明 agent 名称、角色、工具白名单、risk、输入字段、输出格式 | registry 还不包含完整运行预算、handoff 目标、prompt/source、session 策略 |
| Agent 运行 | `agents/base.py` 已有 LLM/tool loop、trace、system prompt 隔离、limit exceeded、legacy function 文本兼容 | `BaseAgent` 仍承担过多职责，缺少显式 `AgentSession` / `AgentRuntime` |
| 工具调用 | `agents/executor.py` 已抽出 `ToolCallExecutor`，agent 通过 MCP client boundary 调工具 | trace_id、budget、identity 等运行时上下文仍依赖 raw `state/context` 传递 |
| Lifecycle hooks | `agents/hooks.py` 已有 contract validation、tool allowlist、output validation、trace audit | hook 是局部机制，还没有由统一 runtime session 串起来 |
| MCP / ToolRuntime | `tools/protocol/runtime.py` 已是工具执行、schema、guard、audit 的核心 | 内部 ToolRuntime 与外部 `mcp_gateway` 边界还需要继续统一语义 |
| Worker / Harness | `evals/harness/agent_harness.py` 已支持单逻辑 trace 和 handoff chain | Flask 同步、Flask SSE、worker/harness 仍是多套编排路径 |
| Workflow | `graph/supervisor.py`、`graph/engine.py` 已有 plan -> step -> execute 模型 | 尚未成为所有多步 agentic 任务的统一执行入口 |
| Eval / Trace | trace 表、eval harness、runtime warning 已具备基础 | eval 还不是模型、prompt、工具、runtime 改动的质量门禁 |

## Claude Code 思路映射

| Claude Code 成熟模式 | CodeRunner-AI 对应升级方向 |
|---|---|
| Subagent 独立上下文 | 每次 agent run 由 `AgentSession` 管理消息、上下文、trace、预算和工具身份 |
| 声明式 agent 配置 | 扩展 `core/definitions.py` 为完整 `AgentDefinition` registry |
| 工具优先 | 所有 agent 能力围绕 MCP tool、ToolRuntime、代码执行、题库、提交、trace、eval 展开 |
| 平台强制权限 | 权限、scope、risk、human gate、audit 在 runtime 强制执行，不依赖 prompt |
| 计划与执行分离 | `SupervisorAgent` / `WorkflowEngine` 成为多步任务的计划和执行核心 |
| 上下文可管理 | 区分用户对话、agent scratch、tool residue、handoff summary、long-term memory |
| 可观测和可回放 | trace + eval + regression replay 形成质量闭环 |

## 分阶段路线

### Phase 1: Agent Runtime Kernel 收束

目标：把已有 `BaseAgent`、`ToolCallExecutor`、hooks、trace、harness 收束成统一运行时内核。

具体方向：

- 新增 `AgentSession`，显式承载 `agent_name`、`definition`、`user_id`、`user_role`、`messages`、`context`、`trace_id`、`budget`、`source`、`tool_client`。
- 新增轻量 `AgentRuntime` facade，统一 `run()` / `stream()` 的运行语义。
- 把 `BaseAgent` 中的模型调用、消息压缩、token usage 统计逐步抽到 `LLMRunner`。
- 让 `ToolCallExecutor` 从 session 获取 trace、identity、budget，而不是散落读取 raw `state/context`。
- 保持四个 specialist agent 的外部行为不变，先做内部边界收束。

验收标准：

- 每次 agent run 都能明确对应一个 session 和 trace。
- 工具调用 audit 使用同一个 trace_id。
- system prompt 仍不写回 conversation history。
- `limit_exceeded`、hook、handoff、output validation 行为不回退。
- 同步 invoke、stream、worker harness 的现有测试继续通过。

### Phase 2: Declarative Agent Registry 完整化

目标：让 `core/definitions.py` 成为 agent 配置的单一事实源。

具体方向：

- 扩展 `AgentDefinition`：`prompt_ref`、`max_tool_iterations`、`max_llm_calls`、`budget_policy`、`handoff_targets`、`context_policy`。
- API、worker、orchestrator、ToolCallExecutor、eval harness 都从 registry 读取 agent 能力。
- 清理 agent 类中重复声明的模型、工具、权限和契约信息。
- 增加 registry consistency tests，防止 contracts、schemas、tools、roles 漂移。

验收标准：

- agent 工具白名单、角色权限、输出 schema、预算都能从一个 registry 查询。
- 新增 agent 不需要修改多处运行时分支。
- `auto` route、worker、eval、MCP scope 读取同一份定义。

### Phase 3: Unified Tool / MCP Boundary

目标：让内部 agent 工具调用和外部 MCP client 调用共享同一套平台边界。

具体方向：

- 明确边界语言：Flask 是主业务 app；FastAPI Agent Host 是 agent runtime/scheduling service；agents 是内部业务逻辑；DeepSeek 是外部 provider；MCP / ToolRuntime 是工具层。
- `mcp_gateway` 保留外部 transport、auth、连接限流职责。
- 工具 schema、RBAC/scope/risk guard、human gate、identity sanitize、audit、trace link 下沉到 ToolRuntime。
- 内部 in-process path 和外部 streamable-http path 保持同等权限语义。

验收标准（状态：已满足，2026-06-04 收口）：

- [x] agent 不直接 import 工具实现 — `tests/test_agent_mcp_client_boundary.py`。
- [x] 外部 MCP 与内部 agent 工具调用返回一致 envelope — `tests/test_mcp_boundary_consistency.py`（同一工具+身份，两路径同 guard 判定 + 同 envelope 形状）。
- [x] 工具调用都能关联 user、role、agent、conversation、task、trace — `CallerContext` + `emit_audit`（`tools/protocol/runtime.py`）。
- [x] high-risk / write 工具继续经过 human gate — `tests/test_mcp_gateway_human_gate.py`。

> 收口范围与剩余加固见 `docs/plans/active/2026-06-04-phase3-unified-tool-mcp-boundary-closeout-plan.md`。
> Phase 3.5（已完成，见 `2026-06-04-phase3.5-toolruntime-hardening-plan.md`）落地了 boundary 内部加固：
> `retry_policy` 真正生效（仅 retryable 错误、`max_attempts=0` 行为不变）、output_schema 补全为真实
> schema 并加 `MCP_OUTPUT_SCHEMA_ENFORCE` 开关（默认 warn-only，可一键转 enforce）。
> 仍延后到 Phase 6 的企业级加固：per-tool/per-user 配额、写工具幂等、多租户隔离、per-tool 熔断、
> live-HTTP 集成测试（均为 YAGNI / 运维质量门禁范畴，待真实需求落地再做）。

### Phase 4: Planning and Task Execution System

目标：把 supervisor/workflow 从“部分场景使用”升级为多步 agentic 任务的核心。

具体方向：

- 强化 `SupervisorAgent` 的任务判断、plan schema、step 类型和失败处理。
- 让多步任务统一进入 `WorkflowEngine`，支持 `agent_call`、`tool_call`、`validation`、`human_gate`、`resume`。
- 每个 workflow run 和 step 都绑定 trace、audit、approval、output。
- 将 handoff 从文本标记进一步收敛为结构化 delegation payload。

验收标准：

- 多步任务可暂停、审批、恢复、失败重试和状态回放。
- workflow step 的输入输出可以被 trace/eval 关联。
- handoff 不再传递完整工具残留，只传递摘要和结构化上下文。

### Phase 5: Context and Memory Architecture

目标：把上下文从“消息列表”升级为可治理资产。

具体方向：

- 区分 user-visible conversation、agent internal scratch、tool residue、handoff summary、long-term memory。
- 建立 compaction 前后 trace 事件，明确哪些内容被压缩、保留或丢弃。
- 让 memory service 只注入与 agent 目标相关的上下文，避免所有 agent 共享同一份无差别记忆。
- 为 eval/replay 保存必要上下文快照。

验收标准：

- agent run 不因历史无限增长而失控。
- handoff 上下文短、结构化、可审计。
- eval replay 能复原关键输入，而不是依赖当时的临时内存。

### Phase 6: EvalOps and Replay

目标：让 eval 成为 agent 平台的质量门禁。

具体方向：

- 数据集分层：`golden`、`regression`、`production_failure`、`security`、`hidden`。
- eval run 绑定 trace、agent version、model tier、prompt/version、tool catalog version。
- CI 跑 fast eval，大改动跑 full eval。
- 线上失败可以回放并沉淀为 regression case。

验收标准：

- prompt/model/tool/runtime 改动前后能看到 eval diff。
- 失败样例能定位到具体 agent、tool、trace span、输出 schema。
- regression case 能阻止已修复问题再次出现。

## Phase 1 起步任务

第一阶段不应先大改 MCP 或 UI，而是先收束运行时内核。

建议顺序：

1. 新建 `agents/session.py`，定义 `AgentSession` 和 state/session 转换方法。
2. 新建 `agents/runtime.py`，提供 `AgentRuntime.run()` 和 `AgentRuntime.stream()` facade。
3. 新建或扩展 `agents/llm_runner.py`，承接模型调用、retry、message compaction、token accounting。
4. 修改 `ToolCallExecutor`，优先从 session 获取 trace_id 和 identity；保留 state 兼容路径。
5. 修改 `BaseAgent`，让 `_invoke_with_mcp_tools()` 和 `_stream_with_mcp_tools()` 通过 session/runtime 组织执行。
6. 修改 `AgentHarness`，使用同一 session/runtime 语义创建 agent run。
7. 增加 focused regression tests，确认 trace、tool identity、hooks、limit exceeded、system prompt 隔离不回退。

## 暂不纳入第一阶段

- 不做 dashboard / trace viewer UI。
- 不做完整 MCP Gateway 重写。
- 不做大规模 eval dataset 扩充。
- 不做四个 specialist agent 的 prompt 重写。
- 不引入新的外部 LLM provider。

## 总体完成标准

完成这条路线后，CodeRunner-AI 应该具备以下平台能力：

- agent 是平台运行时角色，不只是 Python 类。
- 工具权限由平台强制，不靠 prompt 自觉。
- 每次 agent run 可追踪、可审计、可回放。
- 多步任务有计划、执行、审批、恢复和失败终态。
- eval 能保护 agent runtime、prompt、model 和 tool catalog 的持续演进。
