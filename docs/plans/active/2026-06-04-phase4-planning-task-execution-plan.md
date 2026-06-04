# Phase 4: Planning and Task Execution System — 可执行任务清单

> 状态：Active
> 日期：2026-06-04
> 上位计划：`docs/plans/active/2026-06-04-claude-code-inspired-architecture-upgrade-plan.md`（Phase 4 节）
> 范围：`graph/`、`app/models/workflow.py`、`core/db/models/workflow.py`、`core/db/models/agent_trace.py`、`core/db/models/mcp_approval.py`、`migrations/`、`tools/protocol/`

## 背景：代码现状（落任务前的事实基线）

Phase 4 不是从零搭 workflow。早先工作已经搭好 workflow 骨架，本阶段是在其上补“可追溯 / 可审计 / 结构化 delegation / 统一入口”这一层。

已具备：

- `graph/engine.py` `WorkflowEngine.execute()` / `resume_after_approval()`：step 循环、DB 持久化、human_gate 暂停、per-step retry + critic 回退、SSE 事件流。
- `graph/planner.py` `create_plan()`：模板（generation/review）+ LLM 规划，step 类型 `agent_call/tool_call/validation/llm_call/human_gate`，`risk_level`/`requires_approval`/`depends_on`。
- `graph/handlers.py` + `graph/node_registry.py`：step 类型分发；`node_registry.py:57` 已从 agent 返回值取到 `trace_id`，但 engine 未落库。
- `graph/handoff.py`：已产出结构化字段 `handoff_to/handoff_reason/handoff_source/handoff_summary`，但**触发仍是 LLM 文本里 regex 抠 `[HANDOFF: agent | reason]`**。
- `graph/recovery.py`：启动时把中途 workflow 直接标 `failed`（不做 mid-flight resume，安全取向）。

Phase 1 依赖已就绪（已核对）：

- `agents/session.py` `AgentSession` 承载 `trace_id`；`agents/runtime.py` `_acquire()` 生成 `trace_id`（`TraceCollector.run_id`），`run()/stream()` 返回的 state 经 `to_state()` 带回 `trace_id`。
- `core/db/models/agent_trace.py:48` `trace_id` 唯一索引列；**`:55` 已有 `workflow_run_id` 列**（trace→workflow 的反向引用位已存在，但当前未被 engine 写入）。
- 结论：workflow step 要存 trace_id **无需新增贯穿管线**，agent.invoke() 返回的 state 里已有可用且与 trace store 一致的 `trace_id`。

关键约束（写任务时必须遵守）：

1. **双 ORM 一致性**：`workflow_runs` / `workflow_steps` 两张表由两份模型映射——`app/models/workflow.py`(Flask `db.Model`，被 engine/supervisor/recovery/`app/api`/测试用) 与 `core/db/models/workflow.py`(纯 SQLAlchemy `Base`，被 `workers/task_runner.py`、`app/api/v1/agents/workflows.py` 用)。任何加列必须**两份同步改**。
2. **Migration 优先**：按既定 schema 策略，所有加列必须配一条 Alembic migration，模型定义与 migration 同时落地，禁止只靠 `create_all()`。
3. **既有行为不回退**：human_gate 暂停/恢复、per-step retry、critic、SSE 事件、`recovery` 安全标 failed 行为保持。

## 任务清单（按价值与依赖排序）

### T1 — trace_id 双向绑定（最高优先，依赖已就绪）✅ Done

> 落地：`workflow_steps.trace_id` 双 ORM 加列 + migration `b1f7a2c9d3e4`；`graph/engine.py` 注入 `workflow_run_id/step_index` 并回写 `trace_id`；`graph/node_registry.py` 透传/回传 trace_id。验收测试 `tests/test_workflow_trace_binding.py` 绿。

**目标**：每个 workflow step 落库其 agent run 的 `trace_id`；每条 trace 反向记录所属 `workflow_run_id` + `step_index`。打通 workflow ↔ trace ↔ eval。

**改动**：
- schema：`workflow_steps` 加列 `trace_id VARCHAR(64) NULL`（指向 `agent_trace_runs.trace_id`，建索引；用逻辑引用即可，不强加 FK 约束以免跨 ORM/跨库耦合）。两份模型 + 一条 migration。
- `graph/engine.py`：执行 step 前，把 `workflow_run_id` 和 `step_index` 注入传给 agent 的 `state["context"]`，使 `AgentSession`/trace 记录 `workflow_run_id`（填充 `agent_trace.py:55` 已有列）；step 完成后把 handler 返回的 `trace_id`（`node_registry.py:57` 已取到）写入 `WorkflowStep.trace_id`，而不是丢弃。
- `tool_call` step：同理把 `trace_id` 透传到 `ToolCallContext`，保证工具 audit 与 step 同 trace。

**验收**：一个多步 run 执行后，`workflow_steps.trace_id` 全部非空，且能在 `agent_trace_runs` 查到对应 `trace_id`；该 trace 的 `workflow_run_id`/`step_index` 与 step 对应。新增 `tests/test_workflow_trace_binding.py`。

### T2 — 结构化审批审计记录（替换 output_data 内联反馈）✅ Done

> 落地：评估后新建独立 `workflow_approvals` 表（migration `c2e8b4f1a6d7`）+ `WorkflowApproval` 模型（`app/models/workflow.py`），未复用 `mcp_approval`（其 resource/scope 模型面向 MCP 工具审批，强塞 workflow 反而耦合）；`graph/engine.py resume_after_approval()` 先写 approval 记录再分叉 approve/reject，approve 路径 `output_data` 不再含 feedback；`approver_user_id` 由 API（`app/api/v1/ai.py`）→ supervisor → engine 透传，不从 LLM/state 自取。验收测试 `tests/test_workflow_approval_audit.py` 绿。

**目标**：human_gate 审批产生不可变审计记录（审批人、决策、意见、时间），而非把反馈塞进 `WorkflowStep.output_data`。

**改动**：
- 先评估复用 `core/db/models/mcp_approval.py`（已存在的审批模型）——若其结构可承载 workflow 审批（resource 类型 + reference id + approver + decision + feedback + ts），优先扩展复用，避免新建并行审批体系；不合适再新增 `workflow_approvals` 表。
- `graph/engine.py` `resume_after_approval()`：写一条 approval 记录（`workflow_run_id`、`step_index`、`approver_user_id`、`decision=approved|rejected`、`feedback`、`created_at`），`output_data` 不再作为审批轨迹来源。
- `SupervisorAgent.resume_workflow()` / API resume 入口：把当前操作者 user_id 传到 engine，作为 `approver_user_id`（不能从 LLM/state 自取）。

**验收**：审批后存在独立 approval 记录含 approver 身份与决策；驳回路径也留痕。新增 `tests/test_workflow_approval_audit.py`。

### T3 — handoff 改为 tool-based delegation（去掉 regex 文本标记）

**目标**：把 delegation 从“LLM 写 `[HANDOFF:...]` 文本、平台 regex 解析”改为**结构化 tool call**，由工具边界做 schema 校验 + role/target RBAC——对齐“平台强制权限，不依赖 prompt”与 Claude Code 的 tool_use delegation 模式。

**改动**：
- 在 ToolRuntime 注册一个受管控的 `delegate`（或 `handoff`）工具，typed 参数 `target: agent_type`、`reason: str`、`summary: str`；target 合法性、`can_route_to(target, user_role)`、summary 截断在工具边界强制。
- `agents/` 系统 prompt：移除 `HANDOFF_PROMPT_ADDENDUM` 的文本标记教学，改为说明调用 `delegate` 工具。
- `graph/handoff.py`：保留已结构化的 `handoff_to/reason/source/summary` 字段与 `apply_handoff()`/`rebuild_handoff_messages()`（这部分已是好设计）；删除 `HANDOFF_PATTERN` 正则与 `detect_handoff()` 的文本解析，改由 `delegate` 工具调用结果填充这些字段。
- ~~灰度：可加开关，先让 tool 与 regex 并存一版~~ → **执行偏差（已决策）**：不灰度、不留开关，一次性**硬删 regex**，tool-based delegation 成为唯一路径。

**执行偏差与理由（hard-delete regex，非灰度）**

原计划设想 tool/regex 并存一版灰度。决策改为一次性硬删 `[HANDOFF:...]` 文本解析，依据如下业界先例——delegation 应是平台强制的结构化能力，而非可被绕过的「模型输出文本约定」：

- **OpenAI Agents SDK**：handoff 作为 LLM 可调用的工具暴露（如 `transfer_to_refund_agent`），带 typed handoff input / input filter / handoff tracing——委派是 typed tool call，不是文本标记。
- **Claude Code Agent SDK / subagents**：子代理经 Agent 工具调用，拥有独立 context / 专用 prompt / 受限 tool 集——委派由工具边界与能力清单约束。
- **Claude Code MCP 文档**：强调通过 MCP 工具扩展 agent，而非依赖特殊的模型输出文本。

regex 文本通道与 tool 通道并存只会留下一个绕过 RBAC 的后门，灰度无收益；故直接收敛到工具边界。

**实现清单（落地步骤，逐项可勾选）**

*核心管线（delegate 工具落地）*
- [x] `tools/protocol/schemas/catalog.py`：`_reg()` 新增 `coderunner.agent.delegate` 描述符——`server="agent"`、`internal_only=True`、`required_scopes=["agent:delegate"]`、typed 参数 `target`(agent_type enum)/`reason`(str)/`summary`(str)。
- [x] `mcp_gateway/bootstrap.py`：注册 delegate handler（`_register_agent_handlers` → `transport.register_handler`）；handler 经共享 `validate_handoff_target(source, target, role)` 在边界做 `target` 合法性 + per-source 声明 + `can_route_to(target, caller_role)` 校验，越权 raise `MCPPermissionDenied`（→ audit status=error，envelope ok=False）；summary 截断。
- [x] `tools/protocol/runtime.py` `_sanitize_args`：注入 `_caller_agent_type`，使 delegate handler 能识别发起方 agent 做 `can_route_to`。（原计划误写 `agents/runtime.py`；`_sanitize_args` 实际在 `tools/protocol/runtime.py`。）
- [x] `agents/executor.py` `ToolCallExecutor.run`：识别 delegate 工具调用结果，把 `handoff_to/handoff_reason/handoff_source/handoff_summary` 写入 `session.extra_state`（经 `session.to_state()` → `_apply_after_run` 反射回 state）。
- [x] `core/definitions.py`：4 个 agent 的 `allowed_tools` 各加入 `coderunner.agent.delegate`（RBAC 准入前提）。

*硬删 regex*
- [x] `graph/handoff.py`：删除 `HANDOFF_PATTERN`、`detect_handoff()`、旧 `HANDOFF_PROMPT_ADDENDUM`（文本标记教学）；保留 `apply_handoff()`/`rebuild_handoff_messages()`/`VALID_HANDOFF_TARGETS`；新增 tool-based prompt addendum + 共享的 `validate_handoff_target()` 校验函数（handler 复用）。
- [x] `agents/runtime.py` `_apply_after_run`：移除 `detect_handoff(out_state)` 调用，仅保留 `_HANDOFF_KEYS` 反射（字段现由 executor 填充）。

*Prompt*
- [x] 4 个 agent 的系统 prompt（`agents/prompts/*.md` 移除 `[HANDOFF:...]` 文本指令，改为调用 `delegate` 工具）+ `graph/handoff.py` 的 `HANDOFF_PROMPT_ADDENDUM`（教学改为 tool call）；`mcp_gateway/resources.py` 仅引用 addendum 常量名，无需改动。

*Gateway 契约面*
- [x] `mcp_gateway/tool_map.py`：`EXTERNAL_TOOL_MAP` 加 `"delegate": "coderunner.agent.delegate"`。
- [x] 重新生成 `mcp_gateway/generated_tools.py`（`python -m mcp_gateway._codegen`）；`EXPECTED_TOOL_COUNT` 已是 `len(EXTERNAL_TOOL_MAP)`，自动随之自增（原计划设想手改，实际无需）。
- [x] 新增内部 scope `agent:delegate`（归 INTERNAL_SCOPES，非 CANONICAL_SCOPES）；`scopes_for_agent` 自动并入 allowed_tools 的 required_scopes。

*Matrix / 契约测试 oracle 同步*
- [x] `evals/mcp/permission_matrix.yaml`：补 delegate 行（agent_host AGENT_MINIMAL allow；external_client 被 internal_only 拒为 `MCP_PERMISSION_DENIED`）。注：target-edge RBAC 在 handler 而非 guard，matrix 仅覆盖 guard 级准入。
- [x] `tests/test_tool_protocol.py`（catalog 集合）、`tests/test_mcp_gateway_catalog_contract.py`（`EXPECTED_EXTERNAL_TOOL_MAP`、`INTERNAL_SCOPES`）、`tests/test_agent_scopes.py`、`tests/test_agent_mcp_client_boundary.py`（agent 最小 scope 集合）：同步预期值。

*测试*
- [x] 删除 regex 用例：`tests/test_handoff_context.py`（`detect_handoff`）、`tests/test_agent_features.py`（`detect_handoff`）。
- [x] 新增 tool-based handoff 测试：`validate_handoff_target` 单测 + delegate 工具经 in-proc client 端到端触发 handoff（字段正确填充）/ 非法 target 在边界被拒（`MCP_PERMISSION_DENIED`）；`graph/runner.py` 路由与 `workers/chat.py` 流式 handoff 行为不回退（既有用例全绿）。

**验收**：agent 通过调用 `delegate` 工具触发 handoff；非法 target / 越权 role 在工具边界被拒并 audit；`graph/runner.py` handoff 路由与 `workers/chat.py` 流式 handoff 行为不回退；regex 通道彻底移除，无残留绕过路径。**（已完成，416 个相关测试全绿。）**

### T4 — 统一多步任务入口

**目标**：让 `WorkflowEngine` 成为多步 agentic 任务的唯一执行路径，消除“部分场景才用 workflow”。

**改动**：
- 梳理当前入口：`SupervisorAgent.invoke_from_chat()`（chat 启发式）+ `app/api/v1/ai.py` / `app/api/v1/agents/workflows.py`（API）走 workflow；单 agent 走 `graph/runner.py` `AgentOrchestrator`。
- 明确判定边界：单轮单 agent 仍可走 orchestrator；一旦触发 handoff/多步/human_gate，统一收敛进 `WorkflowEngine`，避免两套编排对同类任务并行。
- 不强行把所有单轮对话塞进 workflow（避免过度工程）；目标是“多步任务只有一条路径”。

**验收**：多步/含 handoff 的任务全部经 `WorkflowEngine`，可被 trace/审批/恢复统一覆盖；单轮对话路径不受影响、延迟不退化。补一个入口选择的回归测试。

### T5 — workflow step 上下文残留收敛 ✅ Done

> 落地：`graph/engine.py` 新增 `select_step_outputs(step_def, full_outputs)` + `_summarize_step_outputs()`，在 `_execute_step` 构造下游 context 时裁剪 `step_outputs`——仅透传 `depends_on`（按引用，保留既有 in-place mutation 行为），无声明依赖时给按 `HANDOFF_SUMMARY_LIMIT`(1500) 截断的逐步摘要而非全量残留。验收测试 `tests/test_workflow_context_scope.py` 绿（含 engine 端到端裁剪）。

**目标**：step 间不再无差别传整个 `step_outputs` dict，只传被 `depends_on` 引用的上游输出 + 必要摘要。

**改动**：
- `graph/handlers.py` / `graph/engine.py`：构造下游 step 的 `context` 时，依据该 step 的 `depends_on` 裁剪 `step_outputs`；无声明依赖则给摘要而非全量残留。
- 与 agent handoff 已有的 1500 字摘要策略对齐。

**执行偏差（已落地）**
- 裁剪函数放在 `graph/engine.py`（`_execute_step` 调用处），非 `graph/handlers.py`——handlers.py 是 generation 域 handler，裁剪是 engine 级关注点。
- `depends_on` 声明补在 `graph/planner.py` `GENERATION_TEMPLATE`（模板定义处），非 handlers.py：generation handler 硬编码读 `step_outputs.get(0/1/2/3)`，故给 step1/2/3 补 `depends_on:[0]` 以保证裁剪后仍取得上游全量 → 端到端结果不变。step 0 无上游依赖（其对 step2 的 dedup 读取在线性首跑永不命中，裁剪后取摘要返回 `{}`，行为一致）。
- `validation` step 的 `validates_step` 视作隐式依赖一并透传（否则 `_handle_validation` 取不到目标 step 输出）。

**验收**：下游 step 只能看到声明依赖的上游输出；generation pipeline 端到端结果不变。新增针对裁剪逻辑的单测。**（已完成，相关 66 个测试全绿。）**

### T6 — resume/replay 边界明确化（部分降级，避免过度工程）✅ Done

> 落地：`graph/engine.py` 新增 `resume_from_last_completed_step(workflow_run_id, user_role)`——从 `plan_json` + 已完成 step 的 `output_data` 重建 `step_outputs`，在 `last_completed + 1` 续跑；不重跑已完成 step，不做任意-step 回放。抽出共享 `_run_remaining_steps()`，`resume_after_approval()` 与新方法共用（approval 路径行为不变，T2 测试仍绿）。`recovery.py` 保持安全标 failed 取向，未改动（已满足要求；resume 为显式 opt-in，非自动）。上位计划 Phase 4 验收"状态回放"已降级为"可从最近完成 step 续跑"。验收测试 `tests/test_workflow_resume.py` 绿。

**目标**：明确“可恢复”的语义边界，不在本阶段强做完整 replay。

**改动 / 决策**：
- 保持 `recovery.py` 对中途 workflow 标 failed 的安全取向；在此基础上支持“从最近一个已完成 step 之后恢复”（已有 `current_step_index` + `plan_json` 可支撑）。
- **完整状态回放（任意 step 重放）依赖 step 幂等**，按上位计划推迟到 Phase 6 配合幂等/配额一起做。把上位计划 Phase 4 验收里的“状态回放”相应降级表述为“可从最近完成 step 恢复”。

**执行偏差（已落地）**
- 新增 `resume_from_last_completed_step` 为 engine 级 opt-in 方法，未连 API（避免本阶段范围蔓延；API 接线可留待后续按需）。
- 下游若有 `requires_approval` 且未完成的 step，续跑时重新进入 `waiting_approval`（re-gate），不绕过审批。
- 不替换/触碰 `recovery.py` 的自动行为：续跑必须显式调用，符合"安全取向"。

**验收**：暂停后可从断点继续；不承诺任意 step 重放。文档同步修订上位计划的该条验收。**（已完成，4 个新测试 + T2 审批测试全绿。）**

## 依赖与执行顺序

1. **T1 先做**：trace 绑定是 T2(审批关联 trace)、Phase 6(eval 关联 trace) 的地基，且依赖已 100% 就绪。
2. T2 紧随 T1（审批记录可引用 trace_id）。
3. T3 可与 T1/T2 并行（不同子系统），但需在 T4 之前——T4 的“多步统一入口”假定 delegation 已结构化。
4. T4 在 T3 后。
5. T5、T6 收尾，风险最低。

## 非目标（本阶段不做）

- step 幂等、per-tool/per-user 配额、写工具幂等、多租户隔离 → Phase 6。
- 完整任意-step replay → Phase 6。
- workflow trace viewer / dashboard UI → 不在本路线。
- 不把所有单轮对话强制塞进 WorkflowEngine（T4 只收敛多步任务）。

## schema 变更协议（T1/T2 适用）

每次加列：
1. 改 `app/models/workflow.py`（或 `mcp_approval.py`）+ `core/db/models/workflow.py` **两份**模型，列定义一致。
2. 写一条 Alembic migration（`migrations/`），upgrade/downgrade 完整。
3. 跑既有 `tests/test_graph_engine.py` 等确认不回退，再补本阶段新测试。
